import sqlite3
import json

conn = sqlite3.connect('airpower.db')
c = conn.cursor()
c.execute("SELECT * FROM threat_zones LIMIT 1")
columns = [desc[0] for desc in c.description]
for row in c.fetchall():
    print("THREAT:", dict(zip(columns, row)))

c.execute("SELECT * FROM airspace_zones LIMIT 1")
columns = [desc[0] for desc in c.description]
for row in c.fetchall():
    print("AIRSPACE:", dict(zip(columns, row)))
