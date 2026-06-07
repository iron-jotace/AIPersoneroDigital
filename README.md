# Personero Digital

Personero Digital is an electoral observability MVP. It observes public-style electoral data, preserves append-only snapshots, computes SHA-256 hashes, detects statistical and technical anomalies, opens evidence cases, and presents a SOC-style Streamlit dashboard.

It is not a fraud detector, partisan system, or forecasting tool. Alerts are observational and require human review.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## MVP scope

- Mock ONPE collector only; no real ONPE endpoints are called.
- `SOURCE_MODE` defaults to `MOCK`.
- Real public-data connector settings are present as a disabled read-only skeleton; real endpoints are not called yet.
- Mock runoff labels use `Keiko Fujimori` and `Roberto Sánchez` for local testing only.
- Deterministic fake electoral data with local cache and basic rate limiting.
- Append-only snapshots in `data/bronze/onpe_snapshots.jsonl`.
- Canonical SHA-256 hash per raw snapshot.
- Canonical events: `SNAPSHOT_CAPTURED`, `DOCUMENT_HASH_CHANGED`, `ANOMALY_DETECTED`, `CASE_OPENED`, `CASE_EXPLAINED`, `CASE_CLOSED`, `SYSTEM_FROZEN`.
- `DOCUMENT_HASH_CHANGED` only applies to stable documents or actas with the same stable artifact id; it does not apply to aggregate snapshots.
- Aggregate snapshot hash changes are expected while counting evolves and are marked `EXPECTED_CHANGE`.
- MAD robust anomaly detection over vote gap evolution.
- ERS normalized score using the requested weighted formula.
- Confidence score and evidence levels `E0` to `E5`.
- Evidence lifecycle statuses: `DETECTED`, `CASE_OPENED`, `UNDER_REVIEW`, `EXPLAINED`, `DISMISSED`, `ESCALATED`, `CLOSED`.

## Disclaimers

- Una anomalía no implica fraude.
- El sistema detecta eventos observables, no intenciones.
- Toda alerta requiere revisión humana.
