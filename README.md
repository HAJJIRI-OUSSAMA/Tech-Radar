# tech-radar — the brain

Nightly tech-significance digest. Phase 1: produce a great 3-7 item digest to Telegram.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in as each step needs it
```

## Run (steps 1.1-1.3: collect + pre-filter, no LLM yet)
```bash
python -m digest.run
```
Prints a candidate summary and writes `candidates.json` to eyeball before wiring the rubric (1.4).
