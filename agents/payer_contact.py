"""Payer Contact agent.

Consumes a validated ``PARequest`` and returns a ``PADecision``. It tries the
payer portal API first; on a 5xx or connection error it falls back to the IVR
channel. A 4xx is treated as a bad request (the IVR would fail too), so it is
wrapped directly without fallback. Every step is recorded in ``PADecision.trace``
as a channel-prefixed, human-readable line.

The navigation logic here is deterministic - no LLM call (per CLAUDE.md).

Forward-looking: a Twilio-backed ``voice_payer_contact`` variant will implement
the same IVR tree over real phone calls and return the same ``IVRResult`` shape.
``_decision_from_ivr`` is written to depend only on ``IVRResult`` so that variant
can reuse it; the orchestrator only ever sees ``contact_payer(request) ->
PADecision`` (or its voice twin) and never touches channel internals.
"""

import os

import httpx
from rich import print as rprint

from agents.models import PADecision, PARequest
from mock_payer import ivr
from mock_payer.ivr import IVRResult
from mock_payer.portal import PortalResponse

DEFAULT_PORTAL_BASE_URL = "http://localhost:8000"
PORTAL_TIMEOUT_SECONDS = 5.0


class _Portal4xx(Exception):
    """Raised when the portal returns a 4xx - a client error, not a failure.

    Signals contact_payer to wrap the rejection directly rather than fall back
    to the IVR.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Portal returned {status_code}")
        self.status_code = status_code
        self.detail = detail


def _portal_url() -> str:
    """Resolve the portal endpoint from PORTAL_BASE_URL (or the default)."""
    base = os.getenv("PORTAL_BASE_URL", DEFAULT_PORTAL_BASE_URL).rstrip("/")
    return f"{base}/prior-auth"


def _extract_detail(response: httpx.Response) -> str:
    """Pull a human-readable detail string out of an error response body."""
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return response.text


def _try_portal(request: PARequest, trace: list[str]) -> PortalResponse | None:
    """Attempt the portal.

    Returns the parsed PortalResponse on 2xx; raises _Portal4xx on a 4xx; and
    returns None on a 5xx or connection error (the signal to fall back to IVR).
    """
    url = _portal_url()
    trace.append(f"[portal] Attempting at {url}")
    rprint(f"[bold magenta]Payer Contact[/]: attempting portal at {url}")

    try:
        response = httpx.post(
            url, json=request.model_dump(), timeout=PORTAL_TIMEOUT_SECONDS
        )
    except httpx.RequestError as exc:
        trace.append(
            f"[portal] Connection error ({exc!r}) - falling back to IVR"
        )
        rprint(
            "[bold magenta]Payer Contact[/]: "
            "[red]portal unreachable[/] - falling back to IVR"
        )
        return None

    code = response.status_code
    if code >= 500:
        trace.append(
            f"[portal] Returned {code} {response.reason_phrase} - "
            "treating as failure, falling back to IVR"
        )
        rprint(
            f"[bold magenta]Payer Contact[/]: portal returned "
            f"[red]{code}[/] - falling back to IVR"
        )
        return None
    if code >= 400:
        detail = _extract_detail(response)
        trace.append(
            f"[portal] Returned {code} {response.reason_phrase} - "
            "client error, not falling back"
        )
        raise _Portal4xx(code, detail)

    portal_response = PortalResponse.model_validate_json(response.text)
    summary = f"[portal] Returned {code} {portal_response.status}"
    if portal_response.reference_number:
        summary += f" (ref {portal_response.reference_number})"
    trace.append(summary)
    return portal_response


def _call_ivr(request: PARequest, trace: list[str]) -> IVRResult:
    """Drive the IVR fallback and fold its transcript into the trace."""
    trace.append("[ivr] Falling back to IVR channel")
    rprint("[bold magenta]Payer Contact[/]: navigating IVR phone tree")

    result = ivr.navigate(request=request)
    for line in result.transcript:
        trace.append(f"[ivr] {line}")

    summary = f"[ivr] Result: {result.status}"
    if result.reference_number:
        summary += f" (ref {result.reference_number})"
    if result.reason:
        summary += f" - {result.reason}"
    trace.append(summary)
    return result


def _decision_from_portal(
    response: PortalResponse, trace: list[str]
) -> PADecision:
    """Wrap a successful (2xx) portal response into a PADecision."""
    return PADecision(
        status=response.status,
        reference_number=response.reference_number,
        channel_used="portal",
        trace=trace,
        reason=response.reason,
    )


def _decision_from_portal_rejection(
    status_code: int, detail: str, trace: list[str]
) -> PADecision:
    """Wrap a 4xx portal rejection into a PADecision (no fallback)."""
    return PADecision(
        status="PENDING_INFO",
        reference_number=None,
        channel_used="portal",
        trace=trace,
        reason=f"Portal rejected request (HTTP {status_code}): {detail}",
    )


def _decision_from_ivr(result: IVRResult, trace: list[str]) -> PADecision:
    """Wrap an IVR result into a PADecision.

    Depends only on the IVRResult shape, so the forthcoming Twilio voice variant
    can reuse it unchanged. The IVR's status/reason are copied honestly - a
    PENDING_INFO or DENIED is reported as-is, never dressed up as success.
    """
    return PADecision(
        status=result.status,
        reference_number=result.reference_number,
        channel_used="ivr",
        trace=trace,
        reason=result.reason,
    )


def contact_payer(request: PARequest) -> PADecision:
    """Obtain a PADecision for a PA request: try the portal, fall back to IVR."""
    trace: list[str] = []

    try:
        portal_response = _try_portal(request, trace)
    except _Portal4xx as exc:
        rprint(
            f"[bold magenta]Payer Contact[/]: portal rejected request "
            f"([red]{exc.status_code}[/]) - not falling back"
        )
        return _decision_from_portal_rejection(exc.status_code, exc.detail, trace)

    if portal_response is not None:
        decision = _decision_from_portal(portal_response, trace)
    else:
        ivr_result = _call_ivr(request, trace)
        decision = _decision_from_ivr(ivr_result, trace)

    rprint(
        f"[bold magenta]Payer Contact[/]: decision [green]{decision.status}[/] "
        f"via {decision.channel_used}"
        + (f" (ref {decision.reference_number})" if decision.reference_number else "")
    )
    return decision
