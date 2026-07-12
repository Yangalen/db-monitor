#!/bin/bash
# Create Oracle monitoring user and verify listener
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Step 1: Check listener status ==="
$ORACLE_HOME/bin/lsnrctl status 2>&1

echo "=== Step 2: Create monitoring user ==="
$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF'
connect sys/Oracle123 as sysdba

-- Create monitor_user
CREATE USER monitor_user IDENTIFIED BY Monitor123
DEFAULT TABLESPACE users QUOTA UNLIMITED ON users;

-- Grant basic session
GRANT CREATE SESSION TO monitor_user;

-- Grant SELECT on v$ views
GRANT SELECT ON v$session TO monitor_user;
GRANT SELECT ON v$sysstat TO monitor_user;
GRANT SELECT ON v$system_event TO monitor_user;
GRANT SELECT ON v$instance TO monitor_user;
GRANT SELECT ON v$sgastat TO monitor_user;
GRANT SELECT ON v$pgastat TO monitor_user;
GRANT SELECT ON v$database TO monitor_user;
GRANT SELECT ON v$version TO monitor_user;
GRANT SELECT ON v$sql TO monitor_user;
GRANT SELECT ON v$osstat TO monitor_user;
GRANT SELECT ON v$librarycache TO monitor_user;
GRANT SELECT ON v$dataguard_stats TO monitor_user;
GRANT SELECT ON v$rman_backup_job_details TO monitor_user;

-- Grant SELECT on dba views
GRANT SELECT ON dba_data_files TO monitor_user;
GRANT SELECT ON dba_free_space TO monitor_user;
GRANT SELECT ON dba_tablespaces TO monitor_user;
GRANT SELECT ON dba_temp_files TO monitor_user;
GRANT SELECT ON dba_undo_extents TO monitor_user;

-- Verify
SELECT username, account_status FROM dba_users WHERE username = 'MONITOR_USER';
SELECT name, open_mode FROM v$pdbs;
SELECT banner FROM v$version WHERE ROWNUM = 1;

exit;
SQLEOF

echo "=== Step 3: Test monitor_user connection ==="
$ORACLE_HOME/bin/sqlplus -L -S monitor_user/Monitor123@//localhost:1521/XE << 'TESTEOF'
SELECT 'CONNECTION_OK' AS result FROM dual;
SELECT status FROM v$instance;
SELECT COUNT(*) AS session_count FROM v$session;
SELECT tablespace_name, ROUND(SUM(bytes)/1024/1024,2) AS size_mb FROM dba_data_files GROUP BY tablespace_name;
exit;
TESTEOF

echo "=== DONE ==="
echo "MONITOR_USER_CREATED" > /tmp/monitor-user-status.txt
