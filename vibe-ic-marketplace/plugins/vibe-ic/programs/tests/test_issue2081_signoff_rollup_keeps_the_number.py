#!/usr/bin/env python3
"""test_issue2081_signoff_rollup_keeps_the_number.py

A one-shot runner's per-step rollup must not silently amputate the reason a
FAILING step computed (vibe-ic#2081).

WHAT WAS MEASURED, AND WHERE
----------------------------
#2081 was filed from the published sha256 run (lane rbsha6). Its first stated
defect is that the design "halts at `drv_promotion_corroboration` — which
reports FAIL with no detail at all (the two gates behind it carry the
numbers)". Reproduced against that run's own artefacts on 2026-09-10:

  * the gate's report,
    `reports/phase3/sta/drv_promotion_corroboration.json`, carries
    `signoff_drv_violations: 368`, `claimed_drv_after: 176` and the sentence
    that explains them. It is not detail-free;
  * `run2.log:152` — the rollup a reader actually sees — is 157 characters and
    ends `"... but the sign-off report the acceptance gate"`, mid-clause;
  * `368` sits at offset 133 of that detail. The renderer was
    `print(f"  {s.status:6} {s.name:8} {s.detail[:120]}")`, so the ONE number
    the gate exists to corroborate was 13 characters past the cut.

Reconstructed byte-for-byte from the shipped format string and the shipped
detail: 157 characters, identical to the published line. The cut is the whole
of the reported symptom.

The same silent cut was in FOUR runners — phase3, design (phase2), phase1 and
analog — so this is ONE root cause with four sites, not four defects.

WHAT THIS FILE PINS
-------------------
  * a NON_GREEN row keeps its reason IN FULL, so the number survives;
  * the classification is `verdict.NON_GREEN`, not a literal set
    of words re-spelled in a renderer;
  * the ANTI-CHEAT: a passing row is still BOUNDED — this landing is not "print
    everything", which would be a different change wearing this issue's number;
  * a bounded row that was cut SAYS SO and says by how much, so a rollup line
    can never again be read as a complete reason;
  * every row is ONE physical line — measured on the same log, the `em_signoff`
    row's detail is a JSON fragment and the rollup printed four lines of raw
    JSON for one step;
  * all four call sites are wired, by reading the shipped source.

No design, PDK, vendor or IP-model identifier appears in this file; the sha256
strings below are the published FINDING TEXT quoted as the subject of the
measurement, not a design input.

Run: python3 -m pytest programs/tests/test_issue2081_signoff_rollup_keeps_the_number.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verdict as _tiers  # noqa: E402

# IMPORTED SOFTLY, ON PURPOSE. The falsifier's red arm is `live main sources +
# ONLY these tests`, where `programs/_runner_summary.py` does not exist. A bare
# `import` there is a COLLECTION ERROR — pytest rc 2, "1 error", zero FAILED
# node ids — and a scraper that counts failures reads that as nothing failing.
# So the module's absence is turned into a FAILING ASSERTION with a sentence
# that names the defect, and every test below stays a real red on that tree.
try:
    import _runner_summary as _R_MOD    # noqa: E402
    _IMPORT_ERROR = None
except ImportError as _exc:             # pragma: no cover - the red arm
    _R_MOD, _IMPORT_ERROR = None, _exc


def R():
    """The helper under test, or a named failure if this tree has none."""
    assert _R_MOD is not None, (
        "programs/_runner_summary.py is absent from this tree, so every "
        "one-shot runner still amputates a failing step's reason with a bare "
        f"`detail[:N]` slice (vibe-ic#2081): {_IMPORT_ERROR}")
    return _R_MOD

#: The detail the shipped gate produced on the run #2081 was filed from,
#: quoted verbatim from `reports/phase3/sta/drv_promotion_corroboration.json`.
_MEASURED_DETAIL = (
    "the promotion claimed it ended at 176 DRV violation(s) from its own "
    "session, but the sign-off report the acceptance gate reads shows 368. "
    "Passing your own re-measurement is not passing the downstream gate — "
    "do not ship this route.")

#: The runners whose rollup used a NON-DEFAULT width. Everything else about
#: the population is DERIVED below, never listed: an enumerated set of four
#: names would go quiet on the fifth runner that grows the same line, which is
#: the allow-list failure `verdict`'s own docstring is about.
_NON_DEFAULT_WIDTH = {"analog_one_shot_runner.py": 60}


def _runners():
    """Every one-shot runner in the tree, found by name, not by a list."""
    found = sorted(p.name for p in _PROGRAMS.glob("*_one_shot_runner.py"))
    assert len(found) >= 4, found
    return found


# ── 1. the reproduction, as arithmetic on the shipped strings ───────────────

def test_the_old_cut_dropped_the_number_and_the_new_one_does_not():
    """The measurement #2081 rests on, restated as an executable claim."""
    old = f"  {'FAIL':6} {'drv_promotion_corroboration':8} {_MEASURED_DETAIL[:120]}"
    assert len(old) == 157, len(old)
    assert old.endswith("but the sign-off report the acceptance gate"), old[-60:]
    assert "368" not in old, "the reproduction is void if the old cut kept it"
    assert _MEASURED_DETAIL.index("368") == 133

    new = R().summary_detail(_MEASURED_DETAIL, "FAIL")
    assert "368" in new and "176" in new, new
    assert new == _MEASURED_DETAIL, "a failing row's reason is not paraphrased"


