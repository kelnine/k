#!/usr/bin/env python3
"""Verify that the indicator and the strategy share a byte-identical signal engine.

Both Pine files contain two marked blocks:

    // ╔═══ BEGIN SHARED CORE ═══╗  …  // ╔═══ END SHARED CORE ═══╗
    // ╔═══ BEGIN SHARED RUN ═══╗   …  // ╔═══ END SHARED RUN ═══╗

Everything that defines a signal — inputs, session clock, range builder, breakout /
retest / false-breakout logic, stop / target maths and the virtual trade tracker —
lives inside those blocks. If they differ, the strategy would be testing a different
signal than the indicator shows, so this check fails.

The Chart Beyond variant is generated from the indicator by make_chartbeyond.py; this
check also fails if that generated file is out of date.

Usage:
    python3 pine/tools/check_shared.py            # verify (exit 1 on mismatch)
    python3 pine/tools/check_shared.py --sync     # copy the indicator's blocks into the strategy
"""
from __future__ import annotations

import difflib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDICATOR = ROOT / "MultiSessionORBPro.pine"
STRATEGY = ROOT / "MultiSessionORBPro_Strategy.pine"
BLOCKS = ("SHARED CORE", "SHARED RUN")


def block_span(text: str, name: str) -> tuple[int, int]:
    begin = re.search(rf"^// ╔═+ BEGIN {name} ═+╗\n", text, re.M)
    end = re.search(rf"^// ╔═+ END {name} ═+╗$", text, re.M)
    if not begin or not end or end.start() < begin.end():
        raise SystemExit(f"markers for '{name}' not found or out of order")
    return begin.end(), end.start()


def main() -> int:
    ind = INDICATOR.read_text(encoding="utf-8")
    strat = STRATEGY.read_text(encoding="utf-8")
    if "--sync" in sys.argv:
        for name in BLOCKS:
            a0, a1 = block_span(ind, name)
            b0, b1 = block_span(strat, name)
            strat = strat[:b0] + ind[a0:a1] + strat[b1:]
        STRATEGY.write_text(strat, encoding="utf-8")
        print(f"synced {', '.join(BLOCKS)} into {STRATEGY.name}")
    ok = True
    for name in BLOCKS:
        a0, a1 = block_span(ind, name)
        b0, b1 = block_span(strat, name)
        a, b = ind[a0:a1], strat[b0:b1]
        if a == b:
            print(f"OK  {name}: identical ({a.count(chr(10))} lines)")
        else:
            ok = False
            print(f"FAIL {name} differs:")
            diff = difflib.unified_diff(a.splitlines(), b.splitlines(), "indicator", "strategy", lineterm="", n=1)
            for line in list(diff)[:60]:
                print("   ", line)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import make_chartbeyond  # noqa: E402

    cb = make_chartbeyond.TARGET
    if cb.exists() and cb.read_text(encoding="utf-8") == make_chartbeyond.build():
        print(f"OK  {cb.name}: up to date with the indicator")
    else:
        ok = False
        print(f"FAIL {cb.name} is missing or out of date: run python3 pine/tools/make_chartbeyond.py")
    for path, text in ((INDICATOR, ind), (STRATEGY, strat)):
        if not text.startswith("//@version=6\n"):
            ok = False
            print(f"FAIL {path.name}: first line must be //@version=6")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
