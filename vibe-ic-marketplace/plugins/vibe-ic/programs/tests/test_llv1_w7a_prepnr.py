"""llv1 W7a: pre-PnR preparation pulled out of `step_pnr`.

The extraction is a refactor for the default flow and a hook for the flag:
the default flow must stay byte-identical, and the between-segments step must
run the SAME code the default flow runs. Contracts:
  1. `step_pad_assignment` runs `pad_assignment_gen` exactly as the first
     program of `step_pad_ring_gen` (same program, same PDK arguments, the
     same rc reading), and `step_pad_ring_gen` still runs its four programs
     in order through the same `_run_pad_program`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _r():
    import phase3_one_shot_runner as r
    return r


@pytest.fixture
def calls(monkeypatch):
    """Capture the real container command each pad program is launched with."""
    r = _r()
    seen = []
    rcs = {}
    monkeypatch.setattr(r, "_padring_pdk_root_and_tree",
                        lambda pdk, container: ("/pdkroot", "/pdkroot/tree"))
    monkeypatch.setattr(r, "_to_container_path", lambda path, c: str(path))

    def _exec(container, cmd, marker=None):
        name = Path(marker).name
        seen.append((name, cmd))
        return rcs.get(name, 0), "", ""

    monkeypatch.setattr(r, "_docker_exec", _exec)
    return SimpleNamespace(seen=seen, rc=rcs)


def test_pad_assignment_runs_what_the_ring_step_runs_first(tmp_path, calls):
    r = _r()
    pdk = SimpleNamespace(tech_lef=None)
    r.step_pad_ring_gen(tmp_path, container="c", pdk=pdk)
    ring_first = calls.seen[0]
    assert [n for n, _ in calls.seen] == [
        "pad_assignment_gen.py", "pad_ring_gen.py", "pad_ring_check.py"]
    calls.seen.clear()
    r.step_pad_assignment(tmp_path, container="c", pdk=pdk)
    assert calls.seen == [ring_first]            # the identical command line
    assert ring_first[1].endswith(
        f"{tmp_path} --pdk-root /pdkroot --pdk /pdkroot/tree")


@pytest.mark.parametrize("rc,status,reason", [
    (0, "PASS", ""), (1, "FAIL", ""), (2, "NOT_MEASURED", "not_executed"),
    (127, "NOT_MEASURED", "tool_absent")])
def test_pad_assignment_reads_rc_like_the_ring_step(tmp_path, calls, rc,
                                                    status, reason):
    r = _r()
    calls.rc["pad_assignment_gen.py"] = rc
    rep = tmp_path / "reports" / "phase3" / "pad_assignment.json"
    rep.parent.mkdir(parents=True)
    rep.write_text("{}")
    got = r.step_pad_assignment(tmp_path, container="c", pdk=None)
    assert (got.status, got.reason_class) == (status, reason)
    if rc == 1:
        # (For rc 2 and others the ring step itself raises: it computes a
        # reason class and never passes it to StepResult -- a pre-existing
        # defect of the default flow, left as it is by this refactor.)
        ring = r.step_pad_ring_gen(tmp_path, container="c", pdk=None)
        assert ring.status == status


def test_pad_assignment_rc0_without_its_report_is_a_fail(tmp_path, calls):
    got = _r().step_pad_assignment(tmp_path, container="c", pdk=None)
    assert got.status == "FAIL" and "is absent" in got.detail


# ── 4/4: the between-segments step ──────────────────────────────────────────

import ast  # noqa: E402

RUNNER = PROGRAMS / "phase3_one_shot_runner.py"


def _fn_src(name):
    src = RUNNER.read_text()
    tree = ast.parse(src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


@pytest.fixture
def staged(monkeypatch, tmp_path):
    """step_prepnr with each piece it calls recorded, in order."""
    r = _r()
    order = []
    nl = tmp_path / "phase2" / "stage2" / "synth" / "top_synth.v"
    nl.parent.mkdir(parents=True)
    nl.write_text("module top(); endmodule\n")
    monkeypatch.setattr(r, "pnr_input_netlist", lambda p, t: (nl, "n", False))

    def _padring(project, container, pdk, supply_plan=None):
        order.append("chip_top")
        return r.StepResult("io_pad_chip_top_gen", state.chip_top, 0.0, "ct",
                            reason_class=state.chip_top_reason)

    def _assign(project, container, pdk):
        order.append("pad_assignment")
        return r.StepResult("pad_assignment", state.assign, 0.0, "a")

    def _floorplan(project, top, pdk, container, die_um, util, netlist, t0):
        order.append("floorplan")
        if state.fp_fail:
            return r.StepResult("pnr", "FAIL", 0.0, "PDN_CORE_TOO_SMALL: x")
        return r.PrePnrDieCore(
            die_um="100x100", die_w=100, die_h=100, core_pad=10, core_w=80,
            core_h=80, fp_rect=None, util=0.4, auto_die_requested=True,
            l9_die_note="", ring_floor_pad=10, ring_inset=None,
            ring_pinned_die=False, seal_rec={}, slot=None,
            strap_floor_detail={}, strap_floor_um=None, ct03_pin_rect=None)

    state = SimpleNamespace(assign="PASS", fp_fail=False, ring=True,
                            chip_top="PASS", chip_top_reason="")
    # The seam's LOCAL record check is what these tests exercise, as they were
    # written before FXPORT's reader existed. With FX_STEP7_ASIC_SDC in the
    # tree `read_step7_asic_sdc` is present, so it is removed here; a test of
    # the delegation installs its own reader, and the real reader's handover
    # is exercised in test_step7_asic_sdc_is_authored_once_at_step7.py.
    from _ppa import timing as _timing
    monkeypatch.delattr(_timing, "read_step7_asic_sdc", raising=False)
    monkeypatch.setattr(r, "set_invocation_provenance_sink",
                        lambda p: order.append("provenance_sink"))
    monkeypatch.setattr(r, "_padring_producer_dispatch", _padring)
    monkeypatch.setattr(r, "step_pad_assignment", _assign)
    monkeypatch.setattr(r, "_prepnr_floorplan", _floorplan)
    monkeypatch.setattr(r, "_chip_path_requests_pad_ring",
                        lambda p: state.ring)
    return SimpleNamespace(r=r, order=order, state=state, project=tmp_path)


def _run(st):
    return st.r.step_prepnr(st.project, "top", SimpleNamespace(name="gf180mcuD"),
                            "c", "auto", 0.4)


def _step7_record(project, *, name="top.asic.sdc", top="top",
                  pdk="gf180mcuD", text="create_clock -period 10 [get_ports clk]\n",
                  path=None, **extra):
    import hashlib
    import json
    d = project / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    (d / "asic_sdc.json").write_text(json.dumps({
        "schema": "vibe-ic/step7-asic-sdc/1", "step": 7, "top": top,
        "pdk": pdk, "path": path or f"phase2/stage2/constraints/{name}",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        **extra}))
    return d / name


def test_prepnr_runs_the_pieces_in_step_pnrs_order(staged):
    """step_pnr's order: the provenance sink, the chip-top producer, the die
    and its record, then the pad-ring work (whose first program is the
    assignment) -- review wave8 caught the assignment ahead of the floorplan."""
    res = _run(staged)
    assert staged.order == ["provenance_sink", "chip_top", "floorplan",
                            "pad_assignment"]
    assert res.status == "NOT_MEASURED"                  # no step-7 SDC yet
    assert "SDC_SEAM_PENDING" in res.detail
    assert res.extras["floorplan"]["die_w"] == 100
    # it AUTHORS no SDC: nothing named constraint.sdc appears anywhere
    assert not list(staged.project.rglob("constraint.sdc"))


def test_prepnr_reads_step_7s_sdc_by_its_record(staged):
    sdc = _step7_record(staged.project)
    res = _run(staged)
    assert res.status == "PASS"
    assert res.extras["sdc"]["path"] == str(sdc)
    assert sdc.read_text() == "create_clock -period 10 [get_ports clk]\n"


def test_a_canonicalized_copy_without_a_record_is_not_step_7s(staged):
    """Review wave8 MAJOR: on main, constraints/<top>.sdc is also the copy
    step_canonicalize_artefacts makes of step_pnr's own constraint.sdc -- a
    previous run's deck. Its presence proves nothing."""
    d = staged.project / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True)
    (d / "top.sdc").write_text("create_clock -period 20 [get_ports clk]\n")
    res = _run(staged)
    assert res.status == "NOT_MEASURED" and res.extras["sdc"]["path"] is None
    assert "SDC_SEAM_PENDING" in res.detail


