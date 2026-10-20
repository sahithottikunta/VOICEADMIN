# VoiceAdmin — Prior Authorization Agent

A multi-agent system that automates healthcare **Prior Authorization (PA)** requests. Give it a clinical note PDF and it:

1. **Reads** the note with Gemini and extracts the patient name, diagnosis (ICD-10), procedure (CPT), insurance member ID and payer.
2. **Contacts** a mock insurance payer, first through its portal API. If the portal is down, it **falls back to the payer's phone tree (IVR)**.
3. **Returns** an approval decision with a reference number and a full trace of every step it took.

The agent orchestration is written from scratch on direct Gemini API calls. It uses no LangChain, CrewAI or other agent framework.

> This is a portfolio demo. The payer is simulated, and the sample patient data is fictional.

---

## Architecture

```
                    ┌──────────────────────┐
  clinical_note.pdf │     Orchestrator     │  PADecision
 ──────────────────▶│ agents/orchestrator  │──────────────▶ CLI (rich)
                    └──────────┬───────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌─────────────────────┐          ┌──────────────────────────┐
   │   Document Reader   │          │      Payer Contact       │
   │  pypdf + Gemini     │ PARequest│  channel = auto | voice  │
   │  → PARequest        │─────────▶│                          │
   └─────────────────────┘          └────────────┬─────────────┘
                                                 │
                     ┌───────────────────────────┼──────────────────────────┐
                     ▼                           ▼ 5xx / conn. error        ▼ --channel voice
           ┌──────────────────┐        ┌──────────────────┐        ┌──────────────────────┐
           │  Portal API      │        │  Text IVR        │        │  Voice IVR (Twilio)  │
           │  FastAPI :8000   │        │  dict phone tree │        │  TwiML webhooks :8002│
           │  mock_payer/     │        │  mock_payer/     │        │  mock_payer/         │
           │  portal.py       │        │  ivr.py          │        │  voice_ivr.py        │
           └──────────────────┘        └──────────────────┘        └──────────────────────┘
```

| Component | File | Role |
|---|---|---|
| Orchestrator | [agents/orchestrator.py](agents/orchestrator.py) | Coordinates the agents, dispatches by channel, assembles the trace, and turns any failure into a `PENDING_INFO` decision instead of crashing |
| Document Reader | [agents/document_reader.py](agents/document_reader.py) | Extracts PDF text with `pypdf` and calls Gemini for structured output, validated into a `PARequest` |
| Payer Contact | [agents/payer_contact.py](agents/payer_contact.py) | Calls the portal first. On 5xx or a connection error it falls back to the IVR. On 4xx it returns `PENDING_INFO` with no fallback, because the IVR would reject a bad request too |
| Voice Payer Contact | [agents/voice_payer_contact.py](agents/voice_payer_contact.py) | Places a real outbound Twilio call that walks the same phone tree, then polls for the outcome |
| Data contracts | [agents/models.py](agents/models.py) | Pydantic `PARequest` and `PADecision` models shared by all agents |
| Mock portal | [mock_payer/portal.py](mock_payer/portal.py) | FastAPI payer API. Returns HTTP 503 by default to simulate an outage |
| Mock IVR | [mock_payer/ivr.py](mock_payer/ivr.py) | Touch-tone phone tree implemented as a `dict` state machine, with a transcript of every prompt |
| Voice IVR | [mock_payer/voice_ivr.py](mock_payer/voice_ivr.py) | The same phone tree served as TwiML over Twilio webhooks |

### Design decisions
- **Deterministic fallback rules.** A 5xx means the payer's system is broken, so the agent tries another channel. A 4xx means the request itself is bad, so switching channels won't help.
- **The orchestrator never raises.** Every path ends in a printable `PADecision`. The CLI exits with code `0` on `APPROVED` and `1` otherwise, so the run can gate a CI job.
- **Channel-prefixed traces.** Each trace line is tagged `[orchestrator]`, `[portal]`, `[ivr]` or `[voice]`, so a run reads as one story.
- **Pluggable channels.** The text IVR and the voice IVR share the same tree logic and the same `IVRResult` → `PADecision` conversion, so adding a channel takes one new branch in `_dispatch`.

