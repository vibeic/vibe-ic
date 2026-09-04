"""vibe-ic#693 — the `signoff-integrity` family, wired.

Five gates that #693 measured as referenced from NO executable location. Each
test here holds one property that a MEASUREMENT decided, so the record cannot
outlive the condition it describes:

  * `lvs_signoff_guard`   — the top is DERIVED, never "the first subckt". On a
    real Magic extraction the first `.subckt` is a leaf standard cell, whose
    pins always exist, so the old default made the guard incapable of failing.
  * `drc_vacuous_pass_check` — a citation is a FILENAME, not a design name; and
    `--under` scopes discovery to the artefact the step declares.
  * `step_internal_fail_bubble_up_check` — acknowledgment is IDENTITY, not a
    shared category token; `verdict_mode: ADVISES` is an answer, not a silence;
    the project verdict stays blocking.
  * `silent_decline_audit` — a bare run cannot be wired as a gate, so the
    ratchet must refuse without a baseline rather than pass quietly.
  * `checkpoint_gate_check` — INVENTORIED, and the record is re-derived: the
    moment anything machine-wires it, the disclosure is false and CI says so.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_ROOT = next(b for b in _PLUGIN.parents if (b / "vibe-ic-marketplace").is_dir())


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────────────────────────────────────────────────────
# lvs_signoff_guard — the top must be derived
# ───────────────────────────────────────────────────────────────────────────
G = _load("lvs_signoff_guard")

_HIER = """\
* a Magic-shaped extraction: leaves first, design top last
.subckt sky130_fd_sc_hd__dfxtp_1 VGND VNB VPB VPWR CLK D Q
.ends
.subckt sky130_fd_sc_hd__conb_1 VGND VNB VPB VPWR HI LO
.ends
.subckt spm clk rst_n a b y
Xreg0 VGND VNB VPB VPWR clk a y sky130_fd_sc_hd__dfxtp_1
Xtie0 VGND VNB VPB VPWR b y sky130_fd_sc_hd__conb_1
.ends
"""


def test_first_subckt_is_a_standard_cell_not_the_top():
    """The measurement that condemns the old default, in one assertion."""
    assert G.defined_subckts(_HIER)[0] == "sky130_fd_sc_hd__dfxtp_1"
    assert len(G.subckt_ports(_HIER, None)) == 7        # a std cell's pins
    assert G.derive_tops(_HIER) == ["spm"]
    assert len(G.subckt_ports(_HIER, "spm")) == 5


def test_portless_top_fires_even_though_every_leaf_has_pins(tmp_path):
    """The defect: the design top loses its ports, every standard cell keeps
    theirs. Guarding the first subckt returns PASS; guarding the derived top
    must FAIL."""
    portless = _HIER.replace(".subckt spm clk rst_n a b y", ".subckt spm")
    sp = tmp_path / "top_extracted.sp"
    sp.write_text(portless)
    verdict = tmp_path / "lvs.rpt"
    verdict.write_text("Circuits match uniquely.\n")

    # derived (the wired form)
    assert G.main(["--spice", str(sp), "--verdict-file", str(verdict)]) == 1
    # the OLD default, reproduced: a standard cell always has pins
    assert G.main(["--spice", str(sp), "--top", "sky130_fd_sc_hd__dfxtp_1",
                   "--verdict-file", str(verdict)]) == 0


def test_ambiguous_root_guards_every_root_rather_than_guessing():
    two = _HIER + ".subckt other_top p q\n.ends\n"
    tops, how = G.resolve_tops(two, None)
    assert set(tops) == {"spm", "other_top"}
    assert "ambiguous" in how


def test_project_dir_and_glob_both_resolve(tmp_path):
    d = tmp_path / "phase3" / "stage3" / "extracted"
    d.mkdir(parents=True)
    (d / "spm_extracted.sp").write_text(_HIER)
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    (tmp_path / "reports" / "phase3" / "lvs.rpt").write_text("Circuits match uniquely.\n")
    assert G.main([str(tmp_path)]) == 0
    # the glob form the flow would otherwise hand to a shell that never sees it
    assert G.main(["--spice", str(tmp_path / "phase3/stage3/extracted/*.sp")]) == 0


def test_no_netlist_is_not_checked_not_a_pass(tmp_path, capsys):
    (tmp_path / "reports").mkdir()
    assert G.main([str(tmp_path)]) == 2
    assert capsys.readouterr().out.lstrip().startswith("VACUOUS_PASS")


# ───────────────────────────────────────────────────────────────────────────
# drc_vacuous_pass_check — citation is a filename; --under scopes discovery
# ───────────────────────────────────────────────────────────────────────────
D = _load("drc_vacuous_pass_check")


def _gds(path: pathlib.Path, shapes: int) -> None:
    recs = [(0x00, 0x02, struct.pack(">h", 600)), (0x01, 0x02, b"top\x00")]
    recs += [(0x08, 0x00, b"")] * shapes          # BOUNDARY == drawn geometry
    path.write_bytes(b"".join(
        struct.pack(">H", len(b) + 4) + bytes([rt, dt]) + b for rt, dt, b in recs))


def _lyrdb(path: pathlib.Path, top: str = "spm") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0"?>\n<report-database>\n'
        f' <top-cell>{top}</top-cell>\n <items>\n </items>\n</report-database>\n'
        'Total DRC errors found: 0\nDRC is clean\n')


def test_empty_layout_condemns_a_clean_verdict(tmp_path):
    _gds(tmp_path / "spm.gds", 0)
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_signoff.rpt")
    r = D.audit(tmp_path, None, ["reports/phase3/drc_signoff.rpt"])
    assert r.verdict == "INCONCLUSIVE"
    assert any(f.rule == "DRC_VACUOUS_PASS" for f in r.findings)


def test_real_geometry_earns_the_clean(tmp_path):
    _gds(tmp_path / "spm.gds", 12)
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_signoff.rpt")
    r = D.audit(tmp_path, None, ["reports/phase3/drc_signoff.rpt"])
    assert r.verdict == "PASS"


def test_a_stray_scratch_file_named_after_the_design_cannot_condemn(tmp_path):
    """REGRESSION. `<top-cell>spm</top-cell>` used to bind every file called
    `spm.*`, and a decisive `any(shapes == 0)` then let an unrelated scratch
    DEF condemn a real run with a factually false message. Reproduced on a
    published 9050-shape run before the fix."""
    _gds(tmp_path / "spm.gds", 9050)
    scratch = tmp_path / "phase3" / "stage3" / "pnr_d8"
    scratch.mkdir(parents=True)
    (scratch / "spm.def").write_text(
        "VERSION 5.8 ;\nDESIGN spm ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nEND DESIGN\n")
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_signoff.rpt")
    assert D.audit(tmp_path, None, ["reports/phase3/drc_signoff.rpt"]).verdict == "PASS"
    assert D.audit(tmp_path).verdict == "PASS"


def test_an_exact_filename_citation_is_still_decisive(tmp_path):
    """…and the fix must not cost the gate its subject."""
    _gds(tmp_path / "spm.gds", 0)
    _gds(tmp_path / "unrelated.gds", 500)
    rpt = tmp_path / "reports" / "phase3" / "drc_signoff.rpt"
    _lyrdb(rpt)
    rpt.write_text(rpt.read_text() + "\nchecked layout spm.gds\n")
    r = D.audit(tmp_path, None, ["reports/phase3/drc_signoff.rpt"])
    assert r.verdict == "INCONCLUSIVE"


def test_under_excludes_another_steps_drc_report(tmp_path):
    _gds(tmp_path / "spm.gds", 12)
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_signoff.rpt")
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_router.rpt")
    _lyrdb(tmp_path / "phase3" / "reports" / "drc.rpt")
    assert D.audit(tmp_path).summary["files_found"] == 3
    scoped = D.audit(tmp_path, None, ["reports/phase3/drc_signoff.rpt"])
    assert scoped.summary["files_found"] == 1
    assert scoped.summary["scoped_under"] == ["reports/phase3/drc_signoff.rpt"]


def test_a_typod_scope_is_disclosed_not_silently_empty(tmp_path):
    _lyrdb(tmp_path / "reports" / "phase3" / "drc_signoff.rpt")
    r = D.audit(tmp_path, None, ["reports/phase3/does_not_exist.rpt"])
    assert r.verdict == "SKIP"
    assert r.summary["scoped_under_missing"] == ["reports/phase3/does_not_exist.rpt"]


# ───────────────────────────────────────────────────────────────────────────
# step_internal_fail_bubble_up_check — identity, ADVISES, and the ratchet
# ───────────────────────────────────────────────────────────────────────────
B = _load("step_internal_fail_bubble_up_check")


def _fail_report(root: pathlib.Path, rel: str, extra: dict | None = None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"verdict": "FAIL", **(extra or {})}))
    return p


def test_an_empty_failed_gates_list_is_not_an_acknowledgment(tmp_path):
    """THE defect the identity fix closes, measured on the published corpus:
    `reports/phase2/gates/ip_integration.json` verdict=FAIL was credited as
    bubbled up by the token `gates`, matched against the line
    `"failed_gates": [],` — a line asserting the opposite."""
    _fail_report(tmp_path, "reports/phase2/gates/ip_integration.json")
    aud = tmp_path / "reports" / "audit"
    aud.mkdir(parents=True)
    (aud / "phase23_completion_audit.json").write_text(
        json.dumps({"failed_gates": [], "verdict": "PASS"}))
    verdict, findings, _examined = B.audit(tmp_path)
    assert verdict == "FAIL"
    assert [f.report_file for f in findings] == [
        "reports/phase2/gates/ip_integration.json"]


def test_a_waiver_naming_the_report_still_acknowledges_it(tmp_path):
    _fail_report(tmp_path, "reports/phase2/gates/ip_integration.json")
    (tmp_path / "waivers.json").write_text(json.dumps({"waived_steps": [
        {"id": 14, "reason": "tracked upstream",
         "evidence": "reports/phase2/gates/ip_integration.json"}]}))
    assert B.audit(tmp_path)[0] == "PASS"


def test_category_tokens_no_longer_count_as_identity(tmp_path):
    p = tmp_path / "reports" / "phase2" / "gates" / "ip_integration.json"
    cands = B._name_candidates(p, tmp_path)
    assert "gates" not in cands and "integration" not in cands
    assert "ip_integration" in cands
    assert "reports/phase2/gates/ip_integration.json" in cands


def test_advises_is_an_answer_and_blocks_is_not(tmp_path):
    """The verdict word is PASS, not VACUOUS_PASS, and the difference is the
    point of the change beside this one: a report WAS examined and it declared
    its verdict does not gate, which is a real pass over a real population.
    `VACUOUS_PASS` is this repo's word for a verdict issued over NOTHING, and
    using it here put "I read one report and it advises" in the same class as
    "there was nothing to read" — which is now rc=2 NOT_EXAMINED."""
    r = _fail_report(tmp_path, "reports/phase1/x.json", {"verdict_mode": "ADVISES"})
    v, _f, examined = B.audit(tmp_path)
    assert v == "PASS"
    assert examined == 1, "the ADVISES report was READ; it is skipped, not unseen"
    r.write_text(json.dumps({"verdict": "FAIL", "verdict_mode": "BLOCKS"}))
    assert B.audit(tmp_path)[0] == "FAIL"
    r.write_text(json.dumps({"verdict": "FAIL"}))
    assert B.audit(tmp_path)[0] == "FAIL"


def test_project_mode_stays_blocking(tmp_path):
    """The non-blocking property lives in --corpus. Weakening THIS would put
    the audited defect (an inner FAIL that never reaches the exit code) inside
    the gate that audits for it."""
    _fail_report(tmp_path, "reports/phase3/x.json")
    assert B.main([str(tmp_path)]) == 1
    assert B.main([str(tmp_path), "--strict"]) == 1


def test_corpus_ratchet_refuses_without_a_baseline_and_fires_on_growth(
        tmp_path, monkeypatch):
    # This unit case mutates an explicit private corpus in-process.  The
    # landing harness's byte-attested production binding must not replace that
    # named subject; production binding itself remains exercised by the
    # dedicated hygiene-corpus-binding controls.
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    corpus = tmp_path / "ic"
    run = corpus / "chip" / "clean_run_x"
    _fail_report(run, "reports/phase3/a.json")
    bl = tmp_path / "bl.json"
    # no baseline -> NOT CHECKED, never a quiet pass
    assert B.main(["--corpus", str(corpus), "--baseline", str(bl)]) == 2
    assert B.main(["--corpus", str(corpus), "--baseline", str(bl),
                   "--write-baseline"]) == 0
    assert B.main(["--corpus", str(corpus), "--baseline", str(bl)]) == 0
    _fail_report(run, "reports/phase3/b.json")
    assert B.main(["--corpus", str(corpus), "--baseline", str(bl)]) == 1


def test_corpus_with_nothing_to_sweep_refuses(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    corpus = tmp_path / "ic"
    (corpus / "chip" / "clean_run_x").mkdir(parents=True)
    assert B.main(["--corpus", str(corpus)]) == 2
    assert "VACUOUS_PASS" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────────────────
# silent_decline_audit — the ratchet
# ───────────────────────────────────────────────────────────────────────────
S = _load("silent_decline_audit")

_SILENT = """\
def loosen_die(x):
    return None

