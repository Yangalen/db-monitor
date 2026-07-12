#!/bin/bash
# Set up Oracle environment and test connection
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "ORACLE_HOME=$ORACLE_HOME"
echo "Testing sqlplus..."

# Test basic connection
$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF'
connect / as sysdba
SELECT status FROM v$instance;
exit;
SQLEOF

SQLPLUS_EXIT=$?
echo "SQLPLUS_EXIT=$SQLPLUS_EXIT"

# If instance not available, we need to create the database
if [ $SQLPLUS_EXIT -ne 0 ]; then
    echo "=== Instance not available, running DBCA ==="

    # Start listener
    $ORACLE_HOME/bin/lsnrctl start 2>&1

    # Run DBCA
    $ORACLE_HOME/bin/dbca -silent -createDatabase \
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

    echo "DBCA_EXIT=$?"

    # Verify
    sleep 5
    $ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF2'
connect sys/Oracle123 as sysdba
SELECT status FROM v$instance;
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
exit;
SQLEOF2
fi

echo "=== DONE ==="
