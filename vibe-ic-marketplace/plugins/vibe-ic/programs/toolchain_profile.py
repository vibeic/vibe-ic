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
summary lines alone: **147 vs 122 failed for the same commit**.

MEASURED AFTERWARDS, node by node, over the 12 `test_cvdp_gate*` files — the
family where the toolchain decides, and where 41 of this host's 122 failures
live. Identical invocation both sides, only the environment differing:

    bare host (iverilog only)     29 failed, 135 passed, 51 skipped
    container (full toolchain)     0 failed, 212 passed,  3 skipped

    in container but NOT bare  ->  NONE
    in bare but NOT container  ->  all 29

So for that family the relation is a strict SUBSET: more tools removed 29
failures and introduced none, and 48 skips became real runs that all passed.
"Baseline on the barest host" is SUPPORTED there, not refuted. Scope is one
family; the other ~81 non-matrix failures have not been compared this way.

THAT DOES NOT LICENSE SUBTRACTION, which is the point this module turns on.
Even where the subset holds, a gate that subtracts a bare-host baseline from a
container-run branch attributes all 29 to a PR that touched none of them. The
counts are incomparable regardless of which way the sets nest, so a differing
profile is a reason to REFUSE rather than to subtract.

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
import re
import shutil
import subprocess
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


#: `-V` and not `--version`, measured rather than assumed: all three KEYED
#: tools answer `-V` with rc=0, and **iverilog rejects `--version`** —
#: `iverilog: invalid option -- '-'`, rc=1. That matters more than it looks. A
#: naive `--version` would record the SAME error string on every host, so the
#: version key would be perfectly stable and perfectly uninformative — a fix
#: that reads identically whether or not it works, which is the one shape this
#: module exists to remove.
_VERSION_FLAG = "-V"

#: The first dotted numeral in the tool's own banner. NUMBER ONLY, deliberately:
#: `iverilog -V` reports `Icarus Verilog version 14.0 (devel) (s20260301-263-ge02a0bc)`
#: and `yosys -V` reports `Yosys 0.33 (git sha1 2584903a060)`. Keying on the whole
#: banner would make two hosts running the same release but different devel
#: builds INCOMPARABLE, and this module's own KEYED_TOOLS note warns against
#: exactly that: "then this module would refuse comparisons that are in fact
#: sound." The measured counterexample this closes is a MAJOR difference —
#: iverilog 11.0 vs 14.0 — and the numeral separates those.
_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

#: What the payload records when a tool is PRESENT and its version could not be
#: read. Its own token, never folded into "absent": a tool that is installed but
#: unanswerable is a different host state from one that is not installed, and
#: collapsing them would let the two compare as SAME.
UNKNOWN_VERSION = "?"


def tool_version(tool: str, timeout: int = 10) -> Optional[str]:
    """The dotted version of *tool*, or None if it cannot be read.

    `timeout` is 10s — far under the 60s inner ceiling a 180s harness implies —
    because this is a banner print, and a bound that promises time the harness
    will not give turns one slow tool into a dead session (vibe-ic#1181).
    """
    if shutil.which(tool) is None:
        return None
    try:
        out = subprocess.run([tool, _VERSION_FLAG], capture_output=True,
                             text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = _VERSION_RE.search((out.stdout or "") + (out.stderr or ""))
    return m.group(0) if m else None


def versions(tools=KEYED_TOOLS) -> Dict[str, Optional[str]]:
    """`{tool: version-or-None}` on THIS host."""
    return {t: tool_version(t) for t in tools}


def profile() -> Dict[str, object]:
    """The full record: keyed tools decide comparability, recorded ones inform."""
    keyed = probe(KEYED_TOOLS)
    vers = versions(KEYED_TOOLS)
    return {
        "keyed": keyed,
        "versions": vers,
        "recorded": probe(RECORDED_TOOLS),
        "fingerprint": fingerprint(keyed, vers),
    }


def fingerprint(keyed: Dict[str, bool],
                vers: Optional[Dict[str, Optional[str]]] = None) -> str:
    """A short stable digest of the KEYED tools' PRESENCE and VERSION.

    Sorted, so it does not depend on dict order; over `KEYED_TOOLS` only, so a
    host that happens to install `klayout` stays comparable to one that does not.

    WHY VERSION AND NOT ONLY PRESENCE (vibe-ic#1353 review, measured). Presence
    alone let two hosts carry the SAME stamp while legitimately disagreeing:

        iverilog 11.0   binding an absent parameter -> WARNING, rc=0  -> 2 tests FAIL
        iverilog 14.0   the same case              -> ERROR,   rc=2  -> the same 2 PASS

    Both report `iverilog PRESENT`, so both fingerprinted identically, and a
    subset judgement across them would have attributed a version-caused red to
    the branch — the very substitution this module was written to stop, one
    field narrower.

    `vers=None` is NOT a compatibility shim for the old payload: it produces the
    all-unknown payload, which hashes differently from the pre-version scheme on
    purpose. A baseline recorded before versions were keyed must be re-measured,
    not silently read as matching — the same rule `compare` already applies to a
    baseline carrying no fingerprint at all.
    """
    vers = vers or {}
    payload = ";".join(
        f"{t}={bool(keyed.get(t))}@{vers.get(t) or UNKNOWN_VERSION}"
        for t in sorted(KEYED_TOOLS))
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

    # A VERSION-only difference moves the fingerprint while `moved` stays empty.
    # Without this branch the sentence read "toolchain differs ()" — an empty
    # parenthesis and no way to tell a version drift from a bug in this
    # function. Naming the tool and both versions is the difference between a
    # refusal somebody can act on and one they will work around.
    if not moved:
        b_v = baseline.get("versions")
        c_v = current.get("versions")
        if b_v is None:
            return DIFFERENT, (
                "the same KEYED tools are present on both sides, but the "
                "baseline predates version-keyed fingerprints (no `versions` "
                "key), so its stamp cannot be compared with one that includes "
                "them. Re-measure the baseline; do not assume it matches — "
                "iverilog 11.0 and 14.0 disagree about two tests while both "
                "reporting PRESENT (vibe-ic#1353).")
        b_v, c_v = b_v or {}, c_v or {}
        vmoved = sorted(t for t in KEYED_TOOLS
                        if (b_v.get(t) or UNKNOWN_VERSION)
                        != (c_v.get(t) or UNKNOWN_VERSION))
        vdetail = ", ".join(
            f"{t}: baseline={b_v.get(t) or UNKNOWN_VERSION} "
            f"current={c_v.get(t) or UNKNOWN_VERSION}" for t in vmoved)
        return DIFFERENT, (
            f"the same KEYED tools are present on both sides but their VERSIONS "
            f"differ ({vdetail}), so a failure-set comparison would attribute "
            f"version-caused reds to the branch. MEASURED: iverilog 11.0 treats "
            f"binding an absent parameter as a WARNING (rc=0) and 14.0 as an "
            f"ERROR (rc=2) — two tests change verdict, and presence alone cannot "
            f"see it (vibe-ic#1353). Re-measure the baseline on a matching host.")

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
