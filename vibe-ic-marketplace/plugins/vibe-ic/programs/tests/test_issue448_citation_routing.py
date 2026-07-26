#!/usr/bin/env python3
"""A citation the published layout cannot carry is RECORDED, not left to dangle.

All THREE cells that `benchmark-data/ic/INDEX.md` lists as CONVERGED EVIDENCE
assert, in `reports/phase3/mcorner_ocv_stance.json`:

    "timing_closed_multi_corner": true,
    "setup_worst_slack_ns": 4.56,  "violated_corners": [],
    "report": "phase3/stage3/sta/sta_mcorner_ocv.rpt"

and `git ls-files` returns ZERO files under `phase3/stage3/sta/` in each.

THE REPORT IS NOT MISSING. `PUBLISHING.md` declares the canonical layout ships
`phase3/reports/` and NOT `phase3/stage3/`, so the citation is correct WHERE THE
RUN PUT IT and unfollowable from the published cell. The pointer was published
unchanged; a reader following it finds nothing and is told nothing.

That reframing is what makes the defect general: any JSON citing a run-relative
path under a subtree the publisher does not copy dangles the moment it is
published, however correct the run was.

The repair reuses the precedent already in this program. `LAYOUT_ROUTING.txt`
records blobs as STAGED / ROUTED_AWAY / NOT_PUBLISHED precisely so a reader can
tell "stored elsewhere" from "in the run but out of scope" from "never existed".
`CITATION_ROUTING.txt` does the same for CITED artefacts.

MEASURED on the three converged cells (~200 citations each):

    RESOLVES                 ~125
    OUT_OF_PUBLISHED_SCOPE   71-79     <- the mechanism above
    DANGLING                 3-6       <- genuinely broken, and NOT the same thing

Separating those two is the point. 126 opaque "unresolved" entries in a debt
register become "correct where the run put it" and a handful that are actually
broken — and only the second kind is anyone's bug.

This does NOT decide whether the closure claim is TRUE. The run may well have
closed timing; withdrawing a correct claim to silence a pointer defect would be
the wrong repair in the other direction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import benchmark_evidence_publish as B  # noqa: E402

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data" / "ic"


def _cell(tmp_path: Path, doc_rel: str, cited: str,
          make_target: bool = False) -> Path:
    d = tmp_path / "cell"
    p = d / doc_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"report": cited, "closed": True}))
    if make_target:
        t = d / cited
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text("x\n")
    return d


def test_a_run_coordinate_citation_is_OUT_OF_PUBLISHED_SCOPE(tmp_path):
    """THE LOAD-BEARING CASE — the converged cells' mcorner citation."""
    d = _cell(tmp_path, "reports/phase3/stance.json",
              "phase3/stage3/sta/sta_mcorner_ocv.rpt")
    recs = B.collect_citation_records(d)
    assert len(recs) == 1, recs
    assert recs[0]["decision"] == "OUT_OF_PUBLISHED_SCOPE", recs


def test_a_citation_that_resolves_is_recorded_as_resolving(tmp_path):
    """The paired half: the record must not call everything out of scope."""
    d = _cell(tmp_path, "reports/phase3/stance.json",
              "reports/phase3/sta.rpt", make_target=True)
    recs = B.collect_citation_records(d)
    assert recs[0]["decision"] == "RESOLVES", recs


def test_a_broken_pointer_inside_published_scope_is_DANGLING(tmp_path):
    """The third state, and the one that is actually somebody's bug. A path the
    layout DOES carry, that is simply not there, is not an out-of-scope
    citation and must not be filed as one."""
    d = _cell(tmp_path, "reports/phase3/stance.json",
              "reports/phase3/dynamic_ir.log")
    recs = B.collect_citation_records(d)
    assert recs[0]["decision"] == "DANGLING", recs


def test_the_record_is_written_even_when_everything_resolves(tmp_path):
    """A record that only appears on failure cannot be used to prove there
    were no failures — the same rule LAYOUT_ROUTING.txt already follows."""
    d = _cell(tmp_path, "reports/phase3/stance.json",
              "reports/phase3/sta.rpt", make_target=True)
    B.write_citation_routing(d, B.collect_citation_records(d))
    body = (d / B._CITATION_ROUTING_FILENAME).read_text()
    assert "CITATION_ROUTING" in body
    assert "RESOLVES" in body