# ── 2. the rule, and the anti-cheat beside it ──────────────────────────────

def test_a_non_green_row_is_never_bounded():
    long_reason = "x" * 5000
    for status in sorted(_tiers.NON_GREEN):
        assert R().summary_detail(long_reason, status) == long_reason, status


def test_a_passing_row_is_still_bounded_and_says_it_was_cut():
    """ANTI-CHEAT. If this landing had simply printed everything, this test
    would fail — and "print everything" is a different change that would have
    to argue for itself."""
    out = R().summary_detail(_MEASURED_DETAIL, "PASS")
    assert len(out) < len(_MEASURED_DETAIL)
    assert "368" not in out, "a PASS row is a rollup, not a finding"
    assert out.startswith(_MEASURED_DETAIL[:120])
    assert out.endswith(f"… (+{len(_MEASURED_DETAIL) - 120} chars)"), out[-40:]


def test_a_short_row_is_untouched_and_carries_no_marker():
    """The paired acceptance: a marker that always appeared would say nothing."""
    for status in ("PASS", "NOT_APPLICABLE", "FAIL", None):
        assert R().summary_detail("short reason", status) == "short reason"




# ── 3. one physical line, always ───────────────────────────────────────────

def test_a_multi_line_detail_becomes_one_line_whatever_its_status():
    spill = '  "path",\n    "items": [\n      {\n        "path": "reports/x"\n'
    for status in ("PASS", "FAIL"):
        out = R().summary_detail(spill, status)
        assert "\n" not in out and "\r" not in out, (status, out)
        assert out == '"path", "items": [ { "path": "reports/x"', out


def test_one_line_collapses_tabs_and_runs_of_spaces():
    assert R().one_line("a\t\t b \n\n  c ") == "a b c"
    assert R().one_line(None) == "" and R().one_line("") == ""


# ── 4. every site is wired, read from the shipped source ───────────────────

def test_no_one_shot_runner_still_slices_a_step_detail_by_hand():
    """Asked of the POPULATION, not of a list. The cut was in four runners; a
    repair that fixed one would leave it in the others under a different front
    door, and a fifth runner added later would inherit it unnoticed."""
    offenders = []
    for name in _runners():
        src = (_PROGRAMS / name).read_text()
        for m in re.finditer(r"\.detail\[:\d+\]", src):
            offenders.append(f"{name}: {m.group(0)}")
    assert not offenders, offenders


def test_every_runner_that_renders_a_step_detail_uses_the_shared_helper():
    """The paired direction: a runner that renders a detail at all must do it
    through the helper. A runner that renders none is not an offender, and the
    counts below make the population visible rather than assumed."""
    renders, plain = [], []
    for name in _runners():
        src = (_PROGRAMS / name).read_text()
        if "_rsum.summary_detail(" in src:
            assert "import _runner_summary as _rsum" in src, name
            renders.append(name)
        elif re.search(r"\.detail\b", src):
            plain.append(name)
    assert len(renders) >= 4, (renders, plain)
    for name, width in _NON_DEFAULT_WIDTH.items():
        assert name in renders, (name, renders)
        assert f"width={width}" in (_PROGRAMS / name).read_text(), name
