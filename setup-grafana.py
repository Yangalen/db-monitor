#!/usr/bin/env python3
"""
Grafana 配置脚本 — 通过 HTTP API 创建 InfluxDB 数据源 + 监控仪表盘
运行: python3 setup-grafana.py
"""
import json
import requests
import sys

GRAFANA_URL = "http://localhost:3000"
GRAFANA_USER = "admin"
GRAFANA_PASS = "grafana123"

INFLUXDB_URL = "http://monitor-influxdb:8086"
INFLUXDB_TOKEN = "my-super-secret-token-1234567890"
INFLUXDB_ORG = "myorg"
INFLUXDB_BUCKET = "oracle_metrics"

auth = (GRAFANA_USER, GRAFANA_PASS)
headers = {"Content-Type": "application/json"}


def create_datasource():
    """创建 InfluxDB 数据源"""
    print("===== [1/2] 创建 InfluxDB 数据源 =====")

    # 先检查是否已存在
    resp = requests.get(f"{GRAFANA_URL}/api/datasources/name/InfluxDB", auth=auth)
    if resp.status_code == 200:
        print("  数据源已存在, 跳过创建")
        return resp.json()["id"]

    payload = {
        "name": "InfluxDB",
        "type": "influxdb",
        "uid": "influxdb_oracle",
        "url": INFLUXDB_URL,
        "access": "proxy",
        "isDefault": True,
        "jsonData": {
            "version": "Flux",
            "organization": INFLUXDB_ORG,
            "defaultBucket": INFLUXDB_BUCKET,
            "tlsSkipVerify": True,
        },
        "secureJsonData": {
            "token": INFLUXDB_TOKEN,
        },
    }

    resp = requests.post(
        f"{GRAFANA_URL}/api/datasources",
        auth=auth,
        headers=headers,
        json=payload,
    )

    if resp.status_code in (200, 201):
        ds_id = resp.json()["datasource"]["id"]
        print(f"  数据源创建成功, ID={ds_id}")
        return ds_id
    else:
        print(f"  创建失败: {resp.status_code} {resp.text}")
        sys.exit(1)


