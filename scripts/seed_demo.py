"""
scripts/seed_demo.py
--------------------
Seed the database with a few realistic demo signals so the deployed dashboard
looks alive when a recruiter visits the public URL.

Behaviour:
  * Idempotent — if the ``signals`` table already has any rows, it exits without
    touching the database (so it's safe to run on every Railway boot).
  * Creates the schema if the DB file doesn't exist yet (a fresh Railway
    container starts with no DB, since *.db is gitignored).
  * Inserts matching ``companies`` and ``filings`` rows first so the signal
    foreign keys resolve.

The signal payload matches how the real Phase 2 pipeline stores data: the
analysis fields (sentiment, guidance_quality, management_tone, risk_flags,
bull_case, bear_case) live inside the ``key_metrics`` JSON blob, which the API
flattens for the frontend.

Run standalone:
    python scripts/seed_demo.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow `python scripts/seed_demo.py` from anywhere by putting the project
# root (the parent of scripts/) on the import path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from storage.database import Database  # noqa: E402  (import after sys.path tweak)

# Same env var / default the API uses, so both read & write the same file.
DB_PATH = os.getenv("DB_PATH", "earnings_intel.db")

_MODEL = "claude-haiku-4-5-20251001"

# Each entry carries company metadata, a synthetic filing, and the signal.
DEMO_SIGNALS = [
    {
        "ticker": "NVDA",
        "cik": "0001045810",
        "name": "NVIDIA Corporation",
        "accession_number": "0001045810-26-000050",
        "filing_date": "2026-05-20",
        "confidence": 0.95,
        "sentiment": "bullish",
        "guidance_quality": "raised",
        "management_tone": "optimistic",
        "risk_flags": [
            "China Data Center exclusion from guidance",
            "Inventory buildup risk",
            "Geopolitical headwinds",
        ],
        "extra_metrics": {
            "forward_guidance_change": "raised",
            "revenue_yoy_growth": 0.85,
        },
        "bull_case": (
            "NVIDIA delivered record $81.6B revenue (+85% YoY) with Data Center "
            "revenue reaching $75.2B (+92% YoY), while raising guidance to "
            "$91.0B and authorizing an $80B share repurchase."
        ),
        "bear_case": (
            "Management excluded all China Data Center compute revenue from "
            "forward guidance, signaling geopolitical headwinds."
        ),
        "reasoning": (
            "NVIDIA posted exceptional topline growth with Q1 FY27 revenue of "
            "$81.6B up 85% YoY. Q2 guidance of $91.0B represents a 12% sequential "
            "increase. The zero China assumption introduces material downside risk."
        ),
    },
    {
        "ticker": "AAPL",
        "cik": "0000320193",
        "name": "Apple Inc.",
        "accession_number": "0000320193-26-000045",
        "filing_date": "2026-04-30",
        "confidence": 0.85,
        "sentiment": "bullish",
        "guidance_quality": "none",
        "management_tone": "optimistic",
        "risk_flags": [
            "Tariff uncertainty on hardware margins",
            "China revenue exposure",
            "Services growth deceleration risk",
        ],
        "extra_metrics": {
            "forward_guidance_change": "maintained",
            "revenue_yoy_growth": 0.17,
        },
        "bull_case": (
            "Apple delivered $111.2B revenue (+17% YoY), its best March quarter "
            "ever, driven by iPhone 17 lineup. $2.01 diluted EPS (+22% YoY) with "
            "a $100B buyback and 4% dividend increase."
        ),
        "bear_case": (
            "Management provided no forward guidance citing macro uncertainty. "
            "China revenue remains a key risk amid ongoing trade tensions."
        ),
        "reasoning": (
            "Apple's Q2 FY2026 results significantly exceeded expectations with "
            "broad-based strength across all geographies and product categories. "
            "The lack of forward guidance is the primary risk factor."
        ),
    },
    {
        "ticker": "MSFT",
        "cik": "0000789019",
        "name": "Microsoft Corporation",
        "accession_number": "0000789019-26-000060",
        "filing_date": "2026-04-29",
        "confidence": 0.85,
        "sentiment": "bullish",
        "guidance_quality": "raised",
        "management_tone": "optimistic",
        "risk_flags": [
            "Azure capacity constraints",
            "AI capex pace",
            "FX headwinds in international markets",
        ],
        "extra_metrics": {
            "forward_guidance_change": "raised",
            "revenue_yoy_growth": 0.13,
        },
        "bull_case": (
            "Microsoft reported $70.1B revenue (+13% YoY) with Azure growth "
            "accelerating to 35% YoY. Copilot monetization is beginning to show "
            "up in commercial bookings with $18B in new AI commitments."
        ),
        "bear_case": (
            "Azure capacity constraints may limit near-term growth acceleration. "
            "AI capex is running at $21B per quarter with unclear ROI timeline."
        ),
        "reasoning": (
            "Microsoft's Q3 FY2026 results showed durable cloud growth with Azure "
            "reaccelerating. Copilot integration across the product suite is "
            "creating real revenue uplift. Capacity remains the binding constraint."
        ),
    },
]

# bullish/bearish/neutral → the signals.direction enum (LONG/SHORT/NEUTRAL).
_SENTIMENT_TO_DIRECTION = {"bullish": "LONG", "bearish": "SHORT", "neutral": "NEUTRAL"}


def _build_key_metrics(demo: dict) -> dict:
    """Assemble the key_metrics JSON blob the API expects to flatten."""
    km = {
        "sentiment": demo["sentiment"],
        "guidance_quality": demo["guidance_quality"],
        "management_tone": demo["management_tone"],
        "risk_flags": demo["risk_flags"],
        "bull_case": demo["bull_case"],
        "bear_case": demo["bear_case"],
        # Real pipeline stores these; demos have no estimate comparison → null.
        "eps_beat": None,
        "revenue_beat": None,
    }
    km.update(demo["extra_metrics"])
    return km


def seed(db: Database) -> int:
    """Insert the demo signals. Returns the number of signals inserted."""
    inserted = 0
    for demo in DEMO_SIGNALS:
        company_id = db.upsert_company(demo["ticker"], demo["cik"], demo["name"])

        cik_int = int(demo["cik"])
        acc_nodash = demo["accession_number"].replace("-", "")
        primary_doc = "ex99-1.htm"
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{acc_nodash}/{primary_doc}"
        )
        cleaned_text = (
            f"{demo['name']} ({demo['ticker']}) earnings press release "
            f"(Exhibit 99.1), filed {demo['filing_date']}. "
            f"{demo['bull_case']} {demo['bear_case']}"
        )

        filing_id = db.upsert_filing(
            company_id=company_id,
            accession_number=demo["accession_number"],
            filing_date=demo["filing_date"],
            form_type="8-K",
            period_of_report=demo["filing_date"],
            primary_document=primary_doc,
            document_url=doc_url,
            cleaned_text=cleaned_text,
            word_count=len(cleaned_text.split()),
            fetch_status="success",
        )

        key_metrics = json.dumps(_build_key_metrics(demo), ensure_ascii=False)
        direction = _SENTIMENT_TO_DIRECTION[demo["sentiment"]]

        db._conn.execute(
            """
            INSERT INTO signals
                (filing_id, company_id, signal_date, direction, confidence,
                 reasoning, key_metrics, llm_model,
                 llm_prompt_tokens, llm_completion_tokens, raw_llm_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filing_id,
                company_id,
                demo["filing_date"],
                direction,
                demo["confidence"],
                demo["reasoning"],
                key_metrics,
                _MODEL,
                0,
                0,
                None,
            ),
        )
        db._conn.commit()
        inserted += 1
        print(f"[seed] inserted demo signal: {demo['ticker']} ({demo['filing_date']})")

    return inserted


def main() -> None:
    db = Database(DB_PATH)

    existing = db._conn.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]
    if existing > 0:
        print(
            f"[seed] signals table already has {existing} row(s) — "
            "skipping demo seed (idempotent)."
        )
        return

    count = seed(db)
    print(f"[seed] done — inserted {count} demo signals into {db.db_path}")


if __name__ == "__main__":
    main()
