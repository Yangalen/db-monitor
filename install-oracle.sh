#!/bin/bash
# Download and install Oracle XE 21c on Ubuntu
set -e

echo "=== Step 1: Install prerequisites ==="
apt-get install -y libaio1t64 alien unixodbc bc prelink 2>&1 | tail -3
echo "Prerequisites installed."

echo "=== Step 2: Create download directory ==="
mkdir -p /opt/oracle-monitor/oracle-install
cd /opt/oracle-monitor/oracle-install

echo "=== Step 3: Download Oracle XE 21c RPM (2.5GB, please wait...) ==="
curl -L -o oracle-database-xe-21c.rpm \
  "https://download.oracle.com/otn-pub/otn_software/db-express/oracle-database-xe-21c-1.0-1.ol8.x86_64.rpm" \
  --progress-bar 2>&1

echo "=== Step 4: Verify download ==="
ls -lh oracle-database-xe-21c.rpm
echo "DOWNLOAD_COMPLETE" > /tmp/oracle-rpm-status.txt

echo "=== Step 5: Convert RPM to DEB ==="
alien --scripts -d oracle-database-xe-21c.rpm 2>&1 | tail -5

echo "=== Step 6: Install Oracle XE ==="
dpkg -i oracle-database-xe-21c*.deb 2>&1 | tail -10

echo "=== Step 7: Configure Oracle XE ==="
# Set default password and configure
echo "Setting up Oracle XE configuration..."
cat > /tmp/oracle-xe-config.rsp << 'EOF'
# Oracle XE configuration response file
# Password will be set to Oracle123
EOF

# Configure with password
(echo "Oracle123"; echo "Oracle123") | /etc/init.d/oracle-xe-21c configure 2>&1 | tail -20

echo "=== Step 8: Verify Oracle installation ==="
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export PATH=$PATH:$ORACLE_HOME/bin

sqlplus -s /nolog << 'SQLEOF'
connect / as sysdba
SELECT status FROM v$instance;
SELECT banner FROM v$version WHERE ROWNUM = 1;
exit;
SQLEOF

echo "=== DONE ==="
echo "ORACLE_INSTALL_COMPLETE" > /tmp/oracle-rpm-status.txt