---

## Tech stack
Python 3.11+ · Google Gemini (`google-generativeai`) · FastAPI + uvicorn · pypdf · pydantic · httpx · rich · Twilio (voice channel)

---

## Quick start

```bash
git clone https://github.com/sahithottikunta/VOICEADMIN.git
cd VOICEADMIN
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your-gemini-api-key
```

Start the mock portal in one terminal:

```bash
uvicorn mock_payer.portal:app --reload
```

Run the workflow in another terminal:

```bash
python run.py --input sample_data/sample_note.pdf
```

### Expected result
The sample note requests an **MRI Brain (CPT 70551)** for a **migraine** patient (**ICD-10 G43.909**) with **BlueCross member ID 12345**:

```
Orchestrator → Document Reader   extracts the PARequest via Gemini
Orchestrator → Payer Contact     portal returns 503 → falls back to IVR
IVR: 2 (prior auth) → 12345# → 1 (new request) → 70551#
Final decision: APPROVED via ivr (with a reference number)
```

To see the portal approve the request directly, start it with `PORTAL_FORCE_503=false`.

---

## Voice channel (Twilio) — optional

The voice channel places a real phone call. Twilio reads the IVR prompts aloud, and you answer them with your phone's keypad.

Add the following to `.env`:

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
MY_PHONE_NUMBER=+1...
VOICE_WEBHOOK_BASE_URL=https://<your-public-tunnel-url>
```

Start the voice IVR server, then expose it publicly with a tunnel. With ngrok, add the header shown below so that Twilio isn't served ngrok's browser-warning page:

```bash
uvicorn mock_payer.voice_ivr:app --port 8002
ngrok http 8002 --request-header-add="ngrok-skip-browser-warning:true"
```

Run the workflow over the voice channel:

```bash
python run.py --input sample_data/sample_note.pdf --channel voice
```

When the phone rings, press `2`, then `12345#`, then `1`, then `70551#`. The expected result is **APPROVED via voice** with reference `VOICE-12345-70551`.

---

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | yes | — | Gemini API key used by the Document Reader |
| `GEMINI_MODEL` | no | `gemini-2.5-flash` | Gemini model to use |
| `PORTAL_BASE_URL` | no | `http://localhost:8000` | Address of the mock portal |
| `PORTAL_FORCE_503` | no | `true` | Makes the portal simulate an outage |
| `TWILIO_*`, `MY_PHONE_NUMBER`, `VOICE_WEBHOOK_BASE_URL` | voice only | — | Twilio call settings |

---

## Project structure

```
├── agents/
│   ├── orchestrator.py          # coordinates the agents, builds the trace
│   ├── document_reader.py       # PDF → Gemini → PARequest
│   ├── payer_contact.py         # portal, then IVR fallback
│   ├── voice_payer_contact.py   # Twilio voice channel
│   └── models.py                # pydantic contracts
├── mock_payer/
│   ├── portal.py                # FastAPI payer portal
│   ├── ivr.py                   # dict-based phone tree
│   └── voice_ivr.py             # TwiML phone tree
├── sample_data/
│   ├── generate_sample_note.py  # builds the sample PDF (reportlab)
│   └── sample_note.pdf
├── run.py                       # CLI entry point
└── requirements.txt
```

---

## Roadmap
- [x] Agent pipeline: Document Reader → Payer Contact → Orchestrator
- [x] Portal → IVR fallback with a full decision trace
- [x] Twilio voice channel (code complete; verified by headless tests)
- [ ] Live end-to-end voice call
- [ ] FastAPI wrapper, Dockerfile and docker-compose
- [ ] Fly.io / Azure deployment
- [ ] CI/CD with GitHub Actions
- [ ] Observability
