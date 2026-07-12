#!/bin/bash
# ============================================================
# Stage 6: 验证 + Grafana 数据源配置检查
# 用法: bash 08-verify.sh
# ============================================================

set -e

echo "===== [1/5] 检查 Docker 容器状态 ====="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "monitor|NAME"

echo ""
echo "===== [2/5] 检查 InfluxDB 健康 ====="
curl -s http://localhost:8086/health | python3 -m json.tool 2>/dev/null || echo "InfluxDB 未就绪, 请检查"

echo ""
echo "===== [3/5] 检查 Grafana 健康 ====="
curl -s http://localhost:3000/api/health | python3 -m json.tool 2>/dev/null || echo "Grafana 未就绪, 请检查"

echo ""
echo "===== [4/5] 检查采集服务状态 ====="
systemctl is-active oracle-monitor 2>/dev/null && echo "采集服务: 运行中" || echo "采集服务: 未运行"

echo ""
echo "===== [5/5] 检查最近采集日志 ====="
LOG_FILE="/opt/oracle-monitor/logs/collector.log"
if [ -f "$LOG_FILE" ]; then
    echo "--- 最近 20 行日志 ---"
    tail -20 "$LOG_FILE"
else
    echo "日志文件不存在: $LOG_FILE"
fi

echo ""
echo "========================================"
echo "  验证完成!"
echo "========================================"
echo ""
echo "  下一步:"
echo "    1. 浏览器打开 http://服务器IP:3000"
echo "       账号: admin  密码: grafana123"
echo ""
echo "    2. 添加 InfluxDB 数据源:"
echo "       URL: http://influxdb:8086 (容器间通信用服务名)"
echo "       或:  http://localhost:8086 (本机)"
echo "       Token: my-super-secret-token-1234567890"
echo "       Organization: myorg"
echo "       Bucket: oracle_metrics"
echo ""
echo "    3. 创建仪表盘, 添加面板查询示例:"
echo '       from(bucket: "oracle_metrics")'
echo '         |> range(start: v.timeRangeStart, stop: v.timeRangeStop)'
echo '         |> filter(fn: (r) => r._measurement == "oracle_sessions")'
echo '         |> filter(fn: (r) => r._field == "active")'
echo "========================================"
