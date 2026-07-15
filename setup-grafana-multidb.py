#!/usr/bin/env python3
"""创建多数据库监控 Grafana 仪表盘

使用通用 measurement 名称（db_instance / db_session / db_performance / db_memory / db_tablespace / db_wait_events），
支持按 db_name 标签筛选不同数据库。
"""
import requests
import json
import sys

GRAFANA_URL = "http://localhost:3000"
GRAFANA_USER = "admin"
GRAFANA_PASS = "grafana123"
DATASOURCE_UID = "influxdb_oracle"

INFLUX_BUCKET = "oracle_metrics"

def api(method, path, data=None):
    url = f"{GRAFANA_URL}{path}"
    r = requests.request(method, url, auth=(GRAFANA_USER, GRAFANA_PASS),
                         json=data, headers={"Content-Type": "application/json"})
    return r.json()

# ─── 检查数据源 UID ──────────────────────────────────────

def get_datasource_uid():
    r = requests.get(f"{GRAFANA_URL}/api/datasources", auth=(GRAFANA_USER, GRAFANA_PASS))
    sources = r.json()
    for s in sources:
        if s.get("type") == "influxdb":
            return s.get("uid", s.get("id"))
    print("WARNING: No InfluxDB datasource found", file=sys.stderr)
    return None

# ─── 构建仪表盘 ──────────────────────────────────────────

