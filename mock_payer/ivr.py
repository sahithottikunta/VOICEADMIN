"""Mock insurance payer IVR (interactive voice response).

A pure-Python simulation of a touch-tone phone tree, used as the fallback
channel when the portal API is down. The phone tree is a nested ``dict`` state
machine; ``navigate()`` walks it given a sequence of "keypresses" and returns a
structured result, including a transcript of every prompt "spoken" along the
way (so the CLI demo reads like a real call).

Two calling styles are supported:

    navigate(inputs=["2", "12345", "1", "70551"])   # manual / testing
    navigate(request=pa_request)                     # agent-style, auto-filled
"""

from pydantic import BaseModel

from agents.models import PARequest

# Members this payer recognizes. Unlike the portal, the IVR approves on member
# eligibility alone (no procedure-code rule) — intentionally different logic so
# the orchestrator is seen handling two independent systems.
KNOWN_MEMBERS: dict[str, str] = {"12345": "BlueCross PPO"}


class IVRResult(BaseModel):
    """Raw outcome of an IVR call.

    Mirrors the portal's response shape so the Payer Contact agent can wrap
    either channel into a PADecision the same way. ``transcript`` is the
    IVR-specific extra: the ordered list of prompts spoken during the call.
    """

    status: str  # "APPROVED" | "DENIED" | "PENDING_INFO"
    reference_number: str | None = None
    reason: str | None = None
    transcript: list[str] = []


# The phone tree. Each node has a ``type``:
#   menu      -> consume one input, branch via ``options``
#   entry     -> consume one input, store under ``field``, go to ``next``
#   decision  -> compute outcome from captured context (terminal)
#   terminal  -> fixed outcome (used for stub branches)
IVR_TREE: dict[str, dict] = {
    "start": {
        "type": "menu",
        "prompt": (
            "Welcome to BlueCross. For eligibility, press 1. "
            "For prior authorization, press 2. For claims, press 3. "
            "To speak with a representative, press 0."
        ),
        "options": {
            "1": "eligibility_stub",
            "2": "pa_member_entry",
            "3": "claims_stub",
            "0": "agent_stub",
        },
    },
    "pa_member_entry": {
        "type": "entry",
        "prompt": (
            "You've reached prior authorization. Please enter the member's "
            "ID number, followed by the pound sign."
        ),
        "field": "member_id",
        "next": "pa_menu",
    },
    "pa_menu": {
        "type": "menu",
        "prompt": (
            "To submit a new authorization request, press 1. "
            "To check an existing request, press 2. "
            "To return to the main menu, press 9."
        ),
        "options": {
            "1": "pa_proc_entry",
            "2": "status_stub",
            "9": "start",
        },
    },
    "pa_proc_entry": {
        "type": "entry",
        "prompt": (
            "Please enter the five-digit procedure code, followed by the "
            "pound sign."
        ),
        "field": "procedure_code",
        "next": "pa_submit",
    },
    "pa_submit": {
        "type": "decision",
        "prompt": "Please hold while we process your authorization request.",
    },
    # --- Stub branches: present for realism, not exercised by the demo. ---
    "eligibility_stub": {
        "type": "terminal",
        "prompt": "Eligibility services are not available in this demo. Goodbye.",
        "status": "PENDING_INFO",
        "reason": "Eligibility line not implemented.",
    },
    "claims_stub": {
        "type": "terminal",
        "prompt": "Claims services are not available in this demo. Goodbye.",
        "status": "PENDING_INFO",
        "reason": "Claims line not implemented.",
    },
    "agent_stub": {
        "type": "terminal",
        "prompt": "All representatives are busy. Please try again later. Goodbye.",
        "status": "PENDING_INFO",
        "reason": "No live representative available.",
    },
    "status_stub": {
        "type": "terminal",
        "prompt": "Request status lookup is not available in this demo. Goodbye.",
        "status": "PENDING_INFO",
        "reason": "Status lookup not implemented.",
    },
}


def _inputs_from_request(request: PARequest) -> list[str]:
    """Derive the happy-path keypress sequence for a PA request.

    Walks: prior authorization (2) -> member ID -> submit new request (1) ->
    procedure code.
    """
    return ["2", request.member_id, "1", request.procedure_code]


def _decide(context: dict[str, str], transcript: list[str]) -> IVRResult:
    """Apply the IVR's member-eligibility rule and announce the outcome."""
    member_id = context.get("member_id", "")
    procedure_code = context.get("procedure_code", "")

    if member_id not in KNOWN_MEMBERS:
        transcript.append(
            "We could not locate that member ID. Your request cannot be "
            "processed. Goodbye."
        )
        return IVRResult(
            status="DENIED",
            reason="Member ID not found.",
            transcript=transcript,
        )

    reference = f"IVR-{member_id}-{procedure_code}"
    transcript.append(
        f"Your request has been approved. Your reference number is {reference}. "
        "Goodbye."
    )
    return IVRResult(
        status="APPROVED",
        reference_number=reference,
        transcript=transcript,
    )


def navigate(
    inputs: list[str] | None = None,
    request: PARequest | None = None,
) -> IVRResult:
    """Walk the IVR phone tree and return its outcome.

    Provide exactly one of ``inputs`` (a raw keypress sequence) or ``request``
    (a PARequest, from which the keypresses are auto-derived). If ``inputs`` is
    given it takes precedence.
    """
    if inputs is None and request is None:
        raise ValueError("navigate() requires either 'inputs' or 'request'.")
    if inputs is None:
        inputs = _inputs_from_request(request)  # type: ignore[arg-type]

    context: dict[str, str] = {}
    transcript: list[str] = []
    pressed = iter(inputs)
    node_key = "start"

    while True:
        node = IVR_TREE[node_key]
        transcript.append(node["prompt"])
        node_type = node["type"]

        if node_type == "decision":
            return _decide(context, transcript)

        if node_type == "terminal":
            return IVRResult(
                status=node["status"],
                reason=node.get("reason"),
                transcript=transcript,
            )

        value = next(pressed, None)
        if value is None:
            return IVRResult(
                status="PENDING_INFO",
                reason=f"No input provided at: {node['prompt']}",
                transcript=transcript,
            )

        if node_type == "menu":
            next_key = node["options"].get(value)
            if next_key is None:
                return IVRResult(
                    status="PENDING_INFO",
                    reason=f"Invalid option '{value}' at: {node['prompt']}",
                    transcript=transcript,
                )
            node_key = next_key
        elif node_type == "entry":
            context[node["field"]] = value
            node_key = node["next"]
