#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle 数据库监控采集脚本 (MVP)
功能: 定时采集 Oracle 核心指标, 写入 InfluxDB
依赖: oracledb, influxdb-client, APScheduler
"""

import os
import time
import logging
from datetime import datetime, timezone

import oracledb
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from apscheduler.schedulers.blocking import BlockingScheduler

# ============================================================
# 配置加载 (从环境变量)
# ============================================================
def load_config():
    """从环境变量或 config.env 文件加载配置"""
    config_path = os.path.join(os.path.dirname(__file__), "config.env")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    return {
        "oracle_host": os.environ.get("ORACLE_HOST", "localhost"),
        "oracle_port": os.environ.get("ORACLE_PORT", "1521"),
        "oracle_service": os.environ.get("ORACLE_SERVICE", "ORCLPDB1"),
        "oracle_user": os.environ.get("ORACLE_USER", "monitor_user"),
        "oracle_password": os.environ.get("ORACLE_PASSWORD", "YourPass123"),
        "influx_url": os.environ.get("INFLUXDB_URL", "http://localhost:8086"),
        "influx_token": os.environ.get("INFLUXDB_TOKEN", ""),
        "influx_org": os.environ.get("INFLUXDB_ORG", "myorg"),
        "influx_bucket": os.environ.get("INFLUXDB_BUCKET", "oracle_metrics"),
        "interval": int(os.environ.get("COLLECT_INTERVAL", "10")),
    }


CONFIG = load_config()

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "collector.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
# Oracle 连接
# ============================================================
def get_oracle_connection():
    """创建 Oracle 数据库连接 (thin 模式, 无需 Instant Client)"""
    dsn = f"{CONFIG['oracle_host']}:{CONFIG['oracle_port']}/{CONFIG['oracle_service']}"
    return oracledb.connect(
        user=CONFIG["oracle_user"],
        password=CONFIG["oracle_password"],
        dsn=dsn,
    )


# ============================================================
# 采集函数 — 每个维度一个函数
# ============================================================

def collect_instance_status(conn):
    """采集实例状态 + 会话信息"""
    points = []
    cur = conn.cursor()

    # 实例状态
    cur.execute("SELECT status, instance_name FROM v$instance")
    row = cur.fetchone()
    if row:
        points.append(
            Point("oracle_instance")
            .tag("instance", row[1])
            .field("status_open", 1 if row[0] == "OPEN" else 0)
            .field("status_code", {"OPEN": 1, "MOUNTED": 2, "STARTED": 3}.get(row[0], 0))
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )

    # 会话统计
    cur.execute("""
        SELECT status, COUNT(*) as cnt
        FROM v$session
        GROUP BY status
    """)
    total_sessions = 0
    active_sessions = 0
    for row in cur:
        status, cnt = row[0], row[1]
        total_sessions += cnt
        if status == "ACTIVE":
            active_sessions = cnt

    points.append(
        Point("oracle_sessions")
        .field("total", total_sessions)
        .field("active", active_sessions)
        .field("inactive", total_sessions - active_sessions)
        .time(datetime.now(timezone.utc), WritePrecision.S)
    )

    # 阻塞会话数
    cur.execute("""
        SELECT COUNT(*) FROM v$session
        WHERE blocking_session IS NOT NULL
    """)
    blocked = cur.fetchone()[0]
    points.append(
        Point("oracle_sessions")
        .field("blocked", blocked)
        .time(datetime.now(timezone.utc), WritePrecision.S)
    )

    cur.close()
    return points


def collect_wait_events(conn):
    """采集 TOP 等待事件"""
    points = []
    cur = conn.cursor()
    cur.execute("""
        SELECT event, total_waits, time_waited
        FROM v$system_event
        WHERE wait_class != 'Idle'
        ORDER BY time_waited DESC
        FETCH FIRST 10 ROWS ONLY
    """)
    for row in cur:
        event_name, total_waits, time_waited = row
        points.append(
            Point("oracle_wait_events")
            .tag("event", event_name)
            .field("total_waits", total_waits)
            .field("time_waited_ms", time_waited)
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )
    cur.close()
    return points


def collect_tablespace_usage(conn):
    """采集表空间使用率"""
    points = []
    cur = conn.cursor()
    cur.execute("""
        SELECT
            a.tablespace_name,
            ROUND(a.bytes / 1024 / 1024, 2) AS total_mb,
            ROUND(b.free_bytes / 1024 / 1024, 2) AS free_mb,
            ROUND((a.bytes - b.free_bytes) / 1024 / 1024, 2) AS used_mb,
            ROUND((1 - b.free_bytes / a.bytes) * 100, 2) AS used_pct
        FROM
            (SELECT tablespace_name, SUM(bytes) AS bytes
             FROM dba_data_files GROUP BY tablespace_name) a,
            (SELECT tablespace_name, SUM(bytes) AS free_bytes
             FROM dba_free_space GROUP BY tablespace_name) b
        WHERE a.tablespace_name = b.tablespace_name(+)
    """)
    for row in cur:
        ts_name, total_mb, free_mb, used_mb, used_pct = row
        points.append(
            Point("oracle_tablespace")
            .tag("tablespace", ts_name)
            .field("total_mb", float(total_mb or 0))
            .field("used_mb", float(used_mb or 0))
            .field("free_mb", float(free_mb or 0))
            .field("used_pct", float(used_pct or 0))
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )
    cur.close()
    return points


def collect_performance_metrics(conn):
    """采集性能指标: Buffer Cache 命中率, 解析统计"""
    points = []
    cur = conn.cursor()

    # Buffer Cache 命中率
    cur.execute("""
        SELECT name, value FROM v$sysstat
        WHERE name IN ('db block gets', 'consistent gets', 'physical reads')
    """)
    stats = {}
    for row in cur:
        stats[row[0]] = row[1]

    db_block_gets = stats.get("db block gets", 0)
    consistent_gets = stats.get("consistent gets", 0)
    physical_reads = stats.get("physical reads", 0)
    total_gets = db_block_gets + consistent_gets

    hit_ratio = ((total_gets - physical_reads) / total_gets * 100) if total_gets > 0 else 0

    points.append(
        Point("oracle_performance")
        .field("buffer_cache_hit_pct", round(float(hit_ratio), 2))
        .field("physical_reads", int(physical_reads))
        .field("db_block_gets", int(db_block_gets))
        .field("consistent_gets", int(consistent_gets))
        .time(datetime.now(timezone.utc), WritePrecision.S)
    )

    # 解析统计
    cur.execute("""
        SELECT name, value FROM v$sysstat
        WHERE name IN ('parse count (total)', 'parse count (hard)')
    """)
    parse_stats = {}
    for row in cur:
        parse_stats[row[0]] = row[1]

    total_parse = parse_stats.get("parse count (total)", 0)
    hard_parse = parse_stats.get("parse count (hard)", 0)
    hard_parse_pct = (hard_parse / total_parse * 100) if total_parse > 0 else 0

    points.append(
        Point("oracle_performance")
        .field("parse_total", int(total_parse))
        .field("parse_hard", int(hard_parse))
        .field("hard_parse_pct", round(float(hard_parse_pct), 2))
        .time(datetime.now(timezone.utc), WritePrecision.S)
    )

    cur.close()
    return points


def collect_sga_pga(conn):
    """采集 SGA / PGA 内存使用"""
    points = []
    cur = conn.cursor()

    # SGA 信息 - 按 pool 汇总 + 关键组件
    try:
        # 按 pool 汇总 SGA 使用
        cur.execute("SELECT NVL(pool, 'fixed area') AS pool_name, SUM(bytes) AS total_bytes FROM v$sgastat GROUP BY pool")
        for row in cur:
            pool_name, value = row[0], row[1]
            points.append(
                Point("oracle_memory")
                .tag("type", "SGA")
                .tag("name", pool_name)
                .field("bytes", int(value or 0))
                .time(datetime.now(timezone.utc), WritePrecision.S)
            )
        # SGA 总量
        cur.execute("SELECT SUM(bytes) FROM v$sgastat")
        sga_total = cur.fetchone()[0]
        if sga_total:
            points.append(
                Point("oracle_memory")
                .tag("type", "SGA")
                .tag("name", "total_sga")
                .field("bytes", int(sga_total))
                .time(datetime.now(timezone.utc), WritePrecision.S)
            )
    except Exception as e:
        logger.warning(f"SGA 采集失败: {e}")

    # PGA 信息
    try:
        cur.execute("SELECT name, value FROM v$pgastat WHERE name IN ('total PGA allocated', 'total PGA inuse', 'aggregate PGA target parameter')")
        for row in cur:
            name, value = row[0], row[1]
            points.append(
                Point("oracle_memory")
                .tag("type", "PGA")
                .tag("name", name)
                .field("bytes", int(value or 0))
                .time(datetime.now(timezone.utc), WritePrecision.S)
            )
    except Exception as e:
        logger.warning(f"PGA 采集失败: {e}")

    cur.close()
    return points


# ============================================================
# 主采集流程
# ============================================================
def collect_all():
    """执行全量采集, 写入 InfluxDB"""
    start_time = time.time()
    logger.info("===== 开始采集 =====")

    all_points = []

    try:
        conn = get_oracle_connection()
        logger.info("Oracle 连接成功")

        # 逐维度采集
        try:
            pts = collect_instance_status(conn)
            all_points.extend(pts)
            logger.info(f"  实例状态/会话: {len(pts)} 个数据点")
        except Exception as e:
            logger.error(f"  实例状态采集失败: {e}")

        try:
            pts = collect_wait_events(conn)
            all_points.extend(pts)
            logger.info(f"  等待事件: {len(pts)} 个数据点")
        except Exception as e:
            logger.error(f"  等待事件采集失败: {e}")

        try:
            pts = collect_tablespace_usage(conn)
            all_points.extend(pts)
            logger.info(f"  表空间: {len(pts)} 个数据点")
        except Exception as e:
            logger.error(f"  表空间采集失败: {e}")

        try:
            pts = collect_performance_metrics(conn)
            all_points.extend(pts)
            logger.info(f"  性能指标: {len(pts)} 个数据点")
        except Exception as e:
            logger.error(f"  性能指标采集失败: {e}")

        try:
            pts = collect_sga_pga(conn)
            all_points.extend(pts)
            logger.info(f"  内存 SGA/PGA: {len(pts)} 个数据点")
        except Exception as e:
            logger.error(f"  内存采集失败: {e}")

        conn.close()
        logger.info("Oracle 连接已关闭")

    except Exception as e:
        logger.error(f"Oracle 连接失败: {e}")
        return

    # 写入 InfluxDB
    if all_points:
        try:
            client = InfluxDBClient(
                url=CONFIG["influx_url"],
                token=CONFIG["influx_token"],
                org=CONFIG["influx_org"],
            )
            write_api = client.write_api(write_options=SYNCHRONOUS)
            write_api.write(
                bucket=CONFIG["influx_bucket"],
                record=all_points,
            )
            write_api.close()
            client.close()
            logger.info(f"成功写入 {len(all_points)} 个数据点到 InfluxDB")
        except Exception as e:
            logger.error(f"InfluxDB 写入失败: {e}")

    elapsed = time.time() - start_time
    logger.info(f"===== 采集完成, 耗时 {elapsed:.2f}s =====")


# ============================================================
# 启动定时调度
# ============================================================
def main():
    logger.info("=" * 50)
    logger.info("Oracle 监控采集脚本启动")
    logger.info(f"  Oracle:  {CONFIG['oracle_host']}:{CONFIG['oracle_port']}/{CONFIG['oracle_service']}")
    logger.info(f"  InfluxDB: {CONFIG['influx_url']}")
    logger.info(f"  采集间隔: {CONFIG['interval']} 秒")
    logger.info("=" * 50)

    # 首次立即采集一次
    collect_all()

    # 定时调度
    scheduler = BlockingScheduler()
    scheduler.add_job(
        collect_all,
        "interval",
        seconds=CONFIG["interval"],
        id="collect_oracle_metrics",
        max_instances=1,
        misfire_grace_time=30,
    )

    logger.info(f"调度器已启动, 每 {CONFIG['interval']} 秒采集一次, 按 Ctrl+C 停止")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("采集脚本已停止")


if __name__ == "__main__":
    main()
