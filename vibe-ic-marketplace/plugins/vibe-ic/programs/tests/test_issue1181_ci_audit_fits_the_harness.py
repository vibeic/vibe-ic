"""#1181 — the CI-population audit must finish inside the harness, and must not
lie when it cannot.

`test_gate_discloses_denominator` hung THROUGH `--timeout=180
--timeout-method=thread`: the wait is in `subprocess.communicate`, which a
thread-based timeout cannot interrupt, so pytest printed its stack dump and the
invocation never returned — **the whole selection produced no summary line**.

Measured on `a38902d1`: 50 driveable gates, median 0.1 s, real serial total
~189 s against a 180 s harness. The per-call `timeout=120` was never the
problem; nothing bounded the aggregate.

The two properties this file pins:
  1. the audit is CONCURRENT, so it fits (the idiom the file's two sibling
     populations already use);
  2. a budget that cuts the population short is **not a PASS** — otherwise the
     fix trades a loud hang for a quiet under-count, which is worse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gate_discloses_denominator_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]


# --------------------------------------------------------------------------- #
# THE LOAD-BEARING ONE: a shortened population is not a pass
# --------------------------------------------------------------------------- #
def test_an_exhausted_budget_is_INCOMPLETE_not_PASS():
    """`audit()` returns only `(verdict, findings)` — it drops `not_driven`.

    So if the budget silently shortened the sweep, a caller asserting
    `verdict == "PASS"` would pass over a population the audit never finished.
    A hang at least cannot be mistaken for success; a quiet under-count can.
    """
    res = G.audit_ci(_REPO, budget=0)
    assert res.verdict == "INCOMPLETE", res.verdict
    assert res.verdict != "PASS"
    cut = [lab for lab, why in res.not_driven if "budget was exhausted" in why]
    assert cut, res.not_driven[:3]
    # and it reaches the back-compatible caller, which is the one the test
    # that filed #1181 actually uses
    verdict, _ = G.audit(_REPO, budget=0)
    assert verdict == "INCOMPLETE", verdict


def test_the_budget_cut_names_every_gate_it_dropped():
    """Named, not counted. A count is what made three writers cost three
    separate discoveries elsewhere in this repo."""
    res = G.audit_ci(_REPO, budget=0)
    cut = [lab for lab, why in res.not_driven if "budget was exhausted" in why]
    assert len(cut) >= 40, len(cut)          # ~50 driveable gates
    assert all(isinstance(c, str) and c for c in cut)
    assert res.probed == res.declared - len(res.not_driven)


# --------------------------------------------------------------------------- #
# It fits the harness — the actual subject of #1181
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(170)
def test_a_full_audit_finishes_inside_the_budget_and_answers():
    """ONE full-audit run, asserting both halves.

    Deliberately not two tests: the audit is ~41 s, and an earlier draft of
    this file ran it twice and cost **98.85 s** of a 180 s harness — this file
    would then have been a fresh instance of the very overrun #1181 is about.
    Bounded at 170 s so it FAILS rather than taking the session down if the
    concurrency is ever removed.
    """
    import time
    t0 = time.monotonic()
    res = G.audit_ci(_REPO)
    elapsed = time.monotonic() - t0

    # it finishes …
    assert elapsed < 150, f"the audit no longer fits its budget: {elapsed:.0f}s"
    # … and it answers over the real population rather than a truncated one
    assert res.verdict in ("PASS", "FAIL"), res.verdict
    cut = [lab for lab, why in res.not_driven if "budget was exhausted" in why]
    assert cut == [], f"the default budget did not fit: {cut}"
    assert res.probed >= 40, res.probed


def test_the_audit_is_concurrent_like_its_two_siblings():
    """The fix is the idiom already used twice in this file, not a new one."""
    src = (_PROGRAMS / "gate_discloses_denominator_check.py").read_text()
    body = src.split("def audit_ci(")[1].split("\ndef ")[0]
    assert "ThreadPoolExecutor" in body, "audit_ci went back to serial"


# --------------------------------------------------------------------------- #
# The shared scratch is safe by MEASUREMENT, so the tripwire has to exist
# --------------------------------------------------------------------------- #
def test_the_scratch_fingerprint_sees_a_write(tmp_path):
    """`SCRATCH_MUTATED` is only meaningful if the fingerprint can detect one.

    The sibling population uses a fresh dir per gate because "gates write into
    the project they audit". These were measured not to (0 writers, 42 entries
    before and after), which is why the scratch is shared — and this is the
    tripwire for the day that stops being true, when concurrency would make the
    verdict order-dependent rather than merely wrong.
    """
    root = tmp_path / "s"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f.txt").write_text("x")
    before = G._scratch_fingerprint(root)
    assert before is not None
    assert G._scratch_fingerprint(root) == before          # stable
    (root / "a" / "new.txt").write_text("y")               # an appearance
    assert G._scratch_fingerprint(root) != before
    after = G._scratch_fingerprint(root)
    (root / "a" / "new.txt").write_text("yy")              # a size change
    assert G._scratch_fingerprint(root) != after


# --------------------------------------------------------------------------- #
# PAIRED GUARD
# --------------------------------------------------------------------------- #
def test_a_verdict_that_is_always_PASS_is_not_a_verdict():
    """The always-fires guard.

    A verdict function hardcoded to "PASS" satisfies
    `test_a_generous_budget_drives_the_population_and_passes` and every other
    positive assertion here. It dies on the budget-0 case and only there: a
    sweep that drove nothing must never come back PASS.
    """
    res = G.audit_ci(_REPO, budget=0)
    assert res.verdict != "PASS", (
        "an audit that drove nothing reported PASS")
    assert res.probed < res.declared, (res.probed, res.declared)
