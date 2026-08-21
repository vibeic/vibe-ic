"""The refusal must not name a flag the entry point cannot express.

`--allow-pdk-target-mismatch` existed only on `phase3_one_shot_runner`.
`vibe_ic_one_shot_runner` — the canonical `/vibe-ic-all` front door — forwarded
only `--allow-oss-pdk-fallback`, so a DELIBERATE cross-PDK port was unreachable
from it: the user hit "declared PDK != resolved PDK, REFUSED", read a message
telling them to pass a flag, and could not pass it without abandoning the front
door and driving phase 3 by hand.

The refusal itself is correct and must stay. Measured on sha256 x gf180mcuD:
L19 derives `pdk_target=sky130` from L1, and L7's 9-corner sign-off table and
L9's SDC are sky130-specific, so gf180 numbers cannot claim that sign-off.
Control: spm's L1 names gf180mcuD as a SECOND target with its own library,
period and utilisation — which is why `spm x gf180mcuD` converges legitimately.

Chip-AGNOSTIC: argument plumbing only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
ENTRY = PROGRAMS / "vibe_ic_one_shot_runner.py"
PHASE3 = PROGRAMS / "phase3_one_shot_runner.py"
FLAG = "--allow-pdk-target-mismatch"


def _help(p: Path) -> str:
    return subprocess.run([sys.executable, str(p), "--help"],
                          capture_output=True, text=True).stdout


def test_phase3_accepts_the_flag():
    """The consumer half — if this ever stops being true, the forwarding below
    is pointing at nothing."""
    assert FLAG in _help(PHASE3)


def test_the_canonical_entry_point_accepts_the_flag():
    """THE defect: it did not."""
    assert FLAG in _help(ENTRY)


def test_the_entry_point_forwards_it_to_phase3():
    """Accepting an argument and ignoring it is worse than rejecting it — the
    user would believe they had disclosed the mismatch. Assert the forwarding
    exists, next to the sibling flag that was already forwarded."""
    src = ENTRY.read_text()
    assert re.search(
        r'allow_pdk_target_mismatch[^\n]*\n\s*p3_args\.append\(\s*"'
        + re.escape(FLAG) + r'"', src), \
        "the flag is parsed but never appended to the phase-3 argv"


def test_the_sibling_flag_still_forwards():
    """Control: the pre-existing pass-through must not have been disturbed."""
    src = ENTRY.read_text()
    assert '"--allow-oss-pdk-fallback"' in src
    assert re.search(
        r'allow_oss_pdk_fallback[^\n]*\n\s*p3_args\.append\(', src)
