
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sqlite3, glob, os, statistics, collections

files = sorted(glob.glob(os.path.join(DATA, "*.db")))
print(f"scanning {len(files)} files\n")

total_trips = 0
persons_in_od = collections.Counter()   # uuid_person -> how many files it appears in
vertex_counts = []
modes = collections.Counter()
minx = miny = float("inf"); maxx = maxy = float("-inf")
per_file = {}

for p in files:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c = con.cursor()
    n = c.execute("SELECT COUNT(*) FROM od_matrix").fetchone()[0]
    total_trips += n
    seen = set()
    for uid, route, mode, origin in c.execute(
            "SELECT uuid_person, route, mode, origin FROM od_matrix"):
        seen.add(uid)
        modes[mode] += 1
        if route and route != "None":
            vertex_counts.append(route.count(",") + 1)
        if origin and origin.startswith("POINT"):
            try:
                x, y = origin[origin.index("(")+1:origin.index(")")].split()
                x, y = float(x), float(y)
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
            except ValueError:
                pass
    for u in seen:
        persons_in_od[u] += 1
    per_file[os.path.basename(p)] = (n, len(seen))
    con.close()

print(f"TOTAL trips (od_matrix rows across all files): {total_trips:,}")
print(f"distinct uuid_person appearing in od_matrix:   {len(persons_in_od):,}")

multi = sum(1 for v in persons_in_od.values() if v > 1)
print(f"persons whose trips span >1 file:              {multi:,}"
      f"  ({100*multi/max(len(persons_in_od),1):.1f}%)")
print(f"max files a single person appears in:          {max(persons_in_od.values())}")

print(f"\nroute vertices: min={min(vertex_counts)} median="
      f"{statistics.median(vertex_counts):.0f} mean={statistics.mean(vertex_counts):.1f} "
      f"max={max(vertex_counts)}")
straight = sum(1 for v in vertex_counts if v <= 2)
print(f"routes that are just 2 points (straight line): {straight:,}"
      f" / {len(vertex_counts):,} ({100*straight/len(vertex_counts):.1f}%)")

print(f"\ncoordinate bbox: X {minx:.0f}..{maxx:.0f}   Y {miny:.0f}..{maxy:.0f}")
print("\nmodes:")
for m, n in modes.most_common():
    print(f"  {m:24s} {n:>8,}  ({100*n/total_trips:.1f}%)")
