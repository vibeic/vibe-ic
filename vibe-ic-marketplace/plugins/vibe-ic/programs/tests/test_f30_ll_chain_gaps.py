"""F30 -- two LibreLane-path gaps the combined chain (LL15 -> LL17+18 ->
LL19/20 -> direct tail) left red on spm x gf180mcuD (vibeic-eda 0.3.79), after
F23 closed the 15..18 seam:

1. Step 15.5ic, audit: `reports/phase3/padring.json` was `audit_created`. On
   the LibreLane path the tool places the ring, and the only writer of that
   file was the step's own gate (`pad_ring_check --librelane-state`), so the
   audit refused it as self-certified: no producer record existed. Now
   `pad_ring_gen --librelane-state` describes the ring `OpenROAD.PadRing`
   placed, bound by sha256 to the handoff receipt, and the gate audits it.
2. Step 16, `clock_plan_check` -> CTS_CLOCK_MISSING. With steps 19/20 on
   LibreLane, `cts/clock_tree.rpt` is the tool's `report_cts` summary, which
   names no root. The roots are in the same step's `openroad-cts.log`; the gate
   reads that transcript when the step-19 receipt binds the report to it.

Both are driven through the real programs; nothing EDA is faked here except the
files a tool writes (the pad ring is a DEF `pad_ring_gen` placed, standing in
for PadRing's; the CTS transcripts are real LibreLane 0.3.79 output from
`programs/calibration/`).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402
import librelane_contract as contract  # noqa: E402
import pad_ring_check as CHK  # noqa: E402
import pad_ring_gen as GEN  # noqa: E402
from _stated_eda_image import state_the_image  # noqa: E402


@pytest.fixture(autouse=True)
def _stated_image(monkeypatch):
    """The image identity is STATED, never asked of this host: the runner branch
    below reaches `librelane_contract.resolve_image`, which inside the image (no
    docker) would refuse LL_IMAGE_NOT_RESOLVABLE and on a docker host would
    borrow whatever it holds (tests/_stated_eda_image.py)."""
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    monkeypatch.delenv("VIBEIC_LIBRELANE_IMAGE", raising=False)
    state_the_image(monkeypatch)

_spec = importlib.util.spec_from_file_location(
    "f30_pad_ring_fixtures", Path(__file__).resolve().parent / "test_pad_ring.py")
FX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FX)

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
CAL = PROGRAMS / "calibration"
PADRING_STEP = "phase3/librelane/15-floorplan/06-openroad-padring"
#: what `librelane_contract.handoff_to_direct` is given by the runner
RECEIPT = "reports/phase3/librelane_padring_handoff.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# gap 1: step 15.5ic's producer record on the LibreLane path
# --------------------------------------------------------------------------

def _ll_project(tmp_path: Path) -> Path:
    """A project where a ring was placed and handed over the LibreLane way.

    The ring DEF comes from the real direct placer on the synthetic library of
    `test_pad_ring`, then is moved to where `OpenROAD.PadRing`'s State keeps
    it; `librelane_contract.handoff_to_direct` (the runner's own call) copies
    it to `padring.def` and writes the receipt. The direct report is deleted:
    nothing of the direct arm survives into the LibreLane project.
    """
    root = FX._project(tmp_path)
    assert FX._gen(root) == 0, FX._report(root)["reason"]
    step = root / PADRING_STEP
    step.mkdir(parents=True)
    tool_def = step / "chip_top.def"
    shutil.move(str(root / PR.PADRING_DEF_REL), tool_def)
    (root / PR.REPORT_REL).unlink()
    state = step / "state_out.json"
    state.write_text(json.dumps({"def": str(tool_def)}))
    contract.handoff_to_direct(state, {"def": root / PR.PADRING_DEF_REL},
                               root / RECEIPT)
    return root


def _ll_gen(root: Path) -> int:
    return GEN.main([str(root), *FX._pdk_args(root),
                     "--librelane-state", str(root / PADRING_STEP / "state_out.json")])


def _step(sid: str) -> dict:
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    return next(s for s in steps if str(s.get("id")) == sid)


def _authorship(root: Path):
    """The audit's own reading of `padring.json` for step 15.5ic, with the
    producer and gate names taken from the flow the audit reads."""
    step = _step("15.5ic")
    gates = frozenset(FCC._gate_name(c)
                      for c in FCC._declared_gate_commands(step["gate"]))
    producers = frozenset(step["programs"])
    assert "pad_ring_check" in gates and "pad_ring_gen" in producers
    return FCC.authorship_answer(root / PR.REPORT_REL, gates, producers)


def test_the_ll_ring_gets_a_producer_record_the_audit_credits(tmp_path):
    assert GEN.LL_PADRING_HANDOFF_REL == RECEIPT
    root = _ll_project(tmp_path)
    assert _ll_gen(root) == 0, FX._report(root)
    rep = FX._report(root)
    assert rep["program"] == "pad_ring_gen" and rep["verdict"] == "PASS"
    assert rep["placed_by"] == "OpenROAD.PadRing"
    assert rep["padring_def"] == PR.PADRING_DEF_REL
    ev = rep["tool_evidence"]
    assert ev["padring_def_sha256"] == _sha(root / PR.PADRING_DEF_REL)
    assert ev["state_sha256"] == _sha(root / PADRING_STEP / "state_out.json")
    assert ev["receipt_sha256"] == _sha(root / RECEIPT)
    # the population is the tool DEF's: every declared pad, the corners
    placed = {c["instance"] for c in rep["pads"]}
    assert placed == set(FX.PADS.values())
    assert len(rep["corners"]) == 4 and rep["fillers_placed"] == len(rep["fillers"])
    assert _authorship(root) == (False, FCC.AUTHORSHIP_BY_CONTENT)
    # the flow's own 15.5ic gate audits it and keeps the producer verbatim
    assert FX._chk(root) == 0, FX._report(root)["reason"]
    merged = FX._report(root)
    assert merged["gate"] == "pad_ring_check" and merged["producer"] == rep
    assert _authorship(root) == (False, FCC.AUTHORSHIP_BY_CONTENT)


def test_the_gates_own_document_alone_is_still_refused(tmp_path):
    """The other direction: what the LibreLane path wrote before F30 -- only
    the tool gate's verdict document -- stays the auditor's."""
    root = _ll_project(tmp_path)
    assert CHK.main([str(root), *FX._pdk_args(root), "--librelane-state",
                     str(root / PADRING_STEP / "state_out.json")]) == 0
    assert _authorship(root) == (True, FCC.AUTHORSHIP_BY_CONTENT)


@pytest.mark.parametrize("tamper", ["padring_def", "state", "receipt_source"])
def test_a_ring_the_receipt_does_not_bind_is_refused(tmp_path, tamper):
    root = _ll_project(tmp_path)
    if tamper == "padring_def":
        p = root / PR.PADRING_DEF_REL
        p.write_text(p.read_text() + "# edited after the handoff\n")
    elif tamper == "state":
        s = root / PADRING_STEP / "state_out.json"
        s.write_text(s.read_text() + "\n")
    else:
        r = root / RECEIPT
        doc = json.loads(r.read_text())
        doc["views"]["def"]["source_sha256"] = "0" * 64
        r.write_text(json.dumps(doc))
    assert _ll_gen(root) == 1
    rep = FX._report(root)
    assert rep["verdict"] == "FAIL" and rep["program"] == "pad_ring_gen"
    assert {f["rule"] for f in rep["findings"]} == {"PADRING_LL_UNBOUND"}
    assert FX._chk(root) == 1


def test_no_receipt_means_no_record(tmp_path):
    root = _ll_project(tmp_path)
    (root / RECEIPT).unlink()
    assert _ll_gen(root) == 1
    assert {f["rule"] for f in FX._report(root)["findings"]} == {
        "PADRING_LL_RECEIPT_UNREADABLE"}


def test_a_pad_the_tool_did_not_place_is_refused(tmp_path):
    root = _ll_project(tmp_path)
    tool_def = root / PADRING_STEP / "chip_top.def"
    victim = FX.PADS[FX.SIGNALS["N"][0]]
    text = tool_def.read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith(f"- {victim} "))
    tool_def.write_text(text.replace(line, f"- {victim} pad_bidir + UNPLACED ;"))
    shutil.copyfile(tool_def, root / PR.PADRING_DEF_REL)
    contract.handoff_to_direct(root / PADRING_STEP / "state_out.json",
                               {"def": root / PR.PADRING_DEF_REL},
                               root / RECEIPT)
    assert _ll_gen(root) == 1
    assert victim in FX._report(root)["reason"]


# ---- the runner's LibreLane floorplan branch calls producer, then gate ----

import phase3_one_shot_runner as runner  # noqa: E402

_spec_b = importlib.util.spec_from_file_location(
    "f30_bridge_fixtures",
    Path(__file__).resolve().parent / "test_librelane_state_bridge.py")
BR = importlib.util.module_from_spec(_spec_b)
_spec_b.loader.exec_module(BR)


def _drive_branch(tmp_path, monkeypatch, rc_by_program):
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    wrapper = BR.write(out_dir / "chip_top_io.v", "module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n")
    BR.put(project / "phase3/librelane_switch.json", {"pdk_root_host": str(tmp_path)})
    monkeypatch.setattr(runner, "_padring_chip_top_record", lambda p: {
        "core_module": "core", "chip_top_verilog": str(wrapper.relative_to(project))})
    netlist = BR.write(project / "phase3/stage2/core.v", "module core(a);\n  input a;\nendmodule\n")
    monkeypatch.setattr(runner, "pnr_input_netlist", lambda p, core: (netlist, "n", False))
    monkeypatch.setattr(runner, "_docker_exec", lambda *a, **k: (0, "ok", ""))
    monkeypatch.setattr(contract, "flow_segment", lambda image, first, last, **k: [first, last])
    monkeypatch.setattr(contract, "resolve_step_configs", lambda p, i, pdk, ids, **k: {
        s: BR._declared(tmp_path, s, tmp_path) for s in ids})
    monkeypatch.setattr(contract, "emit_pdn_cfg", lambda *a, **k: None)

    def chain(project, image, triples, **k):
        out = []
        for step, _c, _s in triples:
            f = project / "phase3/librelane/15-floorplan" / step
            BR.put(f / "state_out.json", {"def": str(BR.write(f / "x.def", BR.DEF_TEXT)),
                                          "odb": str(BR.write(f / "x.odb", "o"))})
            out.append(f)
        return out
    monkeypatch.setattr(contract, "run_chain", chain)
    calls = []

    def run(argv, **k):
        calls.append(argv)
        name = Path(argv[1]).name
        return SimpleNamespace(returncode=rc_by_program.get(name, 0),
                               stdout=f"{name} said so", stderr="")
    monkeypatch.setattr(runner._pr, "run", run)
    pdk = BR._pdk(tmp_path)
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, pdk, "c", out_dir, BR._deck(), {"15": "direct", "15.5ic": "librelane"},
        io_view_discover=lambda *a: ([], []))
    return result, consumer, calls, pdk


def test_the_branch_writes_the_record_before_the_step_gate_reads_it(tmp_path, monkeypatch):
    result, consumer, calls, pdk = _drive_branch(tmp_path, monkeypatch, {})
    assert result.status == "PASS", result.detail
    names = [(Path(c[1]).name, c[3] if len(c) > 3 else None) for c in calls]
    assert names[:3] == [("pad_ring_check.py", "--librelane-state"),
                         ("pad_ring_gen.py", "--librelane-state"),
                         ("pad_ring_check.py", "--pdk-root")]
    state = calls[1][calls[1].index("--librelane-state") + 1]
    assert state.endswith("OpenROAD.PadRing/state_out.json")
    root_c, tree = runner._padring_pdk_root_and_tree(pdk, "c")
    for argv in calls[:3]:
        assert argv[-4:] == ["--pdk-root", str(root_c), "--pdk", str(tree)]
    assert "pad_ring_gen.py --librelane-state: rc=0" in result.detail


def test_a_producer_refusal_blocks_routing_by_name(tmp_path, monkeypatch):
    result, consumer, calls, _ = _drive_branch(
        tmp_path, monkeypatch, {"pad_ring_gen.py": 1})
    assert result.status == "FAIL" and consumer is None
    assert result.detail.startswith("PADRING_LL_PRODUCER_FAILED")
    assert [Path(c[1]).name for c in calls] == ["pad_ring_check.py", "pad_ring_gen.py"]


# --------------------------------------------------------------------------
# gap 2: step 16 reads the roots LibreLane CTS recorded
# --------------------------------------------------------------------------

_PLAN = [{"name": "clk", "period_ns": 20, "source": "clk"},
         {"name": "clk2", "period_ns": 30, "source": "clk2"}]
CTS_STEP = "phase3/librelane/19-cts-hold/01-openroad-cts"


def _cts_project(tmp_path: Path, stem: str) -> Path:
    """The step-19 LibreLane handoff as `librelane_cts_hold` writes it, around
    one real LibreLane CTS step folder (calibration/<stem>.{rpt,log})."""
    p = tmp_path / stem
    folder = p / CTS_STEP
    folder.mkdir(parents=True)
    shutil.copyfile(CAL / f"{stem}.rpt", folder / "cts.rpt")
    shutil.copyfile(CAL / f"{stem}.log", folder / "openroad-cts.log")
    report = p / "phase3/stage3/cts/clock_tree.rpt"
    report.parent.mkdir(parents=True)
    shutil.copyfile(folder / "cts.rpt", report)
    (p / "phase3/stage3/cts/clock_plan.json").write_text(json.dumps({"clocks": _PLAN}))
    sdc = p / "phase3/stage3/pnr/constraint.sdc"
    sdc.parent.mkdir(parents=True)
    shutil.copyfile(CAL / "cal_two_clocks.sdc", sdc)
    receipt = p / "reports/phase3/librelane_cts_hold_handoff.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({
        "chain": {"OpenROAD.CTS": CTS_STEP},
        "views": {"cts_rpt": {"source": str(folder / "cts.rpt"),
                              "source_sha256": _sha(folder / "cts.rpt"),
                              "dest": "phase3/stage3/cts/clock_tree.rpt",
                              "dest_sha256": _sha(report)}}}))
    return p


def _clock_gate(project: Path):
    cp = subprocess.run([sys.executable, str(PROGRAMS / "clock_plan_check.py"),
                         str(project), "--json", str(project / "cp.json")],
                        capture_output=True, text=True)
    doc = json.loads((project / "cp.json").read_text())
    return cp.returncode, {f["rule"]: f["message"] for f in doc["findings"]}


SEEN = "ll_cts_clock_roots_seen_negative"
DROPPED = "ll_cts_clock_root_dropped_positive"


def test_the_ll_cts_report_names_no_root_but_its_transcript_does():
    # the measured premise: byte-identical report_cts summaries, roots only in
    # the transcripts
    assert (CAL / f"{SEEN}.rpt").read_bytes() == (CAL / f"{DROPPED}.rpt").read_bytes()
    assert "CTS-0007" not in (CAL / f"{SEEN}.rpt").read_text()
    assert (CAL / f"{SEEN}.log").read_text().count("CTS-0007") == 2


def test_step16_reads_the_roots_librelane_cts_recorded(tmp_path):
    rc, rules = _clock_gate(_cts_project(tmp_path, SEEN))
    assert rc == 0, rules
    assert "CTS_CLOCK_MISSING" not in rules
    assert f"{CTS_STEP}/openroad-cts.log" in rules["CTS_CLOCKS_SEEN"]
    assert "('clk', 'clk'), ('clk2', 'clk2')" in rules["CTS_CLOCKS_SEEN"]


def test_a_root_librelane_cts_never_named_still_fails(tmp_path):
    rc, rules = _clock_gate(_cts_project(tmp_path, DROPPED))
    assert rc == 1 and "CTS_CLOCK_MISSING" in rules
    assert "['clk2']" in rules["CTS_CLOCK_MISSING"]
    assert f"{CTS_STEP}/openroad-cts.log" in rules["CTS_CLOCK_MISSING"]


@pytest.mark.parametrize("break_it,why", [
    ("report", "is not the bytes"),
    ("tool_rpt", "no longer is"),
    ("log", "is absent"),
    ("receipt", "unreadable"),
])
def test_an_unbound_transcript_is_never_read_and_fails_closed(tmp_path, break_it, why):
    p = _cts_project(tmp_path, SEEN)
    if break_it == "report":
        r = p / "phase3/stage3/cts/clock_tree.rpt"
        r.write_text(r.read_text() + "\n")
    elif break_it == "tool_rpt":
        t = p / CTS_STEP / "cts.rpt"
        t.write_text(t.read_text() + "\n")
    elif break_it == "log":
        (p / CTS_STEP / "openroad-cts.log").unlink()
    else:
        (p / "reports/phase3/librelane_cts_hold_handoff.json").write_text("{")
    rc, rules = _clock_gate(p)
    assert rc == 1 and "CTS_CLOCK_MISSING" in rules
    assert why in rules["CTS_CLOCK_MISSING"]
    assert "phase3/stage3/cts/clock_tree.rpt" in rules["CTS_CLOCK_MISSING"]


def test_without_a_receipt_the_report_is_the_transcript(tmp_path):
    """The direct path is unchanged: its clock_tree.rpt carries the CTS lines
    itself, and no receipt means that file is read as it is."""
    p = _cts_project(tmp_path, SEEN)
    (p / "reports/phase3/librelane_cts_hold_handoff.json").unlink()
    rc, rules = _clock_gate(p)
    assert rc == 1 and "CTS_CLOCK_MISSING" in rules
    shutil.copyfile(CAL / "cts_clock_roots_seen_negative.log",
                    p / "phase3/stage3/cts/clock_tree.rpt")
    rc, rules = _clock_gate(p)
    assert rc == 0 and "phase3/stage3/cts/clock_tree.rpt" in rules["CTS_CLOCKS_SEEN"]