def build_dashboard():
    ds_uid = get_datasource_uid()
    if not ds_uid:
        print("ERROR: Cannot find InfluxDB datasource", file=sys.stderr)
        sys.exit(1)

    print(f"Using datasource UID: {ds_uid}")

    def flux(query, ref_id="A"):
        return {
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r["_measurement"] == "{query}")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> last()',
            "refId": ref_id,
        }

    def flux_field(measurement, field, ref_id="A", agg="last"):
        return {
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r["_measurement"] == "{measurement}")\n  |> filter(fn: (r) => r["_field"] == "{field}")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> aggregateWindow(every: v.windowPeriod, fn: {agg}, createEmpty: false)',
            "refId": ref_id,
        }

    def flux_grouped(measurement, field, group_tag, ref_id="A", agg="last"):
        return {
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r["_measurement"] == "{measurement}")\n  |> filter(fn: (r) => r["_field"] == "{field}")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> group(columns: ["{group_tag}"])\n  |> aggregateWindow(every: v.windowPeriod, fn: {agg}, createEmpty: false)',
            "refId": ref_id,
        }

    panels = []
    y = 0

    # Row 1: 状态指标 (4 stat panels)
    # Panel 1: 实例状态
    panels.append({
        "id": 1, "type": "stat", "title": "实例状态",
        "gridPos": {"h": 4, "w": 6, "x": 0, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_instance")\n  |> filter(fn: (r) => r["_field"] == "status_str")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> last()',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"mappings": [], "thresholds": {"mode": "exact", "steps": [
            {"color": "red", "value": None},
            {"color": "green", "value": "OPEN"},
            {"color": "green", "value": "ACCEPTING_CONNECTIONS"},
        ]}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False}, "textMode": "value"},
    })

    # Panel 2: 会话总数 / 活跃
    panels.append({
        "id": 2, "type": "stat", "title": "会话统计",
        "gridPos": {"h": 4, "w": 6, "x": 6, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [
            flux_field("db_session", "total", "A"),
            flux_field("db_session", "active", "B"),
        ],
        "fieldConfig": {"defaults": {"unit": "short", "thresholds": {"mode": "absolute", "steps": [
            {"color": "green", "value": None},
            {"color": "yellow", "value": 100},
            {"color": "red", "value": 500},
        ]}}, "overrides": [
            {"matcher": {"id": "byName", "options": "active"}, "properties": [{"id": "color", "value": "orange"}]},
        ]},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "textMode": "value_and_name"},
    })

    # Panel 3: 缓存命中率
    hit_ratio_field = "buffer_cache_hit_ratio"  # Oracle
    panels.append({
        "id": 3, "type": "gauge", "title": "缓存命中率",
        "gridPos": {"h": 4, "w": 6, "x": 12, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_performance")\n  |> filter(fn: (r) => r["_field"] =~ /hit_ratio|cache_hit/)\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> last()',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": [
            {"color": "red", "value": None},
            {"color": "yellow", "value": 80},
            {"color": "green", "value": 95},
        ]}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })

    # Panel 4: PGA/内存
    panels.append({
        "id": 4, "type": "stat", "title": "PGA 已分配",
        "gridPos": {"h": 4, "w": 6, "x": 18, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_memory")\n  |> filter(fn: (r) => r["_field"] == "bytes")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> filter(fn: (r) => r["name"] == "total PGA allocated" or r["name"] == "total PGA inuse")\n  |> last()',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "bytes", "thresholds": {"mode": "absolute", "steps": [
            {"color": "green", "value": None},
        ]}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "textMode": "value"},
    })

    y += 4

    # Row 2: 趋势图
    # Panel 5: 会话数趋势
    panels.append({
        "id": 5, "type": "timeseries", "title": "会话数趋势",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [
            flux_field("db_session", "total", "A"),
            flux_field("db_session", "active", "B"),
            flux_field("db_session", "blocked", "C"),
        ],
        "fieldConfig": {"defaults": {"unit": "short", "custom": {"drawStyle": "line", "lineInterpolation": "smooth", "fillOpacity": 10}}, "overrides": [
            {"matcher": {"id": "byName", "options": "active"}, "properties": [{"id": "color", "value": "orange"}]},
            {"matcher": {"id": "byName", "options": "blocked"}, "properties": [{"id": "color", "value": "red"}]},
        ]},
        "options": {"legend": {"displayMode": "table", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    })

    # Panel 6: 缓存命中率趋势
    panels.append({
        "id": 6, "type": "timeseries", "title": "缓存命中率趋势",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r["_measurement"] == "db_performance")\n  |> filter(fn: (r) => r["_field"] =~ /hit_ratio|cache_hit/)\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "custom": {"drawStyle": "line", "lineInterpolation": "smooth", "fillOpacity": 20}}, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    })

    y += 8

    # Row 3: 表空间 + 内存
    # Panel 7: 表空间使用率
    panels.append({
        "id": 7, "type": "barchart", "title": "表空间 / 数据库使用率",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_tablespace")\n  |> filter(fn: (r) => r["_field"] == "usage_pct")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> group(columns: ["name"])\n  |> last()\n  |> group()\n  |> keep(columns: ["name", "_value", "_time"])',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": [
            {"color": "green", "value": None},
            {"color": "yellow", "value": 70},
            {"color": "red", "value": 90},
        ]}}, "overrides": []},
        "options": {"xField": "name", "orientation": "auto"},
    })

    # Panel 8: SGA 内存分布
    panels.append({
        "id": 8, "type": "barchart", "title": "SGA / PGA 内存分布",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_memory")\n  |> filter(fn: (r) => r["_field"] == "bytes")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> group(columns: ["type", "name"])\n  |> last()\n  |> group()\n  |> keep(columns: ["type", "name", "_value", "_time"])',
            "refId": "A",
        }],
        "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
        "options": {"xField": "name", "orientation": "auto"},
    })

    y += 8

    # Row 4: 等待事件 + 性能
    # Panel 9: TOP 等待事件
    panels.append({
        "id": 9, "type": "table", "title": "TOP 10 等待事件",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [{
            "datasource": {"type": "influxdb", "uid": ds_uid},
            "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -5m)\n  |> filter(fn: (r) => r["_measurement"] == "db_wait_events")\n  |> filter(fn: (r) => r["_field"] == "time_waited_ms")\n  |> filter(fn: (r) => r["db_name"] == "${{db_name}}")\n  |> group(columns: ["event"])\n  |> last()\n  |> sort(columns: ["_value"], desc: true)\n  |> limit(n: 10)',
            "refId": "A",
        }],
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"_start": True, "_stop": True, "result": True, "table": True, "_time": True}, "renameByName": {"_value": "等待时间(ms)", "event": "事件名"}}},
        ],
        "fieldConfig": {"defaults": {}, "overrides": [
            {"matcher": {"id": "byName", "options": "等待时间(ms)"}, "properties": [{"id": "unit", "value": "ms"}]},
        ]},
    })

    # Panel 10: 物理读写趋势
    panels.append({
        "id": 10, "type": "timeseries", "title": "物理读 / 写趋势",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
        "datasource": {"type": "influxdb", "uid": ds_uid},
        "targets": [
            flux_field("db_performance", "physical_reads", "A"),
            flux_field("db_performance", "physical_writes", "B"),
        ],
        "fieldConfig": {"defaults": {"unit": "short", "custom": {"drawStyle": "line", "lineInterpolation": "smooth", "fillOpacity": 10}}, "overrides": [
            {"matcher": {"id": "byName", "options": "physical_reads"}, "properties": [{"id": "color", "value": "blue"}]},
            {"matcher": {"id": "byName", "options": "physical_writes"}, "properties": [{"id": "color", "value": "purple"}]},
        ]},
        "options": {"legend": {"displayMode": "table", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    })

    # ─── 构建仪表盘 JSON ──────────────────────────────────

    dashboard = {
        "dashboard": {
            "id": None,
            "uid": "multi-db-monitor",
            "title": "多数据库监控总览",
            "tags": ["oracle", "mysql", "postgresql", "monitoring"],
            "timezone": "browser",
            "schemaVersion": 38,
            "version": 0,
            "refresh": "10s",
            "time": {"from": "now-30m", "to": "now"},
            "templating": {
                "list": [{
                    "name": "db_name",
                    "type": "query",
                    "datasource": {"type": "influxdb", "uid": ds_uid},
                    "query": f'from(bucket: "{INFLUX_BUCKET}")\n  |> range(start: -1h)\n  |> filter(fn: (r) => r["_measurement"] == "db_instance")\n  |> filter(fn: (r) => r["_field"] == "status_str")\n  |> group(columns: ["db_name"])\n  |> distinct(column: "db_name")',
                    "refresh": 1,
                    "current": {"text": "", "value": ""},
                    "multi": False,
                    "includeAll": False,
                    "regex": "",
                }]
            },
            "panels": panels,
        },
        "folderId": 0,
        "overwrite": True,
    }

    return dashboard


def main():
    print("Creating multi-database monitoring dashboard...")
    payload = build_dashboard()

    r = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        auth=(GRAFANA_USER, GRAFANA_PASS),
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    result = r.json()
    if r.status_code == 200 and result.get("status") == "success":
        url = result.get("url", "")
        print(f"Dashboard created successfully!")
        print(f"  Title: {payload['dashboard']['title']}")
        print(f"  UID: {payload['dashboard']['uid']}")
        print(f"  Panels: {len(payload['dashboard']['panels'])}")
        print(f"  URL: {GRAFANA_URL}{url}")
    else:
        print(f"ERROR: {r.status_code} - {result}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