def create_dashboard():
    """创建 Oracle 监控仪表盘"""
    print("===== [2/2] 创建监控仪表盘 =====")

    dashboard = {
        "dashboard": {
            "id": None,
            "uid": "oracle-db-monitor",
            "title": "Oracle 数据库监控",
            "tags": ["oracle", "monitoring"],
            "timezone": "browser",
            "schemaVersion": 38,
            "version": 0,
            "refresh": "10s",
            "time": {"from": "now-1h", "to": "now"},
            "panels": [],
        },
        "overwrite": True,
    }

    panels = []
    y_pos = 0
    panel_id = 1

    # ---- Panel 1: 实例状态 ----
    panels.append({
        "id": panel_id, "type": "stat", "title": "实例状态",
        "gridPos": {"h": 4, "w": 4, "x": 0, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_instance" and r._field == "status_open") |> last()',
        }],
        "fieldConfig": {
            "defaults": {
                "mappings": [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "OPEN", "color": "green"}}}],
                "thresholds": {"mode": "absolute", "steps": [{"color": "red"}, {"color": "green", "value": 1}]},
            },
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background"},
    })
    panel_id += 1

    # ---- Panel 2: 会话统计 ----
    panels.append({
        "id": panel_id, "type": "stat", "title": "会话统计",
        "gridPos": {"h": 4, "w": 8, "x": 4, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [
            {"refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_sessions" and r._field == "total") |> last()',
             "legendFormat": "总会话"},
            {"refId": "B", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_sessions" and r._field == "active") |> last()',
             "legendFormat": "活跃"},
            {"refId": "C", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_sessions" and r._field == "blocked") |> last()',
             "legendFormat": "阻塞"},
        ],
        "fieldConfig": {"defaults": {"unit": "short"}},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "orientation": "horizontal"},
    })
    panel_id += 1

    # ---- Panel 3: Buffer Cache 命中率 ----
    panels.append({
        "id": panel_id, "type": "gauge", "title": "Buffer Cache 命中率",
        "gridPos": {"h": 4, "w": 4, "x": 12, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "buffer_cache_hit_pct") |> last()',
        }],
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "min": 0, "max": 100,
                "thresholds": {"mode": "absolute", "steps": [{"color": "red"}, {"color": "yellow", "value": 80}, {"color": "green", "value": 95}]},
            },
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })
    panel_id += 1

    # ---- Panel 4: 硬解析率 ----
    panels.append({
        "id": panel_id, "type": "stat", "title": "硬解析率",
        "gridPos": {"h": 4, "w": 4, "x": 16, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "hard_parse_pct") |> last()',
        }],
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "thresholds": {"mode": "absolute", "steps": [{"color": "green"}, {"color": "yellow", "value": 10}, {"color": "red", "value": 30}]},
            },
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background"},
    })
    panel_id += 1

    # ---- Panel 5: PGA 内存使用 ----
    panels.append({
        "id": panel_id, "type": "stat", "title": "PGA 已分配",
        "gridPos": {"h": 4, "w": 4, "x": 20, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_memory" and r._field == "bytes" and r.type == "PGA" and r.name == "total PGA allocated") |> last()',
        }],
        "fieldConfig": {"defaults": {"unit": "bytes"}},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })
    panel_id += 1

    y_pos += 4

    # ---- Panel 6: 会话趋势图 ----
    panels.append({
        "id": panel_id, "type": "timeseries", "title": "会话数趋势",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [
            {"refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_sessions" and r._field == "total") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
             "legendFormat": "总会话"},
            {"refId": "B", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_sessions" and r._field == "active") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
             "legendFormat": "活跃会话"},
        ],
        "fieldConfig": {"defaults": {"unit": "short"}},
    })
    panel_id += 1

    # ---- Panel 7: Buffer Cache 命中率趋势 ----
    panels.append({
        "id": panel_id, "type": "timeseries", "title": "Buffer Cache 命中率趋势",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "buffer_cache_hit_pct") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
            "legendFormat": "命中率 %",
        }],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100}},
    })
    panel_id += 1

    y_pos += 8

    # ---- Panel 8: 表空间使用率 ----
    panels.append({
        "id": panel_id, "type": "bargauge", "title": "表空间使用率",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_tablespace" and r._field == "used_pct") |> last()',
            "legendFormat": "{{tablespace}}",
        }],
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "min": 0, "max": 100,
                "thresholds": {"mode": "absolute", "steps": [{"color": "green"}, {"color": "yellow", "value": 70}, {"color": "red", "value": 90}]},
            },
        },
        "options": {"orientation": "horizontal", "displayMode": "gradient"},
    })
    panel_id += 1

    # ---- Panel 9: SGA 内存分布 ----
    panels.append({
        "id": panel_id, "type": "bargauge", "title": "SGA 内存分布",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_memory" and r._field == "bytes" and r.type == "SGA") |> last()',
            "legendFormat": "{{name}}",
        }],
        "fieldConfig": {"defaults": {"unit": "bytes"}},
        "options": {"orientation": "horizontal", "displayMode": "gradient"},
    })
    panel_id += 1

    y_pos += 8

    # ---- Panel 10: TOP 等待事件 ----
    panels.append({
        "id": panel_id, "type": "table", "title": "TOP 10 等待事件",
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [{
            "refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
            "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_wait_events" and r._field == "time_waited_ms") |> last() |> sort(desc: true) |> limit(n: 10)',
            "format": "table",
        }],
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"_start": True, "_stop": True, "result": True, "table": True, "_time": True}, "renameByName": {"_value": "等待时间(ms)", "event": "事件名"}}},
        ],
    })
    panel_id += 1

    y_pos += 10

    # ---- Panel 11: 性能指标趋势 ----
    panels.append({
        "id": panel_id, "type": "timeseries", "title": "物理读 & 一致性读趋势",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": y_pos},
        "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
        "targets": [
            {"refId": "A", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "physical_reads") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
             "legendFormat": "物理读"},
            {"refId": "B", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "consistent_gets") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
             "legendFormat": "一致性读"},
            {"refId": "C", "datasource": {"type": "influxdb", "uid": "influxdb_oracle"},
             "query": f'from(bucket: "{INFLUXDB_BUCKET}") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> filter(fn: (r) => r._measurement == "oracle_performance" and r._field == "db_block_gets") |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)',
             "legendFormat": "DB Block Gets"},
        ],
        "fieldConfig": {"defaults": {"unit": "short"}},
    })
    panel_id += 1

    dashboard["dashboard"]["panels"] = panels

    # 检查是否已存在
    resp = requests.get(f"{GRAFANA_URL}/api/dashboards/title/oracle-monitor", auth=auth)
    if resp.status_code == 200 and resp.json().get("dashboard"):
        dashboard["dashboard"]["id"] = resp.json()["dashboard"]["id"]
        print("  仪表盘已存在, 将更新")

    resp = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        auth=auth,
        headers=headers,
        json=dashboard,
    )

    if resp.status_code in (200, 201):
        result = resp.json()
        print(f"  仪表盘创建成功! URL: {result.get('url', 'N/A')}")
        return result
    else:
        print(f"  创建失败: {resp.status_code} {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 60)
    print("  Grafana 配置脚本 — Oracle 监控")
    print("=" * 60)

    ds_id = create_datasource()
    create_dashboard()

    print()
    print("=" * 60)
    print("  配置完成!")
    print(f"  Grafana: http://localhost:3000  (admin / grafana123)")
    print(f"  仪表盘:  左侧菜单 → Dashboards → Oracle 数据库监控")
    print("=" * 60)
