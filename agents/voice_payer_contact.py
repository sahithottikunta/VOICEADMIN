"""Voice Payer Contact agent (Twilio).

A drop-in alternative to ``payer_contact``'s text-IVR channel: it places a real
outbound Twilio call that walks the same phone tree (served by
``mock_payer.voice_ivr``), then retrieves the navigation outcome and wraps it
into a ``PADecision`` with ``channel_used="voice"``.

Two-process design: Twilio drives the webhooks inside the voice-IVR server,
which persists the outcome; this Caller polls the call status and then fetches
that outcome over HTTP. The pressed digits are not retrievable via Twilio's REST
API, so the result store is the bridge between the two halves.

Like ``contact_payer``, this never raises - every failure path (missing config,
call placement failure, timeout, no result) returns a PENDING_INFO PADecision so
the orchestrator and CLI always get a printable decision.
"""

import os
import time

import httpx
from dotenv import load_dotenv
from rich import print as rprint
from twilio.rest import Client

from agents.models import PADecision, PARequest
from agents.payer_contact import _decision_from_ivr
from mock_payer.ivr import IVRResult

POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 3
DEFAULT_RESULT_BASE_URL = "http://localhost:8002"
TERMINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}

_REQUIRED_VARS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "MY_PHONE_NUMBER",
    "VOICE_WEBHOOK_BASE_URL",
)


def _load_config() -> dict[str, str]:
    """Load Twilio + webhook config from .env, raising if anything is missing."""
    load_dotenv()
    config: dict[str, str] = {}
    missing: list[str] = []
    for var in _REQUIRED_VARS:
        value = os.getenv(var)
        if value:
            config[var] = value
        else:
            missing.append(var)
    if missing:
        raise RuntimeError(
            f"Missing required env vars for the voice channel: "
            f"{', '.join(missing)}"
        )
    config["VOICE_WEBHOOK_BASE_URL"] = config["VOICE_WEBHOOK_BASE_URL"].rstrip("/")
    config["VOICE_RESULT_BASE_URL"] = os.getenv(
        "VOICE_RESULT_BASE_URL", DEFAULT_RESULT_BASE_URL
    ).rstrip("/")
    return config


def _poll_until_complete(client: Client, call_sid: str) -> str:
    """Poll Twilio for the call status until terminal or the timeout elapses."""
    elapsed = 0
    status = "queued"
    while elapsed < POLL_TIMEOUT_SECONDS:
        status = client.calls(call_sid).fetch().status
        if status in TERMINAL_STATUSES:
            return status
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
    return status  # last seen, non-terminal -> treated as a timeout


def _fetch_result(result_base_url: str, call_sid: str) -> IVRResult | None:
    """Fetch the IVRResult the webhook server stored for this call."""
    url = f"{result_base_url}/voice/result/{call_sid}"
    try:
        response = httpx.get(url, timeout=10.0)
    except httpx.RequestError:
        return None
    if response.status_code != 200:
        return None
    return IVRResult.model_validate_json(response.text)


def _pending(reason: str, trace: list[str]) -> PADecision:
    """Build a PENDING_INFO voice decision for a failure path."""
    return PADecision(
        status="PENDING_INFO",
        channel_used="voice",
        reason=reason,
        trace=trace,
    )


def contact_payer_voice(request: PARequest) -> PADecision:
    """Place a Twilio call to navigate the IVR and return a PADecision."""
    trace: list[str] = []

    try:
        config = _load_config()
    except RuntimeError as error:
        rprint(f"[bold blue]Voice Payer Contact[/]: [red]config error[/] - {error}")
        trace.append(f"[voice] Configuration error: {error}")
        return _pending(str(error), trace)

    webhook_url = f"{config['VOICE_WEBHOOK_BASE_URL']}/voice/start"
    rprint(
        f"[bold blue]Voice Payer Contact[/]: placing call to "
        f"{config['MY_PHONE_NUMBER']} (Twilio webhook: {webhook_url})"
    )
    trace.append(f"[voice] Placing outbound call to {config['MY_PHONE_NUMBER']}")
    trace.append(f"[voice] Twilio webhook URL: {webhook_url}")
    trace.append(
        f"[voice] Caller should enter member {request.member_id} and "
        f"procedure {request.procedure_code} when prompted"
    )

    client = Client(config["TWILIO_ACCOUNT_SID"], config["TWILIO_AUTH_TOKEN"])
    try:
        call = client.calls.create(
            to=config["MY_PHONE_NUMBER"],
            from_=config["TWILIO_PHONE_NUMBER"],
            url=webhook_url,
            method="POST",
        )
    except Exception as error:  # noqa: BLE001 - report any Twilio failure honestly
        rprint(f"[bold blue]Voice Payer Contact[/]: [red]call failed[/] - {error}")
        trace.append(f"[voice] Failed to place call: {error}")
        return _pending(f"Failed to place call: {error}", trace)

    call_sid = call.sid
    trace.append(f"[voice] Call initiated (SID {call_sid})")
    rprint(
        f"[bold blue]Voice Payer Contact[/]: call {call_sid} placed, polling "
        f"for completion (timeout {POLL_TIMEOUT_SECONDS}s)"
    )

    status = _poll_until_complete(client, call_sid)
    trace.append(f"[voice] Call ended with status: {status}")
    if status != "completed":
        reason = f"Voice call did not complete (status={status})"
        rprint(f"[bold blue]Voice Payer Contact[/]: [red]{reason}[/]")
        return _pending(reason, trace)

    result = _fetch_result(config["VOICE_RESULT_BASE_URL"], call_sid)
    if result is None:
        reason = "Voice call completed but no IVR result was captured"
        rprint(f"[bold blue]Voice Payer Contact[/]: [red]{reason}[/]")
        trace.append(f"[voice] {reason}")
        return _pending(reason, trace)

    for line in result.transcript:
        trace.append(f"[voice] {line}")
    summary = f"[voice] Result: {result.status}"
    if result.reference_number:
        summary += f" (ref {result.reference_number})"
    if result.reason:
        summary += f" - {result.reason}"
    trace.append(summary)

    decision = _decision_from_ivr(result, trace, channel="voice")
    rprint(
        f"[bold blue]Voice Payer Contact[/]: decision [green]{decision.status}[/] "
        f"via voice"
        + (f" (ref {decision.reference_number})" if decision.reference_number else "")
    )
    return decision
