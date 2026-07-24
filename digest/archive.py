"""Persist every run to archive/YYYY-MM-DD.json.

Two jobs, both load-bearing:

1. Rubric tuning. You cannot tell whether a prompt change helped without re-running it
   against the SAME candidate set. `replay` reloads a past night's candidates so you can
   diff old scores against new ones instead of tuning blind.
2. Keepalive. On a public repo, GitHub disables scheduled workflows after 60 days with no
   commit activity. Committing this archive each night resets that timer for free.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger("digest.archive")

ARCHIVE_DIR = Path("archive")


def _serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"not JSON serializable: {type(obj)}")


def save(
    candidates: list[dict],
    scored: list[dict],
    selected: list[dict],
    raws: list[str],
    model: str,
    run_date: date | None = None,
    tag: str | None = None,
) -> Path:
    """tag keeps A/B runs from clobbering each other: re-scoring the same candidates
    with a different model must produce a second file, not overwrite the first."""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    run_date = run_date or datetime.now(timezone.utc).date()
    suffix = f"-{tag}" if tag else ""
    path = ARCHIVE_DIR / f"{run_date.isoformat()}{suffix}.json"

    payload = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "counts": {
            "candidates": len(candidates),
            "scored": sum(1 for s in scored if s["score"] > 0),
            "selected": len(selected),
        },
        "selected": selected,
        "scored": scored,
        "candidates": candidates,
        "raw_responses": raws,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_serialize, ensure_ascii=False)
    log.info("archived run to %s", path)
    return path


def replay(run_date: str) -> list[dict]:
    """Reload a past night's candidates to re-score them after a rubric change.

    Accepts a bare date ("2026-07-22") or a tagged stem ("2026-07-22-ultra"). A bare
    date falls back to the first tagged file for that day, since tagged runs are the
    common case and save() writes them by default.
    """
    path = ARCHIVE_DIR / f"{run_date}.json"
    if not path.exists():
        matches = sorted(ARCHIVE_DIR.glob(f"{run_date}*.json"))
        if not matches:
            raise FileNotFoundError(
                f"no archive for {run_date}. Available: "
                f"{[p.stem for p in sorted(ARCHIVE_DIR.glob('*.json'))]}"
            )
        path = matches[0]
        log.info("replaying %s", path.name)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    for c in data["candidates"]:
        c["published_at"] = datetime.fromisoformat(c["published_at"])
    return data["candidates"]
