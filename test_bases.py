import sqlite3
import json

conn = sqlite3.connect('airpower.db')
c = conn.cursor()
c.execute("SELECT * FROM air_bases LIMIT 2")
columns = [desc[0] for desc in c.description]
for row in c.fetchall():
    print(dict(zip(columns, row)))
