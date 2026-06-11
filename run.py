"""CLI entry point for the VoiceAdmin prior-authorization demo.

    python run.py --input sample_data/sample_note.pdf
    python run.py --input sample_data/sample_note.pdf --channel portal_then_ivr

Runs the full workflow (Document Reader -> Payer Contact) via the orchestrator
and prints a color-coded summary plus the complete decision trace. Exit code is
0 when the request is APPROVED, 1 otherwise (so CI can gate on it).
"""

import argparse
import sys

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from agents.models import PADecision
from agents.orchestrator import run_prior_auth

console = Console()

STATUS_STYLES: dict[str, str] = {
    "APPROVED": "bold green",
    "DENIED": "bold red",
    "PENDING_INFO": "bold yellow",
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="VoiceAdmin - Prior Authorization workflow demo"
    )
    parser.add_argument(
        "--input", required=True, help="Path to the clinical-note PDF"
    )
    parser.add_argument(
        "--channel",
        default="auto",
        choices=["auto", "portal_then_ivr", "voice"],
        help="Payer-contact channel (default: auto)",
    )
    return parser.parse_args()


def _print_header(pdf_path: str, channel: str) -> None:
    """Announce the run in a header panel."""
    console.print(
        Panel(
            f"Running prior-authorization workflow\n"
            f"Input:   {escape(pdf_path)}\n"
            f"Channel: {channel}",
            title="VoiceAdmin",
            border_style="cyan",
        )
    )


def _print_summary(decision: PADecision) -> None:
    """Render the final decision as a color-coded summary panel."""
    style = STATUS_STYLES.get(decision.status, "bold white")
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("Status", f"[{style}]{decision.status}[/]")
    table.add_row("Channel used", decision.channel_used)
    table.add_row("Reference number", decision.reference_number or "-")
    table.add_row("Reason", escape(decision.reason) if decision.reason else "-")
    console.print(
        Panel(
            table, title="Prior Authorization Result", border_style=style
        )
    )


def _print_trace(decision: PADecision) -> None:
    """Render the full decision trace as a numbered tree."""
    tree = Tree("[bold]Decision trace[/]")
    for index, line in enumerate(decision.trace, start=1):
        tree.add(f"{index:>2}. {escape(line)}")
    console.print(tree)


def main() -> int:
    """Run the workflow and return a process exit code."""
    args = _parse_args()
    _print_header(args.input, args.channel)

    decision = run_prior_auth(args.input, channel=args.channel)

    console.print()
    _print_summary(decision)
    _print_trace(decision)

    return 0 if decision.status == "APPROVED" else 1


if __name__ == "__main__":
    sys.exit(main())
