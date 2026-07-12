#!/usr/bin/env python3
"""多数据库采集器工作进程

每个数据库连接运行一个独立进程，通过连接 ID 从 SQLite 读取配置，
连接目标数据库采集指标，写入 InfluxDB。

用法:
    python collector_worker.py <connection_id>          # 启动采集循环
    python collector_worker.py <connection_id> --test   # 仅测试连接
"""
import sys
import os
import time
import sqlite3
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

PORTAL_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PORTAL_DIR, "portal.db")

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-token-1234567890"
INFLUX_ORG = "myorg"
INFLUX_BUCKET = "oracle_metrics"


# ─── SQLite 工具 ───────────────────────────────────────────

def load_config(cid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_status(cid, status, error=None):
    conn = sqlite3.connect(DB_PATH)
    if error:
        conn.execute(
            "UPDATE db_connections SET status=?, last_error=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, str(error)[:500], cid),
        )
    else:
        conn.execute(
            "UPDATE db_connections SET status=?, last_error=NULL, last_collect_at=datetime('now','localtime') WHERE id=?",
            (status, cid),
        )
    conn.commit()
    conn.close()


# ─── Oracle 采集 ──────────────────────────────────────────

def collect_oracle(config):
    import oracledb

    dsn = f"{config['host']}:{config['port']}/{config['service_name']}"
    conn = oracledb.connect(user=config["username"], password=config["password"], dsn=dsn)
    cur = conn.cursor()
    db_name = config["name"]
    now = datetime.now(timezone.utc)
    points = []

    # 1. 实例状态
    try:
        cur.execute("SELECT status, database_status, instance_name FROM v$instance")
        row = cur.fetchone()
        if row:
            points.append(
                Point("db_instance")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .field("status_str", str(row[0]))
                .field("db_status", str(row[1]))
                .field("instance_name", str(row[2]))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[Oracle] instance status error: {e}")

    # 2. 会话统计
    try:
        cur.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN blocking_session IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM v$session"
        )
        row = cur.fetchone()
        if row:
            points.append(
                Point("db_session")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .field("total", int(row[0] or 0))
                .field("active", int(row[1] or 0))
                .field("blocked", int(row[2] or 0))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[Oracle] session error: {e}")

    # 3. 等待事件 TOP 10
    try:
        cur.execute(
            "SELECT event, total_waits, time_waited "
            "FROM v$system_event "
            "WHERE wait_class != 'Idle' "
            "ORDER BY time_waited DESC FETCH FIRST 10 ROWS ONLY"
        )
        for row in cur:
            points.append(
                Point("db_wait_events")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .tag("event", str(row[0]))
                .field("total_waits", int(row[1] or 0))
                .field("time_waited_ms", float(row[2] or 0))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[Oracle] wait events error: {e}")

    # 4. 表空间使用率
    try:
        cur.execute(
            "SELECT df.tablespace_name, df.bytes as total_bytes, "
            "NVL(fs.bytes, 0) as free_bytes "
            "FROM (SELECT tablespace_name, SUM(bytes) bytes FROM dba_data_files GROUP BY tablespace_name) df, "
            "(SELECT tablespace_name, SUM(bytes) bytes FROM dba_free_space GROUP BY tablespace_name) fs "
            "WHERE df.tablespace_name = fs.tablespace_name(+)"
        )
        for row in cur:
            total = int(row[1] or 0)
            free = int(row[2] or 0)
            used = total - free
            pct = round(used / total * 100, 2) if total > 0 else 0
            points.append(
                Point("db_tablespace")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .tag("name", str(row[0]))
                .field("total_bytes", total)
                .field("used_bytes", used)
                .field("free_bytes", free)
                .field("usage_pct", float(pct))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[Oracle] tablespace error: {e}")

    # 5. 性能指标
    try:
        cur.execute(
            "SELECT name, value FROM v$sysstat "
            "WHERE name IN ('buffer cache hit ratio','physical reads','physical writes',"
            "'parse count (total)','parse count (hard)','consistent gets',"
            "'execute count','user commits','user rollbacks')"
        )
        stats = {row[0]: int(row[1] or 0) for row in cur}

        phys_reads = stats.get("physical reads", 0)
        consistent_gets = stats.get("consistent gets", 0)
        denom = consistent_gets + phys_reads
        hit_ratio = round((1 - phys_reads / denom) * 100, 2) if denom > 0 else 100.0

        parse_total = stats.get("parse count (total)", 1)
        parse_hard = stats.get("parse count (hard)", 0)
        hard_parse_pct = round(parse_hard / parse_total * 100, 2) if parse_total > 0 else 0.0

        p = (
            Point("db_performance")
            .tag("db_name", db_name)
            .tag("db_type", "oracle")
            .field("buffer_cache_hit_ratio", float(hit_ratio))
            .field("hard_parse_pct", float(hard_parse_pct))
            .field("physical_reads", phys_reads)
            .field("physical_writes", stats.get("physical writes", 0))
            .field("parse_total", parse_total)
            .field("parse_hard", parse_hard)
            .field("execute_count", stats.get("execute count", 0))
            .field("user_commits", stats.get("user commits", 0))
            .field("user_rollbacks", stats.get("user rollbacks", 0))
        )
        p.time(now, WritePrecision.S)
        points.append(p)
    except Exception as e:
        print(f"[Oracle] performance error: {e}")

    # 6. SGA / PGA 内存
    try:
        cur.execute(
            "SELECT name, bytes FROM v$sgastat "
            "WHERE name IN ('buffer_cache','shared pool','free memory','log_buffer','fixed_sga')"
        )
        for row in cur:
            points.append(
                Point("db_memory")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .tag("type", "SGA")
                .tag("name", str(row[0]))
                .field("bytes", int(row[1] or 0))
                .time(now, WritePrecision.S)
            )

        cur.execute(
            "SELECT name, value FROM v$pgastat "
            "WHERE name IN ('total PGA allocated','total PGA inuse','maximum PGA allocated')"
        )
        for row in cur:
            points.append(
                Point("db_memory")
                .tag("db_name", db_name)
                .tag("db_type", "oracle")
                .tag("type", "PGA")
                .tag("name", str(row[0]))
                .field("bytes", int(row[1] or 0))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[Oracle] memory error: {e}")

    conn.close()
    return points


# ─── MySQL 采集 ───────────────────────────────────────────

def collect_mysql(config):
    import pymysql

    conn = pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["username"],
        password=config["password"],
        database=config["service_name"],
        connect_timeout=10,
    )
    cur = conn.cursor()
    db_name = config["name"]
    now = datetime.now(timezone.utc)
    points = []

    # 1. 全局状态
    cur.execute("SHOW GLOBAL STATUS")
    status = {row[0]: row[1] for row in cur.fetchall()}

    # 2. 实例状态
    uptime = int(status.get("Uptime", 0))
    points.append(
        Point("db_instance")
        .tag("db_name", db_name)
        .tag("db_type", "mysql")
        .field("status_str", "OPEN")
        .field("uptime_seconds", uptime)
        .time(now, WritePrecision.S)
    )

    # 3. 会话统计
    points.append(
        Point("db_session")
        .tag("db_name", db_name)
        .tag("db_type", "mysql")
        .field("total", int(status.get("Threads_connected", 0)))
        .field("active", int(status.get("Threads_running", 0)))
        .field("created", int(status.get("Threads_created", 0)))
        .field("cached", int(status.get("Threads_cached", 0)))
        .time(now, WritePrecision.S)
    )

    # 4. 性能指标
    questions = int(status.get("Questions", 0))
    slow_queries = int(status.get("Slow_queries", 0))
    points.append(
        Point("db_performance")
        .tag("db_name", db_name)
        .tag("db_type", "mysql")
        .field("questions", questions)
        .field("slow_queries", slow_queries)
        .field("com_select", int(status.get("Com_select", 0)))
        .field("com_insert", int(status.get("Com_insert", 0)))
        .field("com_update", int(status.get("Com_update", 0)))
        .field("com_delete", int(status.get("Com_delete", 0)))
        .field("bytes_received", int(status.get("Bytes_received", 0)))
        .field("bytes_sent", int(status.get("Bytes_sent", 0)))
        .time(now, WritePrecision.S)
    )

    # 5. InnoDB Buffer Pool
    bp_total = int(status.get("Innodb_buffer_pool_pages_total", 0))
    bp_free = int(status.get("Innodb_buffer_pool_pages_free", 0))
    bp_used = bp_total - bp_free
    bp_hit_req = int(status.get("Innodb_buffer_pool_read_requests", 0))
    bp_read = int(status.get("Innodb_buffer_pool_reads", 0))
    hit_ratio = round((1 - bp_read / bp_hit_req) * 100, 2) if bp_hit_req > 0 else 100.0

    points.append(
        Point("db_memory")
        .tag("db_name", db_name)
        .tag("db_type", "mysql")
        .tag("type", "innodb_buffer_pool")
        .field("pages_total", bp_total)
        .field("pages_free", bp_free)
        .field("pages_used", bp_used)
        .field("hit_ratio", float(hit_ratio))
        .time(now, WritePrecision.S)
    )

    # 6. 数据库大小
    try:
        cur.execute(
            "SELECT table_schema, "
            "SUM(data_length + index_length) as total_bytes, "
            "SUM(data_length) as data_bytes, "
            "SUM(index_length) as index_bytes "
            "FROM information_schema.tables "
            "WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys') "
            "GROUP BY table_schema ORDER BY total_bytes DESC LIMIT 10"
        )
        for row in cur:
            total = int(row[1] or 0)
            data = int(row[2] or 0)
            idx = int(row[3] or 0)
            points.append(
                Point("db_tablespace")
                .tag("db_name", db_name)
                .tag("db_type", "mysql")
                .tag("name", str(row[0]))
                .field("total_bytes", total)
                .field("used_bytes", data)
                .field("free_bytes", 0)
                .field("index_bytes", idx)
                .field("usage_pct", 0.0)
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[MySQL] table sizes error: {e}")

    conn.close()
    return points


# ─── PostgreSQL 采集 ──────────────────────────────────────

def collect_postgresql(config):
    import psycopg2

    conn = psycopg2.connect(
        host=config["host"],
        port=config["port"],
        user=config["username"],
        password=config["password"],
        dbname=config["service_name"],
        connect_timeout=10,
    )
    cur = conn.cursor()
    db_name = config["name"]
    now = datetime.now(timezone.utc)
    points = []

    # 1. 实例状态
    cur.execute("SELECT now() - pg_postmaster_start_time()")
    row = cur.fetchone()
    if row:
        uptime = int(row[0].total_seconds())
        points.append(
            Point("db_instance")
            .tag("db_name", db_name)
            .tag("db_type", "postgresql")
            .field("status_str", "ACCEPTING_CONNECTIONS")
            .field("uptime_seconds", uptime)
            .time(now, WritePrecision.S)
        )

    # 2. 会话统计
    cur.execute(
        "SELECT count(*), "
        "count(*) FILTER (WHERE state = 'active'), "
        "count(*) FILTER (WHERE state = 'idle'), "
        "count(*) FILTER (WHERE wait_event IS NOT NULL) "
        "FROM pg_stat_activity"
    )
    row = cur.fetchone()
    if row:
        points.append(
            Point("db_session")
            .tag("db_name", db_name)
            .tag("db_type", "postgresql")
            .field("total", int(row[0] or 0))
            .field("active", int(row[1] or 0))
            .field("idle", int(row[2] or 0))
            .field("blocked", int(row[3] or 0))
            .time(now, WritePrecision.S)
        )

    # 3. 性能指标 - Cache 命中率
    cur.execute(
        "SELECT sum(blks_hit), sum(blks_read), sum(xact_commit), sum(xact_rollback), "
        "sum(tup_returned), sum(tup_fetched), sum(tup_inserted), "
        "sum(tup_updated), sum(tup_deleted) FROM pg_stat_database"
    )
    row = cur.fetchone()
    if row:
        blks_hit = int(row[0] or 0)
        blks_read = int(row[1] or 0)
        denom = blks_hit + blks_read
        hit_ratio = round(blks_hit / denom * 100, 2) if denom > 0 else 100.0

        points.append(
            Point("db_performance")
            .tag("db_name", db_name)
            .tag("db_type", "postgresql")
            .field("cache_hit_ratio", float(hit_ratio))
            .field("blks_hit", blks_hit)
            .field("blks_read", blks_read)
            .field("xact_commit", int(row[2] or 0))
            .field("xact_rollback", int(row[3] or 0))
            .field("tup_returned", int(row[4] or 0))
            .field("tup_fetched", int(row[5] or 0))
            .field("tup_inserted", int(row[6] or 0))
            .field("tup_updated", int(row[7] or 0))
            .field("tup_deleted", int(row[8] or 0))
            .time(now, WritePrecision.S)
        )

    # 4. 数据库大小
    cur.execute(
        "SELECT datname, pg_database_size(datname) FROM pg_database "
        "WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC LIMIT 10"
    )
    for row in cur:
        points.append(
            Point("db_tablespace")
            .tag("db_name", db_name)
            .tag("db_type", "postgresql")
            .tag("name", str(row[0]))
            .field("total_bytes", int(row[1] or 0))
            .field("used_bytes", int(row[1] or 0))
            .field("free_bytes", 0)
            .field("usage_pct", 0.0)
            .time(now, WritePrecision.S)
        )

    # 5. 后台写入统计
    try:
        cur.execute(
            "SELECT checkpoints_timed, checkpoints_req, buffers_checkpoint, "
            "buffers_clean, buffers_backend, buffers_alloc FROM pg_stat_bgwriter"
        )
        row = cur.fetchone()
        if row:
            points.append(
                Point("db_memory")
                .tag("db_name", db_name)
                .tag("db_type", "postgresql")
                .tag("type", "bgwriter")
                .field("checkpoints_timed", int(row[0] or 0))
                .field("checkpoints_req", int(row[1] or 0))
                .field("buffers_checkpoint", int(row[2] or 0))
                .field("buffers_clean", int(row[3] or 0))
                .field("buffers_backend", int(row[4] or 0))
                .field("buffers_alloc", int(row[5] or 0))
                .time(now, WritePrecision.S)
            )
    except Exception as e:
        print(f"[PostgreSQL] bgwriter error: {e}")

    conn.close()
    return points


# ─── 连接测试 ─────────────────────────────────────────────

COLLECTORS = {
    "oracle": collect_oracle,
    "mysql": collect_mysql,
    "postgresql": collect_postgresql,
}


def test_connection(config):
    db_type = config["db_type"]
    try:
        if db_type == "oracle":
            import oracledb
            dsn = f"{config['host']}:{config['port']}/{config['service_name']}"
            conn = oracledb.connect(user=config["username"], password=config["password"], dsn=dsn)
            cur = conn.cursor()
            cur.execute("SELECT status, instance_name FROM v$instance")
            row = cur.fetchone()
            conn.close()
            return True, f"连接成功 - 实例: {row[1]}, 状态: {row[0]}"

        elif db_type == "mysql":
            import pymysql
            conn = pymysql.connect(
                host=config["host"], port=config["port"],
                user=config["username"], password=config["password"],
                database=config["service_name"], connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()[0]
            conn.close()
            return True, f"连接成功 - MySQL {ver}"

        elif db_type == "postgresql":
            import psycopg2
            conn = psycopg2.connect(
                host=config["host"], port=config["port"],
                user=config["username"], password=config["password"],
                dbname=config["service_name"], connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute("SELECT version()")
            ver = cur.fetchone()[0]
            conn.close()
            return True, f"连接成功 - {ver}"

        else:
            return False, f"不支持的数据库类型: {db_type}"
    except Exception as e:
        return False, str(e)


# ─── 主入口 ───────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: collector_worker.py <connection_id> [--test]")
        sys.exit(1)

    cid = int(sys.argv[1])
    test_mode = len(sys.argv) > 2 and sys.argv[2] == "--test"

    config = load_config(cid)
    if not config:
        print(f"Configuration {cid} not found")
        sys.exit(1)

    if test_mode:
        ok, msg = test_connection(config)
        if ok:
            print(msg)
            sys.exit(0)
        else:
            print(f"连接失败: {msg}", file=sys.stderr)
            sys.exit(1)

    db_type = config["db_type"]
    collector = COLLECTORS.get(db_type)
    if not collector:
        print(f"Unsupported db_type: {db_type}")
        sys.exit(1)

    influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    interval = config["collect_interval"] or 10
    print(f"[{datetime.now()}] Collector started: '{config['name']}' ({db_type}), interval={interval}s")

    while True:
        try:
            points = collector(config)
            if points:
                write_api.write(bucket=INFLUX_BUCKET, record=points)
                update_status(cid, "running")
                print(f"[{datetime.now()}] Collected {len(points)} points")
            else:
                print(f"[{datetime.now()}] No points collected")
        except Exception as e:
            update_status(cid, "error", str(e))
            print(f"[{datetime.now()}] ERROR: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
