"""Repair mojibake introduced by a PowerShell UTF-8 round-trip."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__)))
                   == 'tools' else os.path.dirname(os.path.abspath(__file__)))
from config import DATA, DER, WEB, HERE  # noqa: E402
import sys

def repair(s):
    # double-encoded UTF-8: bytes were read as cp1252 then written as UTF-8
    out = []
    i = 0
    while i < len(s):
        # try the longest run that round-trips cleanly
        for n in (6, 4, 3, 2):
            chunk = s[i:i+n]
            try:
                fixed = chunk.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if fixed != chunk and len(fixed) < len(chunk):
                out.append(fixed)
                i += n
                break
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    fixed = repair(src)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(fixed)
    bad = [m for m in ("Ã", "â€", "Â") if m in fixed]
    print(f"{path.split(chr(92))[-1]:16s} "
          f"{'CHANGED' if fixed != src else 'unchanged':10s} "
          f"residual mojibake markers: {bad or 'none'}")
