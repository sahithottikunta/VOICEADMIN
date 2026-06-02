"""Mock insurance payer portal (FastAPI).

Simulates a real payer's prior-authorization web API. The Payer Contact agent
calls this first; when it is "down" it returns HTTP 503, which triggers the
agent's fallback to the IVR channel.

Failure is deterministic and configurable via the PORTAL_FORCE_503 env var
(default "true") so the reference demo is reproducible:

    uvicorn mock_payer.portal:app --reload          # portal down -> 503
    PORTAL_FORCE_503=false uvicorn mock_payer.portal:app --reload   # portal up
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.models import PARequest

app = FastAPI(title="Mock Payer Portal")

# Procedure codes this payer auto-approves without manual review.
AUTO_APPROVED_PROCEDURES: set[str] = {"70551"}  # MRI Brain w/o contrast


class PortalResponse(BaseModel):
    """Raw decision returned by the payer portal.

    Intentionally narrower than PADecision: the portal only knows the payer's
    verdict, not which channel was used or the agent's trace.
    """

    status: str  # "APPROVED" | "DENIED" | "PENDING_INFO"
    reference_number: str | None = None
    reason: str | None = None


def _portal_is_down() -> bool:
    """Whether the portal should simulate an outage (HTTP 503)."""
    return os.getenv("PORTAL_FORCE_503", "true").lower() == "true"


def _decide(request: PARequest) -> PortalResponse:
    """Apply the payer's (toy) auto-approval rules to a PA request."""
    if request.procedure_code in AUTO_APPROVED_PROCEDURES:
        ref = f"PORTAL-{request.member_id}-{request.procedure_code}"
        return PortalResponse(status="APPROVED", reference_number=ref)
    return PortalResponse(
        status="PENDING_INFO",
        reason=f"Procedure {request.procedure_code} requires manual review.",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; reports whether the portal is simulating an outage."""
    return {"status": "down" if _portal_is_down() else "up"}


@app.post("/prior-auth", response_model=PortalResponse)
def prior_auth(request: PARequest) -> PortalResponse:
    """Submit a prior-auth request to the portal.

    Returns a PortalResponse when the portal is up, or raises HTTP 503 when it
    is simulating an outage (the demo default).
    """
    if _portal_is_down():
        print(f"[portal] simulating outage (503) for member {request.member_id}")
        raise HTTPException(status_code=503, detail="Portal temporarily unavailable")

    decision = _decide(request)
    print(f"[portal] {request.member_id} -> {decision.status}")
    return decision
