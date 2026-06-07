from __future__ import annotations

from pathlib import Path


APP_NAME = "Personero Digital"
SOURCE_MODE = "MOCK"
CANDIDATE_A_NAME = "Keiko Fujimori"
CANDIDATE_B_NAME = "Roberto Sánchez"

# Real public-data connector skeleton. Disabled by default for the MVP.
REAL_ONPE_ENABLED = False
ONPE_BASE_URL = ""
ONPE_RESULTS_ENDPOINT = ""
ONPE_CACHE_TTL_SECONDS = 300
MAX_REQUESTS_PER_ENDPOINT_PER_5_MIN = 1
USER_AGENT = "PersoneroDigital-MVP/0.1 public-observability research; contact=local"

DATA_DIR = Path("data")
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
EVIDENCE_DIR = DATA_DIR / "evidence"

SNAPSHOTS_PATH = BRONZE_DIR / "onpe_snapshots.jsonl"
EVENTS_PATH = SILVER_DIR / "events.jsonl"
CASES_PATH = EVIDENCE_DIR / "cases.jsonl"
CACHE_PATH = BRONZE_DIR / "onpe_cache.json"

MOCK_SEED = 20260607
RATE_LIMIT_SECONDS = 2.0
FREEZE_THRESHOLD_PCT = 99.5

DISCLAIMER_LINES = [
    "Una anomalía no implica fraude.",
    "El sistema detecta eventos observables, no intenciones.",
    "Toda alerta requiere revisión humana.",
]