def run(x):
    lf = loosen_die(x)
    if lf is not None:
        apply_it(lf)
"""
_DISCLOSED = _SILENT + """    else:
        print("loosen declined: die stays as-is")
"""


def test_ratchet_fires_on_a_new_silent_decline_and_not_on_a_disclosed_one(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text(_SILENT)
    bl = tmp_path / "bl.json"
    assert S.main([str(src), "--ratchet", "--baseline", str(bl)]) == 2  # no baseline
    (src / "m.py").write_text(_DISCLOSED)
    assert S.main([str(src), "--ratchet", "--baseline", str(bl),
                   "--write-baseline"]) == 0
    assert json.loads(bl.read_text())["count"] == 0
    (src / "m.py").write_text(_SILENT)
    assert S.main([str(src), "--ratchet", "--baseline", str(bl)]) == 1


def test_an_empty_scan_refuses_rather_than_passing_quietly(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert S.main([str(empty), "--ratchet"]) == 2
    assert "VACUOUS_PASS" in capsys.readouterr().out


def test_the_shipped_baseline_matches_the_shipped_source():
    """The wired invocation is `silent_decline_audit.py programs --ratchet`;
    if the recorded number drifts from what that measures, CI is comparing
    against a fiction."""
    bl = json.loads((_PROGRAMS / S.BASELINE_NAME).read_text())
    rep = S.audit(sorted(p for p in _PROGRAMS.glob("*.py")
                         if not p.name.startswith("test_")))
    assert rep["count"] <= bl["count"], (
        f"silent declines grew {bl['count']} -> {rep['count']}")


# ───────────────────────────────────────────────────────────────────────────
# checkpoint_gate_check — INVENTORIED, and the record is re-derived
# ───────────────────────────────────────────────────────────────────────────
W = _load("checker_execution_wiring_audit")


def _baseline() -> dict:
    return json.loads((_PROGRAMS / "checker_execution_wiring_baseline.json").read_text())


def test_checkpoint_gate_check_is_disclosed_as_deliberately_unwired():
    d = _baseline().get("unwired_by_decision") or {}
    assert "checkpoint_gate_check.py" in d, (
        "an orphan gate must never be BOTH unwired and unlisted (#693)")
    assert len(d["checkpoint_gate_check.py"]) >= W._MIN_DECISION_REASON


def test_the_disclosure_is_re_derived_not_asserted():
    """It must go stale the moment anything machine-wires it. Otherwise the
    record is a permanent licence rather than a disclosure."""
    rep = W.audit(_PLUGIN, _ROOT)
    assert not rep["machine_runners"].get("checkpoint_gate_check.py"), (
        "checkpoint_gate_check.py now has a machine runner — the "
        "`unwired_by_decision` record is false and must be removed")
    assert not W.check_unwired_by_decision(
        rep, _baseline().get("unwired_by_decision") or {}, _baseline()["known"])


@pytest.mark.parametrize("gate,expected_runner", [
    ("drc_vacuous_pass_check.py", "FLOW"),
    ("lvs_signoff_guard.py", "FLOW"),
    ("step_internal_fail_bubble_up_check.py", "TOOLS"),
    ("silent_decline_audit.py", "TOOLS"),
])
def test_the_wired_four_are_reachable_from_an_executable_location(gate, expected_runner):
    """#693's actual subject. A gate wired somewhere that never executes is the
    same defect moved, so assert the runner CLASS, not merely a mention."""
    hay = W._tokenise(W._haystacks(_PLUGIN, _ROOT))
    r = W.runners(gate[:-3], hay, str(_PROGRAMS / gate))
    assert expected_runner in r, f"{gate}: runners={sorted(r)}"


def test_a_stale_or_falsified_decision_record_is_rejected():
    rep = W.audit(_PLUGIN, _ROOT)
    assert W.check_unwired_by_decision(
        rep, {"no_such_program_check.py": "x" * 200}, [])
    assert W.check_unwired_by_decision(
        rep, {"drc_vacuous_pass_check.py": "x" * 200}, [])   # now flow-wired
    assert W.check_unwired_by_decision(
        rep, {"checkpoint_gate_check.py": "too thin"}, [])
    assert W.check_unwired_by_decision(
        rep, {"checkpoint_gate_check.py": "x" * 200}, ["checkpoint_gate_check.py"])
