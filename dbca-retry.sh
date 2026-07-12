#!/bin/bash
# Clean up oratab and re-run DBCA
set -x

export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export LD_LIBRARY_PATH=$ORACLE_HOME/lib

echo "=== Step 1: Clean up oratab ==="
# Remove XE entry from oratab
sed -i '/^XE:/d' /etc/oratab
cat /etc/oratab
echo "Oratab cleaned"

echo "=== Step 2: Clean up any残留 ==="
rm -f /opt/oracle/homes/OraDBHome21cXE/dbs/initXE.ora
rm -f /opt/oracle/homes/OraDBHome21cXE/dbs/spfileXE.ora
rm -f /opt/oracle/homes/OraDBHome21cXE/dbs/orapwXE
rm -f /opt/oracle/homes/OraDBHome21cXE/dbs/lkXE
rm -f $ORACLE_HOME/dbs/initXE.ora
rm -f $ORACLE_HOME/dbs/spfileXE.ora
rm -f $ORACLE_HOME/dbs/orapwXE
rm -f $ORACLE_HOME/dbs/lkXE
rm -rf /opt/oracle/oradata/XE
rm -rf /opt/oracle/admin/XE
rm -rf /opt/oracle/fast_recovery_area/XE
rm -rf /opt/oracle/cfgtoollogs/dbca
mkdir -p /opt/oracle/oradata/XE
mkdir -p /opt/oracle/admin/XE/adump
mkdir -p /opt/oracle/fast_recovery_area/XE
chown -R oracle:oinstall /opt/oracle
echo "Cleaned up"

echo "=== Step 3: Run DBCA ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

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
echo DBCA_EXIT=\$?
"

echo "=== Step 4: Add to oratab ==="
echo "XE:/opt/oracle/product/21c/dbhomeXE:Y" >> /etc/oratab

echo "=== Step 5: Verify ==="
su - oracle -c "
export ORACLE_HOME=/opt/oracle/product/21c/dbhomeXE
export ORACLE_SID=XE
export ORACLE_BASE=/opt/oracle
export PATH=\$PATH:\$ORACLE_HOME/bin
export LD_LIBRARY_PATH=\$ORACLE_HOME/lib

\$ORACLE_HOME/bin/sqlplus -L -S /nolog << 'VEOF'
connect sys/Oracle123 as sysdba
SELECT status FROM v\$instance;
SELECT banner_full FROM v\$version WHERE ROWNUM = 1;
SELECT name, open_mode FROM v\$pdbs;
exit;
VEOF
"

echo "=== DONE ==="
echo "DBCA_RETRY_COMPLETE" > /tmp/dbca-retry-status.txt
