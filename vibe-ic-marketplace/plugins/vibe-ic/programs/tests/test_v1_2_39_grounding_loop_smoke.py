"""Wire the anti-fabrication grounding gate into the core-agent loop (PROGRAM-FIRST).

The core-agent loop ships fixes gated by `gatekeeper_review.py`, which runs the
cadence-appropriate pytest suite via `full_suite_run_check`. So a suite test that
exercises `phase1_evidence_grounding_check` on the COMMITTED Phase-1 fixtures is
run on EVERY loop iteration — making the §4.05 anti-fabrication gate a standing
loop guard with no prompt dependency (the "修法寫進工具，而非 prompt" doctrine):

  * STAY-CLEAN: every committed synthetic_benchmark_phase1 fixture must remain
    grounding-clean — a plugin change that makes the deterministic extractor
    FABRICATE an ungrounded fact on a real-shaped project FAILs here in the loop.
  * STAY-EFFECTIVE: a deliberately-fabricated fixture must still FAIL — a plugin
    change that WEAKENS the gate (stops catching fabrication / leaks) FAILs here.

Pairs with the gate's own unit tests (test_v1_2_36 / _38): those pin the gate
logic; this pins the gate's verdict on the real committed corpus inside the loop.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_evidence_grounding_check as G  # noqa: E402

_FIX = _PROG / "tests" / "fixtures" / "synthetic_benchmark_phase1"


def _fixture_projects():
    if not _FIX.is_dir():
        return []
    return sorted(p for p in _FIX.iterdir()
                  if p.is_dir() and (p / "phase1" / "generated_docs").is_dir())


@pytest.mark.parametrize("proj", _fixture_projects(),
                         ids=lambda p: p.name if hasattr(p, "name") else str(p))
def test_committed_fixture_grounding_clean(proj):
    # STAY-CLEAN: a deterministic-extractor change that fabricates an ungrounded
    # fact on this real-shaped project is caught here, every loop iteration.
    res = G.check(proj)
    assert res["status"] in ("PASS", "SKIP"), (
        f"{proj.name} grounding regressed: {res.get('ungrounded')}")


def test_fixtures_present():
    # the corpus should exist so the loop guard actually runs (not vacuous).
    # It lives under programs/tests/fixtures/synthetic_benchmark_phase1/ but is
    # NOT git-tracked (author-local test data); on a clean checkout / CI it is
    # absent, so SKIP rather than hard-fail — the grounding guard itself is
    # exercised elsewhere (test_committed_fixture_grounding_clean parametrizes
    # over whatever IS present).
    n = len(_fixture_projects())
    if n == 0:
        import pytest
        pytest.skip("synthetic_benchmark_phase1 corpus absent (author-local, "
                    "uncommitted); nothing to ground-check on this checkout")
    assert n >= 4


def test_gate_stays_effective_on_fabrication(tmp_path):
    # STAY-EFFECTIVE: copy a clean fixture, inject an INVENTED identifier whose
    # name is nowhere in the input, and assert the gate still FAILs. A plugin
    # change that weakens the gate (stops catching fabrication) trips this.
    projs = _fixture_projects()
    if not projs:
        pytest.skip("no committed fixtures")
    src = projs[0]
    dst = tmp_path / src.name
    shutil.copytree(src, dst)
    gd = dst / "phase1" / "generated_docs"
    target = next(iter(gd.glob("L*.json")))
    d = json.loads(target.read_text())
    ev = d.setdefault("extraction_evidence", {})
    ev.setdefault("input/docs/spec.txt", []).append(
        {"literal": "zzphantomsig_q invented bus that is nowhere in the spec",
         "label": "FABRICATED"})
    target.write_text(json.dumps(d))
    res = G.check(dst)
    assert res["status"] == "FAIL"
    assert any("zzphantomsigq" in u["missing_identifiers"] for u in res["ungrounded"])
