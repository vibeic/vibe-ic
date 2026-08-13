"""A FAILED gate report must contain the gate's finding, not its passing entries.

Measured 2026-08-13, while a 57-PR batch was blocked at push time. The hook
reported:

    pre-push: FAILED — benchmark evidence structure
        [PASS] …/benchmark-data/ic/spm/v1.9.96_gf180mcuD  (verdict=PASS_WITH_WAIVERS)

        benchmark_evidence_structure_check: 1/2 conformant, 1 nonconformant

Every visible line was about something that had passed. The finding — a file at
the IC level, where only `input/` and `v<ver>_<PDK>` cells may live — was printed
by the gate but never reached the person who had to act on it, because the hook
selected the excerpt with `tail -3` and gates print findings BEFORE passing
entries. The only way to learn what had failed was to re-run the gate by hand.

That is the repository's own lie-shape: a report whose subject and whose body
disagree. It sat in the hook that guards every push.

The guard below is paired in both directions, which is what makes it a check and
not a ban:

  - `test_finding_is_shown`  — the current selector must surface the finding
  - `test_tail_selector_would_fail_this` — the OLD selector, run on the same
    fixture, must NOT surface it. Without this arm a selector that prints the
    whole output unconditionally would pass the first test while proving nothing,
    and a future "simplification" back to `tail` would look green.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

def _find_hook() -> Path:
    """Walk up to the repo root rather than counting directories.

    A hard-coded `parents[N]` is a guess about how deep this file sits inside the
    marketplace layout, and it was wrong by exactly one level when first written.
    Searching upward for the artefact itself cannot be off by one, and survives
    the plugin being nested differently later.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tools" / "git-hooks" / "pre-push"
        if candidate.is_file():
            return candidate
    raise AssertionError("tools/git-hooks/pre-push not found above this test")


HOOK = _find_hook()

# The real output that blocked the push, verbatim in its original ORDER. The
# order is the whole point: a fixture with the [FAIL] line last cannot detect
# this defect, because `tail` would happen to catch it.
GATE_OUTPUT = (
    "[FAIL] benchmark-data/ic/spm\n"
    "    x IC_LEVEL_LAYOUT: 1 entry at the IC level is neither input/ nor a "
    "v<ver>_<PDK> cell: SOURCE_MANIFEST.md. Run output here is attributable to "
    "no plugin version and no PDK.\n"
    "[PASS] /x/benchmark-data/ic/spm/v1.9.96_gf180mcuD  (IC=spm PDK=gf180mcuD "
    "v1.9.96 verdict=PASS_WITH_WAIVERS)\n"
    "\n"
    "benchmark_evidence_structure_check: 1/2 conformant, 1 nonconformant\n"
)

FINDING = "IC_LEVEL_LAYOUT"
COUNTS = "1 nonconformant"


def _extract_helper() -> str:
    """Lift `_gate_excerpt` out of the hook so it can be exercised alone.

    The hook cannot simply be sourced: it runs a push's worth of gates on import.
    Reading the function out of it keeps this test bound to the SHIPPED text
    rather than to a copy that can drift away from it silently.
    """
    src = HOOK.read_text(encoding="utf-8")
    m = re.search(r"^_gate_excerpt\(\) \{.*?^\}", src, re.S | re.M)
    assert m, (
        "`_gate_excerpt` is not in tools/git-hooks/pre-push. If the failure "
        "excerpt was inlined back into run_gate, re-point this test at it — do "
        "not delete the test, the defect it guards is not theoretical."
    )
    return m.group(0)


def _run(selector_body: str) -> str:
    script = f"{selector_body}\n_gate_excerpt \"$(cat)\"\n"
    p = subprocess.run(
        ["bash", "-c", script],
        input=GATE_OUTPUT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, f"selector errored: {p.stderr}"
    return p.stdout


def test_finding_is_shown():
    out = _run(_extract_helper())
    assert FINDING in out, (
        "the FAILED excerpt does not contain the gate's finding. A reader is "
        "told the push was blocked and shown nothing they can act on:\n" + out
    )
    assert COUNTS in out, (
        "the excerpt dropped the summary line, which carries the counts:\n" + out
    )


def test_a_pass_line_alone_is_never_the_whole_report():
    """The precise shape that shipped: body consists only of passing entries."""
    out = _run(_extract_helper())
    body = [ln.strip() for ln in out.splitlines() if ln.strip()]
    assert body, "the excerpt was empty — a blocked push must say why"
    assert not all(
        ln.startswith("[PASS]") or "conformant" in ln for ln in body
    ), "every line of a FAILED report describes something that passed:\n" + out


def test_tail_selector_would_fail_this():
    """The negative arm: the selector this replaced must NOT pass.

    If this test ever goes green, the fixture has stopped being able to
    distinguish the two selectors and the positive test above is vacuous.
    """
    old = '_gate_excerpt() { printf "%s\\n" "$1" | tail -3 | sed "s/^/    /"; }'
    out = _run(old)
    assert FINDING not in out, (
        "the `tail -3` selector surfaced the finding, so this fixture no longer "
        "reproduces the defect and the positive test proves nothing"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
