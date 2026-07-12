#!/bin/bash
# ============================================================
# Stage 4-5: Python 环境搭建 + 采集脚本部署 + systemd 服务
# 用法: sudo bash 07-deploy-collector.sh
# 前提: 01-system-init.sh 已执行
# ============================================================

set -e

WORK_DIR="/opt/oracle-monitor"
SCRIPTS_DIR="$WORK_DIR/scripts"

echo "===== [1/6] 创建 Python 虚拟环境 ====="
python3 -m venv "$SCRIPTS_DIR/venv"

echo "===== [2/6] 安装 Python 依赖 ====="
"$SCRIPTS_DIR/venv/bin/pip" install --upgrade pip
"$SCRIPTS_DIR/venv/bin/pip" install oracledb influxdb-client APScheduler

echo "===== [3/6] 验证依赖安装 ====="
"$SCRIPTS_DIR/venv/bin/python" -c "
import oracledb; print(f'oracledb: {oracledb.__version__}')
import influxdb_client; print(f'influxdb-client: {influxdb_client.__version__}')
import apscheduler; print(f'APScheduler: {apscheduler.__version__}')
"

echo "===== [4/6] 检查配置文件 ====="
if [ ! -f "$SCRIPTS_DIR/config.env" ]; then
    echo "警告: config.env 不存在, 请复制 04-config.env 并修改!"
    echo "  cp 04-config.env $SCRIPTS_DIR/config.env"
    echo "  vim $SCRIPTS_DIR/config.env"
    exit 1
fi
echo "配置文件: $SCRIPTS_DIR/config.env"

echo "===== [5/6] 安装 systemd 服务 ====="
cp 06-oracle-monitor.service /etc/systemd/system/oracle-monitor.service
systemctl daemon-reload
systemctl enable oracle-monitor

echo "===== [6/6] 启动服务 ====="
systemctl start oracle-monitor
sleep 3
systemctl status oracle-monitor --no-pager

echo ""
echo "========================================"
echo "  采集脚本部署完成!"
echo "========================================"
echo ""
echo "  常用命令:"
echo "    查看状态:  systemctl status oracle-monitor"
echo "    查看日志:  journalctl -u oracle-monitor -f"
echo "    重启服务:  systemctl restart oracle-monitor"
echo "    停止服务:  systemctl stop oracle-monitor"
echo ""
echo "  查看采集日志:"
echo "    tail -f $WORK_DIR/logs/collector.log"
echo "========================================"
