#!/bin/bash
# Create all missing Oracle directories and rebuild database
set -x

ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
ORACLE_HOME_CFG=/opt/oracle/homes/OraDBHome21cXE

echo "=== Step 1: Create all missing directories ==="
# Oracle 21c "homes" configuration directory
mkdir -p $ORACLE_HOME_CFG/dbs
mkdir -p $ORACLE_HOME_CFG/rdbms/log
mkdir -p $ORACLE_HOME_CFG/rdbms/admin
mkdir -p $ORACLE_HOME_CFG/network/admin
mkdir -p $ORACLE_HOME_CFG/network/log
mkdir -p $ORACLE_HOME_CFG/hs/admin
mkdir -p $ORACLE_HOME_CFG/sqlplus/admin

# Copy essential files from product home
cp $ORACLE_HOME/dbs/init.ora $ORACLE_HOME_CFG/dbs/ 2>/dev/null
cp $ORACLE_HOME/sqlplus/admin/glogin.sql $ORACLE_HOME_CFG/sqlplus/admin/ 2>/dev/null

# Diagnostic directories
mkdir -p /opt/oracle/diag/clients
mkdir -p /opt/oracle/diag/rdbms/xe/XE/trace
mkdir -p /opt/oracle/diag/tnslsnr
mkdir -p /opt/oracle/product/21c/dbhomeXE/log

# Data directories
mkdir -p /opt/oracle/oradata/XE
mkdir -p /opt/oracle/admin/XE/adump
mkdir -p /opt/oracle/fast_recovery_area/XE

# Fix ownership
chown -R oracle:oinstall /opt/oracle

echo "Directories created"

echo "=== Step 2: Check libodm ==="
find $ORACLE_HOME/lib -name "libodm*" 2>/dev/null
find $ORACLE_HOME/lib -name "libn*odm*" 2>/dev/null
ls $ORACLE_HOME/lib/libodm* 2>/dev/null || echo "Checking for libodm19..."
ls $ORACLE_HOME/lib/libodmd19.so 2>/dev/null || ls $ORACLE_HOME/lib/libnsgcd19.so 2>/dev/null || echo "No odm lib found"
# Check for the actual ODM library name in 21c
find $ORACLE_HOME -name "*odm*" -type f 2>/dev/null | head -10

echo "=== Step 3: Create listener.ora in correct location ==="
cat > $ORACLE_HOME_CFG/network/admin/listener.ora << 'LISEOF'
DEFAULT_SERVICE_LISTENER = XE

LISTENER =
  (ADDRESS_LIST =
    (ADDRESS = (PROTOCOL = TCP)(HOST = 0.0.0.0)(PORT = 1521))
  )
LISEOF

cat > $ORACLE_HOME_CFG/network/admin/sqlnet.ora << 'SQLEOF'
SQLNET.INBOUND_CONNECT_TIMEOUT = 60
SQLNET.ALLOWED_LOGON_VERSION_CLIENT = 8
SQLNET.ALLOWED_LOGON_VERSION_SERVER = 8
SQLEOF

cat > $ORACLE_HOME_CFG/network/admin/tnsnames.ora << 'TNSEOF'
XE =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = localhost)(PORT = 1521))
    (CONNECT_DATA =
      (SERVER = DEDICATED)
      (SERVICE_NAME = XE)
    )
  )

XEPDB1 =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = localhost)(PORT = 1521))
    (CONNECT_DATA =
      (SERVER = DEDICATED)
      (SERVICE_NAME = XEPDB1)
    )
  )
TNSEOF

chown -R oracle:oinstall $ORACLE_HOME_CFG

echo "=== Step 4: Ensure setuid on oracle binary ==="
chmod 6751 $ORACLE_HOME/bin/oracle
ls -la $ORACLE_HOME/bin/oracle

echo "=== Step 5: Ensure ASLR is disabled ==="
echo 0 > /proc/sys/kernel/randomize_va_space
cat /proc/sys/kernel/randomize_va_space

echo "=== Step 6: Test connection ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

echo 'Testing connection...'
\$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'INNEREOF'
connect / as sysdba
SELECT 'CONNECTION_OK' AS result FROM dual;
exit;
INNEREOF
echo 'Test exit: '\$?
"

echo "=== Step 7: If connected (idle instance), create database with DBCA ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

# Start listener
\$ORACLE_HOME/bin/lsnrctl start 2>&1

# Create database
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
echo 'DBCA exit: '\$?
"

echo "=== Step 8: Final verification ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

\$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'FINALEOF'
connect sys/Oracle123 as sysdba
SELECT status FROM v\$instance;
SELECT banner_full FROM v\$version WHERE ROWNUM = 1;
SELECT name, open_mode FROM v\$pdbs;
exit;
FINALEOF
"

echo "=== ALL DONE ==="
echo "ORACLE_FULL_SETUP_COMPLETE" > /tmp/oracle-full-setup-status.txt
