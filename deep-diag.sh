#!/bin/bash
# Deep strace diagnosis of Oracle connection failure
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Check 1: ASLR ==="
cat /proc/sys/kernel/randomize_va_space

echo "=== Check 2: Oracle binary permissions ==="
ls -la $ORACLE_HOME/bin/oracle

echo "=== Check 3: strace sqlplus connect ==="
strace -f -o /tmp/oracle-strace.log $ORACLE_HOME/bin/sqlplus -L -S /nolog << 'SQLEOF'
connect / as sysdba
exit;
SQLEOF

echo "=== Check 4: strace results (key lines) ==="
grep -E "SIGSEGV|SIGBUS|SIGABRT|EACCES|EPERM|ENOENT|exit_group" /tmp/oracle-strace.log | tail -20

echo "=== Check 5: Oracle trace files ==="
find /opt/oracle -name "*.trc" -newer /tmp/test-conn.sh 2>/dev/null | head -10
find /opt/oracle -name "alert*.log" 2>/dev/null | head -5

echo "=== Check 6: Alert log ==="
cat /opt/oracle/diag/rdbms/xe/XE/trace/alert_XE.log 2>/dev/null | tail -20 || echo "No alert log"

echo "=== Check 7: Try direct oracle binary ==="
$ORACLE_HOME/bin/oracle < /dev/null 2>&1; echo "oracle_exit=$?"

echo "=== Check 8: Check libodm ==="
ls -la $ORACLE_HOME/lib/libodm* 2>/dev/null || echo "No libodm"
ls -la $ORACLE_HOME/rdbms/lib/libodm* 2>/dev/null || echo "No rdbms libodm"

echo "=== DONE ==="
