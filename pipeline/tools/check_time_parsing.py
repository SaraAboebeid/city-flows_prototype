
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, glob, re, collections

files = sorted(glob.glob(os.path.join(DATA, "*.db")))

pat = re.compile(
    r"Start Time:\s*(\d{1,2}):(\d{2}):(\d{2}),\s*End Time:\s*(\d{1,2}):(\d{2}):(\d{2})")

print("=== raw transit_activity samples ===")
con = sqlite3.connect(f"file:{files[0]}?mode=ro", uri=True)
for (ta,) in con.execute("SELECT transit_activity FROM od_matrix LIMIT 3"):
    print("  " + repr(ta))
con.close()

ok = bad = 0
hours = collections.Counter()
badsamples = []
for p in files:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for (ta,) in con.execute("SELECT transit_activity FROM od_matrix"):
        m = pat.search(ta or "")
        if m:
            ok += 1
            hours[int(m.group(1))] += 1
        else:
            bad += 1
            if len(badsamples) < 5:
                badsamples.append(ta)
    con.close()

print(f"\nparsed OK: {ok:,}   failed: {bad:,}")
if badsamples:
    print("failed samples:")
    for b in badsamples:
        print("  " + repr(b))

print("\ndeparture hour histogram (start hour -> trips):")
for h in sorted(hours):
    print(f"  {h:02d}  {hours[h]:>7,}  " + "#" * int(60 * hours[h] / max(hours.values())))
