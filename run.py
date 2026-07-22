"""Phase 1, steps 1.1-1.3: collect -> dedupe -> pre-filter, then eyeball the candidates.

No LLM yet (that's step 1.4). The point of this run is to look at the raw candidate list
with your own eyes and sanity-check the sources + pre-filter before spending any tokens.

    python -m digest.run
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from dotenv import load_dotenv

from .collect import collect_all
from .process import dedupe, prefilter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
load_dotenv()


def main() -> None:
    raw = collect_all()
    deduped = dedupe(raw)
    candidates = prefilter(deduped)

    print(f"\nraw={len(raw)}  deduped={len(deduped)}  candidates={len(candidates)}")
    by_source = Counter(s for c in candidates for s in c["sources"])
    print("by source:", dict(by_source))
    multi = [c for c in candidates if len(c["sources"]) > 1]
    print(f"multi-source clusters: {len(multi)}\n")

    for c in candidates[:40]:
        kinds = "+".join(sorted({s.split(":", 1)[0] for s in c["sources"]}))
        print(f"[{c['engagement']:>5}] {kinds:<18} {c['title'][:80]}")

    with open("candidates.json", "w") as f:
        json.dump(candidates, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nwrote candidates.json ({len(candidates)} items)")


if __name__ == "__main__":
    main()
