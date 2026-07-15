#!/usr/bin/env python3
"""数据库监控管理平台 - Web Portal

提供可视化的数据库连接配置管理：
- 添加/编辑/删除数据库连接（Oracle/MySQL/PostgreSQL）
- 测试数据库连通性
- 一键启停采集进程
- 查看采集日志
- 跳转 Grafana 仪表盘
"""
import os
import sys
import json
import sqlite3
import subprocess
import signal
import time
import requests
from flask import Flask, render_template, jsonify, request, make_response

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

PORTAL_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PORTAL_DIR, "portal.db")
VENV_PYTHON = "/opt/oracle-monitor/scripts/venv/bin/python"
WORKER_SCRIPT = os.path.join(PORTAL_DIR, "collector_worker.py")
LOG_DIR = os.path.join(PORTAL_DIR, "logs")

# InfluxDB 配置
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-token-1234567890"
INFLUX_ORG = "myorg"
INFLUX_BUCKET = "oracle_metrics"
GRAFANA_URL = "http://localhost:3000"

os.makedirs(LOG_DIR, exist_ok=True)


# ─── SQLite 工具 ───────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS db_connections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            db_type         TEXT NOT NULL,
            host            TEXT NOT NULL,
            port            INTEGER NOT NULL,
            service_name    TEXT DEFAULT '',
            username        TEXT NOT NULL,
            password        TEXT NOT NULL,
            collect_interval INTEGER DEFAULT 10,
            status          TEXT DEFAULT 'stopped',
            pid             INTEGER,
            last_error      TEXT,
            last_collect_at TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    # 告警配置表
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_config (
            id              INTEGER PRIMARY KEY DEFAULT 1,
            webhook_url     TEXT DEFAULT '',
            enabled         INTEGER DEFAULT 1,
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO alert_config (id) VALUES (1)"
    )
    # 告警规则表
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            db_name         TEXT NOT NULL DEFAULT '*',
            metric          TEXT NOT NULL,
            threshold       REAL NOT NULL DEFAULT 0,
            comparison      TEXT NOT NULL DEFAULT '>',
            enabled         INTEGER DEFAULT 1,
            cooldown_minutes INTEGER DEFAULT 5,
            last_alert_at   TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.commit()
    conn.close()


def is_process_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ─── 页面路由 ──────────────────────────────────────────────

@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ─── REST API ──────────────────────────────────────────────

@app.route("/api/db-types")
def db_types():
    """返回支持的数据库类型列表"""
    return jsonify(
        [
            {"value": "oracle", "label": "Oracle", "default_port": 1521, "service_label": "Service Name", "service_placeholder": "XE"},
            {"value": "mysql", "label": "MySQL", "default_port": 3306, "service_label": "数据库名", "service_placeholder": "mydb"},
            {"value": "postgresql", "label": "PostgreSQL", "default_port": 5432, "service_label": "数据库名", "service_placeholder": "mydb"},
        ]
    )


@app.route("/api/connections")
def list_connections():
    """列出所有数据库连接配置"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM db_connections ORDER BY id").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        # 校验进程是否真的在运行
        if d["status"] == "running" and not is_process_running(d.get("pid")):
            d["status"] = "stopped"
            conn.execute(
                "UPDATE db_connections SET status='stopped', pid=NULL WHERE id=?",
                (d["id"],),
            )
            conn.commit()
        result.append(d)
    conn.close()
    return jsonify(result)


@app.route("/api/connections", methods=["POST"])
def create_connection():
    """创建新的数据库连接配置"""
    data = request.json
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO db_connections
                (name, db_type, host, port, service_name, username, password, collect_interval)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data["db_type"],
                data["host"],
                data["port"],
                data.get("service_name", ""),
                data["username"],
                data["password"],
                data.get("collect_interval", 10),
            ),
        )
        conn.commit()
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return jsonify({"id": cid, "message": "创建成功"}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "数据库名称已存在"}), 400
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/connections/<int:cid>", methods=["PUT"])
def update_connection(cid):
    """更新数据库连接配置"""
    data = request.json
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE db_connections SET
                name=?, db_type=?, host=?, port=?, service_name=?,
                username=?, password=?, collect_interval=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
            """,
            (
                data["name"],
                data["db_type"],
                data["host"],
                data["port"],
                data.get("service_name", ""),
                data["username"],
                data["password"],
                data.get("collect_interval", 10),
                cid,
            ),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "更新成功"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "数据库名称已存在"}), 400


