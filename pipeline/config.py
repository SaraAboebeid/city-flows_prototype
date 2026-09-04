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

# the self-hosted web build
WEB = os.path.join(PROJECT, "gothenburg-day")

os.makedirs(DER, exist_ok=True)
os.makedirs(WEB, exist_ok=True)
