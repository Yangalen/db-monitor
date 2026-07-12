#!/bin/bash
# Oracle 21c auto-start configuration for Ubuntu
# Run: sudo bash config-oracle-autostart.sh

set -e

echo "===== [1/3] 持久化 ASLR=0 ====="
echo "kernel.randomize_va_space=0" > /etc/sysctl.d/99-oracle.conf
sysctl -p /etc/sysctl.d/99-oracle.conf
echo "  ASLR persisted: $(cat /proc/sys/kernel/randomize_va_space)"

echo "===== [2/3] 创建 Oracle systemd 服务 ====="
cat > /etc/systemd/system/oracle-db.service << 'UNIT'
[Unit]
Description=Oracle Database 21c XE
After=network.target
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=oracle
Environment=ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
Environment=ORACLE_SID=XE
Environment=ORACLE_BASE=/opt/oracle
Environment=LD_LIBRARY_PATH=/opt/oracle/product/21c/dbhomeXE/lib
ExecStart=/opt/oracle/product/21c/dbhomeXE/bin/dbstart /opt/oracle/product/21c/dbhomeXE
ExecStop=/opt/oracle/product/21c/dbhomeXE/bin/dbshut /opt/oracle/product/21c/dbhomeXE

[Install]
WantedBy=multi-user.target
UNIT

echo "===== [3/3] 启用服务 ====="
systemctl daemon-reload
systemctl enable oracle-db
echo "  Oracle auto-start enabled"

echo ""
echo "===== Oracle 开机自启配置完成 ====="
echo "  ASLR: /etc/sysctl.d/99-oracle.conf"
echo "  Service: oracle-db.service (enabled)"
echo "  oratab: XE:/opt/oracle/product/21c/dbhomeXE:Y"
