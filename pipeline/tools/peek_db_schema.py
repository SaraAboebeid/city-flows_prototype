
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, sys

db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()

tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

for t in tables:
    n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    cols = [(r[1], r[2]) for r in cur.execute(f'PRAGMA table_info("{t}")')]
    print(f"\n=== {t}  ({n:,} rows) ===")
    print("  " + ", ".join(f"{c}:{ty}" for c, ty in cols))
    row = cur.execute(f'SELECT * FROM "{t}" LIMIT 1').fetchone()
    if row:
        print("  sample:")
        for (c, _), v in zip(cols, row):
            s = str(v)
            if len(s) > 90:
                s = s[:90] + f"... [len={len(str(v))}]"
            print(f"    {c} = {s}")
con.close()
