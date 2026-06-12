"""Mock payer voice IVR (Twilio TwiML webhooks).

A telephony implementation of the same phone tree as ``mock_payer.ivr``, served
as TwiML over Twilio webhooks. It is the server half of the voice channel; the
Caller half lives in ``agents.voice_payer_contact``.

State management (stateless-friendly, demo-appropriate):
- The Twilio ``CallSid`` (sent in every webhook body) is the session key.
- Captured digits flow forward as query params on each ``<Gather action=...>``
  URL (e.g. ``/voice/menu_chosen?member_id=12345``).
- Per-call transcript and the final outcome are held in an in-memory
  ``CALL_SESSIONS`` dict and retrieved by the Caller via
  ``GET /voice/result/{call_sid}``.

Approval logic reuses ``mock_payer.ivr.KNOWN_MEMBERS`` so the voice and text
channels stay logically consistent; the reference number uses a ``VOICE-`` prefix
so the channel is visible in the result.

Run standalone:  uvicorn mock_payer.voice_ivr:app --port 8002
"""

from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import Gather, VoiceResponse

from mock_payer.ivr import KNOWN_MEMBERS, IVRResult

app = FastAPI(title="Mock Payer Voice IVR")

# In-memory per-call state, keyed by Twilio CallSid. Demo-only; no persistence.
CALL_SESSIONS: dict[str, dict] = {}

WELCOME_PROMPT = (
    "Welcome to BlueCross. For eligibility, press 1. For prior authorization, "
    "press 2. For claims, press 3. To speak with a representative, press 0."
)
MEMBER_PROMPT = (
    "You've reached prior authorization. Please enter the member's ID number, "
    "followed by the pound sign."
)
PA_MENU_PROMPT = (
    "To submit a new authorization request, press 1. To check an existing "
    "request, press 2. To return to the main menu, press 9."
)
PROC_PROMPT = (
    "Please enter the five-digit procedure code, followed by the pound sign."
)


def _session(call_sid: str) -> dict:
    """Return (creating if needed) the per-call session state."""
    return CALL_SESSIONS.setdefault(call_sid, {"transcript": []})


def _spoken(target: object, session: dict, text: str) -> None:
    """Speak a line via TwiML and record it in the call transcript."""
    session["transcript"].append(text)
    target.say(text)  # type: ignore[attr-defined]


def _twiml(response: VoiceResponse) -> Response:
    """Serialize a VoiceResponse to an XML HTTP response."""
    return Response(content=str(response), media_type="application/xml")


def _finalize(
    session: dict,
    response: VoiceResponse,
    status: str,
    reason: str | None,
    announcement: str,
    reference: str | None = None,
) -> None:
    """Announce a terminal outcome, store the IVRResult, and hang up."""
    _spoken(response, session, announcement)
    session["result"] = IVRResult(
        status=status,
        reference_number=reference,
        reason=reason,
        transcript=list(session["transcript"]),
    )
    response.hangup()


async def _body(request: Request) -> dict[str, str]:
    """Parse Twilio's url-encoded webhook body without python-multipart."""
    raw = (await request.body()).decode()
    return {key: values[0] for key, values in parse_qs(raw).items()}


@app.post("/voice/start")
async def voice_start(request: Request) -> Response:
    """Entry webhook: play the main menu and gather one digit."""
    form = await _body(request)
    session = _session(form.get("CallSid", ""))
    vr = VoiceResponse()
    gather = Gather(num_digits=1, action="/voice/start_choice", method="POST")
    _spoken(gather, session, WELCOME_PROMPT)
    vr.append(gather)
    # Fallback spoken only if the caller stays silent (Gather times out). Use
    # plain say(), not _spoken(): a silent call dead-ends with no stored result,
    # so this line must not pollute the transcript of a call that did proceed.
    vr.say("We did not receive any input. Goodbye.")
    vr.hangup()
    return _twiml(vr)


@app.post("/voice/start_choice")
async def voice_start_choice(request: Request) -> Response:
    """Handle the main-menu choice; '2' proceeds to prior authorization."""
    form = await _body(request)
    session = _session(form.get("CallSid", ""))
    vr = VoiceResponse()
    if form.get("Digits") == "2":
        gather = Gather(
            finish_on_key="#", timeout=10,
            action="/voice/member_entered", method="POST",
        )
        _spoken(gather, session, MEMBER_PROMPT)
        vr.append(gather)
    else:
        _finalize(
            session, vr, "PENDING_INFO",
            "Requested option is not available in this demo.",
            "That option is not available in this demo. Goodbye.",
        )
    return _twiml(vr)


@app.post("/voice/member_entered")
async def voice_member_entered(request: Request) -> Response:
    """Capture the member ID, then present the prior-auth submenu."""
    form = await _body(request)
    session = _session(form.get("CallSid", ""))
    member_id = form.get("Digits", "")
    vr = VoiceResponse()
    gather = Gather(
        num_digits=1,
        action=f"/voice/menu_chosen?member_id={member_id}", method="POST",
    )
    _spoken(gather, session, PA_MENU_PROMPT)
    vr.append(gather)
    return _twiml(vr)


@app.post("/voice/menu_chosen")
async def voice_menu_chosen(request: Request) -> Response:
    """Handle the submenu choice; '1' proceeds to procedure-code entry."""
    form = await _body(request)
    session = _session(form.get("CallSid", ""))
    member_id = request.query_params.get("member_id", "")
    vr = VoiceResponse()
    if form.get("Digits") == "1":
        gather = Gather(
            finish_on_key="#", timeout=10,
            action=f"/voice/proc_entered?member_id={member_id}", method="POST",
        )
        _spoken(gather, session, PROC_PROMPT)
        vr.append(gather)
    else:
        _finalize(
            session, vr, "PENDING_INFO",
            "Requested option is not available in this demo.",
            "That option is not available in this demo. Goodbye.",
        )
    return _twiml(vr)


@app.post("/voice/proc_entered")
async def voice_proc_entered(request: Request) -> Response:
    """Capture the procedure code, decide the outcome, and announce it."""
    form = await _body(request)
    session = _session(form.get("CallSid", ""))
    member_id = request.query_params.get("member_id", "")
    procedure_code = form.get("Digits", "")
    vr = VoiceResponse()

    if member_id not in KNOWN_MEMBERS:
        _finalize(
            session, vr, "DENIED", "Member ID not found.",
            "We could not locate that member ID. Your request cannot be "
            "processed. Goodbye.",
        )
    else:
        reference = f"VOICE-{member_id}-{procedure_code}"
        _finalize(
            session, vr, "APPROVED", None,
            f"Your request has been approved. Your reference number is "
            f"{reference}. Goodbye.",
            reference=reference,
        )
    return _twiml(vr)


@app.get("/voice/result/{call_sid}")
async def voice_result(call_sid: str) -> JSONResponse:
    """Return the stored IVRResult for a call, or 404 if not yet available."""
    session = CALL_SESSIONS.get(call_sid)
    if not session or "result" not in session:
        return JSONResponse(
            status_code=404, content={"detail": "result not ready"}
        )
    return JSONResponse(content=session["result"].model_dump())
