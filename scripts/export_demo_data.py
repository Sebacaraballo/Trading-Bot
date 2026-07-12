"""
scripts/export_demo_data.py
---------------------------
Export the local earnings_intel.db into the two demo artifacts, keeping the
dashboard, the seed, and the static snapshot on one source of truth:

  1. scripts/demo_data.json
     Raw rows (companies, earnings_dates, filings sans raw_html, signals,
     latest backtest run) consumed by scripts/seed_demo.py wherever the
     backend boots with an empty database.

  2. dashboard/public/snapshot/*.json
     Byte-for-byte API responses captured through FastAPI's TestClient, shipped
     with the Vercel build. This is the dashboard's primary data source when no
     live API is configured, and its fallback when a configured API is down:
       stats.json         GET /api/stats
       signals.json       GET /api/signals?limit=500
       filings.json       GET /api/filings?limit=500
       backtest.json      GET /api/backtest/latest
       filing-texts.json  {filing_id: GET /api/filings/{id}/text}
       meta.json          generation timestamp + counts

Run after any change to the local dataset (new signals, new backtest run):
    python scripts/export_demo_data.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

DB_PATH = os.getenv("DB_PATH", "earnings_intel.db")
DEMO_DATA_PATH = _PROJECT_ROOT / "scripts" / "demo_data.json"
SNAPSHOT_DIR = _PROJECT_ROOT / "dashboard" / "public" / "snapshot"


def _dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[export] wrote {path.relative_to(_PROJECT_ROOT)} ({path.stat().st_size:,} bytes)")


def export_seed_data() -> dict:
    """Dump raw DB rows into scripts/demo_data.json for the seeder."""
    from storage.database import Database
    from backtest.store import get_latest_backtest

    db = Database(DB_PATH)
    conn = db._conn

    companies = [
        dict(r)
        for r in conn.execute(
            "SELECT ticker, cik, name, exchange, sector FROM companies ORDER BY ticker"
        )
    ]

    earnings_dates = [
        dict(r)
        for r in conn.execute(
            """
            SELECT c.ticker, e.earnings_date, e.eps_estimate, e.eps_actual,
                   e.surprise_pct, e.revenue_estimate, e.revenue_actual
            FROM   earnings_dates e JOIN companies c ON c.id = e.company_id
            ORDER BY c.ticker, e.earnings_date
            """
        )
    ]

    # raw_html is ~4 MB across the DB and nothing downstream reads it — skip it.
    filings = [
        dict(r)
        for r in conn.execute(
            """
            SELECT c.ticker, f.accession_number, f.filing_date, f.form_type,
                   f.period_of_report, f.primary_document, f.document_url,
                   f.cleaned_text, f.word_count, f.fetch_status, f.error_message
            FROM   filings f JOIN companies c ON c.id = f.company_id
            ORDER BY f.filing_date, f.accession_number
            """
        )
    ]

    signals = []
    for r in conn.execute(
        """
        SELECT c.ticker, f.accession_number, s.signal_date, s.direction,
               s.confidence, s.reasoning, s.key_metrics, s.llm_model,
               s.llm_prompt_tokens, s.llm_completion_tokens,
               s.raw_llm_response, s.created_at
        FROM   signals s
        JOIN   filings f ON f.id = s.filing_id
        JOIN   companies c ON c.id = s.company_id
        ORDER BY s.signal_date, c.ticker
        """
    ):
        row = dict(r)
        # Store the blob as parsed JSON so the file stays readable/diffable.
        row["key_metrics"] = json.loads(row["key_metrics"]) if row["key_metrics"] else None
        signals.append(row)

    backtest = get_latest_backtest(db)
    if backtest is not None:
        backtest.pop("id", None)  # row id is DB-local; the seeder inserts fresh

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "companies": companies,
        "earnings_dates": earnings_dates,
        "filings": filings,
        "signals": signals,
        "backtest": backtest,
    }
    _dump(DEMO_DATA_PATH, payload)
    return payload


def export_snapshot() -> None:
    """Capture real API responses into dashboard/public/snapshot/."""
    os.environ["DB_PATH"] = DB_PATH
    from fastapi.testclient import TestClient

    from api.main import app

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)

    def get(path: str) -> object:
        res = client.get(path)
        res.raise_for_status()
        return res.json()

    stats = get("/api/stats")
    signals = get("/api/signals?limit=500")
    filings = get("/api/filings?limit=500")
    backtest = get("/api/backtest/latest")

    filing_texts = {}
    for filing in filings:
        if filing["fetch_status"] != "success":
            continue
        res = client.get(f"/api/filings/{filing['id']}/text")
        if res.status_code == 200:
            filing_texts[str(filing["id"])] = res.json()

    _dump(SNAPSHOT_DIR / "stats.json", stats)
    _dump(SNAPSHOT_DIR / "signals.json", signals)
    _dump(SNAPSHOT_DIR / "filings.json", filings)
    _dump(SNAPSHOT_DIR / "backtest.json", backtest)
    _dump(SNAPSHOT_DIR / "filing-texts.json", filing_texts)
    _dump(
        SNAPSHOT_DIR / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "signals": len(signals),
            "filings": len(filings),
            "trades": backtest.get("trades_executed") if isinstance(backtest, dict) else None,
        },
    )


def main() -> None:
    payload = export_seed_data()
    export_snapshot()
    bt = payload["backtest"] or {}
    print(
        f"[export] done - {len(payload['signals'])} signals, "
        f"{len(payload['companies'])} companies, {len(payload['filings'])} filings, "
        f"backtest: {bt.get('trades_executed', 0)} trades"
    )


if __name__ == "__main__":
    main()