@pytest.mark.parametrize("damage", ["sha", "top", "pdk", "schema", "absent"])
def test_a_step7_record_that_does_not_hold_is_pending(staged, damage):
    import json
    sdc = _step7_record(staged.project,
                        top="other" if damage == "top" else "top",
                        pdk="sky130A" if damage == "pdk" else "gf180mcuD")
    rec = sdc.parent / "asic_sdc.json"
    if damage == "sha":
        sdc.write_text(sdc.read_text() + "# edited\n")
    if damage == "schema":
        rec.write_text(json.dumps({**json.loads(rec.read_text()),
                                   "schema": "x"}))
    if damage == "absent":
        sdc.unlink()
    res = _run(staged)
    assert res.status == "NOT_MEASURED" and "SDC_SEAM_PENDING" in res.detail


@pytest.mark.parametrize("digest_key", ["input_digest", "asic_sdc_input_digest"])
def test_fallback_refuses_an_unverified_step7_input_digest(staged, monkeypatch,
                                                           digest_key):
    from _ppa import timing
    monkeypatch.delattr(timing, "read_step7_asic_sdc", raising=False)
    _step7_record(staged.project, **{digest_key: "0000stale"})
    res = _run(staged)
    assert res.status == "NOT_MEASURED"
    assert res.extras["sdc"]["path"] is None
    assert "SDC_SEAM_PENDING" in res.detail