def test_the_same_citation_is_not_recorded_twice(tmp_path):
    """A doc naming the same path in two keys is one citation, or a reader
    counting lines is counting mentions."""
    d = tmp_path / "cell"
    p = d / "reports" / "x.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"a": "phase3/stage3/sta/x.rpt",
                             "b": "phase3/stage3/sta/x.rpt"}))
    recs = B.collect_citation_records(d)
    assert len(recs) == 1, recs


def test_the_three_converged_cells_are_measured_not_assumed():
    """Real data, and the numbers that justify separating the two states."""
    import pytest
    cells = ["spm/v1.5.58_ihp-sg13g2", "spm/v1.5.65_sky130A",
             "spm/v1.5.66_gf180mcuD"]
    seen = 0
    for c in cells:
        d = _CORPUS / c
        if not d.is_dir():
            continue
        seen += 1
        recs = B.collect_citation_records(d)
        kinds = {r["decision"] for r in recs}
        assert "RESOLVES" in kinds and "OUT_OF_PUBLISHED_SCOPE" in kinds, (c, kinds)
        mc = [r for r in recs if "mcorner" in r["doc"]]
        assert mc, c
        assert mc[0]["decision"] == "OUT_OF_PUBLISHED_SCOPE", (c, mc)
    if seen == 0:
        pytest.skip("published corpus not checked out")
    assert seen == 3, f"only {seen} of 3 converged cells present"


# ── the PLAN-versus-CLAIM split ────────────────────────────────────────────
def test_a_dangling_citation_under_a_PASS_is_separated_from_a_plan(tmp_path):
    """A step that has not run naming the report it WOULD write is a PLAN. A
    step that says PASS while naming a report that is not there is a CLAIM
    whose evidence is absent. Both look identical as a path, and only the
    second is anyone's bug."""
    d = tmp_path / "cell"
    p = d / "reports" / "orchestrator" / "run.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"steps": [
        {"name": "planned", "status": "SKIP",
         "detail": "would write reports/phase3/lvs.rpt"},
        {"name": "claimed", "status": "PASS",
         "detail": "produced reports/lec.json"},
    ]}))
    recs = {r["cited"]: r["decision"] for r in B.collect_citation_records(d)}
    assert recs["reports/phase3/lvs.rpt"] == "DANGLING"
    assert recs["reports/lec.json"] == "DANGLING_UNDER_PASS"


def test_a_nested_SKIP_is_not_attributed_to_an_enclosing_PASS(tmp_path):
    """The over-attribution this cost me once. A document with a top-level
    `verdict: PASS` must not make EVERY citation in it an assertion — a claim
    is made by the NEAREST enclosing record, not by every ancestor."""
    d = tmp_path / "cell"
    p = d / "reports" / "run.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{"name": "s", "status": "SKIP",
                   "detail": "would write reports/phase3/em.rpt"}],
    }))
    recs = {r["cited"]: r["decision"] for r in B.collect_citation_records(d)}
    assert recs["reports/phase3/em.rpt"] == "DANGLING", recs


def test_the_collector_walks_the_PUBLISHED_tree_not_the_disk(tmp_path):
    """Reproduced in the fix for #448 itself: run as an AUDIT over a published
    cell, `rglob` picked up untracked `clean_run_*` leftovers a reader never
    receives. Same defect this repo fixed in four programs (#447)."""
    import subprocess as sp
    d = tmp_path / "cell"
    (d / "reports").mkdir(parents=True)
    (d / "reports" / "kept.json").write_text(
        json.dumps({"status": "PASS", "d": "reports/gone.rpt"}))
    leftover = d / "clean_run_local" / "reports"
    leftover.mkdir(parents=True)
    (leftover / "stray.json").write_text(
        json.dumps({"status": "PASS", "d": "reports/also_gone.rpt"}))

    sp.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        sp.run(["git", "-C", str(d), "config", k, v], check=True)
    sp.run(["git", "-C", str(d), "add", "reports/kept.json"], check=True)
    sp.run(["git", "-C", str(d), "commit", "-qm", "publish"], check=True)

    docs = {r["doc"] for r in B.collect_citation_records(d)}
    assert "reports/kept.json" in docs, docs
    assert not any("clean_run_local" in x for x in docs), docs
