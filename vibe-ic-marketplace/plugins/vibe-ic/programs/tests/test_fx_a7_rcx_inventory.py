"""A7 compares a layout with the netlist it was DRAWN from, or says it cannot.

MEASURED (lane rfa7, delta_sigma on ihp-sg13g2, vibeic-eda 0.3.83): the A7 tool
arm ended `A7_RCX_DEVICE_INVENTORY_MISMATCH` -- cap_cmim (w, l) multiset A3=23
extracted=78, nmos/pmos sum(w*m) short. Nothing was wrong with the counting or
the extraction: the SAME extracted netlist compared with the netlist A5 had
actually drawn (its `layout_provenance.json` `netlist`, 360 devices) is a
device-for-device MATCH. The layout (09-15) was simply older than the A3
netlist it was being compared with (re-emitted 09-16, 335 devices): a stale
layout reported as a layout that had lost devices, after a ~3 h pre-layout
simulation that could not have produced a comparison.

The rule now: A5 records the netlist's content digest; A7 checks, before it
extracts or simulates anything, that the layout is a layout of the current
netlist -- by A5's successful draw record and content digest. An older
record's path can expose a mismatch, but cannot prove a match because A3 may
rewrite that path. A layout of a different netlist is refused by name
(`A7_LAYOUT_NOT_OF_THIS_NETLIST`, the honest-gap tier: A7's input -- a layout
of THIS netlist -- is not on disk). An identity that cannot be established is
recorded as UNVERIFIED and leaves A7 NOT_MEASURED until a match is proved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _analog_producer_common as PC
import analog_a7_post_layout_emit as A7
from test_analog_a7_post_layout_emit import (  # noqa: E402,F401
    IMAGE, RCX_RC, _project, _rcx, _stated_identity, stub)

#: The netlist the layout was drawn from: `_project`'s block plus one device.
#: The extraction (`RCX_RC`) is of the CURRENT netlist's device set, so what
#: is compared here is identity alone.
DRAWN = (".lib ../../../models/m.lib tt\n.subckt blk a b vss\n"
         "X0 a b vss vss nfet w=1u l=1u\nX1 a b vss vss nfet w=2u l=1u\n"
         ".ends blk\n")


#: What Magic extracts from a layout of `DRAWN`: `RCX_RC` plus the extra
#: device -- a faithful extraction of the layout that is actually on disk.
RCX_DRAWN = RCX_RC.replace(
    "R0 a a.n1 12.5", "X1 a b vss vss nfet w=2u l=1u\nR0 a a.n1 12.5")


def _provenance(project: Path, **extra) -> None:
    p = project / "phase3/analog/blk/layout_provenance.json"
    doc = json.loads(p.read_text())
    doc.update(extra)
    p.write_text(json.dumps(doc))


def _record(project: Path) -> dict:
    return json.loads(
        (project / "phase3/analog/blk/a7_post_layout.json").read_text())


def test_a_layout_of_another_netlist_is_refused_by_name_before_any_run(stub):
    """The reported shape: the extraction is faithful to the layout on disk,
    and that layout is of a netlist A3 has since replaced. On main this ran
    the pre-layout simulation and then refused
    A7_RCX_DEVICE_INVENTORY_MISMATCH -- a stale layout named as one that lost
    or gained devices."""
    project = _project(stub)
    _rcx(stub, RCX_DRAWN)
    _provenance(project, netlist_content_sha256=PC.content_digest(DRAWN))
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 2
    rec = _record(project)
    assert rec.get("rule") == "A7_LAYOUT_NOT_OF_THIS_NETLIST", rec.get("rule")
    assert (rec.get("layout_netlist_identity") or {}).get("state") == "STALE"
    # nothing was extracted and nothing was simulated
    assert "pre" not in rec and "corners" not in rec


def test_an_older_record_is_checked_by_the_netlist_path_it_names(stub):
    project = _project(stub)
    _rcx(stub, RCX_DRAWN)
    drawn = stub / "elsewhere" / "blk.sp"
    drawn.parent.mkdir()
    drawn.write_text(DRAWN)
    _provenance(project, netlist_content_sha256="", netlist=str(drawn))
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 2
    assert _record(project).get("rule") == "A7_LAYOUT_NOT_OF_THIS_NETLIST"


def test_a_layout_of_this_netlist_goes_ahead(stub):
    project = _project(stub)
    _rcx(stub, RCX_RC)
    sp = project / "phase3/analog/blk/blk.sp"
    body = sp.read_text()
    # a provenance comment is not content: the netlist on disk and the one A5
    # drew differ ONLY in their provenance stamp, as a byte-identical
    # re-emission of A3 does
    sp.write_text("* _provenance: emitted at run B\n" + body)
    _provenance(project, netlist_content_sha256=PC.content_digest(
        "* _provenance: emitted at run A\n" + body))
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 0
    assert (_record(project).get("layout_netlist_identity") or {}).get(
        "state") == "MATCH"


def test_an_unverified_identity_cannot_certify_a7(stub):
    project = _project(stub)
    _rcx(stub, RCX_RC)
    _provenance(project, netlist_content_sha256="",
                netlist=str(stub / "gone" / "blk.sp"))
    assert A7.run(project, "blk", "vibeic-eda", IMAGE) == 2
    rec = _record(project)
    assert rec.get("layout_netlist_identity", {}).get("state") == "UNVERIFIED"
    assert rec.get("rule") == "A7_LAYOUT_IDENTITY_UNVERIFIED"
    assert rec.get("result") == "NOT_PRODUCED"
    assert "pre" not in rec and "corners" not in rec


def test_a_mutable_legacy_path_is_not_identity_proof(stub):
    project = _project(stub)
    _rcx(stub, RCX_RC)
    current = project / "phase3/analog/blk/blk.sp"
    _provenance(project, netlist_content_sha256="", netlist=str(current))
    rc = A7.run(project, "blk", "vibeic-eda", IMAGE)
    rec = _record(project)
    assert (rc, rec.get("layout_netlist_identity", {}).get("state"),
            rec.get("rule"), rec.get("result")) == (
                2, "UNVERIFIED", "A7_LAYOUT_IDENTITY_UNVERIFIED",
                "NOT_PRODUCED")
    assert "pre" not in rec and "corners" not in rec


# ── A5 hands the identity over ─────────────────────────────────────────────
def test_a5_records_the_content_digest_of_the_netlist_it_draws(
        tmp_path, monkeypatch):
    import test_analog_a5_layout_emit as T5
    project = T5._project(tmp_path, T5.LEGAL_NARROW)
    T5._run(monkeypatch, project, T5.FakeStage())
    prov = json.loads((project / "phase3/analog/blk/layout_provenance.json")
                      .read_text())
    assert prov.get("netlist_content_sha256") == \
        PC.content_digest(T5.LEGAL_NARROW)


# ── A6 gets the same contract (ADC_A5_A7_E2E item 1) ──────────────────────
import subprocess  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))
_NET = ".subckt ldo vdd vss\nX0 vdd vss vss vss nfet w=1u l=1u\n.ends ldo\n"
_NET_OLD = _NET.replace("w=1u", "w=2u")


def _a6_block(tmp_path: Path, drawn: str, *, comp_says: str = "match",
              **prov) -> Path:
    p = tmp_path / "proj"
    b = p / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True)
    (p / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["ldo"]}))
    (b / "ldo.sp").write_text(_NET)
    (b / "ldo.gds").write_bytes(b"\x00" * 64)
    (b / "drc.report").write_text("Total DRC errors: 0\n")
    # an LVS verdict left from a run of the layout's OWN (earlier) netlist
    (b / "comp.json").write_text(json.dumps({"result": comp_says}))
    (b / "layout_provenance.json").write_text(json.dumps(
        {"producer": "analog_a5_layout_emit",
         **({"netlist_content_sha256": PC.content_digest(drawn)}
            if drawn is not None else {}), **prov}))
    return p


def _a6_gate(project: Path) -> tuple:
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "analog_a6_block_pv_check.py"),
         str(project), "--json", str(project / "a6.json")],
        capture_output=True, text=True)
    return cp.returncode, json.loads((project / "a6.json").read_text())


def _rules(rpt: dict) -> list:
    return sorted({f.get("rule") for f in rpt.get("findings", [])})


def test_a6_refuses_an_lvs_verdict_about_a_layout_of_another_netlist(
        tmp_path):
    """MEASURED on the delta_sigma copy: comp.json `match` (source_devices
    360, the netlist A5 drew) PASSed A6 against the current 335-device
    netlist."""
    project = _a6_block(tmp_path, _NET_OLD)
    rc, rpt = _a6_gate(project)
    assert rc != 0
    assert "A6_LAYOUT_NOT_OF_THIS_NETLIST" in _rules(rpt), rpt


def test_a6_passes_a_layout_of_this_netlist(tmp_path):
    project = _a6_block(tmp_path, "* _provenance: other stamp\n" + _NET)
    rc, rpt = _a6_gate(project)
    assert rc == 0, rpt
    assert "A6_LAYOUT_NOT_OF_THIS_NETLIST" not in _rules(rpt)


def test_a6_an_unverifiable_identity_does_not_block(tmp_path):
    project = _a6_block(tmp_path, None, netlist=str(tmp_path / "gone.sp"))
    rc, rpt = _a6_gate(project)
    assert rc == 0, rpt


def test_a6_does_not_run_lvs_on_a_layout_of_another_netlist(tmp_path):
    import analog_a6_native_pv as PV
    project = _a6_block(tmp_path, _NET_OLD)
    called = []
    res = PV.run_block_pv(
        project, "ldo", {"drc_deck": None, "lvs_deck": str(tmp_path / "x.lvs")},
        lvs_runner=lambda *a: (called.append(1), ("MATCH", {}))[1])
    assert called == []
    assert (res["lvs"] or {}).get("rule") == "A6_LAYOUT_NOT_OF_THIS_NETLIST"
    comp = json.loads(
        (project / "phase3/analog/ldo/comp.json").read_text())
    assert comp["result"] == "refused"


# ── the runner redraws a stale layout before A5 grades it ─────────────────
def _a5_calls(tmp_path, monkeypatch, drawn: str) -> list:
    import _eda_pin as PIN
    import analog_one_shot_runner as R
    project = _a6_block(tmp_path, drawn)
    calls = []
    real_run = R._pr.run

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a5_layout_emit.py") for x in cmd):
            calls.append("emit")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(R._pr, "run", fake_run)
    monkeypatch.setattr(R._pin, "container_image_digest",
                        lambda c: (PIN.IMAGE_DIGEST, ""))
    R.step_for_block(project, {"name": "ldo", "type": "ldo"}, "A5_layout",
                     None)
    return calls


def test_the_runner_redraws_a_layout_of_another_netlist(tmp_path,
                                                        monkeypatch):
    """MEASURED: the A5 step graded the 09-15 layout of the old netlist, the
    gate passed its geometry, and the emitter -- which ran only when the
    layout was MISSING -- never redrew it."""
    assert _a5_calls(tmp_path, monkeypatch, _NET_OLD)[:1] == ["emit"]


def test_the_runner_keeps_a_layout_of_this_netlist(tmp_path, monkeypatch):
    assert "emit" not in _a5_calls(tmp_path, monkeypatch, _NET)


def test_first_a5_draw_uses_the_same_run_pdk(tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    import analog_pdk_availability as APA
    import test_analog_a5_layout_emit as T5
    project = T5._runner_project(tmp_path)
    layout = project / "phase3/analog/b/layout.mag"
    ran = T5._Ran(layout=layout,
                  writes=lambda: layout.write_text("magic\nuse c i\n"))
    monkeypatch.setattr(R, "_pr", ran)
    def resolve(target, **kwargs):
        assert target == "gf180mcuD"
        assert kwargs == {"project": None, "container": "vibeic-eda"}
        return {"available": True, "source": "container_installed",
                "rung": 2, "matched_dir": "gf180mcuD",
                "pdk_root": "/foundry/gf180mcuD"}

    monkeypatch.setattr(APA, "resolve_pdk", resolve)
    res = R.step_for_block(
        project, {"name": "b"}, "A5_layout",
        SimpleNamespace(pdk="gf180mcuD", container="vibeic-eda"))
    argv = next(a for a in ran.argv
                if Path(a[1]).name == "analog_a5_layout_emit.py")
    family = (argv[argv.index("--family") + 1]
              if "--family" in argv else "<emitter default>")
    assert family == "gf180mcuD", (family, res.status)
    assert argv[argv.index("--pdk-root") + 1] == "/foundry"
    assert res.status == "PASS"


def test_a_named_but_unresolvable_pdk_does_not_draw_in_a_default_family(
        tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    import analog_pdk_availability as APA
    import test_analog_a5_layout_emit as T5
    project = T5._runner_project(tmp_path)
    layout = project / "phase3/analog/b/layout.mag"
    ran = T5._Ran(layout=layout,
                  writes=lambda: layout.write_text("wrong process\n"))
    monkeypatch.setattr(R, "_pr", ran)
    monkeypatch.setattr(APA, "resolve_pdk", lambda *a, **k: {
        "available": False, "reason": "selected PDK not installed"})
    res = R.step_for_block(
        project, {"name": "b"}, "A5_layout",
        SimpleNamespace(pdk="custom_process", container="vibeic-eda"))
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == \
        "tool_absent"
    assert "custom_process" in res.detail
    assert not layout.exists()
    assert not any(Path(a[1]).name == "analog_a5_layout_emit.py"
                   for a in ran.argv)


@pytest.mark.parametrize("rc,emitter_result,expected,reason_class", [
    (1, "FORBIDDEN", "FAIL", ""),
    (2, "ENV_UNAVAILABLE", "NOT_MEASURED", "tool_absent"),
    (3, "REFUSED", "FAIL", ""),
    (3, "TOOL_ERROR", "FAIL", ""),
])
def test_stale_redraw_preserves_emitter_outcome_tier(
        tmp_path, monkeypatch, rc, emitter_result, expected, reason_class):
    import analog_one_shot_runner as R
    import analog_pdk_availability as APA
    project = _a6_block(tmp_path, _NET_OLD)
    bdir = project / "phase3/analog/ldo"
    monkeypatch.setattr(APA, "resolve_pdk", lambda *a, **k: {
        "available": True, "source": "container_installed", "rung": 2,
        "matched_dir": "gf180mcuD", "pdk_root": "/foundry/gf180mcuD"})

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a5_layout_emit.py") for x in cmd):
            report = {"result": emitter_result,
                      "reason": f"{emitter_result}: magic could not draw ldo"}
            if rc == 2:
                # The real emitter exits before its per-block loop when the
                # environment is unavailable; old layout provenance remains.
                return subprocess.CompletedProcess(cmd, rc,
                                                   json.dumps(report), "")
            (bdir / "layout_provenance.json").write_text(json.dumps(
                {"block": "ldo", **report}))
            return subprocess.CompletedProcess(cmd, rc, "", "")
        raise AssertionError(f"redraw failure should stop before gate: {cmd}")

    monkeypatch.setattr(R._pr, "run", fake_run)
    res = R.step_for_block(
        project, {"name": "ldo", "type": "ldo"}, "A5_layout",
        SimpleNamespace(pdk="gf180mcuD", container="vibeic-eda"))
    assert res.status == expected, (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == reason_class
    assert res.extras["layout_redrawn"]["emitter_rc"] == rc
    assert res.extras["verdict_tier"] == emitter_result
    assert emitter_result in res.detail


@pytest.mark.parametrize("wrong_block_record", [False, True])
def test_stale_redraw_crash_cannot_reuse_previous_refusal(
        tmp_path, monkeypatch, wrong_block_record):
    import analog_one_shot_runner as R
    import analog_pdk_availability as APA
    project = _a6_block(
        tmp_path, _NET_OLD, block="ldo", result="REFUSED",
        reason="old width violation")
    bdir = project / "phase3/analog/ldo"
    monkeypatch.setattr(APA, "resolve_pdk", lambda *a, **k: {
        "available": True, "source": "container_installed", "rung": 2,
        "matched_dir": "gf180mcuD", "pdk_root": "/foundry/gf180mcuD"})

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a5_layout_emit.py") for x in cmd):
            if wrong_block_record:
                (bdir / "layout_provenance.json").write_text(json.dumps({
                    "block": "other", "result": "REFUSED",
                    "reason": "wrong block width violation"}))
            return subprocess.CompletedProcess(cmd, 1, "", "emitter crashed")
        raise AssertionError(f"crashed redraw must stop before gate: {cmd}")

    monkeypatch.setattr(R._pr, "run", fake_run)
    res = R.step_for_block(
        project, {"name": "ldo", "type": "ldo"}, "A5_layout",
        SimpleNamespace(pdk="gf180mcuD", container="vibeic-eda"))
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == \
        "execution_error"
    assert res.extras["verdict_tier"] == "rc 1"
    assert "width violation" not in res.detail


@pytest.mark.parametrize("rc,emitter_result,expected,reason_class", [
    (1, "FORBIDDEN", "FAIL", ""),
    (1, "SHORTED", "FAIL", ""),
    (1, "CLAMPED_GEOMETRY", "FAIL", ""),
    (3, "REFUSED", "FAIL", ""),
    (3, "TOOL_ERROR", "FAIL", ""),
    (3, "NO_GENCELL", "FAIL", ""),
    (3, "UNREADABLE_NETLIST", "FAIL", ""),
    (2, "ENV_UNAVAILABLE", "NOT_MEASURED", "tool_absent"),
])
def test_first_draw_preserves_emitter_outcome_tier(
        tmp_path, monkeypatch, rc, emitter_result, expected, reason_class):
    import analog_one_shot_runner as R
    import test_analog_a5_layout_emit as T5
    project = T5._runner_project(tmp_path)
    layout = project / "phase3/analog/b/layout.mag"
    report = json.dumps({"result": "NOT_OK", "blocks": {
        "b": {"result": emitter_result,
              "reason": f"{emitter_result}: PDK geometry refusal"}}})
    if emitter_result != "ENV_UNAVAILABLE":
        report = f"LAYOUT: {emitter_result} [b] 0 deviation(s)\n" + report
    ran = T5._Ran(layout=layout, emit_rc=rc, emit_out=report)
    monkeypatch.setattr(R, "_pr", ran)
    res = R.step_for_block(project, {"name": "b"}, "A5_layout", None)
    assert res.status == expected, (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == reason_class
    assert res.extras["producer_rc"] == rc
    assert res.extras["verdict_tier"] == emitter_result
    assert emitter_result in res.detail
    assert not layout.exists()


def test_first_draw_refusal_cannot_pass_partial_geometry(tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    import test_analog_a5_layout_emit as T5
    project = T5._runner_project(tmp_path)
    layout = project / "phase3/analog/b/layout.mag"
    report = json.dumps({"result": "NOT_OK", "blocks": {
        "b": {"result": "FORBIDDEN", "reason": "PDK rejected geometry"}}})
    ran = T5._Ran(layout=layout, emit_rc=1, emit_out=report,
                  writes=lambda: layout.write_text("partial geometry\n"))
    monkeypatch.setattr(R, "_pr", ran)
    res = R.step_for_block(project, {"name": "b"}, "A5_layout", None)
    assert (res.status, res.extras["verdict_tier"], res.extras["producer_rc"]) == \
        ("FAIL", "FORBIDDEN", 1)
    assert sum(Path(a[1]).name == "analog_a5_layout_check.py"
               for a in ran.argv) == 1


def test_first_draw_does_not_reuse_an_old_refusal_record(tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    import test_analog_a5_layout_emit as T5
    project = T5._runner_project(tmp_path)
    bdir = project / "phase3/analog/b"
    (bdir / "layout_provenance.json").write_text(json.dumps({
        "block": "b", "result": "FORBIDDEN", "reason": "old attempt"}))
    layout = bdir / "layout.mag"
    ran = T5._Ran(layout=layout, emit_rc=2, emit_out="")
    monkeypatch.setattr(R, "_pr", ran)
    res = R.step_for_block(project, {"name": "b"}, "A5_layout", None)
    assert (res.status, str(getattr(res.reason_class, "value",
                            res.reason_class)), res.extras["verdict_tier"]) == \
        ("NOT_MEASURED", "execution_error", "rc 2")


@pytest.mark.parametrize("record_result,expected_tier,expected_reason", [
    ("OK", "USAGE_ERROR", "execution_error"),
    ("ENV_UNAVAILABLE", "USAGE_ERROR", "execution_error"),
])
def test_rc2_without_a_current_json_report_does_not_read_old_success_as_env(
        tmp_path, monkeypatch, record_result, expected_tier, expected_reason):
    import analog_one_shot_runner as R
    import analog_pdk_availability as APA
    project = _a6_block(tmp_path, _NET_OLD, result=record_result,
                        reason=f"{record_result}: previous A5 attempt")
    monkeypatch.setattr(APA, "resolve_pdk", lambda *a, **k: {
        "available": True, "source": "container_installed", "rung": 2,
        "matched_dir": "gf180mcuD", "pdk_root": "/foundry/gf180mcuD"})

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a5_layout_emit.py") for x in cmd):
            return subprocess.CompletedProcess(cmd, 2, "",
                                               "usage: emitter arg invalid")
        raise AssertionError(f"redraw failure should stop before gate: {cmd}")

    monkeypatch.setattr(R._pr, "run", fake_run)
    res = R.step_for_block(
        project, {"name": "ldo", "type": "ldo"}, "A5_layout",
        SimpleNamespace(pdk="gf180mcuD", container="vibeic-eda"))
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == \
        expected_reason
    assert res.extras["verdict_tier"] == expected_tier


# ── a redraw that fails leaves the layout STALE, and the A5 step says so ──
def test_a_failed_a5_record_does_not_vouch_for_the_layout_on_disk(tmp_path):
    """MEASURED: the gencell refused the current netlist, A5 rewrote its
    record (`result: TOOL_ERROR`, no netlist named) and the 09-15 layout
    stayed on disk; A6 then read the identity as unverifiable and ran LVS on
    the old layout."""
    project = _a6_block(tmp_path, None, result="TOOL_ERROR",
                        reason="magic did not reach A5_PROBE_OK")
    rc, rpt = _a6_gate(project)
    assert "A6_LAYOUT_NOT_OF_THIS_NETLIST" in _rules(rpt), rpt
    assert rc != 0


def test_the_a5_step_fails_when_the_needed_redraw_is_refused(
        tmp_path, monkeypatch):
    import _eda_pin as PIN
    import analog_one_shot_runner as R
    project = _a6_block(tmp_path, _NET_OLD)
    real_run = R._pr.run

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a5_layout_emit.py") for x in cmd):
            (project / "phase3/analog/ldo/layout_provenance.json").write_text(
                json.dumps({"block": "ldo", "result": "TOOL_ERROR",
                            "reason": "...\nError parsing \"a5probe.tcl\": "
                                      "cap_cmim: refused: length above the "
                                      "maximum"}))
            return subprocess.CompletedProcess(cmd, 3, "", "")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(R._pr, "run", fake_run)
    monkeypatch.setattr(R._pin, "container_image_digest",
                        lambda c: (PIN.IMAGE_DIGEST, ""))
    res = R.step_for_block(project, {"name": "ldo", "type": "ldo"},
                           "A5_layout", None)
    assert res.status == "FAIL", (res.status, res.detail)
    assert "A5_LAYOUT_NOT_REDRAWN" in res.detail
    assert "cap_cmim: refused" in res.detail


def test_an_a7_refusal_for_a_stale_layout_is_not_measured_not_waived(
        tmp_path, monkeypatch):
    """MEASURED on the delta_sigma copy: the producer refused
    A7_LAYOUT_NOT_OF_THIS_NETLIST (rc 2), the runner fell through to the
    skill hand-off, the gate WAIVED the missing comparison, and the step read
    PASS_WITH_WAIVERS."""
    import _eda_pin as PIN
    import analog_one_shot_runner as R
    project = _a6_block(tmp_path, _NET_OLD)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A7": "librelane"}}))
    real_run = R._pr.run

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a7_post_layout_emit.py") for x in cmd):
            return subprocess.CompletedProcess(
                cmd, 2, "", "HONEST_GAP: analog_a7_post_layout_emit "
                "A7_LAYOUT_NOT_OF_THIS_NETLIST: ldo.gds was drawn from a "
                "different netlist")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(R._pr, "run", fake_run)
    monkeypatch.setattr(R._pin, "container_image_digest",
                        lambda c: (PIN.IMAGE_DIGEST, ""))
    res = R.step_for_block(project, {"name": "ldo", "type": "ldo"},
                           "A7_post_layout_resim", None)
    assert res.status == "NOT_MEASURED", (res.status, res.detail)
    assert str(getattr(res.reason_class, "value", res.reason_class)) == \
        "input_absent"
    assert "A7_LAYOUT_NOT_OF_THIS_NETLIST" in res.detail
