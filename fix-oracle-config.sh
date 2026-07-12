#!/bin/bash
# Fix Oracle XE 21c configuration issues on Ubuntu
set -x

export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Fix 1: /etc/hosts - add hostname resolution ==="
HOSTNAME=$(hostname)
HOST_IP=$(hostname -I | awk '{print $1}')
echo "Hostname: $HOSTNAME, IP: $HOST_IP"
# Remove old entries for this hostname
sed -i "/$HOSTNAME/d" /etc/hosts
# Add new entry
echo "$HOST_IP $HOSTNAME" >> /etc/hosts
cat /etc/hosts
echo "Hosts file fixed"

echo "=== Fix 2: Create missing Oracle Home directories ==="
mkdir -p /opt/oracle/homes/OraDBHome21cXE/network/admin
mkdir -p /opt/oracle/homes/OraDBHome21cXE/network/log
mkdir -p /opt/oracle/homes/OraDBHome21cXE/rdbms/admin
chown -R oracle:oinstall /opt/oracle/homes
echo "Oracle Home directories created"

echo "=== Fix 3: Check and fix Oracle binary permissions ==="
ls -la $ORACLE_HOME/bin/oracle
# Oracle binary needs setuid
chmod 6751 $ORACLE_HOME/bin/oracle
ls -la $ORACLE_HOME/bin/oracle

echo "=== Fix 4: Create listener.ora ==="
cat > /opt/oracle/homes/OraDBHome21cXE/network/admin/listener.ora << 'LISEOF'
DEFAULT_SERVICE_LISTENER = XE

LISTENER =
  (ADDRESS_LIST =
    (ADDRESS = (PROTOCOL = TCP)(HOST = 0.0.0.0)(PORT = 1521))
  )
LISEOF

echo "=== Fix 5: Create sqlnet.ora ==="
cat > /opt/oracle/homes/OraDBHome21cXE/network/admin/sqlnet.ora << 'SQLEOF'
SQLNET.INBOUND_CONNECT_TIMEOUT = 60
SQLNET.ALLOWED_LOGON_VERSION_CLIENT = 8
SQLNET.ALLOWED_LOGON_VERSION_SERVER = 8
SQLEOF

chown -R oracle:oinstall /opt/oracle/homes/OraDBHome21cXE/network/admin/

echo "=== Fix 6: Create tnsnames.ora ==="
cat > /opt/oracle/homes/OraDBHome21cXE/network/admin/tnsnames.ora << 'TNSEOF'
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

chown oracle:oinstall /opt/oracle/homes/OraDBHome21cXE/network/admin/tnsnames.ora

echo "=== Fix 7: Re-run Oracle XE configure ==="
# Clean up previous failed config
rm -rf /opt/oracle/oradata/XE/*
rm -rf /opt/oracle/admin/XE/*
rm -rf /opt/oracle/fast_recovery_area/XE/*
rm -f /opt/oracle/product/21c/dbhomeXE/dbs/initXE.ora
rm -f /opt/oracle/product/21c/dbhomeXE/dbs/spfileXE.ora
rm -f /opt/oracle/product/21c/dbhomeXE/dbs/orapwXE

# Run configure again
echo "Running oracle-xe-21c configure..."
(echo "Oracle123"; echo "Oracle123") | /etc/init.d/oracle-xe-21c configure 2>&1

echo "=== CONFIGURE_EXIT=$? ==="

echo "=== Fix 8: If configure failed, try manual DBCA ==="
if [ ! -f /opt/oracle/oradata/XE/system01.dbf ]; then
    echo "Database not created, trying manual DBCA..."
    su - oracle -c "
    export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
    export ORACLE_SID=XE
    export ORACLE_BASE=/opt/oracle
    export PATH=\$PATH:\$ORACLE_HOME/bin
    export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

    # Start listener
    \$ORACLE_HOME/bin/lsnrctl start 2>&1

    # Create database with DBCA
    \$ORACLE_HOME/bin/dbca -silent -createDatabase \
      -templateName General_Purpose.dbc \
      -gdbName XE \
      -sid XE \
      -createAsContainerDatabase true \
      -numberOfPDBs 1 \
      -pdbName XEPDB1 \
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
fi

echo "=== Fix 9: Verify ==="
sleep 5
$ORACLE_HOME/bin/lsnrctl status 2>&1 | head -15
echo "---"
$ORACLE_HOME/bin/sqlplus -s /nolog << 'SQLEOF'
connect sys/Oracle123 as sysdba
SELECT status FROM v$instance;
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
exit;
SQLEOF

echo "=== ALL DONE ==="
echo "ORACLE_FIX_COMPLETE" > /tmp/oracle-fix-status.txt
