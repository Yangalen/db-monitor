#!/bin/bash
# Create Oracle monitoring user - CDB compatible
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Create monitoring user in CDB ==="
$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF'
connect sys/Oracle123 as sysdba

-- Create common user (C## prefix required in CDB)
CREATE USER C##MONITOR IDENTIFIED BY Monitor123
DEFAULT TABLESPACE users QUOTA UNLIMITED ON users;

-- Grant roles for monitoring
GRANT CREATE SESSION TO C##MONITOR;
GRANT SELECT_CATALOG_ROLE TO C##MONITOR;
GRANT SELECT ANY DICTIONARY TO C##MONITOR;

-- Verify
SELECT username, account_status FROM dba_users WHERE username = 'C##MONITOR';
SELECT name, open_mode FROM v$pdbs;
SELECT banner FROM v$version WHERE ROWNUM = 1;

exit;
SQLEOF

echo ""
echo "=== Test monitor_user connection ==="
$ORACLE_HOME/bin/sqlplus -L -S C##MONITOR/Monitor123@//localhost:1521/XE << 'TESTEOF'
SELECT 'CONNECTION_OK' AS result FROM dual;
SELECT status FROM v$instance;
SELECT COUNT(*) AS session_count FROM v$session;
SELECT tablespace_name, ROUND(SUM(bytes)/1024/1024,2) AS size_mb FROM dba_data_files GROUP BY tablespace_name ORDER BY tablespace_name;
SELECT event, time_waited FROM v$system_event WHERE wait_class != 'Idle' ORDER BY time_waited DESC FETCH FIRST 5 ROWS ONLY;
exit;
TESTEOF

echo "=== DONE ==="
echo "MONITOR_USER_READY" > /tmp/monitor-user-status.txt
