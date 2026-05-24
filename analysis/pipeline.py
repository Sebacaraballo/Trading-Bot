"""
analysis/pipeline.py
--------------------
Orchestrates Phase 2: LLM signal extraction from SEC 8-K filings.

Full flow for each unanalyzed filing:
  1. Query DB for filings with fetch_status='success' that have no signals row
  2. Fetch Exhibit 99.1 from SEC EDGAR (the real press release with numbers)
  3. Run the exhibit text through the LLM → structured EarningsSignal
  4. Persist the signal to the signals table

Usage:
    from analysis.pipeline import SignalPipeline
    pipeline = SignalPipeline(db)
    run = pipeline.run("AAPL")
    for result in run.results:
        print(result.signal.sentiment, result.signal.confidence)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from data.sec_client import SECClient
from storage.database import Database
from analysis.exhibit_fetcher import ExhibitFetcher
from analysis.llm_client import EarningsSignal, LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    """Outcome of processing a single filing through the pipeline."""

    filing_id: int
    accession_number: str
    filing_date: str
    ticker: str
    signal: Optional[EarningsSignal] = None
    exhibit_found: bool = False
    success: bool = False
    error: Optional[str] = None


@dataclass
class PipelineRun:
    """Summary of a full pipeline run for one ticker."""

    ticker: str
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0          # No Exhibit 99.1 found
    results: list[SignalResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class SignalPipeline:
    """
    End-to-end signal extraction pipeline.

    Args:
        db:         Initialized :class:`~storage.database.Database` instance.
        llm_client: Optional pre-initialized :class:`~analysis.llm_client.LLMClient`.
                    Creates one from env vars if not provided.
        sec_client: Optional pre-initialized :class:`~data.sec_client.SECClient`.
                    Creates a new one if not provided.
    """

    def __init__(
        self,
        db: Database,
        llm_client: Optional[LLMClient] = None,
        sec_client: Optional[SECClient] = None,
    ) -> None:
        self._db = db
        self._sec = sec_client or SECClient()
        self._exhibit_fetcher = ExhibitFetcher(self._sec)
        self._llm = llm_client or LLMClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_pending_filings(self, ticker: str) -> list[dict]:
        """
        Return all successfully-fetched filings for *ticker* that have no
        signal row yet.

        Args:
            ticker: Stock ticker symbol (case-insensitive).

        Returns:
            List of dicts with keys:
              ``filing_id``, ``accession_number``, ``filing_date``,
              ``period_of_report``, ``ticker``, ``cik``
        """
        rows = self._db._conn.execute(
            """
            SELECT
                f.id               AS filing_id,
                f.accession_number,
                f.filing_date,
                f.period_of_report,
                c.ticker,
                c.cik
            FROM   filings   f
            JOIN   companies c ON c.id = f.company_id
            LEFT JOIN signals s ON s.filing_id = f.id
            WHERE  f.fetch_status = 'success'
              AND  c.ticker       = ?
              AND  s.id IS NULL
            ORDER BY f.filing_date DESC
            """,
            (ticker.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def process_filing(self, filing: dict) -> SignalResult:
        """
        Run the full pipeline for a single filing dict.

        Steps:
          1. Fetch Exhibit 99.1 via :class:`~analysis.exhibit_fetcher.ExhibitFetcher`
          2. Call LLM via :class:`~analysis.llm_client.LLMClient`
          3. Persist result via :meth:`~storage.database.Database.save_signal`

        Args:
            filing: Row dict as returned by :meth:`get_pending_filings`.

        Returns:
            Populated :class:`SignalResult` (``success=True`` on full success).
        """
        result = SignalResult(
            filing_id=filing["filing_id"],
            accession_number=filing["accession_number"],
            filing_date=filing["filing_date"],
            ticker=filing["ticker"],
        )

        # ── Step 1: Fetch Exhibit 99.1 ────────────────────────────────
        logger.info(
            "Fetching Exhibit 99.1 for %s  accession=%s",
            filing["ticker"], filing["accession_number"],
        )
        exhibit_text = self._exhibit_fetcher.get_exhibit_text(
            accession_number=filing["accession_number"],
            cik=filing["cik"],
        )

        if not exhibit_text:
            result.error = "Exhibit 99.1 not found or download failed"
            return result

        result.exhibit_found = True

        # ── Step 2: LLM analysis ──────────────────────────────────────
        try:
            signal = self._llm.analyze_exhibit(
                ticker=filing["ticker"],
                filing_date=filing["filing_date"],
                exhibit_text=exhibit_text,
            )
            result.signal = signal
        except Exception as exc:
            logger.error(
                "LLM analysis failed for %s %s: %s",
                filing["ticker"], filing["accession_number"], exc,
            )
            result.error = f"LLM error: {exc}"
            return result

        # ── Step 3: Persist to DB ─────────────────────────────────────
        try:
            company = self._db.get_company(filing["ticker"])
            if company is None:
                raise ValueError(f"Company {filing['ticker']} not found in DB")

            self._db.save_signal(
                filing_id=result.filing_id,
                company_id=company["id"],
                signal_date=filing["filing_date"],
                signal=signal,
            )
            result.success = True
            logger.info(
                "Signal saved  %s %s → %s (confidence=%.2f)",
                filing["ticker"], filing["filing_date"],
                signal.direction, signal.confidence,
            )
        except Exception as exc:
            logger.error(
                "Failed to save signal for %s %s: %s",
                filing["ticker"], filing["accession_number"], exc,
            )
            result.error = f"DB save failed: {exc}"

        return result

    def run(self, ticker: str) -> PipelineRun:
        """
        Run the signal extraction pipeline for every pending filing of *ticker*.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            :class:`PipelineRun` with per-filing results and aggregate stats.
        """
        start = time.monotonic()
        run = PipelineRun(ticker=ticker.upper())

        pending = self.get_pending_filings(ticker)
        run.total = len(pending)

        if not pending:
            logger.info("No pending (unanalyzed) filings for %s", ticker)
            return run

        logger.info("Found %d pending filings for %s", len(pending), ticker)

        for filing in pending:
            result = self.process_filing(filing)
            run.results.append(result)

            if result.success:
                run.succeeded += 1
            elif not result.exhibit_found:
                run.skipped += 1
            else:
                run.failed += 1

        run.elapsed_seconds = time.monotonic() - start
        return run
