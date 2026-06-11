"""Orchestrator.

The thin coordinator that wires Document Reader -> Payer Contact and owns the
end-to-end story of a prior-authorization workflow. Most logic already lives in
the agents; this file is glue, trace assembly, and error handling.

It guarantees a printable PADecision on every path: if document extraction or
payer contact fails, the error is caught and wrapped in a PENDING_INFO decision
rather than allowed to crash the CLI demo.
"""

from typing import Literal

from rich import print as rprint

from agents.document_reader import read_document
from agents.models import PADecision, PARequest
from agents.payer_contact import contact_payer

Channel = Literal["auto", "portal_then_ivr"]


def _dispatch(channel: Channel, request: PARequest) -> PADecision:
    """Route the request to a payer-contact implementation by channel.

    "auto" and "portal_then_ivr" are currently aliases. Adding tomorrow's voice
    channel is a single branch here (``elif channel == "voice": ...``), not a
    refactor.
    """
    if channel in ("auto", "portal_then_ivr"):
        return contact_payer(request)
    raise ValueError(f"Unknown channel: {channel!r}")


def _ref_suffix(decision: PADecision) -> str:
    """Render a ``(ref ...)`` suffix when a reference number is present."""
    return f" (ref {decision.reference_number})" if decision.reference_number else ""


def _failure_decision(reason: str, trace: list[str]) -> PADecision:
    """Build the least-bad PADecision for an orchestrator-level failure."""
    return PADecision(
        status="PENDING_INFO",
        channel_used="portal",
        reason=reason,
        trace=trace,
    )


def run_prior_auth(pdf_path: str, channel: Channel = "auto") -> PADecision:
    """Run the full PA workflow for a clinical-note PDF and return a PADecision.

    Never raises: any failure in document extraction or payer contact is caught
    and returned as a PENDING_INFO decision so the CLI always ends printably.
    """
    rprint(
        f"[bold yellow]Orchestrator[/]: starting PA workflow for "
        f"{pdf_path} (channel={channel})"
    )
    trace: list[str] = [
        f"[orchestrator] Starting PA workflow for {pdf_path} (channel={channel})"
    ]

    # Step 1 + 2: extract the structured request from the PDF.
    try:
        request = read_document(pdf_path)
    except Exception as error:
        rprint(f"[bold yellow]Orchestrator[/]: [red]document extraction failed[/] - {error}")
        trace.append(f"[orchestrator] Document extraction failed: {error}")
        return _failure_decision(f"Document extraction failed: {error}", trace)

    trace.append(
        f"[orchestrator] Document extracted: {request.patient_name} "
        f"({request.diagnosis_code} / {request.procedure_code}, "
        f"{request.payer_name} member {request.member_id})"
    )

    # Step 3 + 4: dispatch to the payer-contact channel.
    try:
        decision = _dispatch(channel, request)
    except Exception as error:
        rprint(f"[bold yellow]Orchestrator[/]: [red]payer contact failed[/] - {error}")
        trace.append(f"[orchestrator] Payer contact failed: {error}")
        return _failure_decision(f"Payer contact failed: {error}", trace)

    # Step 5: assemble the final trace top-down so it reads as one story:
    #   [orchestrator] start -> [orchestrator] extracted -> [portal]/[ivr] ...
    #   -> [orchestrator] final decision
    final_line = (
        f"[orchestrator] Final decision: {decision.status} "
        f"via {decision.channel_used}{_ref_suffix(decision)}"
    )
    decision.trace = trace + decision.trace + [final_line]

    rprint(
        f"[bold yellow]Orchestrator[/]: final decision "
        f"[green]{decision.status}[/] via {decision.channel_used}"
        f"{_ref_suffix(decision)}"
    )
    return decision
