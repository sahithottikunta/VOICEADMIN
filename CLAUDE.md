# VoiceAdmin Demo — Prior Authorization Agent

## Session Log
**Saturday session — completed**
- Built: models.py, mock_payer/portal.py + ivr.py, sample_data PDF generator + fixture, document_reader.py, payer_contact.py, orchestrator.py, run.py
- Verified end-to-end: `python run.py --input sample_data/sample_note.pdf` returns APPROVED via IVR fallback with exit 0; missing-PDF returns PENDING_INFO with exit 1
- Key design decisions: deterministic IVR text simulation (real telephony is a deliberate Sunday addition); 4xx → PENDING_INFO no-fallback; channel-prefixed traces; orchestrator owns trace assembly
- Architecture seam ready for tomorrow's voice variant: orchestrator._dispatch has the elif slot; payer_contact._decision_from_ivr is reusable; run.py's --channel already accepts "voice"

**Sunday session — partial**
- Built: agents/voice_payer_contact.py, mock_payer/voice_ivr.py (Twilio + TwiML voice channel)
- Updated: models.py (channel "voice"), payer_contact.py (channel param on _decision_from_ivr), orchestrator.py (voice dispatch branch)
- Headless verification: all 4 tests passed (imports, simulated webhook walk, config guard, text-path regression)
- Live call status: Twilio places call successfully, phone rings, but ngrok free-tier browser-warning interstitial blocks Twilio from receiving TwiML — call sits silent. Fix is known: restart ngrok with `--request-header-add="ngrok-skip-browser-warning:true"` flag, OR claim a free static domain.

**Resume here next session**
1. Restart ngrok with bypass header (or static domain)
2. Update VOICE_WEBHOOK_BASE_URL in .env to the new URL
3. Re-run: python run.py --input sample_data/sample_note.pdf --channel voice
4. Pickup phone, press 2 / 12345# / 1 / 70551# at the prompts
5. Expect APPROVED via voice with reference VOICE-12345-70551

**Remaining roadmap**
- Block 2: FastAPI wrapper around run.py logic + Dockerfile + docker-compose
- Block 3: Fly.io deployment, get live public URL
- Block 4: README with architecture diagram + push to GitHub
- This week: CI/CD (GitHub Actions), Azure deployment, observability, blog post

## Project Goal
A weekend demo project that simulates a multi-agent system for handling healthcare Prior Authorization (PA) requests. Given a clinical note (PDF), the system extracts structured info, contacts a mock insurance payer (via API or simulated IVR fallback), and returns an approval decision. This is a portfolio piece, not production code.

## Architecture
Three agents coordinated by an orchestrator:

1. **Orchestrator** (`agents/orchestrator.py`)
   - Entry point for any PA request
   - Decides which sub-agents to call and in what order
   - Handles failures and fallbacks between channels
   - Returns the final approval decision

2. **Document Reader Agent** (`agents/document_reader.py`)
   - Input: path to a clinical note PDF
   - Output: structured JSON with patient name, diagnosis code (ICD-10), procedure code (CPT), insurance member ID

3. **Payer Contact Agent** (`agents/payer_contact.py`)
   - Input: structured PA request
   - Tries the mock portal API first (`mock_payer/portal.py`)
   - On portal failure, falls back to the mock IVR (`mock_payer/ivr.py`)
   - Output: approval status with reference number

## Tech Stack
- **Python 3.11+**
- **Google Gemini API** (free tier) for all LLM calls inside agents — use the `google-generativeai` library
- **FastAPI + uvicorn** for the mock payer portal
- **pypdf** for reading PDF files
- **pydantic** for structured data schemas
- **python-dotenv** for loading the API key from `.env`
- **rich** for pretty CLI output

## Folder Structure
```
voiceadmin-agent/
├── agents/              # The 3 agents
├── mock_payer/          # Fake portal (FastAPI) + fake IVR (Python dict tree)
├── sample_data/         # Sample clinical PDFs for demo
├── run.py               # CLI entry point
├── CLAUDE.md            # This file
├── README.md            # Project description for humans
├── requirements.txt     # Python dependencies
├── .env                 # GEMINI_API_KEY lives here (NEVER commit)
└── .gitignore
```

## Conventions
- All functions must have type hints
- Use `pydantic.BaseModel` for any structured data passed between agents
- Use `rich.print` for any user-facing CLI output (colored, readable)
- Keep functions short — one responsibility each
- Log every agent decision to stdout so the demo run is readable

## Important Constraints — Do NOT
- Do NOT use LangChain, LlamaIndex, CrewAI, or any agent framework. Call the Gemini API directly via `google-generativeai`. The whole point is to show I can build agent orchestration from primitives.
- Do NOT add a database. JSON files in `sample_data/` are sufficient.
- Do NOT add a frontend. CLI only.
- Do NOT use Anthropic's API at runtime — Gemini only (the Claude API key is not available here).
- Do NOT mock the LLM calls — agents must actually call Gemini.
- Do NOT add tests beyond a simple sanity check unless I explicitly ask.

## Commands
- Install deps: `pip install -r requirements.txt`
- Start mock payer portal: `uvicorn mock_payer.portal:app --reload`
- Run a PA workflow: `python run.py --input sample_data/sample_note.pdf`

## Demo Scenario
The reference scenario the project should handle end-to-end:
- Input: PDF clinical note requesting an MRI Brain (CPT 70551) for a migraine patient (ICD-10 G43.909) with BlueCross member ID 12345
- Orchestrator calls Document Reader → gets structured request
- Orchestrator calls Payer Contact → portal returns 503 → falls back to IVR → IVR returns APPROVED with a reference number
- Orchestrator returns final result with full trace of decisions


