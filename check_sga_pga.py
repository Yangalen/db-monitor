#!/usr/bin/env python3
"""Check SGA/PGA actual column names and data"""
import oracledb

conn = oracledb.connect(user='C##MONITOR', password='Monitor123', dsn='localhost:1521/XE')
cur = conn.cursor()

# Check SGA stats
cur.execute("SELECT name, bytes FROM v$sgastat WHERE name IN ('Free Memory', 'Buffer Cache', 'Shared Pool')")
rows = cur.fetchall()
print("SGA rows (filtered):")
for r in rows:
    print(f"  name={r[0]}, bytes={r[1]}")

# Check all SGA pool names
cur.execute("SELECT DISTINCT pool FROM v$sgastat")
pools = cur.fetchall()
print("\nSGA pools:", [r[0] for r in pools])

# Check top SGA by bytes
cur.execute("SELECT name, pool, bytes FROM v$sgastat ORDER BY bytes DESC FETCH FIRST 10 ROWS ONLY")
print("\nTop 10 SGA stats by bytes:")
for r in cur:
    print(f"  name={r[0]}, pool={r[1]}, bytes={r[2]}")

# Check PGA stats
cur.execute("SELECT name, value, unit FROM v$pgastat")
print("\nPGA all rows:")
for r in cur:
    print(f"  name={r[0]}, value={r[1]}, unit={r[2]}")

cur.close()
conn.close()
