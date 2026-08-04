"""tests/test__analog_layout_matching.py

The matching disclosure, and the two gates that read it. Every test RUNS the
gate as the flow runs it (subprocess, `--json`) or calls the module's own
entry point — none of them assert on source text.

WHAT IS BEING PINNED, in one sentence: A6's LVS compare is topology-only, so a
block laid out as N isolated devices closes it exactly as green as a
common-centroid quad, and until this artefact existed nothing in the tree told
the two apart.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
A5 = PROGS / "analog_a5_layout_check.py"
A6 = PROGS / "analog_a6_block_pv_check.py"

sys.path.insert(0, str(PROGS))
import _analog_layout_matching as lm  # noqa: E402


# ── fixtures: a real project tree ─────────────────────────────────────────

#: A real-geometry .mag above A5's 200-byte substance floor.
_MAG = ("magic\ntech testtech\ntimestamp 1\n"
        "<< metal1 >>\n" + "rect 0 0 100 100\n" * 16 + "<< end >>\n")
assert len(_MAG) > 200


def _project(tmp_path: Path, blocks, matching=None, layout=True) -> Path:
    ad = tmp_path / "phase3" / "analog"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))
    for b in blocks:
        d = ad / b
        d.mkdir(exist_ok=True)
        if layout:
            (d / "layout.mag").write_text(_MAG)
        doc = (matching or {}).get(b)
        if doc is not None:
            (d / lm.MATCHING_ARTEFACT).write_text(
                doc if isinstance(doc, str) else json.dumps(doc))
    return tmp_path


def _run(prog: Path, project: Path, *args) -> tuple:
    out = project / f"{prog.stem}.json"
    r = subprocess.run([sys.executable, str(prog), str(project),
                        "--json", str(out), *args],
                       capture_output=True, text=True, cwd=str(PROGS))
    rpt = json.loads(out.read_text()) if out.exists() else {}
    return r, rpt


_MATCHED = {"matching_style": "common_centroid",
            "matched_groups": [{"name": "input_pair",
                                "devices": ["Mn1", "Mn2"],
                                "style": "common_centroid",
                                "dummies_per_side": 2}],
            "lvs_dummy_waiver": "WAIVER-DUMMY-1"}
_NONE = {"matching_style": "none"}


# ── the classification itself ─────────────────────────────────────────────

def test_a_block_that_says_nothing_is_not_a_block_that_says_none(
        tmp_path: Path) -> None:
    """THE point of the whole artefact. Before it, these two trees produced
    byte-identical A5 reports; a reader could only tell them apart by opening
    the layout."""
    silent = _project(tmp_path / "s", ["ota"])
    declared = _project(tmp_path / "d", ["ota"], matching={"ota": _NONE})
    _, rs = _run(A5, silent)
    _, rd = _run(A5, declared)
    assert rs["matching_disclosure"] == {"ota": lm.DISCLOSURE_UNDISCLOSED}, rs
    assert rd["matching_disclosure"] == {"ota": lm.DISCLOSURE_NONE}, rd
    assert rs["blocks_matching_undisclosed"] == ["ota"]
    assert rd["blocks_no_matching_structure"] == ["ota"]
    # ...and the two documents are no longer the same document.
    assert json.dumps(rs, sort_keys=True) != json.dumps(rd, sort_keys=True)


def test_declaring_no_matching_structure_still_certifies_a5(
        tmp_path: Path) -> None:
    """`none` is a legitimate answer — a level shifter, a power switch and an
    ESD clamp have no matching group to build. A rule that failed them would
    teach runs to invent a centroid to satisfy a gate."""
    p = _project(tmp_path, ["ota"], matching={"ota": _NONE})
    r, rpt = _run(A5, p)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert rpt["verdict"] == "PASS", rpt
    assert rpt["blocks_no_matching_structure"] == ["ota"]


def test_a_matched_disclosure_certifies_and_is_recorded(
        tmp_path: Path) -> None:
    p = _project(tmp_path, ["ota"], matching={"ota": _MATCHED})
    r, rpt = _run(A5, p)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert rpt["blocks_matching_declared"] == ["ota"], rpt
    assert rpt["blocks_no_matching_structure"] == []


def test_the_sentinel_is_printed_on_a_passing_run(tmp_path: Path) -> None:
    """Same contract as `structure_only_disclosure`: a consumer must be able
    to read the fact from a gate that PASSED, without the gate changing its
    exit code."""
    p = _project(tmp_path, ["ota"], matching={"ota": _NONE})
    r, _ = _run(A5, p)
    assert r.returncode == 0
    lines = (r.stdout + r.stderr).splitlines()
    assert any(l.startswith(lm.MATCHING_TOKEN) for l in lines), r.stdout
    assert any("NO matching structure" in l for l in lines), r.stdout


def test_the_sentinel_is_printed_on_a_failing_run_too(tmp_path: Path) -> None:
    """A step can fail for one block and still have recorded an unmatched
    layout for another; a reader needs both facts."""
    p = _project(tmp_path, ["ota", "bg"], matching={"ota": _NONE})
    (p / "phase3" / "analog" / "bg" / "layout.mag").write_text("magic\n")
    r, rpt = _run(A5, p)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert any(l.startswith(lm.MATCHING_TOKEN)
               for l in (r.stdout + r.stderr).splitlines()), r.stdout
    assert rpt["blocks_no_matching_structure"] == ["ota"], rpt


def test_a_block_with_no_layout_is_not_asked(tmp_path: Path) -> None:
    """It has nothing drawn to have a structure; counting it as "did not say"
    would report the A5 gap twice under two different names. Measured on a
    MIXED tree, because the all-missing tree short-circuits to VACUOUS_PASS
    before any block is examined."""
    p = _project(tmp_path, ["drawn", "notdrawn"], matching={"drawn": _NONE})
    (p / "phase3" / "analog" / "notdrawn" / "layout.mag").unlink()
    r, rpt = _run(A5, p)
    assert rpt["matching_disclosure"] == {"drawn": lm.DISCLOSURE_NONE}, rpt
    assert rpt["blocks_matching_undisclosed"] == [], rpt


def test_the_all_missing_tree_says_nothing_about_matching(
        tmp_path: Path) -> None:
    """VACUOUS_PASS: the step has not run. There is no layout anywhere, so
    there is no matching fact to report and the sentinel must stay quiet."""
    p = _project(tmp_path, ["ota"], layout=False)
    r, rpt = _run(A5, p)
    assert rpt["verdict"] == "VACUOUS_PASS", rpt
    assert not any(l.startswith(lm.MATCHING_TOKEN)
                   for l in (r.stdout + r.stderr).splitlines()), r.stdout


# ── the rules, every one of which fires only on a record that EXISTS ──────

@pytest.mark.parametrize("doc,rule", [
    ("not json at all {{{", "A5_MATCHING_DISCLOSURE_MALFORMED"),
    ({"note": "we did some matching"}, "A5_MATCHING_DISCLOSURE_MALFORMED"),
    ({"matching_style": ""}, "A5_MATCHING_DISCLOSURE_MALFORMED"),
    ({"matching_style": "none",
      "matched_groups": [{"name": "p", "dummies_per_side": 2}]},
     "A5_MATCHING_STYLE_GROUPS_CONTRADICT"),
    ({"matching_style": "interdigitated", "matched_groups": []},
     "A5_MATCHING_STYLE_GROUPS_CONTRADICT"),
    ({"matching_style": "common_centroid",
      "matched_groups": [{"name": "p", "dummies_per_side": 1}],
      "lvs_dummy_waiver": "T-1"},
     "A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT"),
    ({"matching_style": "common_centroid",
      "matched_groups": [{"name": "p"}]},
     "A5_MATCHING_GROUP_DUMMIES_INSUFFICIENT"),
    ({"matching_style": "common_centroid",
      "matched_groups": [{"name": "p", "dummies_per_side": 2}]},
     "A5_MATCHING_DUMMIES_LVS_UNRECONCILED"),
])
def test_a_disclosure_that_exists_is_held_to_its_content(
        tmp_path: Path, doc, rule) -> None:
    p = _project(tmp_path, ["ota"], matching={"ota": doc})
    r, rpt = _run(A5, p)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert rule in {f["rule"] for f in rpt["findings"]}, rpt


def test_the_dummy_lvs_rule_names_the_contradiction_it_is_about(
        tmp_path: Path) -> None:
    """A dummy is a device the schematic does not contain, so the A6 compare
    either sees it and does not match, or something suppressed it and nothing
    said what. `lvs-triage` already records that dummies need a waiver; this
    is that sentence, executed."""
    doc = {"matching_style": "common_centroid",
           "matched_groups": [{"name": "p", "dummies_per_side": 2}]}
    p = _project(tmp_path, ["ota"], matching={"ota": doc})
    _, rpt = _run(A5, p)
    f = next(x for x in rpt["findings"]
             if x["rule"] == "A5_MATCHING_DUMMIES_LVS_UNRECONCILED")
    assert f["dummies"] == 4, f          # 2 per side, both sides
    # ...and naming the waiver clears it.
    doc["lvs_dummy_waiver"] = "T-77"
    p2 = _project(tmp_path / "ok", ["ota"], matching={"ota": doc})
    r2, _ = _run(A5, p2)
    assert r2.returncode == 0, (r2.stdout, r2.stderr)


# ── the arithmetic rule (an N-way split must SUM to W x M) ────────────────

def _partition(children):
    return {"matching_style": "none",
            "device_partitions": [{"schematic_device": "Mpass",
                                   "w_um": 6.0, "m": 120,
                                   "layout_devices": children}]}


def test_a_partition_that_sums_certifies(tmp_path: Path) -> None:
    p = _project(tmp_path, ["ota"],
                 matching={"ota": _partition([{"w_um": 60.0, "nf": 1}] * 12)})
    r, rpt = _run(A5, p)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_a_partition_that_does_not_sum_fails(tmp_path: Path) -> None:
    """netgen merges parallel devices by ADDING their widths, so the compare
    sees the sum and not the intent."""
    p = _project(tmp_path, ["ota"],
                 matching={"ota": _partition([{"w_um": 60.0, "nf": 1}] * 11)})
    r, rpt = _run(A5, p)
    assert r.returncode == 1, (r.stdout, r.stderr)
    f = next(x for x in rpt["findings"]
             if x["rule"] == "A5_DEVICE_PARTITION_WIDTH_MISMATCH")
    assert f["w_layout_sum_um"] == 660.0 and f["w_schematic_total_um"] == 720.0


def test_a_multifinger_layout_device_is_recorded_not_failed(
        tmp_path: Path) -> None:
    """Whether a multi-finger gencell extracts with per-finger pins that break
    the compare is a property of ONE PDK's device generator, verified with one
    netgen command. A gate that failed it would ship one PDK's defect as a
    universal rule — so it is a RECORD."""
    p = _project(tmp_path, ["ota"],
                 matching={"ota": _partition([{"w_um": 360.0, "nf": 6},
                                              {"w_um": 360.0, "nf": 6}])})
    r, rpt = _run(A5, p)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert rpt["multifinger_layout_devices"] == {"ota": ["Mpass", "Mpass"]}, rpt


# ── A6 carries the record without ever changing its verdict ───────────────

def _pv_evidence(project: Path, block: str) -> None:
    d = project / "phase3" / "analog" / block
    (d / "drc.report").write_text("total violations: 0\n")
    (d / "lvs.report").write_text("Final result: Circuits match uniquely.\n"
                                  "netlists match\n")


def test_a6_records_an_unmatched_layout_on_a_green_pass(
        tmp_path: Path) -> None:
    """The exact hole: A6 goes green on a block with zero matching structure.
    It still goes green — and now it says so."""
    p = _project(tmp_path, ["ota"], matching={"ota": _NONE})
    _pv_evidence(p, "ota")
    r, rpt = _run(A6, p)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert rpt["verdict"] == "PASS", rpt
    assert rpt["blocks_no_matching_structure"] == ["ota"], rpt
    assert any(l.startswith(lm.MATCHING_TOKEN)
               for l in (r.stdout + r.stderr).splitlines()), r.stdout


def test_a6_verdict_is_untouched_by_every_matching_class(
        tmp_path: Path) -> None:
    """The record must not become a second, silent PV rule. Same DRC/LVS
    evidence, four different disclosures, one verdict."""
    seen = set()
    for tag, doc in (("u", None), ("n", _NONE), ("m", _MATCHED),
                     ("bad", {"note": "nothing"})):
        p = _project(tmp_path / tag, ["ota"],
                     matching=None if doc is None else {"ota": doc})
        _pv_evidence(p, "ota")
        r, rpt = _run(A6, p)
        seen.add((r.returncode, rpt["verdict"]))
    assert seen == {(0, "PASS")}, seen


def test_the_two_gates_read_one_file_through_one_rule(
        tmp_path: Path) -> None:
    """A5 and A6 must not drift about the same artefact the way two gates over
    `pre_vs_post.json` once did."""
    p = _project(tmp_path, ["ota", "bg"],
                 matching={"ota": _NONE, "bg": _MATCHED})
    for b in ("ota", "bg"):
        _pv_evidence(p, b)
    _, r5 = _run(A5, p)
    _, r6 = _run(A6, p)
    assert r5["matching_disclosure"] == r6["matching_disclosure"], (r5, r6)


# ── the module's own contract ─────────────────────────────────────────────

def test_read_disclosure_on_a_missing_directory_is_undisclosed(
        tmp_path: Path) -> None:
    d = lm.read_disclosure(tmp_path / "nope", "ota")
    assert d.klass == lm.DISCLOSURE_UNDISCLOSED
    assert d.findings == [] and d.declared is False


def test_summarise_names_every_class_even_when_empty() -> None:
    """A consumer keying on a summary field must not have to guess whether an
    absent key means zero or means the gate did not look."""
    s = lm.summarise({})
    for k in ("matching_disclosure", "blocks_matching_declared",
              "blocks_no_matching_structure", "blocks_matching_undisclosed",
              "blocks_matching_malformed"):
        assert k in s, s
