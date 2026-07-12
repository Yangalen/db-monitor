#!/bin/bash
# Test Oracle connection after setuid fix
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Testing sqlplus connection ==="

$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF'
connect / as sysdba
SELECT status FROM v$instance;
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
exit;
SQLEOF

echo ""
echo "SQLPLUS_EXIT=$?"
echo "=== Test complete ==="