@app.route("/api/connections/<int:cid>", methods=["DELETE"])
def delete_connection(cid):
    """删除数据库连接配置（先停止采集进程）"""
    conn = get_db()
    row = conn.execute("SELECT pid, status FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "配置不存在"}), 404

    if row["status"] == "running" and row["pid"]:
        try:
            os.kill(row["pid"], signal.SIGTERM)
            time.sleep(1)
        except Exception:
            pass

    conn.execute("DELETE FROM db_connections WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "删除成功"})


@app.route("/api/connections/<int:cid>/test", methods=["POST"])
def test_connection(cid):
    """测试数据库连接"""
    conn = get_db()
    row = conn.execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "配置不存在"}), 404

    try:
        result = subprocess.run(
            [VENV_PYTHON, WORKER_SCRIPT, str(cid), "--test"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "message": result.stdout.strip()})
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return jsonify({"ok": False, "error": err})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "连接超时（30s）"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/connections/<int:cid>/start", methods=["POST"])
def start_monitoring(cid):
    """启动采集进程"""
    conn = get_db()
    row = conn.execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "配置不存在"}), 404

    if row["status"] == "running" and is_process_running(row["pid"]):
        conn.close()
        return jsonify({"message": "已在运行中"})

    log_file = open(os.path.join(LOG_DIR, f"worker_{cid}.log"), "a")
    proc = subprocess.Popen(
        [VENV_PYTHON, WORKER_SCRIPT, str(cid)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    conn.execute(
        "UPDATE db_connections SET status=?, pid=?, last_error=NULL WHERE id=?",
        ("running", proc.pid, cid),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "监控已启动", "pid": proc.pid})


@app.route("/api/connections/<int:cid>/stop", methods=["POST"])
def stop_monitoring(cid):
    """停止采集进程"""
    conn = get_db()
    row = conn.execute("SELECT pid FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "配置不存在"}), 404

    if row["pid"]:
        try:
            os.kill(row["pid"], signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(row["pid"], signal.SIGKILL)
            except Exception:
                pass
        except ProcessLookupError:
            pass

    conn.execute(
        "UPDATE db_connections SET status='stopped', pid=NULL WHERE id=?",
        (cid,),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "监控已停止"})


@app.route("/api/connections/<int:cid>/logs")
def get_logs(cid):
    """获取采集日志（最后 200 行）"""
    log_path = os.path.join(LOG_DIR, f"worker_{cid}.log")
    if not os.path.exists(log_path):
        return jsonify({"logs": ""})
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
        return jsonify({"logs": "".join(lines)})
    except Exception as e:
        return jsonify({"logs": f"读取日志失败: {e}"})


@app.route("/api/stats")
def stats():
    """统计信息"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM db_connections").fetchone()["c"]
    running = conn.execute("SELECT COUNT(*) as c FROM db_connections WHERE status='running'").fetchone()["c"]
    error = conn.execute("SELECT COUNT(*) as c FROM db_connections WHERE status='error'").fetchone()["c"]
    by_type = conn.execute(
        "SELECT db_type, COUNT(*) as c FROM db_connections GROUP BY db_type"
    ).fetchall()
    conn.close()
    return jsonify(
        {
            "total": total,
            "running": running,
            "stopped": total - running - error,
            "error": error,
            "by_type": {r["db_type"]: r["c"] for r in by_type},
        }
    )


@app.route("/api/grafana-url")
def grafana_url():
    return jsonify({"url": GRAFANA_URL})


# ─── 告警配置 API ─────────────────────────────────────────

METRICS_INFO = [
    {"value": "active_sessions",   "label": "活跃会话数",     "unit": "个"},
    {"value": "total_sessions",    "label": "总会话数",       "unit": "个"},
    {"value": "tablespace_usage",  "label": "表空间使用率",   "unit": "%"},
    {"value": "buffer_hit_ratio",  "label": "缓冲命中率",     "unit": "%"},
    {"value": "parse_count",       "label": "每秒解析次数",   "unit": "次/s"},
    {"value": "instance_status",   "label": "实例状态",       "unit": ""},
]


@app.route("/api/alert-config", methods=["GET", "PUT"])
def alert_config():
    """获取或更新告警全局配置"""
    conn = get_db()
    if request.method == "GET":
        row = conn.execute("SELECT * FROM alert_config WHERE id=1").fetchone()
        conn.close()
        return jsonify(dict(row) if row else {"webhook_url": "", "enabled": 1})
    else:
        data = request.json
        conn.execute(
            "UPDATE alert_config SET webhook_url=?, enabled=?, updated_at=datetime('now','localtime') WHERE id=1",
            (data.get("webhook_url", ""), data.get("enabled", 1)),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "保存成功"})


@app.route("/api/alert-config/test", methods=["POST"])
def test_webhook():
    """测试 Webhook 推送"""
    data = request.json
    url = data.get("webhook_url", "")
    if not url:
        return jsonify({"ok": False, "error": "Webhook URL 为空"})

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": (
                "## ✅ 告警通知测试\n\n"
                "> 这是一条来自 **数据库监控平台** 的测试消息\n"
                "> 如果您收到此消息，说明 Webhook 配置正确\n"
                f"> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return jsonify({"ok": True, "message": "测试消息已发送，请检查企业微信群"})
        else:
            return jsonify({"ok": False, "error": f"请求失败: HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/alert-rules")
def list_alert_rules():
    """列出所有告警规则"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/alert-rules", methods=["POST"])
def create_alert_rule():
    """创建告警规则"""
    data = request.json
    conn = get_db()
    conn.execute(
        """INSERT INTO alert_rules (db_name, metric, threshold, comparison, enabled, cooldown_minutes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            data.get("db_name", "*"),
            data["metric"],
            data["threshold"],
            data.get("comparison", ">"),
            data.get("enabled", 1),
            data.get("cooldown_minutes", 5),
        ),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return jsonify({"id": rid, "message": "规则创建成功"}), 201


@app.route("/api/alert-rules/<int:rid>", methods=["PUT", "DELETE"])
def manage_alert_rule(rid):
    """更新或删除告警规则"""
    conn = get_db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM alert_rules WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({"message": "规则已删除"})
    else:
        data = request.json
        conn.execute(
            """UPDATE alert_rules SET db_name=?, metric=?, threshold=?, comparison=?,
               enabled=?, cooldown_minutes=?, updated_at=datetime('now','localtime')
               WHERE id=?""",
            (
                data.get("db_name", "*"),
                data["metric"],
                data["threshold"],
                data.get("comparison", ">"),
                data.get("enabled", 1),
                data.get("cooldown_minutes", 5),
                rid,
            ),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "规则已更新"})


@app.route("/api/metrics-info")
def metrics_info():
    """返回可用监控指标列表"""
    return jsonify(METRICS_INFO)


# ─── 启动时自动恢复采集进程 ────────────────────────────────

def auto_restore_collectors():
    """门户重启后，自动恢复之前正在运行的采集进程"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, status FROM db_connections WHERE status='running'"
    ).fetchall()
    conn.close()

    for row in rows:
        cid = row["id"]
        name = row["name"]
        try:
            log_file = open(os.path.join(LOG_DIR, f"worker_{cid}.log"), "a")
            log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Auto-restoring collector for '{name}'\n")
            proc = subprocess.Popen(
                [VENV_PYTHON, WORKER_SCRIPT, str(cid)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            conn = get_db()
            conn.execute(
                "UPDATE db_connections SET pid=?, last_error=NULL WHERE id=?",
                (proc.pid, cid),
            )
            conn.commit()
            conn.close()
            print(f"[Auto-restore] Started collector for '{name}' (PID: {proc.pid})")
        except Exception as e:
            print(f"[Auto-restore] Failed for '{name}': {e}")
            conn = get_db()
            conn.execute(
                "UPDATE db_connections SET status='stopped', pid=NULL, last_error=? WHERE id=?",
                (str(e)[:500], cid),
            )
            conn.commit()
            conn.close()


# ─── 启动 ──────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    auto_restore_collectors()
    app.run(host="0.0.0.0", port=5000, debug=False)
