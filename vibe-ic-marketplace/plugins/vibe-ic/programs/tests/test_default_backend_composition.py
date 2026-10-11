"""Shared enclosing caller controls; offline transport, never native evidence.

The cache cases belong to Ultra's retained enclosing caller. Default dispatches
current rows individually and does not enter those legacy caches.
"""
import json
from pathlib import Path

import pytest
import phase3_one_shot_runner as R
import librelane_contract as LL
from test_default_power_density import build, authority


class ReachedFollowingRow(Exception):
    """Stop after the real Step24/25 callsite, before unrelated rows."""


@pytest.mark.parametrize("subject", ["CURRENT_PARTIAL", "NATIVE_MISSING", "CSV_CHANGED", "AUTHORITY_CHANGED", "SDC_CHANGED"])
def test_ordinary_cache_caller_binds_current_ir_em_before_following_row(tmp_path, monkeypatch, subject):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    project, original_pdk, _ = build(tmp_path, monkeypatch, via=True)
    pdk = R.PdkConfig(name=original_pdk.name, liberty=original_pdk.liberty,
                      tech_lef=original_pdk.tech_lef, cell_lef=original_pdk.cell_lef,
                      cell_gds=None, site="unitSite", drc_deck=None, metal_prefix="wire")
    rpt = project / "reports/phase3"
    native = rpt / "em_openroad_density.json"
    if subject == "NATIVE_MISSING":
        native.unlink()
    elif subject in ("CSV_CHANGED", "AUTHORITY_CHANGED", "SDC_CHANGED"):
        path = {"CSV_CHANGED": rpt / "em_openroad_density_PWR.csv",
                "AUTHORITY_CHANGED": rpt / "em_native_authority.tlef",
                "SDC_CHANGED": R._pl.pnr_dir(project) / "constraint.sdc"}[subject]
        # Frozen shipping has no native density CSV; perturb its selected
        # authority instead so the shared caller still sees a changed value.
        if not path.exists():
            path = Path(original_pdk.tech_lef)
        path.write_text(path.read_text() + "\n# changed current input/output\n")
    predicate = getattr(R, "_step25_native_density_due", None)
    producer = R._emit_ir_em_reports
    transport = R._docker_exec
    observed = {"cache": "NO_CURRENT_BINDING_CHECK", "producer": "STALE_REUSED"}

    def admission(*args):
        due = predicate(*args) if predicate else True
        observed["cache"] = "REFRESH_REQUIRED" if due else "CURRENT_PARTIAL"
        return due

    def emit(*args, **kwargs):
        result = producer(*args, **kwargs)
        observed["producer"] = "REFRESHED"
        return result

    def only_owned_transport(container, cmd, **kwargs):
        return transport(container, cmd, **kwargs) if "ir_em_unit.tcl" in cmd else (1, "", "unrelated tool outside test scope")

    def following_row(*args, **kwargs):
        raise ReachedFollowingRow

    monkeypatch.setattr(R, "_step25_native_density_due", admission, raising=False)
    monkeypatch.setattr(R, "_emit_ir_em_reports", emit)
    monkeypatch.setattr(R, "_docker_exec", only_owned_transport)
    monkeypatch.setattr(R, "_docker_exec_raw", lambda *args, **kwargs: (1, "", "outside scope"))
    monkeypatch.setattr(R, "_discover_container_corner_libs", lambda *args: [])
    monkeypatch.setattr(R, "_signoff_regen", lambda path, *args: Path(path).name == "antenna.rpt")
    monkeypatch.setattr(R, "_emit_antenna_report", following_row)
    with pytest.raises(ReachedFollowingRow):
        R.step_canonicalize_artefacts(project, "unit", pdk, "offline")
    assert observed["cache"] == ("CURRENT_PARTIAL" if subject == "CURRENT_PARTIAL" else "REFRESH_REQUIRED"), observed
    assert observed["producer"] == ("STALE_REUSED" if subject == "CURRENT_PARTIAL" else "REFRESHED"), observed
    assert authority(project, pdk)[0] == "INCOMPLETE"
    assert not (project / "phase3/librelane_switch.json").exists()


def test_backend_defaults_preserve_frontend_and_current_step14_policy(tmp_path):
    assert LL.selected_mode(tmp_path, "2") == "librelane"
    assert LL.selected_mode(tmp_path, "3") == "librelane"
    assert LL.selected_mode(tmp_path, "24") == "direct"
    assert R._step24_primary_mode(tmp_path) == "librelane"
    assert LL.selected_mode(tmp_path, "25") == "direct"
    assert LL.selected_mode(tmp_path, "14") == "direct"
    switch = tmp_path / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text(json.dumps({"steps": {"24": "direct"}}))
    assert R._step24_primary_mode(tmp_path) == "direct"


@pytest.mark.parametrize("subject", ["CURRENT", "RECEIPT_MISSING", "COMPANION_CHANGED",
                                      "SPEF_CHANGED", "EXECUTION_MISSING"])
