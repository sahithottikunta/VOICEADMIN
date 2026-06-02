"""One-off generator for the demo clinical-note PDF.

Run this once to produce ``sample_data/sample_note.pdf``, then commit the PDF.
It is NOT called at runtime — the committed PDF is the fixture the demo reads.

    python sample_data/generate_sample_note.py

The demo facts (patient Jane Doe, MRI Brain w/o contrast CPT 70551, migraine
ICD-10 G43.909, BlueCross member 12345) are woven into natural clinical prose
rather than a labeled key/value list, so the Document Reader's extraction is a
genuine test of the LLM rather than a trivial pattern match.
"""

import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample_note.pdf")

# Each entry is a paragraph of the note. Demo facts are embedded in prose.
NOTE_PARAGRAPHS: list[str] = [
    "<b>NORTHSIDE NEUROLOGY ASSOCIATES</b>",
    "Clinical Progress Note &amp; Prior Authorization Request",
    "Date of Visit: May 28, 2026",
    "<b>Patient:</b> Jane Doe is a 34-year-old female who presents today for "
    "follow-up of her chronic headache disorder. She is insured through "
    "BlueCross under member identification number 12345.",
    "<b>History of Present Illness:</b> The patient reports a longstanding "
    "history of recurrent, throbbing, unilateral headaches accompanied by "
    "photophobia and nausea, consistent with migraine without aura. Episodes "
    "now occur up to twelve days per month. She has trialed and failed "
    "adequate courses of both NSAIDs and two separate triptan agents, and "
    "more recently a course of topiramate, without meaningful improvement.",
    "<b>Assessment:</b> Chronic migraine, intractable, without status "
    "migrainosus (ICD-10 G43.909). Given the increasing frequency, the "
    "refractory nature of her symptoms, and new-onset positional features, "
    "intracranial pathology must be excluded prior to escalating therapy.",
    "<b>Plan:</b> I am requesting prior authorization for magnetic resonance "
    "imaging of the brain without contrast (CPT 70551) to rule out a "
    "structural or secondary cause of her headaches. The study is medically "
    "necessary before initiating CGRP monoclonal antibody therapy. The "
    "request is submitted to BlueCross for member 12345.",
    "Electronically signed by Dr. Alan Reyes, MD — Board Certified Neurology",
]


def build_pdf(path: str = OUTPUT_PATH) -> str:
    """Render the clinical note to a PDF at ``path`` and return that path."""
    doc = SimpleDocTemplate(path, pagesize=letter, title="Clinical Note")
    styles = getSampleStyleSheet()
    body = styles["BodyText"]

    flowables: list = []
    for text in NOTE_PARAGRAPHS:
        flowables.append(Paragraph(text, body))
        flowables.append(Spacer(1, 10))

    doc.build(flowables)
    return path


if __name__ == "__main__":
    written = build_pdf()
    print(f"Wrote {written}")
