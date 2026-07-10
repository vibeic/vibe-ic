"""test_flow_dashboard_data.py — the live-dashboard DATA PROVIDER.

flow_dashboard_data.collect(project, full=False) reads the canonical flow yaml
and resolves each step's required_outputs against a project tree to a fast,
file-stat-only status. These tests are fully synthetic (no docker, no real flow
run): a tiny temp project with a couple of fake outputs + a disclosed-skip
sentinel exercises the status logic and the exact JSON contract the CLI and web
renderers depend on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import flow_dashboard_data as D  # noqa: E402

_PHASE_ORDER = ["phase1", "phase2", "phase3", "analog", "mixed", "manufacturing"]
# Track the module's canonical status contract so this never silently drifts
# when a new honest status (e.g. "partial") is added.
_STATUSES = list(D._STATUSES)


# --------------------------------------------------------------------------- #
# Contract-shape invariants against the REAL flow yaml
# --------------------------------------------------------------------------- #
def _find_step(data, sid):
    for ph in data["phases"]:
        for st in ph["steps"]:
            if st["id"] == sid:
                return st, ph
    return None, None


def test_real_flow_empty_project_has_six_phases_and_never_raises(tmp_path):
    # nonexistent/empty project — must not raise, must emit all 6 lanes.
    proj = tmp_path / "does_not_exist_yet"
    data = D.collect(proj)  # dir does not exist
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER
    # every lane carries its declared label + icon and step count fields
    for p in data["phases"]:
        assert p["label"] and p["icon"]
        assert isinstance(p["steps"], list)
        assert p["total"] == len(p["steps"])
        # DONE (resolved) = every judged verdict, not just the PASS subset.
        assert p["resolved"] == sum(
            1 for s in p["steps"] if s["status"] in D._RESOLVED)
        assert p["done"] == p["resolved"]  # back-compat alias
        assert p["passed"] == sum(
            1 for s in p["steps"] if s["status"] == "pass")
    total = sum(p["total"] for p in data["phases"])
    assert total > 40, f"expected >40 canonical steps, got {total}"
    assert data["summary"]["total"] == total
    assert data["mode"] == "lightweight"
    assert data["project_name"] == "does_not_exist_yet"


def test_real_flow_key_steps_land_in_expected_lanes(tmp_path):
    data = D.collect(tmp_path)
    # P0 + D1 in phase1
    for sid in ("P0", "D1"):
        st, ph = _find_step(data, sid)
        assert st is not None, f"{sid} missing"
        assert ph["key"] == "phase1"
    # id 39 (FPGA on-board bring-up) claimed by phase2 despite stage4
    st, ph = _find_step(data, "39")
    assert st is not None and ph["key"] == "phase2"
    # analog / mixed / manufacturing exemplars
    assert _find_step(data, "A1")[1]["key"] == "analog"
    assert _find_step(data, "M1")[1]["key"] == "mixed"
    assert _find_step(data, "40")[1]["key"] == "manufacturing"


def test_summary_counts_are_internally_consistent(tmp_path):
    data = D.collect(tmp_path)
    s = data["summary"]
    # per-status counts + the two roll-ups (resolved = DONE, passed = the PASS
    # subset) + total.
    assert set(s.keys()) == {"total", "resolved", "passed", *(_STATUSES)}
    assert sum(s[k] for k in _STATUSES) == s["total"]
    # DONE (resolved) = total minus the two unresolved states.
    assert s["resolved"] == s["total"] - s["running"] - s["pending"]
    assert s["passed"] == s["pass"]
    # every status is one of the canonical values
    for p in data["phases"]:
        for st in p["steps"]:
            assert st["status"] in _STATUSES
            assert st["status_label"] == st["status"].upper()


def _phase_statuses(data, key):
    ph = next(p for p in data["phases"] if p["key"] == key)
    return {s["status"] for s in ph["steps"]}


def test_digital_project_analog_mixed_are_na_not_pending(tmp_path):
    # A project with no analog block list → the analog A1-A9 + mixed M1-M4 lanes
    # NEVER run for this design; they must read `na`, never a misleading pending.
    data = D.collect(tmp_path)
    assert _phase_statuses(data, "analog") == {"na"}
    assert _phase_statuses(data, "mixed") == {"na"}
    # and none of them leaked a bare pending
    assert "pending" not in _phase_statuses(data, "analog")


def test_manufacturing_is_external_not_pending(tmp_path):
    # Manufacturing 40-44 are off-machine until silicon is physically received.
    data = D.collect(tmp_path)
    assert _phase_statuses(data, "manufacturing") == {"external"}


def test_analog_applicable_project_is_not_reclassified(tmp_path):
    # Once the design declares analog blocks, the analog lane is APPLICABLE — it
    # must NOT be forced to `na` (it is genuinely pending until it runs).
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(
        "{}", encoding="utf-8")
    data = D.collect(tmp_path)
    assert "na" not in _phase_statuses(data, "analog")


def test_p0_done_once_synth_netlist_exists(tmp_path):
    # P0 (structural pre-flight umbrella, no output of its own) is proven passed
    # by a produced synth netlist — synthesis runs strictly after pre-flight.
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text("module m(); endmodule\n", encoding="utf-8")
    data = D.collect(tmp_path)
    st, _ = _find_step(data, "P0")
    assert st["status"] == "pass"


def test_every_output_entry_has_required_keys(tmp_path):
    data = D.collect(tmp_path)
    for p in data["phases"]:
        for st in p["steps"]:
            assert set(st.keys()) >= {
                "id", "name", "stage", "status", "status_label",
                "blocks_on", "gate", "detail", "outputs",
            }
            assert isinstance(st["blocks_on"], list)
            for o in st["outputs"]:
                assert set(o.keys()) == {"rel", "abs", "exists", "size", "mtime"}
                assert isinstance(o["exists"], bool)


# --------------------------------------------------------------------------- #
# Status logic against a synthetic project with real outputs
# --------------------------------------------------------------------------- #
def _write(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_step_with_all_outputs_present_is_done(tmp_path):
    # Step 1 (Spec-to-RTL) needs an RTL file + two extraction reports.
    _write(tmp_path / "phase2" / "stage1" / "rtl" / "top.sv", "module top; endmodule")
    _write(tmp_path / "reports" / "phase1" / "extraction_coverage_report.md")
    # Second required report — resolve dynamically from the yaml so the test
    # does not hard-code a path that could drift.
    _doc, steps = D._load_flow()
    step1 = next(s for s in steps if str(s.get("id")) == "1")
    for spec in step1.get("required_outputs", []):
        for alt in D._split_alts(spec):
            if "*" not in alt:  # literal path → materialize it
                _write(tmp_path / alt)
    data = D.collect(tmp_path)
    st, ph = _find_step(data, "1")
    assert ph["key"] == "phase2"
    assert st["status"] == "pass"
    assert st["status_label"] == "PASS"
    # the RTL glob resolved to a real existing file
    rtl = [o for o in st["outputs"] if o["exists"] and o["rel"].endswith(".sv")]
    assert rtl and rtl[0]["size"] > 0 and rtl[0]["mtime"] > 0


def test_disclosed_skip_sentinel_yields_skipped(tmp_path):
    # Pick a real step and drop a *_not_run.json sentinel in its first output
    # dir while its canonical outputs are ABSENT -> status must be "skipped".
    _doc, steps = D._load_flow()
    # choose a step whose required_outputs have a concrete (non-glob) dir
    target = None
    for s in steps:
        dirs = D._output_dirs(s.get("required_outputs"))
        if dirs and str(s.get("id")) != "1":
            target = s
            break
    assert target is not None
    sid = str(target["id"])
    outdir = D._output_dirs(target["required_outputs"])[0]
    sentinel = tmp_path / outdir / "dft_atpg_not_run.json"
    _write(sentinel, json.dumps({"verdict": "SKIPPED-CONDITION"}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, sid)
    assert st["status"] == "skipped"
    assert st["detail"], "skipped step should carry a disclosed-skip reason"


def test_verdict_field_skip_yields_skipped(tmp_path):
    # A *.json (not a *_not_run sentinel) whose top-level verdict is SKIP,
    # with _-vs- normalization, also discloses a skip.
    _doc, steps = D._load_flow()
    target = next(
        s for s in steps
        if D._output_dirs(s.get("required_outputs")) and str(s.get("id")) != "1"
    )
    sid = str(target["id"])
    outdir = D._output_dirs(target["required_outputs"])[0]
    _write(tmp_path / outdir / "gate_result.json", json.dumps({"verdict": "skip"}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, sid)
    assert st["status"] == "skipped"


def test_step_with_no_outputs_is_pending(tmp_path):
    # P0 is the umbrella step with NO required_outputs -> pending (lightweight
    # cannot cheaply judge an umbrella; no reports present).
    data = D.collect(tmp_path)
    st, ph = _find_step(data, "P0")
    assert ph["key"] == "phase1"
    assert st["status"] == "pending"
    assert st["outputs"] == []


def test_partial_outputs_is_running(tmp_path):
    # Materialize SOME but not all of a multi-output step -> running.
    _doc, steps = D._load_flow()
    # step 3 (CDC/RDC) has 3 concrete report outputs
    step3 = next(s for s in steps if str(s.get("id")) == "3")
    specs = step3.get("required_outputs", [])
    assert len(specs) >= 2
    # write only the first
    first_alt = D._split_alts(specs[0])[0]
    _write(tmp_path / first_alt, json.dumps({"ok": True}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, "3")
    assert st["status"] == "running"


def test_missing_flow_yaml_style_robustness(tmp_path, monkeypatch):
    # collect must not raise even when full-mode compliance is stubbed to fail;
    # it should transparently fall back to lightweight and record a note.
    monkeypatch.setattr(D, "_run_compliance", lambda project: None)
    data = D.collect(tmp_path, full=True)
    assert data["mode"] == "lightweight"
    assert data["note"], "fallback should record a note"
    # shape still intact
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER


def test_full_mode_structural_mapping(tmp_path, monkeypatch):
    # Structurally exercise the full-mode path with a stubbed compliance result:
    # map PASS->done, FAIL->fail, SKIPPED-CONDITION->skipped, WAIVED->waived.
    fake = [
        {"id": 1, "status": "PASS", "reasons": []},
        {"id": 2, "status": "FAIL", "reasons": ["lint error over threshold"]},
        {"id": 3, "status": "SKIPPED-CONDITION", "reasons": ["no async input"]},
        {"id": "A1", "status": "WAIVED", "reasons": ["analog waived"]},
        {"id": 15, "status": "MISSING", "reasons": []},
        {"id": "D1", "status": "VACUOUS_PASS", "reasons": []},
    ]
    monkeypatch.setattr(D, "_run_compliance", lambda project: fake)
    data = D.collect(tmp_path, full=True)
    assert data["mode"] == "full"
    assert data["note"] == ""
    assert _find_step(data, "1")[0]["status"] == "pass"
    assert _find_step(data, "2")[0]["status"] == "fail"
    assert _find_step(data, "2")[0]["detail"] == "lint error over threshold"
    assert _find_step(data, "3")[0]["status"] == "skipped"
    assert _find_step(data, "A1")[0]["status"] == "waived"
    assert _find_step(data, "15")[0]["status"] == "missing"
    assert _find_step(data, "D1")[0]["status"] == "pass"  # VACUOUS_PASS


def test_status_mapping_helper_covers_documented_verdicts():
    m = D._map_compliance_status
    assert m("PASS") == "pass"
    assert m("VACUOUS_PASS") == "pass"
    assert m("VACUOUS-PASS") == "pass"
    assert m("SKIPPED-CONDITION") == "skipped"
    assert m("DEFERRED-BY-UPSTREAM") == "skipped"
    assert m("WAIVED") == "waived"
    assert m("WAIVED-DEFERRED") == "waived"
    assert m("FAIL") == "fail"
    assert m("MISSING") == "missing"
    assert m("SOMETHING-ELSE") == "pending"


def test_json_cli_roundtrip(tmp_path):
    out = tmp_path / "dash.json"
    rc = D.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER
    assert data["mode"] == "lightweight"


# --------------------------------------------------------------------------- #
# Plugin version — the dashboard badge shows the SHIPPED plugin version
# --------------------------------------------------------------------------- #
def test_plugin_version_resolves_from_manifest():
    # The real plugin manifest sits at ../.claude-plugin/plugin.json — a
    # dotted semver string. Never raises.
    v = D._plugin_version()
    assert isinstance(v, str)
    # in the shipped tree it is a non-empty dotted version
    assert v == "" or v.count(".") >= 1


def test_collect_emits_plugin_version(tmp_path):
    data = D.collect(tmp_path)
    assert "plugin_version" in data
    assert data["plugin_version"] == D._plugin_version()


# --------------------------------------------------------------------------- #
# FLEET — discover_projects + collect_fleet (multi-IC overview)
# --------------------------------------------------------------------------- #
def _make_project(root: Path, name: str) -> Path:
    p = root / name
    (p / "phase1").mkdir(parents=True)
    return p


def test_discover_projects_finds_children(tmp_path):
    _make_project(tmp_path, "chipA")
    _make_project(tmp_path, "chipB")
    # a non-project sibling (no flow marker) must be ignored
    (tmp_path / "logs").mkdir()
    # a hidden dir must be ignored
    (tmp_path / ".cache" / "phase1").mkdir(parents=True)
    found = D.discover_projects(str(tmp_path))
    names = sorted(Path(p).name for p in found)
    assert names == ["chipA", "chipB"]


def test_discover_projects_single_project_root(tmp_path):
    # A root that is ITSELF a project (and has no project children) resolves to
    # just itself, so `--fleet <one-project>` still works.
    (tmp_path / "phase2").mkdir(parents=True)
    found = D.discover_projects(str(tmp_path))
    assert found == [str(tmp_path.resolve())]


def test_discover_projects_unreadable_root_is_empty(tmp_path):
    missing = tmp_path / "nope"
    assert D.discover_projects(str(missing)) == []


def test_collect_fleet_shape_and_aggregate(tmp_path):
    _make_project(tmp_path, "chipA")
    _make_project(tmp_path, "chipB")
    fl = D.collect_fleet([], root=str(tmp_path))
    assert fl["kind"] == "fleet"
    assert fl["count"] == 2
    assert fl["plugin_version"] == D._plugin_version()
    # cards carry a compact, contractual shape (NO heavy per-step outputs)
    for c in fl["fleet"]:
        assert set(c.keys()) >= {
            "project", "project_name", "mode", "summary",
            "phases_mini", "running_steps",
        }
        assert isinstance(c["phases_mini"], list) and c["phases_mini"]
        for pm in c["phases_mini"]:
            assert set(pm.keys()) == {"key", "label", "icon", "resolved", "total"}
    # aggregate = element-wise sum of the per-IC summaries
    agg = fl["agg"]
    assert agg["ic_count"] == 2
    assert agg["total"] == sum(c["summary"]["total"] for c in fl["fleet"])
    assert agg["resolved"] == sum(c["summary"]["resolved"] for c in fl["fleet"])
    for k in _STATUSES:
        assert agg[k] == sum(c["summary"][k] for c in fl["fleet"])


def test_collect_fleet_explicit_project_list(tmp_path):
    a = _make_project(tmp_path, "chipA")
    b = _make_project(tmp_path, "chipB")
    fl = D.collect_fleet([str(a), str(b)])
    assert fl["count"] == 2
    assert {c["project_name"] for c in fl["fleet"]} == {"chipA", "chipB"}


def test_collect_fleet_empty_is_safe(tmp_path):
    fl = D.collect_fleet([], root=str(tmp_path / "no_projects_here"))
    assert fl["kind"] == "fleet"
    assert fl["count"] == 0
    assert fl["agg"]["ic_count"] == 0
    assert fl["fleet"] == []


def test_collect_fleet_running_and_done_rollup(tmp_path):
    # chipA: a genuinely running (partial multi-output) step -> counts as running IC.
    a = _make_project(tmp_path, "chipA")
    _doc, steps = D._load_flow()
    step3 = next(s for s in steps if str(s.get("id")) == "3")
    first_alt = D._split_alts(step3.get("required_outputs", [])[0])[0]
    _write(a / first_alt, json.dumps({"ok": True}))
    # chipB: nothing running.
    _make_project(tmp_path, "chipB")
    fl = D.collect_fleet([], root=str(tmp_path))
    # at least chipA reports a running step
    running_cards = [c for c in fl["fleet"] if c["summary"]["running"] > 0]
    assert running_cards, "chipA should have a running step"
    assert fl["agg"]["ic_running"] == len(running_cards)
    # running_steps list on chipA carries the step id/name
    a_card = next(c for c in fl["fleet"] if c["project_name"] == "chipA")
    assert any(rs["id"] == "3" for rs in a_card["running_steps"])


def test_collect_fleet_cli_smoke(tmp_path, capsys):
    _make_project(tmp_path, "chipA")
    rc = D.main([str(tmp_path), "--fleet"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["kind"] == "fleet"
    assert data["count"] == 1


# --------------------------------------------------------------------------- #
# AUTO — cheap while live, authoritative once idle
# --------------------------------------------------------------------------- #
def _light(running, paths=("a.v",)):
    # one step whose existing outputs are the given rel-paths (mtime is
    # deliberately varied to prove the fingerprint IGNORES it).
    steps = [{"id": "1", "status": "pass",
              "outputs": [{"exists": True, "rel": p, "mtime": 100.0} for p in paths]}]
    return {"summary": {"running": running}, "phases": [{"steps": steps}],
            "mode": "lightweight"}


def test_collect_auto_stays_lightweight_while_running(monkeypatch):
    D._AUTO_FULL_CACHE.clear()
    calls = []

    def fake(project, full=False):
        calls.append(full)
        if full:
            raise AssertionError("must NOT escalate to full while a step is running")
        return _light(running=1)

    monkeypatch.setattr(D, "collect", fake)
    d = D.collect_auto("/p")
    assert d["mode"] == "auto:live"
    assert calls == [False]           # only the cheap pass ran


def test_collect_auto_escalates_when_idle_then_caches(monkeypatch):
    D._AUTO_FULL_CACHE.clear()
    calls = []

    def fake(project, full=False):
        calls.append(full)
        if full:
            return {"summary": {"running": 0}, "phases": [], "mode": "full"}
        return _light(running=0)

    monkeypatch.setattr(D, "collect", fake)
    d1 = D.collect_auto("/p2")
    assert d1["mode"] == "auto:full"
    assert calls == [False, True]     # cheap pass then ONE full run
    # second poll, tree unchanged → cache hit, NO second full run
    d2 = D.collect_auto("/p2")
    assert d2["mode"] == "auto:full"
    assert calls == [False, True, False]


def test_collect_auto_ignores_mtime_only_changes(monkeypatch):
    # A full run rewrites its own report files in place (mtime bumps, same set
    # of outputs) — that must NOT bust the cache, or the expensive full run
    # would repeat every poll.
    D._AUTO_FULL_CACHE.clear()
    state = {"mtime": 100.0}
    calls = []

    def fake(project, full=False):
        calls.append(full)
        if full:
            return {"summary": {"running": 0}, "phases": [], "mode": "full"}
        s = [{"id": "1", "status": "pass",
              "outputs": [{"exists": True, "rel": "a.v", "mtime": state["mtime"]}]}]
        return {"summary": {"running": 0}, "phases": [{"steps": s}], "mode": "lightweight"}

    monkeypatch.setattr(D, "collect", fake)
    D.collect_auto("/p3")
    assert calls == [False, True]
    state["mtime"] = 999999.0            # mtime moved, structure identical
    D.collect_auto("/p3")
    assert calls == [False, True, False]  # cache HIT — no second full run


def test_collect_auto_reescalates_when_output_set_changes(monkeypatch):
    D._AUTO_FULL_CACHE.clear()
    state = {"paths": ("a.v",)}
    calls = []

    def fake(project, full=False):
        calls.append(full)
        if full:
            return {"summary": {"running": 0}, "phases": [], "mode": "full"}
        return _light(running=0, paths=state["paths"])

    monkeypatch.setattr(D, "collect", fake)
    D.collect_auto("/p3b")
    assert calls == [False, True]
    # a new flow output appeared (build progressed) → fingerprint busts → re-run
    state["paths"] = ("a.v", "b.v")
    D.collect_auto("/p3b")
    assert calls == [False, True, False, True]


def test_collect_auto_does_not_cache_a_fallback(monkeypatch):
    D._AUTO_FULL_CACHE.clear()

    def fake(project, full=False):
        # full mode "fell back" to lightweight (compliance checker missing)
        return {"summary": {"running": 0}, "phases": [], "mode": "lightweight"}

    monkeypatch.setattr(D, "collect", fake)
    d = D.collect_auto("/p4")
    assert d["mode"] == "auto:lightweight"      # surfaced, not mislabeled full
    key = str(Path("/p4").resolve())
    assert key not in D._AUTO_FULL_CACHE         # a non-authoritative result is never cached


def test_collect_fleet_auto_uses_adaptive_collector(tmp_path):
    # Integration: a real tmp fleet in auto mode — every card resolves through
    # collect_auto (mode prefixed "auto:") and never raises.
    _make_project(tmp_path, "chipA")
    _make_project(tmp_path, "chipB")
    fl = D.collect_fleet([], root=str(tmp_path), auto=True)
    assert fl["count"] == 2
    for c in fl["fleet"]:
        assert str(c["mode"]).startswith("auto:")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