def test_ordinary_power_cache_admits_only_current_tool_adoption(tmp_path, monkeypatch, subject):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    from test_default_current_power import project as power_project, write, POWER
    project, folder, lib = power_project(tmp_path)
    pnr = R._pl.pnr_dir(project)
    write(pnr / "neutral.def", "VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n")
    write(pnr / "sta.rpt", "slack (MET) 1.0\n")
    report = project / "reports/phase3/power.rpt"
    pdk = R.PdkConfig("neutral", str(lib), "", "", None, "unitSite", None)
    # Seed a current adoption in the composed arm. Frozen main retains a
    # fresh scalar report, so this control observes its real cache decision.
    if getattr(R, "_adopt_current_power_report", None):
        assert R._adopt_current_power_report(project, "neutral", report, [])
    else:
        write(report, POWER)
    if subject == "RECEIPT_MISSING":
        report.with_suffix(".current.json").unlink(missing_ok=True)
    elif subject == "COMPANION_CHANGED":
        write(report.with_suffix(".json"), '{"total_power_w": 0.0}')
    elif subject == "SPEF_CHANGED":
        spef = R._pl.extracted_dir(project) / "neutral.spef"
        spef.write_text(spef.read_text() + "\n# changed physical subject\n")
    elif subject == "EXECUTION_MISSING":
        (folder / "invocation.log").unlink()
    due = getattr(R, "_step33_current_power_due", None)
    producer = R._emit_power_report
    observed = {"cache": "NO_CURRENT_BINDING_CHECK", "adoptions": 0}

    def admission(*args):
        needed = due(*args) if due else True
        observed["cache"] = "REFRESH_REQUIRED" if needed else "CURRENT"
        return needed

    def adopt(*args, **kwargs):
        if kwargs.get("basis") != "post_pnr":
            return False  # The independent pre-PnR preview is outside Step33.
        observed["adoptions"] += 1
        return producer(*args, **kwargs)

    def following_row(*args, **kwargs):
        raise ReachedFollowingRow

    monkeypatch.setattr(R, "_step33_current_power_due", admission, raising=False)
    monkeypatch.setattr(R, "_emit_power_report", adopt)
    monkeypatch.setattr(R, "_signoff_regen", lambda *args: False)
    monkeypatch.setattr(R, "_step25_native_density_due", lambda *args: False, raising=False)
    monkeypatch.setattr(R, "_step27_current_si_due", lambda *args: False, raising=False)
    monkeypatch.setattr(R, "_docker_exec", lambda *args, **kwargs: (1, "", "outside scoped source fixture"))
    monkeypatch.setattr(R, "_docker_exec_raw", lambda *args, **kwargs: (1, "", "outside scope"))
    monkeypatch.setattr(R, "_discover_container_corner_libs", lambda *args: [])
    monkeypatch.setattr(R, "_emit_router_drc_report", following_row)
    with pytest.raises(ReachedFollowingRow):
        R.step_canonicalize_artefacts(project, "neutral", pdk, "offline")
    assert observed["adoptions"] == (0 if subject == "CURRENT" else 1), observed
    assert observed["cache"] == ("CURRENT" if subject == "CURRENT" else "REFRESH_REQUIRED"), observed
    assert (project / "phase3/librelane_switch.json").is_file()
    assert "steps" not in json.loads((project / "phase3/librelane_switch.json").read_text())
    if subject in ("CURRENT", "RECEIPT_MISSING", "COMPANION_CHANGED"):
        from test_default_current_power import gate
        assert gate(project, "33") == 0
    else:
        from test_default_current_power import gate
        assert gate(project, "33") == 1


def test_default_prestream_dispatches_current_rows_without_legacy_cache_reads(tmp_path, monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "default"})
    observed = {}
    expected = R.StepResult("current_rows", "PASS", 0.0, "dispatch control only")

    def current(project, top, pdk, container, step_ids, **kwargs):
        observed.update(project=project, top=top, step_ids=step_ids)
        return expected

    monkeypatch.setattr(R, "_default_pnr_rows", current)
    for name in ("_step25_native_density_due", "_step33_current_power_due"):
        monkeypatch.setattr(R, name, lambda *a: pytest.fail("Default entered a legacy cache"))
    assert R.step_canonicalize_artefacts(tmp_path, "unit", object(), "offline", prestream=True) is expected
    assert observed["project"] == tmp_path and observed["top"] == "unit"
    assert {"24", "25", "33"}.issubset(observed["step_ids"])


def test_ordinary_finished_gds_dispatch_uses_reviewed_primary(tmp_path, monkeypatch):
    import librelane_fill_dfm as finishing
    project = tmp_path / "finished-project"
    pnr = R._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    (pnr / "neutral.def").write_text("VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n")
    canonical = R._pl.gds_dir(project) / "neutral.gds"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"SOURCE_FIXTURE: dispatch only, no native layout claim")
    calls = []

    def primary(*args):
        calls.append("reviewed_primary")
        return {"canonical": str(canonical), "receipt": str(project / "promotion.json")}

    def legacy(*args):
        calls.append("legacy")
        raise LL.Refusal("SOURCE_FIXTURE_LEGACY_SELECTED", "observed ordinary dispatch")

    monkeypatch.setattr(finishing, "default_stream", primary, raising=False)
    monkeypatch.setattr(R, "_layout_basis", lambda *args: ("current", None))
    monkeypatch.setattr(R._ga, "stream_refusal", lambda *args: None)
    monkeypatch.setattr(R, "_vacuous_on_unrouted", lambda *args: None)
    monkeypatch.setattr(R, "publish_database_unit_declaration", lambda *args: {"verdict": "PASS", "reason": "SOURCE_FIXTURE"})
    monkeypatch.setattr(R, "_streamout_top", lambda *args: ("neutral", ""))
    monkeypatch.setattr(R, "publish_tapeout_declarations", lambda *args: {"published": [], "not_determined": [], "already_answered": []})
    monkeypatch.setattr(R, "_magic_def_to_gds", legacy)
    try:
        result = R.step_gds(project, "neutral", R.PdkConfig("neutral", "", "", "", None, "", None), "offline")
    except LL.Refusal:
        result = None
    assert calls == ["reviewed_primary"], calls
    assert result is not None and result.status == "PASS"
    assert str(canonical) in result.output_files
    assert not (project / "phase3/librelane_switch.json").exists()
