"""Pydantic data schemas shared between the PA agents.

These models are the contract every agent depends on: the Document Reader
produces a PARequest, the Payer Contact agent consumes it and produces a
PADecision, and the Orchestrator passes both around.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PARequest(BaseModel):
    """A structured prior authorization request.

    Extracted from a clinical note by the Document Reader agent and handed to
    the Payer Contact agent to seek an approval decision.
    """

    patient_name: str
    diagnosis_code: str  # ICD-10
    procedure_code: str  # CPT
    member_id: str
    payer_name: str  # e.g. "BlueCross"


class PADecision(BaseModel):
    """The final prior authorization decision.

    Produced by the Payer Contact agent (via portal or IVR) and returned by the
    Orchestrator, including a trace of the steps taken to reach the decision.
    """

    status: Literal["APPROVED", "DENIED", "PENDING_INFO"]
    reference_number: str | None = None
    channel_used: Literal["portal", "ivr"]
    trace: list[str] = Field(default_factory=list)
    reason: str | None = None
