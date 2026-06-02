"""Document Reader agent.

Reads a clinical-note PDF, sends its text to Gemini with a structured-output
prompt, and returns a validated ``PARequest``. This is the only component that
produces a PARequest; everything downstream operates on its output.
"""

import os
import warnings

# We intentionally remain on the legacy `google-generativeai` SDK: CLAUDE.md
# mandates it. It emits a FutureWarning that it is deprecated in favor of
# `google-genai`; migrating is a known, deliberate follow-up, so we suppress
# just that one warning here to keep the CLI demo output clean. We match on the
# message (not module): the SDK raises it with a stacklevel pointing at the
# importer, so a module-based filter wouldn't catch it.
warnings.filterwarnings(
    "ignore",
    message=r"(?s).*google\.generativeai.*",
    category=FutureWarning,
)

import google.generativeai as genai  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from rich import print as rprint  # noqa: E402

from agents.models import PARequest  # noqa: E402

DEFAULT_MODEL = "gemini-2.5-flash"


def _load_api_key() -> str:
    """Load GEMINI_API_KEY from .env (or the environment)."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )
    return api_key


def _extract_text(pdf_path: str) -> str:
    """Extract and concatenate text from every page of the PDF."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(f"No extractable text found in {pdf_path}")
    return text


def _build_prompt(note_text: str) -> str:
    """Assemble the extraction instruction and append the note text."""
    return (
        "You are a prior-authorization intake assistant. Extract the following "
        "fields from the clinical note below.\n"
        "- patient_name: the patient's full name.\n"
        "- diagnosis_code: the ICD-10 diagnosis code (e.g. G43.909).\n"
        "- procedure_code: the CPT procedure code being requested (e.g. 70551).\n"
        "- member_id: the patient's insurance member ID.\n"
        "- payer_name: the insurance company name (e.g. BlueCross).\n"
        "Return only the structured fields, drawn strictly from the note.\n\n"
        "--- CLINICAL NOTE ---\n"
        f"{note_text}"
    )


def _call_gemini(prompt: str) -> str:
    """Send the prompt to Gemini in JSON mode and return the raw JSON text."""
    model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=PARequest,
            temperature=0,
        ),
    )
    return response.text


def read_document(pdf_path: str) -> PARequest:
    """Extract a structured PARequest from a clinical-note PDF via Gemini."""
    genai.configure(api_key=_load_api_key())

    note_text = _extract_text(pdf_path)
    rprint(
        f"[bold cyan]Document Reader[/]: extracted "
        f"{len(note_text)} chars from {pdf_path}"
    )

    raw_json = _call_gemini(_build_prompt(note_text))
    request = PARequest.model_validate_json(raw_json)
    rprint(
        f"[bold cyan]Document Reader[/]: parsed PARequest for "
        f"[green]{request.patient_name}[/] "
        f"({request.diagnosis_code} / {request.procedure_code}, "
        f"{request.payer_name} member {request.member_id})"
    )
    return request
