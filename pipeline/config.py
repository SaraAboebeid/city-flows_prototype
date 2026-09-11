"""Shared paths for the Göteborg city-flows pipeline.

Edit DATA if you move the 4.5 GB Zenodo download; everything else follows.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

# raw Zenodo record 10801936 -- 94 neighbourhood .db files
DATA = r"C:\Users\saraabo\gothenburg-synthpop"

# everything the pipeline generates
DER = os.path.join(DATA, "_derived")

# FlowSense Traffic Flows (Zenodo 16794871): mobile-phone-based vehicle flows
FLOWSENSE = r"C:\Users\saraabo\flowsense-trafficflows"

# the self-hosted single-file page, and its JavaScript twin
WEB = os.path.join(PROJECT, "gothenburg-day")
JSWEB = os.path.join(PROJECT, "gothenburg-day-js")
# the separate phone-data (FlowSense) dashboard
PHONEWEB = os.path.join(PROJECT, "gothenburg-phone-js")

# CARTO basemap tiles now need a (free) API key: carto.com/basemaps/apikey
TILE_URL = "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png"
KEY_FILE = os.path.join(PROJECT, "carto_api_key.txt")


def carto_key():
    """The CARTO API key: env var CARTO_API_KEY, else carto_api_key.txt at the
    project root (kept out of git). Empty string if neither is set."""
    k = os.environ.get("CARTO_API_KEY", "").strip()
    if not k and os.path.exists(KEY_FILE):
        # accepts a bare key, or NAME=value lines (e.g. CARTO_API=...);
        # blank lines and # comments are ignored
        for line in open(KEY_FILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k = line.split("=", 1)[1].strip() if "=" in line else line
            k = k.strip("\"'")
            break
    return k


os.makedirs(DER, exist_ok=True)
os.makedirs(WEB, exist_ok=True)