@pytest.mark.parametrize("unsafe_path", [
    "absolute", "traversal", "sibling", "noncanonical", "symlink",
])
def test_step7_sdc_path_must_be_canonical_and_inside_constraints(
        staged, monkeypatch, unsafe_path):
    from _ppa import timing
    monkeypatch.delattr(timing, "read_step7_asic_sdc", raising=False)
    sdc = _step7_record(staged.project)
    if unsafe_path == "absolute":
        outside = staged.project.parent / f"{staged.project.name}-outside.sdc"
        outside.write_text(sdc.read_text())
        path = str(outside)
    elif unsafe_path == "traversal":
        path = "phase2/stage2/constraints/../top.asic.sdc"
        (sdc.parent.parent / sdc.name).write_text(sdc.read_text())
    elif unsafe_path == "sibling":
        path = "phase2/stage2/top.asic.sdc"
        (sdc.parent.parent / sdc.name).write_text(sdc.read_text())
    elif unsafe_path == "noncanonical":
        path = "phase2/stage2/constraints/./top.asic.sdc"
    else:
        outside = staged.project.parent / f"{staged.project.name}-outside.sdc"
        outside.write_text(sdc.read_text())
        sdc.unlink()
        sdc.symlink_to(outside)
        path = "phase2/stage2/constraints/top.asic.sdc"
    import json
    rec = sdc.parent / "asic_sdc.json"
    rec.write_text(json.dumps({**json.loads(rec.read_text()), "path": path}))
    res = _run(staged)
    assert res.status == "NOT_MEASURED"
    assert res.extras["sdc"]["path"] is None
    assert "SDC_SEAM_PENDING" in res.detail


def test_a_failed_chip_top_stops_a_ring_path(staged):
    """Review wave8 MAJOR: the producer's verdict is the step's when the chip
    path requests a ring, as step_pnr's pad-ring gate makes it."""
    status, reason = "FAIL", ""
    staged.state.chip_top, staged.state.chip_top_reason = status, reason
    _step7_record(staged.project)
    res = _run(staged)
    assert (res.status, res.reason_class) == (status, reason)
    assert staged.order == ["provenance_sink", "chip_top"]
    staged.order.clear()
    staged.state.ring = False                  # no ring requested: not a gate
    assert _run(staged).status == "PASS"


def test_a_nonmeasured_chip_top_keeps_later_failures_visible(staged):
    """Wave9 MAJOR: only a plain producer FAIL may stop before floorplan.

    The producer is unavailable, but the floorplan itself can still prove the
    pinned die is too small. Replacing the `== FAIL` gate with `!= PASS`
    makes this red by returning NOT_MEASURED before the floorplan dispatch.
    """
    staged.state.chip_top, staged.state.chip_top_reason = (
        "NOT_MEASURED", "not_executed")
    staged.state.fp_fail = True
    _step7_record(staged.project)
    res = _run(staged)
    assert res.status == "FAIL" and "PDN_CORE_TOO_SMALL" in res.detail
    assert staged.order == ["provenance_sink", "chip_top", "floorplan"]


