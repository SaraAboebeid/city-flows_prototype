"""Look up NVDB road data for reference links (RLID) through Trafikverket's open API.

FlowSense's RLID is NVDB's Element_Id, so each road can be given its official
street name, road number, road manager and speed limit. Needs
TRAFIKVERKET_API_KEY in ../.env (gitignored). Answers are cached in
<DER>/nvdb_cache.json so a rerun only asks for links it has not seen.
"""
import os, json, datetime, urllib.request
from config import DER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://api.trafikinfo.trafikverket.se/v2/data.json"
CACHE = os.path.join(DER, "nvdb_cache.json")
BATCH = 400
# object type, schema version, the fields to keep
TYPES = {
    "Gatunamn":        ("1.2", ["Namn"]),
    "Vägnummer":       ("1.2", ["Huvudnummer", "Undernummer", "Europaväg"]),
    "Väghållare":      ("1.2", ["Väghållartyp", "Väghållarnamn"]),
    "Hastighetsgräns": ("1.4", ["Högsta_tillåtna_hastighet"]),
}


def _key():
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig"):
        if line.strip().startswith("TRAFIKVERKET_API_KEY="):
            k = line.split("=", 1)[1].strip().strip('"').strip("'")
            if k:
                return k
    raise SystemExit("TRAFIKVERKET_API_KEY missing from .env")


def _query(key, objtype, version, fields, ids):
    inc = "".join(f"<INCLUDE>{f}</INCLUDE>" for f in ["Element_Id", "Valid_To", "Deleted"] + fields)
    xml = (f'<REQUEST><LOGIN authenticationkey="{key}"/>'
           f'<QUERY objecttype="{objtype}" namespace="vägdata.nvdb_dk_o" schemaversion="{version}" limit="20000">'
           f'<FILTER><IN name="Element_Id" value="{",".join(ids)}"/></FILTER>{inc}</QUERY></REQUEST>')
    req = urllib.request.Request(URL, data=xml.encode("utf-8"), headers={"Content-Type": "text/xml"})
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read())["RESPONSE"]["RESULT"][0]
    if "ERROR" in res:
        raise RuntimeError(f"{objtype}: {res['ERROR']}")
    return res.get(objtype, [])


def lookup(rlids):
    """{rlid: {type: [records]}} for every RLID, from the cache or the API."""
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    todo = sorted({r for r in rlids if r and r not in cache})
    if todo:
        key, today = _key(), datetime.date.today().isoformat()
        print(f"  NVDB: asking Trafikverket for {len(todo):,} links in batches of {BATCH}", flush=True)
        # batch by batch, saved as it goes, so an interrupted run resumes where it stopped
        for i in range(0, len(todo), BATCH):
            ids = todo[i:i + BATCH]
            got = {r: {t: [] for t in TYPES} for r in ids}
            for t, (ver, fields) in TYPES.items():
                for rec in _query(key, t, ver, fields, ids):
                    if rec.get("Deleted") or str(rec.get("Valid_To", "9999"))[:10] < today:
                        continue
                    got[rec["Element_Id"]][t].append({f: rec.get(f) for f in fields})
            cache.update(got)
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"    {min(i + BATCH, len(todo)):,} / {len(todo):,}", flush=True)
    return {r: cache.get(r) for r in rlids}


def _join(vals):
    return " / ".join(dict.fromkeys(str(v) for v in vals if v not in (None, "")))


def describe(rec):
    """flat columns for one RLID's records"""
    if not rec:
        return {"nvdb_street_name": "", "nvdb_road_number": "", "nvdb_road_manager": "", "nvdb_speed_limit": ""}
    num = [("E" if r.get("Europaväg") else "") + str(r["Huvudnummer"]) +
           (f".{r['Undernummer']}" if r.get("Undernummer") else "") for r in rec["Vägnummer"]]
    return {
        "nvdb_street_name": _join(r["Namn"] for r in rec["Gatunamn"]),
        "nvdb_road_number": _join(num),
        "nvdb_road_manager": _join(f"{r['Väghållarnamn']} ({r['Väghållartyp']})" if r.get("Väghållarnamn")
                                   else r.get("Väghållartyp") for r in rec["Väghållare"]),
        "nvdb_speed_limit": _join(r["Högsta_tillåtna_hastighet"] for r in rec["Hastighetsgräns"]),
    }
