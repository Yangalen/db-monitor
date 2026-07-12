#!/bin/bash
# Clean up and convert Oracle RPM to DEB
pkill -f alien 2>/dev/null
sleep 2
cd /opt/oracle-monitor/oracle-install
rm -rf oracle-database-xe-21c-1.0
rm -f /tmp/alien-status2.txt
echo "=== CLEANED, starting conversion ==="

alien --scripts -d oracle-database-xe-21c.rpm
RESULT=$?

if [ $RESULT -eq 0 ]; then
    echo "CONVERT_OK" > /tmp/alien-status2.txt
    echo "=== Conversion successful ==="
    ls -lh *.deb
else
    echo "CONVERT_FAIL" > /tmp/alien-status2.txt
    echo "=== Conversion failed with code $RESULT ==="
fi
