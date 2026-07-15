#!/usr/bin/env python3
"""告警巡检脚本 —— 定时查询 InfluxDB 指标，超阈值则推送企业微信群机器人通知。

用法:
  python3 alert_checker.py            # 执行一次巡检
  python3 alert_checker.py --daemon   # 后台持续运行，每 60 秒巡检一次

部署为 systemd timer 每分钟执行一次:
  /opt/oracle-monitor/scripts/venv/bin/python3 /opt/oracle-monitor/portal/alert_checker.py
"""
import os
import sys
import sqlite3
import time
from datetime import datetime, timedelta
import requests
from influxdb_client import InfluxDBClient

PORTAL_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PORTAL_DIR, "portal.db")
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-token-1234567890"
INFLUX_ORG = "myorg"
INFLUX_BUCKET = "oracle_metrics"

# ─── 指标 → InfluxDB 查询映射 ────────────────────────────

METRIC_LABELS = {
    "active_sessions":  ("活跃会话数",   "个"),
    "total_sessions":   ("总会话数",     "个"),
    "tablespace_usage": ("表空间使用率", "%"),
    "buffer_hit_ratio": ("缓冲命中率",   "%"),
    "parse_count":      ("每秒解析次数", "次/s"),
    "instance_status":  ("实例状态",     ""),
}


def get_config():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM alert_config WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_rules():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM alert_rules WHERE enabled=1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_metric(metric, db_name):
    """从 InfluxDB 查询最新指标值"""
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()

    try:
        # 需要 max 聚合的指标
        max_metrics = {"tablespace_usage"}

        if metric == "instance_status":
            flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "db_instance")
  |> filter(fn: (r) => r["_field"] == "status_str")'''
        elif metric in ("active_sessions", "total_sessions"):
            field = "active_count" if metric == "active_sessions" else "total_count"
            flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "db_session")
  |> filter(fn: (r) => r["_field"] == "{field}")'''
        elif metric == "tablespace_usage":
            flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "db_tablespace")
  |> filter(fn: (r) => r["_field"] == "usage_pct")'''
        elif metric in ("buffer_hit_ratio", "parse_count"):
            field = "buffer_hit_pct" if metric == "buffer_hit_ratio" else "parse_count"
            flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "db_performance")
  |> filter(fn: (r) => r["_field"] == "{field}")'''
        else:
            return None

        # 按数据库过滤（* 表示全部）
        if db_name and db_name != "*":
            flux += f'\n  |> filter(fn: (r) => r["db_name"] == "{db_name}")'

        # 聚合
        if metric in max_metrics:
            flux += "\n  |> group()\n  |> max()"
        else:
            flux += "\n  |> last()"

        result = query_api.query(flux)
        values = []
        for table in result:
            for record in table.records:
                val = record.get_value()
                db = record.values.get("db_name", db_name or "*")
                values.append((db, val))

        return values if values else None
    except Exception as e:
        print(f"  [ERROR] query_metric({metric}, {db_name}): {e}")
        return None
    finally:
        client.close()


def check_rule(value, threshold, comparison):
    """判断值是否触发告警阈值"""
    if value is None:
        return False
    try:
        ops = {
            ">":  lambda v, t: v > t,
            "<":  lambda v, t: v < t,
            ">=": lambda v, t: v >= t,
            "<=": lambda v, t: v <= t,
            "==": lambda v, t: v == t,
            "!=": lambda v, t: v != t,
        }
        return ops.get(comparison, lambda v, t: v > t)(value, threshold)
    except TypeError:
        # 字符串比较（如 instance_status）
        return str(value) != str(threshold) if comparison == "!=" else str(value) == str(threshold)


def send_webhook(webhook_url, db_name, metric, value, threshold, comparison):
    """发送企业微信群机器人通知"""
    label, unit = METRIC_LABELS.get(metric, (metric, ""))

    if metric == "instance_status":
        content = (
            f"## 🚨 数据库告警\n\n"
            f"> **数据库**: <font color=\"warning\">{db_name}</font>\n"
            f"> **指标**: {label}\n"
            f"> **当前状态**: <font color=\"warning\">{value}</font>\n"
            f"> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        content = (
            f"## 🚨 数据库告警\n\n"
            f"> **数据库**: <font color=\"warning\">{db_name}</font>\n"
            f"> **指标**: {label}\n"
            f"> **当前值**: <font color=\"warning\">{value}{unit}</font>\n"
            f"> **阈值**: {comparison} {threshold}{unit}\n"
            f"> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  [ERROR] Webhook 发送失败: {e}")
        return False


def update_last_alert(rule_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE alert_rules SET last_alert_at=datetime('now','localtime') WHERE id=?",
        (rule_id,),
    )
    conn.commit()
    conn.close()


def run_once():
    """执行一次巡检"""
    config = get_config()
    if not config or not config["webhook_url"] or not config["enabled"]:
        return

    rules = get_rules()
    if not rules:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 巡检 {len(rules)} 条规则...")

    for rule in rules:
        # 冷却检查
        if rule["last_alert_at"]:
            try:
                last_alert = datetime.strptime(rule["last_alert_at"], "%Y-%m-%d %H:%M:%S")
                cooldown = timedelta(minutes=rule["cooldown_minutes"])
                if datetime.now() - last_alert < cooldown:
                    continue
            except ValueError:
                pass

        # 查询指标
        results = query_metric(rule["metric"], rule["db_name"])
        if not results:
            continue

        for db_name, value in results:
            if check_rule(value, rule["threshold"], rule["comparison"]):
                print(f"  [ALERT] {db_name} {rule['metric']}={value} "
                      f"({rule['comparison']} {rule['threshold']})")
                if send_webhook(config["webhook_url"], db_name, rule["metric"],
                                value, rule["threshold"], rule["comparison"]):
                    update_last_alert(rule["id"])
                    print(f"    -> Webhook 已发送")
                break  # 同一规则只发一次


def main():
    if "--daemon" in sys.argv:
        print("告警巡检守护进程启动 (每 60 秒巡检一次)")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[ERROR] 巡检异常: {e}")
            time.sleep(60)
    else:
        run_once()


if __name__ == "__main__":
    main()
