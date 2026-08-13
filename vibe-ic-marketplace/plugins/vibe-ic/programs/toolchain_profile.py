#!/usr/bin/env python3
"""toolchain_profile — a red-test baseline is only comparable to one measured
under the SAME toolchain, so the baseline has to carry it.

vibe-ic#1327. The landing standard is "a stack lands when its failures are a
SUBSET of main's". That sentence has no meaning while `main's` varies with the
host, and it does. MEASURED 2026-08-13, same commit `a38902d16`, two hosts in
this fleet, both clean and `porcelain=0`:

    host A   iverilog ABSENT    147 failed   121 non-matrix
    8HD-8    iverilog PRESENT   122 failed    95 non-matrix

One tool's difference. **25 failures of divergence** — far larger than the delta
most PRs produce, so a branch measured on one host and a baseline taken on the
other are not comparable.

WHAT THIS DOES NOT CLAIM, BECAUSE I GOT IT WRONG ONCE
------------------------------------------------------
An earlier draft of this module said the red set is "not monotonic in toolchain
completeness", on the strength of host A reporting 20 collection ERRORs against
8HD-8's 37. **That comparison was invalid and the claim is withdrawn.** The 37
were `ERROR: ` lines printed on stdout by `cvdp_gate.py`; 8HD-8's run reported
ZERO pytest errors — no `ERRORS` section, no `ERROR <nodeid>` summary rows. I
compared another host's pytest errors against my own host's program output.

On the corrected numbers the richer host had FEWER failures (122 vs 147) and
fewer errors (0 vs 20), which is consistent with monotonicity, not against it.
So "baseline on the barest host" is NOT refuted by this measurement, and this
module must not be read as evidence against it.

The divergence itself is what justifies this module, and it stands on the two
summary lines alone: **147 vs 122 failed for the same commit**. Whether the
relationship is monotonic is a separate question this data does not settle —
a subset relation needs the failure SETS compared node by node, which nobody
has done across two hosts. Until someone does, "comparable" cannot be inferred
from "richer", and a differing profile is a reason to refuse rather than to
subtract.

WHAT THIS REFUSES, AND WHY REFUSING IS THE POINT
------------------------------------------------
`<tool> not available — cannot be enforced` is an **rc-2 "I could not look"**
condition. It is not a pass and it is not a failure, and the whole of this
repository's discipline says such a thing must not be silently resolved into
either — the same rule as `VACUOUS_PASS`, and as `UNMEASURED` in the coverage
tool from #1306.

So :func:`compare` returns **REFUSE**, not a diff, when the two profiles differ.
A subtraction across unequal profiles produces a number that looks like a delta
and is not one: it silently attributes ~25 host-caused failures to the branch
under test, which is far larger than the delta most PRs produce. Reporting "I
cannot compare these" is worth more than a confident wrong subtraction.

NOT A GATE, DELIBERATELY
------------------------
This module answers a question; it does not fail a build. It exists to be called
by whatever compares a branch against a baseline — #1144's sharded landing gate
and the #1191 aggregator — so that comparison can refuse rather than subtract.
Wiring it to a gate before those exist would be a check with nothing to check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

#: The tools the gates in this repository actually key on. Derived from the
#: refusal sites rather than invented: `benchmark/cvdp_gate.py` names exactly
#: these three, and they are the ones whose presence moves the red set.
#:
#: Deliberately NOT every EDA binary that might be installed. A profile that
#: records tools no gate consults would report a difference where none of the
#: measurements can differ, and then this module would refuse comparisons that
#: are in fact sound.
KEYED_TOOLS: Tuple[str, ...] = ("iverilog", "yosys", "verilator")

#: Tools that gate *other* dimensions (DRC/LVS/layout). Recorded for the report
#: but NOT part of the fingerprint, for the reason above: no red in the measured
#: 122/147 sets is attributable to them today. Promote one into `KEYED_TOOLS`
#: only with a measurement showing it moves the count.
RECORDED_TOOLS: Tuple[str, ...] = ("klayout", "magic", "netgen", "openroad")

SAME = "SAME"
DIFFERENT = "DIFFERENT"
UNREADABLE = "UNREADABLE"


def probe(tools=KEYED_TOOLS) -> Dict[str, bool]:
    """`{tool: present}` on THIS host, by resolving it on PATH."""
    return {t: shutil.which(t) is not None for t in tools}


def profile() -> Dict[str, object]:
    """The full record: keyed tools decide comparability, recorded ones inform."""
    return {
        "keyed": probe(KEYED_TOOLS),
        "recorded": probe(RECORDED_TOOLS),
        "fingerprint": fingerprint(probe(KEYED_TOOLS)),
    }


def fingerprint(keyed: Dict[str, bool]) -> str:
    """A short stable digest of the KEYED tools only.

    Sorted, so it does not depend on dict order; over `KEYED_TOOLS` only, so a
    host that happens to install `klayout` stays comparable to one that does not.
    """
    payload = ";".join(f"{t}={bool(keyed.get(t))}" for t in sorted(KEYED_TOOLS))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _read(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def compare(baseline: Optional[dict], current: Optional[dict]) -> Tuple[str, str]:
    """`(verdict, sentence)` — SAME / DIFFERENT / UNREADABLE.

    UNREADABLE is its own verdict and never collapses into DIFFERENT: "the
    baseline did not record a profile" and "the baseline recorded a different
    profile" call for different remedies, and only the second is somebody's
    fault. Both refuse; neither guesses.
    """
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        return UNREADABLE, (
            "a profile could not be read, so comparability is UNKNOWN — this is "
            "not evidence that the profiles match")
    b_fp, c_fp = baseline.get("fingerprint"), current.get("fingerprint")
    if not b_fp or not c_fp:
        return UNREADABLE, (
            "a profile carries no fingerprint, so comparability is UNKNOWN. A "
            "baseline recorded before this module existed cannot be compared; "
            "re-measure it rather than assuming it matches.")
    if b_fp == c_fp:
        return SAME, f"toolchain fingerprint {b_fp} on both sides — comparable"
    b_keyed = baseline.get("keyed") or {}
    c_keyed = current.get("keyed") or {}
    moved = sorted(t for t in KEYED_TOOLS
                   if bool(b_keyed.get(t)) != bool(c_keyed.get(t)))
    detail = ", ".join(
        f"{t}: baseline={'PRESENT' if b_keyed.get(t) else 'ABSENT'} "
        f"current={'PRESENT' if c_keyed.get(t) else 'ABSENT'}" for t in moved)
    return DIFFERENT, (
        f"toolchain differs ({detail}), so a failure-set comparison would "
        f"attribute host-caused reds to the branch. MEASURED on this repo: one "
        f"tool's difference moved main's red set by 25 failures and 17 errors "
        f"(vibe-ic#1327). Re-measure the baseline on a matching host.")


def verdict_code(verdict: str) -> int:
    """0 comparable, 2 refuse. There is deliberately no exit code 1.

    A profile mismatch is not a FAILURE of the thing being measured — nothing is
    broken, we simply cannot answer. Giving it rc=1 would let a caller that
    treats non-zero as "the branch is bad" blame the branch for the host.
    """
    return 0 if verdict == SAME else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit", metavar="PATH",
                    help="write this host's profile as JSON")
    ap.add_argument("--compare", metavar="BASELINE_JSON",
                    help="compare a recorded baseline profile against this host")
    args = ap.parse_args(argv)

    cur = profile()
    if args.emit:
        Path(args.emit).write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n")
        print(f"[EMIT] toolchain fingerprint {cur['fingerprint']} -> {args.emit}")
        return 0

    if args.compare:
        verdict, sentence = compare(_read(Path(args.compare)), cur)
        tag = "OK" if verdict == SAME else "REFUSE"
        print(f"[{tag}] {verdict}: {sentence}")
        return verdict_code(verdict)

    keyed = cur["keyed"]
    print(f"toolchain fingerprint {cur['fingerprint']}")
    for t in sorted(KEYED_TOOLS):
        print(f"  keyed    {t:<10} {'PRESENT' if keyed[t] else 'ABSENT'}")
    for t in sorted(RECORDED_TOOLS):
        print(f"  recorded {t:<10} "
              f"{'PRESENT' if cur['recorded'][t] else 'ABSENT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
