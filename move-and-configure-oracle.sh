#!/bin/bash
# Move extracted Oracle files to correct locations and configure
set -x

echo "=== Step 1: Move Oracle files to correct locations ==="
cd /opt/oracle-monitor/oracle-install

# Move /opt/oracle to the real /opt/oracle
mkdir -p /opt/oracle
cp -a opt/oracle/* /opt/oracle/
echo "Oracle files moved to /opt/oracle/"

# Move /etc files
cp -a etc/* /etc/
echo "Config files moved to /etc/"

# Move /usr files (build-id, doc)
cp -a usr/* /usr/
echo "USR files moved"

echo "=== Step 2: Clean up alien directory ==="
rm -rf oracle-database-xe-21c-1.0
echo "Alien directory cleaned"

echo "=== Step 3: Fix ownership and permissions ==="
chown -R oracle:oinstall /opt/oracle
chmod +x /etc/init.d/oracle-xe-21c
echo "Ownership fixed"

echo "=== Step 4: Create required directories ==="
mkdir -p /opt/oracle/oradata/XE
mkdir -p /opt/oracle/admin/XE/adump
mkdir -p /opt/oracle/fast_recovery_area/XE
mkdir -p /var/log/oracle
chown -R oracle:oinstall /opt/oracle
echo "Directories created"

echo "=== Step 5: Set up Oracle environment ==="
cat > /etc/profile.d/oracle.sh << 'ENVEOF'
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib
ENVEOF
chmod 755 /etc/profile.d/oracle.sh

echo "=== Step 6: Check init script ==="
cat /etc/init.d/oracle-xe-21c | head -20
echo "---"

echo "=== Step 7: Verify sqlplus exists ==="
ls -la /opt/oracle/product/21c/dbhomeXE/bin/sqlplus
echo "SQLPLUS verified"

echo "=== Step 8: Run Oracle XE configure ==="
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

# Fix libaio symlink issue on Ubuntu
ln -sf /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 2>/dev/null
ln -sf /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /lib/x86_64-linux-gnu/libaio.so.1 2>/dev/null

# Run configure
echo "Running oracle-xe-21c configure..."
(echo "Oracle123"; echo "Oracle123") | /etc/init.d/oracle-xe-21c configure 2>&1

echo "=== CONFIGURE_EXIT_CODE=$? ==="

echo "=== Step 9: Verify Oracle is running ==="
sleep 5
$ORACLE_HOME/bin/sqlplus -s /nolog << 'SQLEOF'
connect / as sysdba
SELECT status FROM v$instance;
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
exit;
SQLEOF

echo "=== Step 10: Check listener ==="
$ORACLE_HOME/bin/lsnrctl status 2>&1 | head -15

echo "=== DONE ==="
echo "ORACLE_CONFIG_COMPLETE" > /tmp/oracle-config-status.txt
