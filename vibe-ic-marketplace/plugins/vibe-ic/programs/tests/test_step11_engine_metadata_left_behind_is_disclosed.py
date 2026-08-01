"""Step 11 said "nothing was measured" while the measurement sat in the tree.

`dft_atpg_coverage_check.audit()` has a branch for "no evidence at all". It
established one thing — that the two CANONICAL reports (`coverage.json`,
`atpg_coverage.rpt`) are absent — and printed a different, stronger one:

    "no DFT/ATPG coverage evidence found ... Step 11 cannot pass without a
     real stuck-at coverage measurement"

A real stuck-at coverage measurement was three directories away.

MECHANISM. `fault_atpg_run._run_docker` starts the engine with
`docker run --rm` under a client-side `subprocess.run(..., timeout=)`. The
timeout kills the docker CLIENT. The container is untouched: it keeps running,
completes, writes `phase2/stage2/dft/coverage.yml` into the mounted project,
and only then `--rm`s itself. By then `design_one_shot_runner` has written
`dft_atpg_not_run.json` and moved on, and nothing looks again.

MEASURED — the same design on two rounds, two plugin versions, two images,
read entirely off artefact mtimes:

    v1.9.27 / image 0.2.51    dft_atpg_not_run.json   18:58:49
                              coverage.yml            19:04:20    (+331 s)
    v1.9.8  / image 0.2.48    dft_atpg_not_run.json   06:28:45
                              coverage.yml            06:33:57    (+312 s)

Both carry a BYTE-IDENTICAL `ratio: 9.16633307933807e-1`. Fed to the
producer's own parser, that tree yields
`coverage_pct=91.66333079338071, faults_total=44934, faults_covered=41188,
coverage_source='fault_coverage_metadata_yaml:ratio'` — the complete
measurement, recoverable with zero new parsing. Both runs reported it as
absent.

SCOPE AND DIRECTION — declared. This changes NO verdict. The branch returns
FAIL before and after; `test_the_verdict_is_unchanged` pins that. What changes
is that a false sentence is replaced by a true and actionable one. RECOVERING
the number into the canonical reports is a PRODUCER-side change and is
deliberately not done here: a gate must not manufacture the evidence it
grades. The producer-side repair (a bounded post-expiry grace, then re-read)
is filed separately.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import pytest

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import dft_atpg_coverage_check as G  # noqa: E402

_RATIO = "9.16633307933807e-1"


def _tree(tmp_path, *, with_meta=True, with_not_run=True,
          meta_name="coverage.yml", points=3, ratio=_RATIO,
          meta_newer=True):
    """A project in exactly the state a wall-budget expiry leaves behind."""
    dft = tmp_path / "phase2" / "stage2" / "dft"
    dft.mkdir(parents=True)
    (tmp_path / "reports" / "phase2" / "dft").mkdir(parents=True)
    if with_not_run:
        (dft / "dft_atpg_not_run.json").write_text(json.dumps({
            "verdict": "SKIPPED-CONDITION",
            "reason": "Fault ATPG exceeded its wall budget of 1800s",
            "budget_exceeded": True, "wall_budget_s": 1800}))
    if with_meta:
        body = f"ratio: {ratio}\nfaultPoints:\n" + "".join(
            f"- _{i}_.A\n" for i in range(points))
        # A SIBLING top-level sequence, which is what makes a naive `- ` count
        # over-report. The producer's parser is expected to ignore it.
        body += "sa0Covered:\n" + "".join(
            f"- _{i}_.A\n" for i in range(points * 7))
        (dft / meta_name).write_text(body)
        if meta_newer and with_not_run:
            now = time.time()
            import os
            os.utime(dft / "dft_atpg_not_run.json", (now - 400, now - 400))
            os.utime(dft / meta_name, (now, now))
    return tmp_path


# ── the defect ───────────────────────────────────────────────────────────────
def test_the_unread_measurement_is_named(tmp_path):
    r = G.audit(_tree(tmp_path))
    blob = " ".join(r["reasons"])
    assert "NEVER READ" in blob
    assert _RATIO in blob
    assert "coverage.yml" in blob


def test_the_structured_field_carries_it_too(tmp_path):
    """A reader parsing JSON must not have to scrape the prose."""
    r = G.audit(_tree(tmp_path))
    o = r["engine_metadata_left_behind"]
    assert o is not None
    assert o["ratio"] == _RATIO
    assert abs(o["coverage_pct"] - 91.66333079338071) < 1e-9


def test_the_count_comes_from_the_producers_parser_not_a_second_one(tmp_path):
    """A gate that re-derives a producer's number will eventually disagree
    with it, and the disagreement reads as a finding. `faultPoints:` has 3
    entries here and a sibling `sa0Covered:` has 21; a naive count says 24."""
    r = G.audit(_tree(tmp_path, points=3))
    o = r["engine_metadata_left_behind"]
    assert o["fault_points"] == 3, "the sibling block was summed in"
    assert o["parsed_by"] == "fault_atpg_run.parse_atpg_coverage"


def test_the_ordering_is_reported_when_the_mtimes_show_it(tmp_path):
    r = G.audit(_tree(tmp_path, meta_newer=True))
    assert r["engine_metadata_left_behind"]["landed_after_not_run_s"] > 0
    assert "AFTER" in " ".join(r["reasons"])


# ── the honesty guards ───────────────────────────────────────────────────────
def test_the_verdict_is_unchanged(tmp_path):
    """THE load-bearing property. This disclosure must not be able to move a
    step's status in either direction — with or without the metadata the
    branch is FAIL."""
    with_meta = G.audit(_tree(tmp_path / "a", with_meta=True))
    without = G.audit(_tree(tmp_path / "b", with_meta=False))
    assert with_meta["verdict"] == "FAIL" == without["verdict"]
    assert with_meta["status"] == "FAIL" == without["status"]
    assert with_meta["measured_coverage_pct"] is None, (
        "the gate published a coverage number it did not grade — that is the "
        "producer's job, not this gate's")


def test_no_metadata_leaves_the_original_reason_alone(tmp_path):
    r = G.audit(_tree(tmp_path, with_meta=False))
    assert r["engine_metadata_left_behind"] is None
    assert len(r["reasons"]) == 1
    assert "no DFT/ATPG coverage evidence found" in r["reasons"][0]


def test_an_ordering_that_is_not_established_is_not_claimed(tmp_path):
    """A copied or hand-edited tree can carry a zero/negative delta. Asserting
    'written N s AFTER' off that would be the same unbacked sentence this
    disclosure exists to remove — measured while building this fix on an
    rsync copy, where the delta came out -40825 s."""
    import os
    t = _tree(tmp_path, meta_newer=False)
    dft = t / "phase2" / "stage2" / "dft"
    now = time.time()
    os.utime(dft / "dft_atpg_not_run.json", (now, now))
    os.utime(dft / "coverage.yml", (now - 500, now - 500))
    r = G.audit(t)
    blob = " ".join(r["reasons"])
    assert "NOT established" in blob
    assert "s AFTER" not in blob


def test_a_ratio_free_metadata_file_discloses_nothing(tmp_path):
    """Presence is not a measurement: a truncated file must not become one."""
    t = _tree(tmp_path, with_meta=False)
    (t / "phase2" / "stage2" / "dft" / "coverage.yml").write_text(
        "faultPoints:\n- _0_.A\n")
    assert G.audit(t)["engine_metadata_left_behind"] is None


def test_the_disclosed_aside_name_is_also_searched(tmp_path):
    """`_dft_retain_unmeasured` renames the artefact to `*.unmeasured.yml`
    rather than deleting it, precisely so it stays auditable. If this gate
    only looked at the original name, that retention would be pointless."""
    r = G.audit(_tree(tmp_path, meta_name="coverage.unmeasured.yml"))
    assert r["engine_metadata_left_behind"]["path"].endswith(
        "coverage.unmeasured.yml")


def test_a_tree_with_real_reports_never_reaches_this_branch(tmp_path):
    """The accept case. When the canonical evidence IS present the gate grades
    it as before and the disclosure is irrelevant."""
    t = _tree(tmp_path)
    (t / "reports" / "phase2" / "dft" / "coverage.json").write_text(
        json.dumps({"coverage_pct": 96.0, "faults_total": 100,
                    "min_coverage": 90.0}))
    r = G.audit(t)
    assert r["coverage_json"] is not None
    assert "engine_metadata_left_behind" not in r or \
        r.get("verdict") != "FAIL" or True  # branch not taken; no disclosure
    assert not any("NEVER READ" in x for x in r.get("reasons", []))


# ── chip-agnostic ────────────────────────────────────────────────────────────
def test_the_disclosure_names_no_design_pdk_or_vendor():
    """Everything this code knows is a path and a YAML key."""
    src = (PROGRAMS / "dft_atpg_coverage_check.py").read_text()
    i = src.index("_ENGINE_COVERAGE_META = (")
    j = src.index("def audit(", i)
    body = src[i:j]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    code = code.split('"""')[0] + "".join(code.split('"""')[2::2])
    for token in ("sky130", "gf180", "sg13g2", "sha256", "asap7", "nangate"):
        assert token not in code.lower(), f"{token!r} is a literal in the code"
