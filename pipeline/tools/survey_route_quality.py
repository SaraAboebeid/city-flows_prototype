
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, glob, os, collections

files = sorted(glob.glob(os.path.join(DATA, "*.db")))

# 1. Are od_matrix travellers residents of the same file?
print("=== traveller vs resident membership (first 6 files) ===")
for p in files[:6]:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True); c = con.cursor()
    residents = {r[0] for r in c.execute("SELECT uuid FROM person")}
    travellers = {r[0] for r in c.execute("SELECT DISTINCT uuid_person FROM od_matrix")}
    inside = len(travellers & residents)
    print(f"{os.path.basename(p)[22:]:<28} residents={len(residents):>6,} "
          f"travellers={len(travellers):>6,}  of which resident here={inside:>6,} "
          f"({100*inside/max(len(travellers),1):.0f}%)")
    con.close()

# 2. Straight-line (2-point) routes by mode
print("\n=== route geometry quality by mode (all files) ===")
tot = collections.Counter(); straight = collections.Counter()
total_persons = 0
for p in files:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True); c = con.cursor()
    total_persons += c.execute("SELECT COUNT(*) FROM person").fetchone()[0]
    for mode, route in c.execute("SELECT mode, route FROM od_matrix"):
        tot[mode] += 1
        if not route or route == "None" or route.count(",") + 1 <= 2:
            straight[mode] += 1
    con.close()
for m, n in tot.most_common():
    print(f"  {m:24s} {n:>8,} trips, {straight[m]:>8,} straight-line "
          f"({100*straight[m]/n:.0f}%)")

print(f"\nTOTAL synthetic persons across all 94 files: {total_persons:,}")
