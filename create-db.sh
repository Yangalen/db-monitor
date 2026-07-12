#!/bin/bash
# Create Oracle database using DBCA directly
set -x

export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Step 1: Create oracle user home directory ==="
mkdir -p /home/oracle
chown oracle:oinstall /home/oracle
usermod -d /home/oracle oracle
echo "Oracle home directory created"

echo "=== Step 2: Create oratab file ==="
cat > /etc/oratab << 'ORATABEOF'
XE:/opt/oracle/product/21c/dbhomeXE:Y
ORATABEOF
chmod 664 /etc/oratab
echo "Oratab created"

echo "=== Step 3: Stop listener and clean up ==="
$ORACLE_HOME/bin/lsnrctl stop 2>&1
rm -rf /opt/oracle/oradata/XE
rm -rf /opt/oracle/admin/XE
rm -rf /opt/oracle/fast_recovery_area/XE
rm -rf /opt/oracle/cfgtoollogs/dbca
mkdir -p /opt/oracle/oradata/XE
mkdir -p /opt/oracle/admin/XE/adump
mkdir -p /opt/oracle/fast_recovery_area/XE
chown -R oracle:oinstall /opt/oracle
echo "Cleaned up"

echo "=== Step 4: Run DBCA to create database ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

# Start listener
\$ORACLE_HOME/bin/lsnrctl start 2>&1

# Create database using DBCA
\$ORACLE_HOME/bin/dbca -silent -createDatabase \
  -templateName XE_Database.dbc \
  -gdbName XE \
  -sid XE \
  -createAsContainerDatabase true \
  -numberOfPDBs 1 \
  -pdbName XEPDB1 \
  -pdbAdminPassword Oracle123 \
  -sysPassword Oracle123 \
  -systemPassword Oracle123 \
  -emConfiguration NONE \
  -storageType FS \
  -datafileDestination /opt/oracle/oradata \
  -recoveryAreaDestination /opt/oracle/fast_recovery_area \
  -characterSet AL32UTF8 \
  -nationalCharacterSet AL16UTF16 \
  -totalMemory 1024 \
  -databaseType MULTIPURPOSE \
  -initparams processes=300 2>&1
" 2>&1

echo "DBCA_EXIT=$?"

echo "=== Step 5: Check what was created ==="
ls -la /opt/oracle/oradata/XE/ 2>/dev/null
echo "---"
ls -la $ORACLE_HOME/dbs/ 2>/dev/null

echo "=== Step 6: Try to start the database ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

\$ORACLE_HOME/bin/sqlplus -s /nolog << 'SQLEOF'
connect sys/Oracle123 as sysdba
startup mount;
alter database open;
SELECT status FROM v\$instance;
SELECT banner_full FROM v\$version WHERE ROWNUM = 1;
exit;
SQLEOF
" 2>&1

echo "=== Step 7: Check listener ==="
$ORACLE_HOME/bin/lsnrctl status 2>&1

echo "=== DONE ==="
echo "DBCA_CREATE_COMPLETE" > /tmp/dbca-create-status.txt