def test_a_nonmeasured_chip_top_cannot_turn_a_clean_ring_path_pass(staged):
    staged.state.chip_top, staged.state.chip_top_reason = (
        "NOT_MEASURED", "not_executed")
    _step7_record(staged.project)
    res = _run(staged)
    assert (res.status, res.reason_class) == ("NOT_MEASURED", "not_executed")
    assert staged.order == ["provenance_sink", "chip_top", "floorplan",
                            "pad_assignment"]


def test_the_seam_delegates_to_fxports_input_bound_reader(staged, monkeypatch):
    """Wave9 MINOR: the FXPORT handover is executable, not a docstring.

    This is red on the reviewed tip: it ignores the available reader, falls
    through to its local record check, and reports the absent local record.
    """
    from _ppa import timing
    sdc = staged.project / "phase2" / "stage2" / "constraints" / "from_fxport.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -period 8 [get_ports clk]\n")
    calls = []

    def reader(rt, project, top, pdk):
        calls.append((rt, project, top, pdk.name))
        return {"path": "phase2/stage2/constraints/from_fxport.sdc"}, ""

    monkeypatch.setattr(timing, "read_step7_asic_sdc", reader,
                        raising=False)
    res = _run(staged)
    assert res.status == "PASS"
    assert res.extras["sdc"]["path"] == str(sdc)
    assert calls and calls[0][1:] == (staged.project, "top", "gf180mcuD")


def test_fxport_reader_refusal_keeps_stale_inputs_pending(staged, monkeypatch):
    from _ppa import timing
    _step7_record(staged.project, input_digest="0000stale")
    calls = []

    def reader(rt, project, top, pdk):
        calls.append((project, top, pdk.name))
        return None, "the step-7 SDC's inputs changed since step 7"

    monkeypatch.setattr(timing, "read_step7_asic_sdc", reader,
                        raising=False)
    res = _run(staged)
    assert calls == [(staged.project, "top", "gf180mcuD")]
    assert res.status == "NOT_MEASURED"
    assert res.extras["sdc"]["path"] is None
    assert "inputs changed since step 7" in res.detail


def test_fxport_reader_does_not_read_an_outside_record_path(staged, monkeypatch):
    from _ppa import timing
    sdc = _step7_record(staged.project)
    outside = staged.project.parent / f"{staged.project.name}-outside.sdc"
    outside.write_text(sdc.read_text())
    import json
    rec = sdc.parent / "asic_sdc.json"
    rec.write_text(json.dumps({**json.loads(rec.read_text()),
                               "path": str(outside)}))
    calls = []

    def reader(*args):
        calls.append(args)
        return {"path": str(outside)}, ""

    monkeypatch.setattr(timing, "read_step7_asic_sdc", reader, raising=False)
    res = _run(staged)
    assert calls == []
    assert res.status == "NOT_MEASURED"
    assert res.extras["sdc"]["path"] is None
    assert "SDC_SEAM_PENDING" in res.detail


def test_prepnr_refusals_stop_it(staged):
    staged.state.assign = "FAIL"
    assert _run(staged).status == "FAIL"
    assert staged.order == ["provenance_sink", "chip_top", "floorplan",
                            "pad_assignment"]
    staged.order.clear()
    staged.state.assign, staged.state.fp_fail = "PASS", True
    res = _run(staged)
    assert res.status == "FAIL" and "PDN_CORE_TOO_SMALL" in res.detail
    assert staged.order == ["provenance_sink", "chip_top", "floorplan"]
    staged.order.clear()
    staged.state.fp_fail, staged.state.ring = False, False
    _run(staged)
    assert staged.order == ["provenance_sink", "chip_top", "floorplan"]


def test_the_default_flow_and_the_step_run_the_same_code():
    pnr, prep = _fn_src("step_pnr"), _fn_src("step_prepnr")
    for call in ("_padring_producer_dispatch(", "_prepnr_floorplan("):
        assert pnr.count(call) == 1 and prep.count(call) == 1, call
    assert "constraint.sdc" not in prep
    assert "_floorplan_rectangles_record(" in _fn_src("_prepnr_floorplan")
    assert "_prepnr_geometry(" in _fn_src("_prepnr_floorplan")
    assert "_floorplan_rectangles_record(" not in pnr.split(
        "_prep_dc = _prepnr_floorplan(")[0]
