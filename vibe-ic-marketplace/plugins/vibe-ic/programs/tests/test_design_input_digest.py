#!/usr/bin/env python3
"""A published tally must carry a record of what it was computed over.

The tests are written against the OBSERVABLE PROPERTIES a different correct
implementation would also have to satisfy:

  P1  a re-run over an untouched design reproduces the digest — otherwise the
      field says nothing
  P2  a changed design input moves the digest
  P3  a digest that covers nothing, or covers a truncated scan, is REFUSED
      rather than published (the "narrow the filter until the count reaches
      zero" failure, which would satisfy P1 perfectly)
  P4  a tally movement is only ever attributed to the design when the design
      hash actually moved (the fabrication direction)
  P5  arriving TOOL evidence — DRC/LVS/STA reports, which in this corpus live
      under `reports/phase3/` next to the checkers' own JSON — moves the
      digest (the over-correction: a prefix exclusion of `reports/` passes P1
      and P3 and still makes the artefact assert that a design which really
      moved had not)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_input_digest as did  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _shipped_version import shipped_plugin_version  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
AUDIT_REL = Path("reports/audit/phase23_completion_audit.json")


# ───────────────────────── helpers ──────────────────────────────────


def _design(root: Path) -> Path:
    """A minimal project of PUBLIC grammar: nothing here names a PDK."""
    (root / "phase2/stage1/rtl").mkdir(parents=True, exist_ok=True)
    (root / "phase2/stage1/rtl/core.v").write_text(
        "module core(input clk, output q); assign q = clk; endmodule\n")
    (root / "phase3/stage3/constraints").mkdir(parents=True, exist_ok=True)
    (root / "phase3/stage3/constraints/top.sdc").write_text(
        "create_clock -name clk -period 10 [get_ports clk]\n")
    (root / "phase1/generated_docs").mkdir(parents=True, exist_ok=True)
    (root / "phase1/generated_docs/L1.json").write_text('{"layer": 1}\n')
    (root / "reports/phase3").mkdir(parents=True, exist_ok=True)
    return root


def _audit_like(root: Path, written, want_kept=False, carried=None):
    """Do what the auditor does: write into `reports/`, then carry its own
    footprint forward the way the gate carries it out of the prior audit.
    Returns the digest block a caller would publish."""
    pre = did.scan_inputs(root)
    for rel, body in written:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    post = did.scan_inputs(root)
    fp = did.auditor_footprint(pre, post, [str(AUDIT_REL)], carried)
    block = did.build_digest(pre, fp)
    if want_kept:
        return block, did.kept_inputs(pre, fp)
    return block


def _audit_like_chain(root: Path, written, runs=3):
    """`runs` successive audits over an untouched design, each carrying the
    previous footprint — what the gate actually does."""
    out, carried = [], None
    for _ in range(runs):
        blk = _audit_like(root, written, carried=carried)
        carried = blk["auditor_written_paths"]
        out.append(blk)
    return out


def _mk_audit(design_sha, meas_id, counts, **extra):
    a = {"verdict": "FAIL", "step_counts": dict(counts),
         "passed_gate_count": counts.get("PASS", 0),
         "failed_gate_count": counts.get("FAIL", 0),
         "run_at": "2026-08-05T00:00:00+00:00"}
    if design_sha is not None:
        a["design_input_digest"] = {"sha256": design_sha}
    if meas_id is not None:
        a["measurement"] = {"id": meas_id}
    a.update(extra)
    return a


# ─────────────────── P1: the field has to MEAN something ─────────────


def test_a_rerun_over_an_untouched_design_reproduces_the_digest(tmp_path):
    """The auditor writes ~250 report files into the tree it judges. If those
    landed in the digest, it would change on every run and could never
    separate a design change from a ruler change."""
    root = _design(tmp_path / "proj")
    writes = [("reports/phase3/checker_a.json", '{"verdict": "PASS"}'),
              (str(AUDIT_REL), '{"verdict": "FAIL"}'),
              ("reports/phase2/gates/checker_b.json", '{"n": 1}')]
    # Run 1 is the fresh-tree transition (the auditor's outputs do not exist
    # yet); 2, 3 and 4 are steady state and must agree exactly.
    _first, second, third, fourth = _audit_like_chain(root, writes, runs=4)
    assert second["sha256"] is not None
    assert second["sha256"] == third["sha256"] == fourth["sha256"]
    assert second["file_count"] == third["file_count"] == fourth["file_count"]


def test_a_byte_identical_rewrite_is_still_a_write(tmp_path):
    """An identical-byte rewrite is a write, and the footprint has to say so.

    Measured on a tracked project: of the 24 pre-existing files the auditor
    touched, 17 came back BYTE-IDENTICAL. A footprint that reported 7 instead
    of 24 would be describing what happened to DIFFER rather than what the
    auditor WROTE, and the published name set is the only thing a reviewer has
    to judge the exclusion by.

    Asserted from the second audit on. The first audit over a tree the auditor
    has never run on has no carried footprint, and an identical-byte rewrite
    landing inside one filesystem tick is invisible to both content and stat —
    which is exactly why the footprint is carried rather than re-derived.
    """
    root = _design(tmp_path / "proj")
    same = ("reports/phase3/checker_a.json", '{"verdict": "PASS"}')
    (root / same[0]).write_text(same[1])
    writes = [same, (str(AUDIT_REL), "{}")]
    blocks = _audit_like_chain(root, writes, runs=4)
    assert len({b["sha256"] for b in blocks[1:]}) == 1
    for b in blocks[1:]:
        assert same[0] in b["auditor_written_paths"]
        assert b["sha256"] is not None
    _, kept = _audit_like(root, writes, want_kept=True,
                          carried=blocks[-1]["auditor_written_paths"])
    assert same[0] not in kept
    assert "phase2/stage1/rtl/core.v" in kept


def test_a_rewrite_inside_one_timestamp_tick_is_still_a_write(tmp_path):
    """The hole in the (mtime_ns, size) signal, pinned deterministically.

    This is not hypothetical: a stat-only version of this code FAILED this
    file's byte-identical-rewrite test on 4 of 12 runs, because two writes
    landed in one filesystem tick. Left open it is the fabrication direction —
    the auditor's own file stays in the digest, the digest moves between two
    runs over an untouched tree, and the artefact reports that the DESIGN
    moved. Here the collision is forced with utime so the content signal is
    measured rather than hoped for.
    """
    root = _design(tmp_path / "proj")
    target = root / "reports/phase3/checker_a.json"
    target.write_text('{"verdict": "PASS"}')
    pre = did.scan_inputs(root)
    frozen = pre.stats["reports/phase3/checker_a.json"]
    target.write_text('{"verdict": "FAIL"}')          # same size, new content
    os.utime(target, ns=(frozen[0], frozen[0]))        # same tick, same size
    post = did.scan_inputs(root)
    assert post.stats["reports/phase3/checker_a.json"] == frozen, (
        "the collision this test exists to force did not happen")
    fp = did.auditor_footprint(pre, post, [str(AUDIT_REL)])
    assert "reports/phase3/checker_a.json" in fp, (
        "a rewrite invisible to the (mtime_ns, size) signal must still be "
        "caught by content")


def test_the_carried_footprint_cannot_grow_to_cover_the_design(tmp_path):
    """THE OVER-CORRECTION ON THE CARRIED SET. "Once excluded, always
    excluded" is one step from "eventually everything is excluded", and a
    footprint that grew to cover the tree would leave a digest that is
    perfectly reproducible and completely blind. Nothing may enter the carried
    set that was not measured as written, and a caller cannot smuggle the
    design in through it either — so a design file named in the carried list
    still has to have been written to be excluded on the evidence, and the
    population must survive twenty audits over an untouched tree.
    """
    root = _design(tmp_path / "proj")
    writes = [("reports/phase3/checker_a.json", '{"verdict": "PASS"}'),
              (str(AUDIT_REL), "{}")]
    blocks = _audit_like_chain(root, writes, runs=20)
    steady = blocks[1:]
    assert len({b["sha256"] for b in steady}) == 1, "the digest drifted"
    assert len({b["file_count"] for b in steady}) == 1
    assert steady[-1]["file_count"] == 3, steady[-1]["file_count"]
    assert steady[-1]["sha256"] is not None
    # The carried set is exactly the auditor's own two paths, forever.
    assert set(steady[-1]["auditor_written_paths"]) == {
        "reports/phase3/checker_a.json", str(AUDIT_REL)}


# ─────────────────── P2 / P5: it has to SEE the design ───────────────


def test_a_changed_rtl_file_moves_the_digest(tmp_path):
    root = _design(tmp_path / "proj")
    before = _audit_like(root, [(str(AUDIT_REL), "{}")])
    (root / "phase2/stage1/rtl/core.v").write_text(
        "module core(input clk, output q); assign q = ~clk; endmodule\n")
    after = _audit_like(root, [(str(AUDIT_REL), "{}")])
    assert before["sha256"] != after["sha256"]


def test_arriving_tool_evidence_under_reports_moves_the_digest(tmp_path):
    """THE OVER-CORRECTION TEST.

    The obvious way to keep the auditor out of its own digest is to exclude
    `reports/` by prefix. Measured across the 28 audit-bearing tracked
    projects, `reports/phase3/` is exactly where the DRC and LVS sign-off
    reports live (5 and 7 roots). An implementation that excludes the prefix
    passes every determinism test in this file and then reports
    MEASUREMENT_CHANGE over a run where a real 3-corner STA deck arrived —
    fabricating "the ruler moved" out of a design that moved. This test fails
    such an implementation.
    """
    root = _design(tmp_path / "proj")
    before = _audit_like(root, [(str(AUDIT_REL), "{}")])
    # Not written by the auditor: an EDA tool's sign-off report.
    (root / "reports/phase3/sta_multicorner.rpt").write_text(
        "corner ss: WNS 0.031\ncorner tt: WNS 0.204\ncorner ff: WNS 0.410\n")
    after = _audit_like(root, [(str(AUDIT_REL), "{}")])
    assert before["sha256"] != after["sha256"], (
        "evidence arriving under reports/ must move the design hash; a "
        "prefix exclusion of reports/ would hide it")
    assert after["file_count"] == before["file_count"] + 1


def test_a_deleted_design_file_moves_the_digest(tmp_path):
    root = _design(tmp_path / "proj")
    before = _audit_like(root, [(str(AUDIT_REL), "{}")])
    (root / "phase3/stage3/constraints/top.sdc").unlink()
    after = _audit_like(root, [(str(AUDIT_REL), "{}")])
    assert before["sha256"] != after["sha256"]


def test_a_retargeted_symlink_moves_the_digest(tmp_path):
    root = _design(tmp_path / "proj")
    (root / "phase2/stage1/rtl/alias.v").symlink_to("core.v")
    before = _audit_like(root, [(str(AUDIT_REL), "{}")])
    (root / "phase2/stage1/rtl/alias.v").unlink()
    (root / "phase2/stage1/rtl/alias.v").symlink_to("other.v")
    after = _audit_like(root, [(str(AUDIT_REL), "{}")])
    assert before["symlink_count"] == 1
    assert before["sha256"] != after["sha256"]


# ─────────────────── P3: an empty answer is refused ──────────────────


def test_a_digest_over_nothing_is_refused_not_published(tmp_path):
    """A filter narrowed until nothing survives is perfectly reproducible and
    perfectly useless: two unrelated projects would both hash to the digest of
    the empty set and read as "the same design"."""
    root = tmp_path / "empty"
    root.mkdir()
    block = did.build_digest(did.scan_inputs(root), [])
    assert block["sha256"] is None
    assert block["file_count"] == 0
    assert "no design inputs" in (block["unusable_reason"] or "")


def test_a_digest_whose_every_input_was_the_auditors_own_is_refused(tmp_path):
    root = tmp_path / "proj"
    (root / "reports").mkdir(parents=True)
    (root / "reports/only.json").write_text("{}")
    scan = did.scan_inputs(root)
    block = did.build_digest(scan, ["reports/only.json"])
    assert block["sha256"] is None
    assert block["unusable_reason"]


def test_a_truncated_scan_is_refused_and_says_so(tmp_path, monkeypatch):
    root = _design(tmp_path / "proj")
    monkeypatch.setattr(did, "LIMIT_FILES", 1)
    block = did.build_digest(did.scan_inputs(root), [])
    assert block["truncated"] is True
    assert block["sha256"] is None
    assert "truncat" in (block["unusable_reason"] or "").lower()


def test_the_published_block_names_its_own_exclusions(tmp_path):
    """A cap or an exclusion nobody can see reads as full coverage."""
    root = _design(tmp_path / "proj")
    block = _audit_like(root, [(str(AUDIT_REL), "{}")])
    for key in ("file_count", "bytes", "excluded_dir_names",
                "auditor_written_paths_excluded",
                "auditor_written_paths", "unreadable_count",
                "truncated"):
        assert key in block, key
    assert block["file_count"] > 0
    assert block["auditor_written_paths_excluded"] >= 1


# ─────────────────── P4: attribution, in both directions ─────────────

_COUNTS_A = {"PASS": 22, "FAIL": 5, "MISSING": 0}
_COUNTS_B = {"PASS": 6, "FAIL": 8, "MISSING": 2}


def test_same_design_new_ruler_moving_tally_is_a_measurement_change():
    """The finding itself: one run directory, byte-identical, 22 PASS under
    one plugin and 6 under a newer one."""
    prior = _mk_audit("D", "M-1.9.76", _COUNTS_A)
    current = _mk_audit("D", "M-newer", _COUNTS_B)
    r = did.classify(prior, current)
    assert r["classification"] == "MEASUREMENT_CHANGE"
    assert r["attributable_to_design"] is False
    assert "BYTE-IDENTICAL" in r["statement"]
    assert did.exit_code_for(r["classification"]) == 1


def test_a_design_change_is_never_reported_as_a_measurement_change():
    """THE FABRICATION DIRECTION. Whatever the ruler did, a moved design hash
    must never produce the sentence "the design did not change"."""
    for meas_prior, meas_current in (("M", "M"), ("M", "M2"),
                                     (None, None), ("M", None)):
        r = did.classify(_mk_audit("D1", meas_prior, _COUNTS_A),
                         _mk_audit("D2", meas_current, _COUNTS_B))
        assert r["classification"] != "MEASUREMENT_CHANGE", (
            meas_prior, meas_current)
        assert r["classification"] != "UNEXPLAINED_TALLY_MOVE"
        if r["classification"] != "NOT_COMPARABLE":
            assert r["design_moved"] is True


def test_design_moved_and_ruler_still_gives_a_design_reading():
    r = did.classify(_mk_audit("D1", "M", _COUNTS_A),
                     _mk_audit("D2", "M", _COUNTS_B))
    assert r["classification"] == "DESIGN_CHANGE"
    assert r["attributable_to_design"] is True
    assert did.exit_code_for(r["classification"]) == 0


def test_both_moved_is_not_attributable_and_does_not_fire():
    """A plugin upgrade landing in the same window as real design work is
    ORDINARY. It cannot support a progress claim, but a rule that exits
    non-zero on it would flag the state this repo ships every week."""
    r = did.classify(_mk_audit("D1", "M1", _COUNTS_A),
                     _mk_audit("D2", "M2", _COUNTS_B))
    assert r["classification"] == "NOT_ATTRIBUTABLE"
    assert r["attributable_to_design"] is False
    assert did.exit_code_for(r["classification"]) == 0
    assert "not attributable" in r["statement"].lower()


def test_nothing_moved_but_the_tally_did_is_named_not_explained_away():
    r = did.classify(_mk_audit("D", "M", _COUNTS_A),
                     _mk_audit("D", "M", _COUNTS_B))
    assert r["classification"] == "UNEXPLAINED_TALLY_MOVE"
    assert did.exit_code_for(r["classification"]) == 1


def test_an_audit_without_the_record_refuses_rather_than_guesses():
    """Every one of the 28 audit artefacts tracked today lands here."""
    r = did.classify(_mk_audit(None, None, _COUNTS_A),
                     _mk_audit("D", "M", _COUNTS_B))
    assert r["classification"] == "NOT_COMPARABLE"
    assert did.exit_code_for(r["classification"]) == 2
    r2 = did.classify(None, _mk_audit("D", "M", _COUNTS_B))
    assert r2["classification"] == "NOT_COMPARABLE"


def test_unchanged_tally_over_a_moved_design_says_the_verdict_did_not_respond():
    r = did.classify(_mk_audit("D1", "M", _COUNTS_A),
                     _mk_audit("D2", "M", _COUNTS_A))
    assert r["classification"] == "UNCHANGED"
    assert r["design_moved"] is True
    assert "did not respond" in r["statement"]


# ─────────────────── the ruler's own identity ────────────────────────


def test_the_measurement_id_moves_with_the_plugin_version():
    a = did.build_measurement("1.9.76", None, {})
    b = did.build_measurement("1.9.79", None, {})
    assert a["id"] != b["id"]


def test_the_measurement_id_moves_with_a_ruler_flag(tmp_path):
    a = did.build_measurement("1.9.79", None, {"skip_analog": False})
    b = did.build_measurement("1.9.79", None, {"skip_analog": True})
    assert a["id"] != b["id"]


def test_the_measurement_id_ignores_where_the_work_happened():
    a = did.build_measurement("1.9.79", None,
                              {"project_dir": "/a", "json": "/x.json",
                               "read_only": True, "phase": "all"})
    b = did.build_measurement("1.9.79", None,
                              {"project_dir": "/b", "json": "/y.json",
                               "read_only": False, "phase": "all"})
    assert a["id"] == b["id"]


def test_the_measurement_id_moves_with_the_flow_definition(tmp_path):
    f1 = tmp_path / "f1.yaml"
    f2 = tmp_path / "f2.yaml"
    f1.write_text("steps: [{id: 1}]\n")
    f2.write_text("steps: [{id: 1}, {id: 2}]\n")
    assert (did.build_measurement("1.9.79", f1, {})["id"]
            != did.build_measurement("1.9.79", f2, {})["id"])


def test_every_flow_compliance_option_is_classified_as_ruler_or_not():
    """Anti-recurrence. A ruler flag added later and left unclassified would
    silently drop out of `measurement.id`; this fails the suite instead.

    Limitation, stated rather than implied: the scan reads `add_argument`
    literals out of the source, so an option assembled at runtime would not be
    seen. No such option exists today.
    """
    src = FCC.read_text(encoding="utf-8")
    opts = set()
    for m in re.finditer(r'add_argument\(\s*"(--[A-Za-z0-9][A-Za-z0-9-]*)"',
                         src):
        opts.add(m.group(1)[2:].replace("-", "_"))
    assert len(opts) > 10, "the option scan found almost nothing; it is broken"
    known = set(did.RULER_FLAGS) | set(did.NON_RULER_FLAGS)
    assert opts - known == set(), (
        f"unclassified flow_compliance_check options: {sorted(opts - known)}; "
        f"add each to design_input_digest.RULER_FLAGS or NON_RULER_FLAGS")


# ─────────────────── the published artefact ──────────────────────────


def _run_fcc(project: Path, *extra):
    env = dict(os.environ)
    return _pr.run(
        [sys.executable, str(FCC), str(project), "--phase", "all", *extra],
        capture_output=True, text=True, env=env)


def _read_audit(project: Path):
    return json.loads((project / AUDIT_REL).read_text(encoding="utf-8"))


def _sha(audit):
    """The published design hash, or None. `.get` and not `[...]`: a KeyError
    would fail whatever the behaviour, and this suite's pre-fix failures have
    to be statements about what the artefact says."""
    return ((audit or {}).get("design_input_digest") or {}).get("sha256")


def test_the_published_audit_carries_the_population_beside_the_tally(tmp_path):
    """Contract-level: what a consumer of the artefact can actually read."""
    root = _design(tmp_path / "proj")
    _run_fcc(root)
    audit = _read_audit(root)
    assert audit.get("step_counts") is not None
    assert _sha(audit), (
        "the tally was published with no record of what it was computed over")
    meas = audit.get("measurement")
    assert isinstance(meas, dict) and meas.get("id")
    assert meas.get("plugin_version") == shipped_plugin_version()


def test_the_audits_own_version_is_read_not_restated(tmp_path):
    """It said "0.119.62" on every artefact this plugin has ever written,
    across releases 1.0.0 through 1.9.79 — so it could not tell two rulers
    apart, which is half of the defect."""
    root = _design(tmp_path / "proj")
    _run_fcc(root)
    audit = _read_audit(root)
    assert audit.get("version") == shipped_plugin_version()
    assert audit.get("version") != "0.119.62"


def test_rerunning_the_gate_on_an_untouched_tree_reproduces_the_digest(
        tmp_path):
    """The digest is stable across re-runs, and the classification never
    attributes the difference to the design.

    UNCHANGED is not required on the second run because this digest classifies
    every audit-side-effect population, not only declared outputs. Issue 1981
    made the declared-output subset idempotent: files created by a step's own
    gate are removed and can no longer become evidence on run two. Other audit
    diagnostics may still move the tally once, and this record must name that
    movement without attributing it to byte-identical design inputs. The third
    run pins the eventual steady state.
    """
    root = _design(tmp_path / "proj")
    _run_fcc(root)
    first = _read_audit(root)
    _run_fcc(root)
    second = _read_audit(root)
    assert _sha(first) is not None and _sha(first) == _sha(second), (
        "two audits over an untouched design published different populations")
    td = second.get("tally_delta") or {}
    assert td.get("design_moved") is False, (
        "the artefact does not state that the design inputs held still")
    assert td.get("attributable_to_design") is False
    assert td.get("classification") in ("UNCHANGED", "UNEXPLAINED_TALLY_MOVE")
    # And once the auditor's own outputs are in steady state, it settles.
    _run_fcc(root)
    third = _read_audit(root)
    assert _sha(third) == _sha(first)
    assert (third.get("tally_delta") or {}).get("classification") == "UNCHANGED"


def test_a_ruler_change_over_an_untouched_tree_is_stated_in_the_artefact(
        tmp_path):
    """The shape the finding came from: one run directory, re-judged."""
    root = _design(tmp_path / "proj")
    _run_fcc(root)
    before = _read_audit(root)
    proc = _run_fcc(root, "--skip-analog")
    after = _read_audit(root)
    td = after.get("tally_delta") or {}
    assert _sha(after) is not None and _sha(after) == _sha(before), (
        "the design did not move; the artefact must be able to say so")
    assert td.get("classification") in ("MEASUREMENT_CHANGE", "UNCHANGED"), (
        f"the artefact did not classify the re-judge: {td!r}")
    if td.get("tally_moved"):
        assert td["classification"] == "MEASUREMENT_CHANGE"
        assert td["attributable_to_design"] is False
        assert "TALLY_DELTA MEASUREMENT_CHANGE" in proc.stdout


def test_the_record_never_moves_the_verdict_or_the_exit_code(tmp_path):
    """This is a statement ABOUT the measurement, not one of the gates being
    measured. A record that could fail a run would be a new gate smuggled in
    under a provenance change."""
    root = _design(tmp_path / "proj")
    a = _run_fcc(root)
    first = _read_audit(root)
    b = _run_fcc(root)
    second = _read_audit(root)
    assert a.returncode == b.returncode
    assert first["verdict"] == second["verdict"]
    assert first["step_counts"] == second["step_counts"]


def test_the_audit_survives_a_digest_that_cannot_be_computed(tmp_path,
                                                             monkeypatch):
    """Degradation, measured rather than asserted: with the module removed
    from the import path the audit is still written, still carries its tally,
    and says why the record is absent."""
    root = _design(tmp_path / "proj")
    # PYTHONPATH cannot shadow it: `flow_compliance_check` runs with its own
    # directory at sys.path[0]. Blocking the module in sys.modules is the one
    # way to make the import fail exactly as a missing file would.
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(PROGRAMS)!r});"
        "sys.modules['design_input_digest'] = None;"
        "import flow_compliance_check as f;"
        f"sys.exit(f.main([{str(root)!r}, '--phase', 'all']))")
    _pr.run([sys.executable, "-c", code],
                   capture_output=True, text=True)
    audit = _read_audit(root)
    assert audit.get("step_counts") is not None
    assert audit.get("verdict")
    blk = audit.get("design_input_digest")
    assert blk is None or blk.get("sha256") is None


# ─────────────────── the CLI a consumer uses ─────────────────────────


def test_compare_cli_exit_codes(tmp_path):
    p = tmp_path / "prior.json"
    c = tmp_path / "curr.json"
    p.write_text(json.dumps(_mk_audit("D", "M1", _COUNTS_A)))
    c.write_text(json.dumps(_mk_audit("D", "M2", _COUNTS_B)))
    assert did.main(["--compare", str(p), str(c)]) == 1
    c.write_text(json.dumps(_mk_audit("D2", "M1", _COUNTS_B)))
    assert did.main(["--compare", str(p), str(c)]) == 0
    c.write_text(json.dumps(_mk_audit(None, None, _COUNTS_B)))
    assert did.main(["--compare", str(p), str(c)]) == 2


def test_project_cli_refuses_an_empty_tree(tmp_path):
    empty = tmp_path / "e"
    empty.mkdir()
    assert did.main(["--project", str(empty)]) == 2
    assert did.main(["--project", str(_design(tmp_path / "p"))]) == 0
