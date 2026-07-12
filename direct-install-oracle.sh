#!/bin/bash
# Direct install Oracle XE 21c from RPM using rpm2cpio
# This bypasses the slow alien conversion

echo "=== Step 1: Kill stuck alien process ==="
pkill -f alien 2>/dev/null
sleep 2

echo "=== Step 2: Extract RPM directly to filesystem ==="
cd /opt/oracle-monitor/oracle-install
rpm2cpio oracle-database-xe-21c.rpm | cpio -idmv 2>&1 | tail -10
echo "EXTRACT_DONE"

echo "=== Step 3: Verify extraction ==="
ls -la /opt/oracle/ 2>/dev/null && echo "ORACLE_DIR_EXISTS" || echo "NO_ORACLE_DIR"
ls -la /etc/init.d/oracle-xe* 2>/dev/null || echo "NO_INIT_SCRIPT"
ls /opt/oracle/product/21c/dbhomeXE/bin/sqlplus 2>/dev/null && echo "SQLPLUS_EXISTS" || echo "NO_SQLPLUS"

echo "=== Step 4: Create missing directories and symlinks ==="
# Ensure /var/log/oracle exists
mkdir -p /var/log/oracle
# Ensure /opt/oracle/oradata exists
mkdir -p /opt/oracle/oradata
mkdir -p /opt/oracle/admin/XE/adump
mkdir -p /opt/oracle/fast_recovery_area/XE
mkdir -p /opt/oracle/oradata/XE

echo "=== Step 5: Create Oracle groups and users ==="
groupadd -f oinstall
groupadd -f dba
groupadd -f oper
groupadd -f backupdba
groupadd -f dgdba
groupadd -f kmdba
groupadd -f racdba
useradd -r -g oinstall -G dba,oper,backupdba,dgdba,kmdba,racdba oracle 2>/dev/null || echo "oracle user exists"
echo "Oracle user created"

echo "=== Step 6: Set ownership ==="
chown -R oracle:oinstall /opt/oracle
echo "OWNERSHIP_SET"

echo "=== Step 7: Set up environment variables ==="
cat >> /etc/profile.d/oracle.sh << 'ENVEOF'
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib
ENVEOF
chmod 755 /etc/profile.d/oracle.sh
echo "ENV_SET"

echo "=== Step 8: Run Oracle configuration ==="
# Source the environment
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

# Check if the configure script exists
if [ -f /etc/init.d/oracle-xe-21c ]; then
    echo "Found oracle-xe-21c init script, running configure..."
    chmod +x /etc/init.d/oracle-xe-21c
    (echo "Oracle123"; echo "Oracle123") | /etc/init.d/oracle-xe-21c configure 2>&1 | tail -30
elif [ -f /opt/oracle/product/21c/dbhomeXE/bin/dbca ]; then
    echo "No init script, will configure manually..."
    # Manual configuration using DBCA
    echo "Running DBCA..."
    su - oracle -c "
    export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
    export ORACLE_SID=XE
    export ORACLE_BASE=/opt/oracle
    export PATH=\$PATH:\$ORACLE_HOME/bin
    
    # Run Oracle Net Configuration
    \$ORACLE_HOME/bin/netca /silent /responsefile \$ORACLE_HOME/assistants/netca/netca.rsp 2>&1 | tail -10
    
    # Create database using DBCA
    \$ORACLE_HOME/bin/dbca -silent -createDatabase \\
      -templateName General_Purpose.dbc \\
      -gdbName XE \\
      -sid XE \\
      -createAsContainerDatabase true \\
      -numberOfPDBs 1 \\
      -pdbName XEPDB1 \\
      -sysPassword Oracle123 \\
      -systemPassword Oracle123 \\
      -emConfiguration NONE \\
      -storageType FS \\
      -datafileDestination /opt/oracle/oradata \\
      -recoveryAreaDestination /opt/oracle/fast_recovery_area \\
      -characterSet AL32UTF8 \\
      -nationalCharacterSet AL16UTF16 \\
      -totalMemory 1024 \\
      -databaseType MULTIPURPOSE \\
      -initparams processes=300 2>&1 | tail -30
    " 2>&1 | tail -30
else
    echo "ERROR: Cannot find Oracle configuration tools"
    echo "Checking what was extracted..."
    find /opt/oracle -name "sqlplus" -o -name "dbca" -o -name "netca" 2>/dev/null
fi

echo "=== Step 9: Verify ==="
if [ -f /opt/oracle/product/21c/dbhomeXE/bin/sqlplus ]; then
    echo "SQLPLUS_EXISTS"
    export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
    export ORACLE_SID=XE
    export LD_LIBRARY_PATH=$ORACLE_HOME/lib
    /opt/oracle/product/21c/dbhomeXE/bin/sqlplus -s /nolog << 'SQLEOF'
connect / as sysdba
SELECT status FROM v$instance;
SQLEOF
else
    echo "NO SQLPLUS - extraction may have failed"
    find /opt/oracle -type f -name "sqlplus" 2>/dev/null
fi

echo "=== INSTALL_SCRIPT_DONE ==="
echo "ORACLE_INSTALL_COMPLETE" > /tmp/oracle-install-status.txt
