#!/bin/bash
# Clean re-configure Oracle XE 21c
set -x

export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=$PATH:$ORACLE_HOME/bin
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Step 1: Stop listener and clean up ==="
$ORACLE_HOME/bin/lsnrctl stop 2>&1

# Clean up all previous config attempts
rm -rf /opt/oracle/oradata/XE/*
rm -rf /opt/oracle/admin/XE/*
rm -rf /opt/oracle/fast_recovery_area/XE/*
rm -rf /opt/oracle/cfgtoollogs/dbca/*
rm -f $ORACLE_HOME/dbs/initXE.ora
rm -f $ORACLE_HOME/dbs/spfileXE.ora
rm -f $ORACLE_HOME/dbs/orapwXE
rm -f $ORACLE_HOME/dbs/lkXE
echo "Cleaned up"

echo "=== Step 2: Ensure /etc/hosts is correct ==="
cat /etc/hosts

echo "=== Step 3: Check kernel parameters ==="
sysctl kernel.shmmax 2>/dev/null
sysctl kernel.shmall 2>/dev/null
sysctl kernel.shmmni 2>/dev/null

echo "=== Step 4: Set kernel parameters for Oracle ==="
echo "kernel.shmmax = 4398046511104" >> /etc/sysctl.conf
echo "kernel.shmall = 1073741824" >> /etc/sysctl.conf
echo "kernel.shmmni = 4096" >> /etc/sysctl.conf
echo "fs.file-max = 6815744" >> /etc/sysctl.conf
echo "net.ipv4.ip_local_port_range = 9000 65500" >> /etc/sysctl.conf
echo "net.core.rmem_default = 262144" >> /etc/sysctl.conf
echo "net.core.rmem_max = 4194304" >> /etc/sysctl.conf
echo "net.core.wmem_default = 262144" >> /etc/sysctl.conf
echo "net.core.wmem_max = 1048576" >> /etc/sysctl.conf
echo "fs.aio-max-nr = 1048576" >> /etc/sysctl.conf
sysctl -p 2>&1 | tail -5
echo "Kernel parameters set"

echo "=== Step 5: Set limits for Oracle user ==="
cat >> /etc/security/limits.conf << 'LIMEOF'
oracle soft nproc 2047
oracle hard nproc 16384
oracle soft nofile 1024
oracle hard nofile 65536
oracle soft stack 10240
oracle hard stack 32768
LIMEOF
echo "Limits set"

echo "=== Step 6: Re-run oracle-xe-21c configure ==="
(echo "Oracle123"; echo "Oracle123") | /etc/init.d/oracle-xe-21c configure 2>&1
CONFIGURE_EXIT=$?
echo "CONFIGURE_EXIT=$CONFIGURE_EXIT"

echo "=== Step 7: If configure failed, try DBCA directly ==="
if [ ! -f /opt/oracle/oradata/XE/system01.dbf ]; then
    echo "Database not created, trying DBCA directly..."
    su - oracle -c "
    export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
    export ORACLE_SID=XE
    export ORACLE_BASE=/opt/oracle
    export PATH=\$PATH:\$ORACLE_HOME/bin
    export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

    # Start listener first
    \$ORACLE_HOME/bin/lsnrctl start 2>&1

    # Run DBCA with the correct XE template
    \$ORACLE_HOME/bin/dbca -silent -createDatabase \
      -templateName XE_Database.dbc \
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
    "
    echo "DBCA_EXIT=$?"
fi

echo "=== Step 8: Verify ==="
sleep 10
$ORACLE_HOME/bin/lsnrctl status 2>&1 | head -15
echo "---"
$ORACLE_HOME/bin/sqlplus -s /nolog << 'SQLEOF'
connect sys/Oracle123 as sysdba
SELECT status FROM v$instance;
SELECT banner_full FROM v$version WHERE ROWNUM = 1;
SELECT name FROM v$datafiles;
exit;
SQLEOF

echo "=== ALL DONE ==="
echo "ORACLE_RECONFIG_COMPLETE" > /tmp/oracle-reconfig-status.txt
