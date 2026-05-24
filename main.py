"""
main.py
-------
CLI entry point for the Earnings Intelligence System — Phase 1.

Usage
-----
    python main.py AAPL
    python main.py AAPL --filings 3
    python main.py AAPL --filings 3 --preview
    python main.py AAPL --filings 5 --db ./data/my_db.sqlite --preview

The command fetches recent 8-K filings from SEC EDGAR and historical
earnings dates from yfinance, then stores everything in a local SQLite
database ready for Phase 2 (LLM signal extraction).
"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from data.fetcher import DataFetcher, IngestResult
from storage.database import Database

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

console = Console()

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """
    Construct the CLI argument parser.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Earnings Intelligence System — Phase 1: Data Ingest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              python main.py AAPL
              python main.py MSFT --filings 3 --preview
              python main.py NVDA --filings 10 --db ./nvda.db
            """
        ),
    )
    parser.add_argument(
        "ticker",
        type=str,
        help="Stock ticker symbol (e.g. AAPL, MSFT, NVDA)",
    )
    parser.add_argument(
        "--filings",
        type=int,
        default=5,
        metavar="N",
        help="Number of 8-K filings to fetch (default: 5)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the first 600 words of the most recent filing",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="earnings_intel.db",
        metavar="PATH",
        help="SQLite database file path (default: earnings_intel.db)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_header() -> None:
    """Print the application banner."""
    console.print(
        Panel.fit(
            "[bold cyan]Earnings Intelligence System[/bold cyan]  [dim]v0.1.0[/dim]\n"
            "[dim]Phase 1 — SEC EDGAR + yfinance Data Ingest[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def print_summary(result: IngestResult) -> None:
    """
    Render a summary table of what was stored.

    Args:
        result: Populated ``IngestResult`` from ``DataFetcher.ingest()``.
    """
    console.print()
    console.print(Rule("[bold]Summary[/bold]", style="cyan"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key",   style="dim", no_wrap=True)
    table.add_column("value", style="bold")

    table.add_row("Ticker",          result.ticker)
    table.add_row("Company",         result.company_name)
    table.add_row("CIK",             result.cik)
    table.add_row(
        "Filings stored",
        f"[green]{result.filings_ok}[/green] ok  "
        + (f"[red]{result.filings_failed}[/red] failed" if result.filings_failed else ""),
    )
    table.add_row("Earnings dates",  str(result.earnings_count))
    table.add_row("Database",        result.db_path)
    table.add_row("Elapsed",         f"{result.elapsed_seconds:.2f}s")

    console.print(table)


def print_filings_table(result: IngestResult) -> None:
    """
    Render a table of individual filing outcomes.

    Args:
        result: Populated ``IngestResult``.
    """
    if not result.filings:
        return

    console.print()
    console.print(Rule("[bold]Filing Detail[/bold]", style="dim"))

    tbl = Table(
        "Date",
        "Accession Number",
        "Form",
        "Words",
        "Status",
        box=None,
        padding=(0, 2),
        header_style="bold dim",
    )
    for f in result.filings:
        status_cell = "[green]✓ ok[/green]" if f.success else "[red]✗ failed[/red]"
        words_cell  = f"{f.word_count:,}" if f.word_count is not None else "—"
        tbl.add_row(f.filing_date, f.accession_number, f.form_type, words_cell, status_cell)

    console.print(tbl)


def print_preview(result: IngestResult, word_limit: int = 600) -> None:
    """
    Print a truncated preview of the most recent successful filing.

    Args:
        result:     Populated ``IngestResult``.
        word_limit: Maximum words to display (default 600).
    """
    if not result.latest_filing_text:
        console.print(
            "\n[yellow]⚠[/yellow]  No filing text available to preview."
        )
        return

    console.print()
    console.print(Rule("[bold]Filing Preview[/bold]", style="cyan"))

    # Metadata row
    meta_table = Table(show_header=False, box=None, padding=(0, 2))
    meta_table.add_column("k", style="dim")
    meta_table.add_column("v", style="bold")
    meta_table.add_row("Date",   result.latest_filing_date or "—")
    meta_table.add_row("Words",  f"{result.latest_filing_words:,}" if result.latest_filing_words else "—")
    meta_table.add_row("URL",    Text(result.latest_filing_url or "—", overflow="fold", style="dim cyan"))
    console.print(meta_table)
    console.print()

    # Text preview
    words = result.latest_filing_text.split()
    preview_text = " ".join(words[:word_limit])
    if len(words) > word_limit:
        preview_text += f"\n\n[dim]… {len(words) - word_limit:,} more words — run with --db to query the full text[/dim]"

    console.print(
        Panel(
            preview_text,
            border_style="dim",
            padding=(0, 1),
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Parse CLI arguments, run the ingestion pipeline, and render results.

    Exits with code 1 on unrecoverable errors (e.g. unknown ticker).
    """
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print_header()

    # Initialise database and fetcher
    try:
        db = Database(args.db)
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] Could not open database: {exc}")
        sys.exit(1)

    fetcher = DataFetcher(db)

    # Run ingestion pipeline
    try:
        result = fetcher.ingest(args.ticker.upper(), args.filings)
    except ValueError as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as exc:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {exc}")
        logger.exception("Unhandled exception in ingest()")
        sys.exit(1)

    # Render results
    print_summary(result)
    print_filings_table(result)

    if args.preview:
        print_preview(result)

    console.print()


if __name__ == "__main__":
    main()
