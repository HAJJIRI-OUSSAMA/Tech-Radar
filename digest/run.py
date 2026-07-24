"""Pipeline orchestrator.

    python -m digest.run                 # full run: collect -> process -> score
    python -m digest.run --no-llm        # steps 1.1-1.3 only, eyeball candidates, zero tokens
    python -m digest.run --replay DATE   # re-score an archived night after a rubric change
    python -m digest.run --limit 30      # cap candidates (cheap while iterating on the prompt)

Delivery (Telegram, step 1.5) is not wired yet — output goes to the terminal.
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter

from dotenv import load_dotenv

from . import archive, notify
from .collect import collect_all
from .process import dedupe, prefilter
from .score import MAX_DIGEST, THRESHOLD, model_name, score, select

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("digest.run")
load_dotenv()


def show_candidates(candidates: list[dict]) -> None:
    by_source = Counter(s.split(":", 1)[0] for c in candidates for s in c["sources"])
    multi = sum(1 for c in candidates if len(c["sources"]) > 1)
    print(f"\ncandidates={len(candidates)}  multi-source={multi}  by_source={dict(by_source)}\n")
    for c in candidates[:40]:
        kinds = "+".join(sorted({s.split(":", 1)[0] for s in c["sources"]}))
        print(f"[{c['engagement']:>5}] {kinds:<18} {c['title'][:80]}")


def show_digest(selected: list[dict]) -> None:
    if not selected:
        print("\n=== nothing major today ===")
        print("Correct output on a slow evening. Never pad to hit a count.\n")
        return
    print(f"\n=== digest: {len(selected)} item(s) ===\n")
    for s in selected:
        kinds = "+".join(sorted({x.split(':', 1)[0] for x in s["sources"]}))
        print(f"[{s['score']:>2}/10] {s['action'].upper():<6} {s['category']}")
        print(f"        {s['title'][:90]}")
        print(f"        why: {s['why']}")
        print(f"        {kinds} | {s['url'][:80]}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="stop after pre-filter, spend no tokens")
    ap.add_argument("--replay", metavar="YYYY-MM-DD", help="re-score an archived candidate set")
    ap.add_argument("--limit", type=int, help="cap candidates before scoring")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--tag", help="archive suffix, e.g. --tag ultra (keeps A/B runs separate)")
    ap.add_argument("--send", action="store_true", help="deliver to Telegram")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the Telegram message instead of sending it")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()

    if args.replay:
        candidates = archive.replay(args.replay)
        log.info("replaying %d candidates from %s", len(candidates), args.replay)
    else:
        raw = collect_all()
        deduped = dedupe(raw)
        candidates = prefilter(deduped)
        log.info("raw=%d deduped=%d candidates=%d", len(raw), len(deduped), len(candidates))

    if args.limit:
        candidates = candidates[:args.limit]

    show_candidates(candidates)

    if args.no_llm:
        print("--no-llm: stopping before the scoring call.")
        return

    scored, raws = score(candidates)

    # A quiet evening and a dead scorer look identical downstream. Never let a scoring
    # failure masquerade as "nothing major today" — that is the one bug that would go
    # unnoticed for weeks once this runs unattended.
    if candidates and not any(s["score"] > 0 for s in scored):
        reason = f"scoring failed: 0/{len(candidates)} candidates scored"
        log.error("SCORING FAILED: 0/%d items scored. This is NOT a quiet day.",
                  len(candidates))
        if not args.no_archive:
            archive.save(candidates, scored, [], raws, model_name(), tag=args.tag)
        if args.send or args.dry_run:
            notify.send_failure(reason, dry_run=args.dry_run)
        raise SystemExit(1)

    scored_count = sum(1 for s in scored if s["score"] > 0)
    if scored_count < len(candidates) * 0.9:
        log.warning("PARTIAL: only %d/%d candidates scored — digest may be missing items",
                    scored_count, len(candidates))

    selected = select(scored, threshold=args.threshold, cap=MAX_DIGEST)
    show_digest(selected)

    # Archive BEFORE delivering: a Telegram outage must not cost you the run's data,
    # which is the tuning ledger and the Actions keepalive.
    if not args.no_archive:
        archive.save(candidates, scored, selected, raws, model_name(), tag=args.tag)

    if args.send or args.dry_run:
        notify.send_digest(selected, dry_run=args.dry_run)


if __name__ == "__main__":
    main()