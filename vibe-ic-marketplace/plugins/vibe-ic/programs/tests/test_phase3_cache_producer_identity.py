"""The phase-3 synth/PnR/GDS cache must be keyed on the RECIPE, not only on
the design inputs — EXECUTABLE, end-to-end through ``main()``.

THE DEFECT
==========
Every pre-existing key on this cache asks "did the INPUT change?":

  * ``_netlist_matches_liberty``                       — the PDK  (PR-A3)
  * ``_stale_rtl_by_fingerprint`` / ``_stale_rtl_vs_netlist``
                                                       — the RTL  (#289/#349)
  * ``_pnr_cache_valid_for``                           — the die  (#593/#596)

Not one of them asks "did the RECIPE change?". So a landed fix to the synth /
PnR / stream-out recipe is a SILENT NO-OP on any tree that already holds an
artefact: the flow reuses what the OLD code produced and reports PASS for code
that never ran. "We landed the fix, re-run to confirm" becomes structurally
unable to confirm anything.

MEASURED, three independent times in one convergence round:
  * a landed tie-cell fix left two steps failing with the exact message it was
    written to eliminate, until the netlist was moved aside BY HAND;
  * three staged files had to be deleted by hand before fixed emitters ran;
  * "netlist already present ... (skipped re-run to preserve provenance)" was
    followed by PnR reading the PREVIOUS DAY's DEF.

THE MUTATION THESE TESTS CATCH
==============================
Deleting any one of the three ``_producer_cache_valid_for`` call sites in
``main()`` — the #755 "fixed one site is not fixed the class" shape. Each of
the three producing steps has its own test below, so removing the key from any
one of them fails a named test rather than being absorbed by the other two.

A source-string test alone would not catch this: a permanently-True
``_prod_ok`` satisfies "the helper is mentioned in main()". These tests DRIVE
``main()`` and observe whether the step was actually invoked.

chip-AGNOSTIC: plugin version + runner source digest; no design, PDK, vendor
or part identifier anywhere.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402

TOP = "chip_top"
DIE, UTIL = "200x200", 0.45


# ── unit level: the key itself ──────────────────────────────────────────────

def test_matching_producer_is_reusable(tmp_path):
    """Control: an artefact stamped by THIS build stays reusable — the fix
    must not degenerate into 'always re-run'."""
    R._write_producer_identity(tmp_path, "synth")
    ok, msg = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is True, msg
    assert "producer unchanged" in msg


def test_older_plugin_version_invalidates(tmp_path):
    """THE defect: the artefact was produced by an earlier plugin build, so
    every recipe change landed since then is absent from it."""
    now = R._producer_identity_now()
    (tmp_path / R._PRODUCER_SIDECAR).write_text(json.dumps({
        "synth": {"plugin_version": "0.0.1-older",
                  "recipe_sha256": now["recipe_sha256"]}}))
    ok, msg = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is False, (
        "a netlist produced by an OLDER plugin build was judged reusable — "
        "every fix landed since then is a silent no-op")
    assert "0.0.1-older" in msg and "re-running" in msg


def test_edited_recipe_invalidates_without_a_version_bump(tmp_path):
    """The in-tree case a released version number cannot see: same version,
    edited runner source. This is the shape an agent testing its own fix hits
    on every iteration."""
    now = R._producer_identity_now()
    (tmp_path / R._PRODUCER_SIDECAR).write_text(json.dumps({
        "pnr": {"plugin_version": now["plugin_version"],
                "recipe_sha256": "0" * 64}}))
    ok, msg = R._producer_cache_valid_for(tmp_path, "pnr")
    assert ok is False, msg
    assert "recipe" in msg


def test_unstamped_artefact_fails_closed(tmp_path):
    """Every artefact that exists TODAY has no stamp. Absence of evidence is
    not evidence of freshness: reuse requires positive proof."""
    ok, msg = R._producer_cache_valid_for(tmp_path, "gds")
    assert ok is False
    assert "NO producer stamp" in msg


def test_unreadable_stamp_fails_closed(tmp_path):
    """A corrupt stamp is unreadable evidence, therefore no evidence."""
    (tmp_path / R._PRODUCER_SIDECAR).write_text("{not json")
    ok, _ = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is False


def test_unresolvable_current_identity_fails_closed(tmp_path, monkeypatch):
    """If THIS build cannot name itself, it cannot prove a match either."""
    R._write_producer_identity(tmp_path, "synth")
    monkeypatch.setattr(R, "_plugin_version", lambda: "")
    ok, msg = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is False
    assert "unresolvable" in msg


def test_kinds_are_recorded_separately(tmp_path):
    """A run that re-derived the DEF but reused the GDS is exactly the #593
    shape; one shared record could not express it."""
    R._write_producer_identity(tmp_path, "pnr")
    assert R._producer_cache_valid_for(tmp_path, "pnr")[0] is True
    assert R._producer_cache_valid_for(tmp_path, "gds")[0] is False, (
        "stamping the DEF must not silently vouch for the GDS")
    R._write_producer_identity(tmp_path, "gds")
    assert R._producer_cache_valid_for(tmp_path, "pnr")[0] is True, (
        "stamping the GDS must not erase the DEF's stamp")


def test_forced_reuse_is_permanently_disclosed(tmp_path, monkeypatch):
    """The escape hatch may buy back the reuse; it may NEVER buy back the
    appearance of freshness. The token must reach the step detail, which is
    what the published JSON report carries."""
    monkeypatch.setenv(R._STALE_PRODUCER_ENV, "1")
    ok, msg = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is True, "the documented override must actually permit reuse"
    assert "PRODUCER-STALE" in msg and R._STALE_PRODUCER_ENV in msg


def test_one_version_reader_for_the_whole_repo():
    """The plugin version must come from `plugin_manifest_discovery`, the
    repo's one reader. A second reader here is how the two drift apart
    (#309/#312/#348) — the producer/consumer split this campaign keeps
    re-finding."""
    import inspect
    src = inspect.getsource(R._plugin_version)
    assert "plugin_manifest_discovery" in src
    assert "plugin.json" not in src, (
        "a private second plugin.json reader was introduced — use the shared "
        "one so a manifest-layout change cannot desynchronise them")


# ── end-to-end: all THREE call sites, driven through main() ─────────────────

def _pdk() -> R.PdkConfig:
    return R.PdkConfig(name="testpdk", liberty="/nonexistent/tt.lib",
                       tech_lef="/nonexistent/tech.lef",
                       cell_lef="/nonexistent/cells.lef", cell_gds=None,
                       site="unit", drc_deck=None)


def _project(tmp_path: Path, *, stamp: bool) -> Path:
    """The 'everything already exists from a previous run' state. `stamp`
    decides whether that previous run was THIS build or an unknown one."""
    pnr = R._pl.pnr_dir(tmp_path)
    synth = R._pl.synth_dir(tmp_path)
    rtl = R._pl.rtl_dir(tmp_path)
    for d in (pnr, synth, rtl):
        d.mkdir(parents=True, exist_ok=True)
    (rtl / f"{TOP}.v").write_text(f"module {TOP}(); endmodule\n")
    (synth / f"{TOP}_synth.v").write_text("// cached netlist\n")
    # The DECLARED input of the PnR step, owed by step 12 and read by step 15.
    # Not decoration: `step_preflight` refuses to dispatch a step whose declared
    # inputs are absent, and it landed AFTER this fixture was written. Without
    # this file the runner never reaches the cache decision at all — the pnr row
    # comes back BLOCKED/REFUSED TO RUN and the two tests below assert about a
    # step that was never offered the chance to be cached or re-run.
    #
    # This is the fixture catching up with the flow, NOT a relaxation: preflight
    # still refuses when the input is genuinely absent (that is its own suite's
    # subject), and the tests below still fail if the producer key is removed
    # from their call site, which is the mutation they exist to catch.
    (synth / "post_dft_netlist.v").write_text("// cached post-DFT netlist\n")
    (pnr / f"{TOP}.def").write_text(
        "DIEAREA ( 0 0 ) ( 200000 200000 ) ;\nPINS 0 ;\nEND PINS\n")
    (pnr / f"{TOP}.gds").write_text("cached GDS\n")
    R._write_pnr_args_sidecar(pnr, DIE, UTIL)
    R._write_synth_inputs_sidecar(synth / f"{TOP}_synth.v", rtl)
    if stamp:
        R._write_producer_identity(synth, "synth")
        R._write_producer_identity(pnr, "pnr")
        R._write_producer_identity(pnr, "gds")
    return tmp_path


def _drive(monkeypatch, project: Path) -> list:
    """Neutralise everything main() does that is not the cache decision, and
    record which steps it invokes. The producer helpers are LEFT REAL — the
    cache verdict is what is under test."""
    called: list = []

    def _step(name):
        def _f(*a, **k):
            called.append(name)
            return R.StepResult(name, "PASS", 0.0, f"{name} ok")
        return _f

    for attr in ("step_synth", "step_pnr", "step_gds", "step_drc", "step_lvs",
                 "step_canonicalize_artefacts"):
        monkeypatch.setattr(R, attr, _step(attr[len("step_"):]))
    monkeypatch.setattr(R, "step_signoff_spef_repair", lambda *a, **k: None)
    monkeypatch.setattr(R, "step_signoff_drv_wire_length_repair",
                        lambda *a, **k: None)
    monkeypatch.setattr(R, "_detect_pdk", lambda *a, **k: _pdk())
    monkeypatch.setattr(R._runner_lock, "acquire_or_reenter",
                        lambda *a, **k: object())
    monkeypatch.setattr(R, "commercial_pdk_fallback_guard",
                        lambda *a, **k: None)
    monkeypatch.setattr(R, "macro_lef_layer_compat_guard", lambda *a, **k: None)
    monkeypatch.setattr(R, "_container_mounts", lambda *a, **k: [])
    monkeypatch.setattr(R, "_is_pure_analog_no_rtl_track",
                        lambda *a, **k: (False, ""))
    monkeypatch.setattr(R, "_netlist_matches_liberty", lambda *a, **k: True)
    monkeypatch.setattr(R, "_stale_rtl_by_fingerprint", lambda *a, **k: [])
    monkeypatch.setattr(R, "_stale_rtl_vs_netlist", lambda *a, **k: [])
    monkeypatch.setattr(R, "_resolve_asic_top_structural",
                        lambda proj, top, hint=None: top)
    monkeypatch.setattr(R, "_DERIVED_ARTEFACT_GENERATORS", ())
    monkeypatch.setattr(R._pl, "emit_final_summary", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", [
        "phase3_one_shot_runner", str(project), "--top-name", TOP,
        "--die-um", DIE, "--util", str(UTIL), "--container", "",
    ])
    return called


def _plan(project: Path):
    doc = json.loads(
        R._pl.report_path(project, "phase3_one_shot.json").read_text())
    return {s["name"]: s for s in doc["steps"]}


# THE REGRESSION, one test per call site so removing the key from ONE of the
# three fails a named test instead of hiding behind the other two.

def test_unstamped_netlist_forces_a_synth_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the synth call site."""
    project = _project(tmp_path, stamp=False)
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" in called, (
        "an unstamped netlist was reused: every synth fix landed since it was "
        f"written is a silent no-op. synth row: {_plan(project)['synth']}")


def test_unstamped_def_forces_a_pnr_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the PnR call site.
    The netlist IS stamped, so only the PnR key can force this re-run."""
    project = _project(tmp_path, stamp=False)
    R._write_producer_identity(R._pl.synth_dir(project), "synth")
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called, "control: the stamped netlist must be reused"
    assert "pnr" in called, (
        f"an unstamped DEF was reused. pnr row: {_plan(project)['pnr']}")


def test_unstamped_gds_forces_a_gds_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the GDS call site.
    Netlist and DEF are stamped, so only the GDS key can force this re-run —
    and the stream-out recipe can change while the router does not."""
    project = _project(tmp_path, stamp=False)
    R._write_producer_identity(R._pl.synth_dir(project), "synth")
    R._write_producer_identity(R._pl.pnr_dir(project), "pnr")
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called and "pnr" not in called, (
        f"control: stamped netlist+DEF must be reused; called={called}")
    assert "gds" in called, (
        f"an unstamped GDS was reused. gds row: {_plan(project)['gds']}")


def test_stamped_tree_still_hits_every_cache(tmp_path, monkeypatch):
    """The other direction, without which the three tests above would pass on
    an 'always re-run' mutation. Same build, same inputs, same geometry: the
    provenance-preserving reuse #593/v1.6.36 kept is UNCHANGED."""
    project = _project(tmp_path, stamp=True)
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called and "pnr" not in called \
        and "gds" not in called, (
        f"a same-build re-run must still hit all three caches; called={called}")
    plan = _plan(project)
    for name in ("synth", "pnr", "gds"):
        assert "skipped re-run" in plan[name]["detail"]


def test_a_real_rerun_stamps_the_producer(tmp_path, monkeypatch):
    """The write side: after a producing step actually runs, the NEXT run must
    be able to prove the artefact is current. Without this the fix would
    re-run forever and would be reverted."""
    project = _project(tmp_path, stamp=False)
    called = _drive(monkeypatch, project)
    R.main()
    assert {"synth", "pnr", "gds"} <= set(called)
    assert R._producer_cache_valid_for(
        R._pl.synth_dir(project), "synth")[0] is True
    assert R._producer_cache_valid_for(
        R._pl.pnr_dir(project), "pnr")[0] is True
    assert R._producer_cache_valid_for(
        R._pl.pnr_dir(project), "gds")[0] is True


def test_a_failed_step_does_not_stamp_a_producer(tmp_path, monkeypatch):
    """A FAILED synth must not stamp the netlist it did not produce —
    otherwise the next run would vouch for an artefact from the old build."""
    project = _project(tmp_path, stamp=False)
    _drive(monkeypatch, project)
    monkeypatch.setattr(
        R, "step_synth",
        lambda *a, **k: R.StepResult("synth", "FAIL", 0.0, "yosys died"))
    R.main()
    assert R._producer_cache_valid_for(
        R._pl.synth_dir(project), "synth")[0] is False, (
        "a FAILED synth stamped a producer identity onto the previous build's "
        "netlist — the next run would then reuse it as if it were current")


def test_reused_rows_name_the_producing_build(tmp_path, monkeypatch):
    """A stderr banner is lost in a log; the published JSON report is what
    every downstream gate and every human reads. A reused row must say which
    build produced the artefact, IN the report."""
    project = _project(tmp_path, stamp=True)
    _drive(monkeypatch, project)
    R.main()
    plan = _plan(project)
    version = R._plugin_version()
    for name in ("synth", "pnr", "gds"):
        assert "producer" in plan[name]["detail"], (
            f"the reused {name} row does not disclose its producer: "
            f"{plan[name]['detail']!r}")
        assert version in plan[name]["detail"]


#: The producer KINDS this runner has. Not a count of call sites — see
#: `_producer_kinds`.
_PRODUCER_KINDS = {"synth", "pnr", "gds"}


def _producer_kinds(src: str, fn: str):
    """(kinds, unreadable) — the `kind` literal each `fn(...)` call site names.

    WHY A SET OF KINDS AND NOT A COUNT OF CALL SITES. This guard existed as
    `src.count("_write_producer_identity(") == 3`, and MEASURED on live main
    7903c1972305 (2026-09-03, host load 6.3, pinned image
    sha256:66c33ff2...) that read 4:

        E   AssertionError: each producing call site must stamp on success;
            found 4

    The fourth site is `phase3_one_shot_runner.py:47353`,
    `_write_producer_identity(_pl.pnr_dir(project), "pnr")`, added by
    `551560ba18` (PDN/EM first-pass resize, v1.14.30): when EM sizing forces a
    resize the PnR step is RE-DISPATCHED, so the SAME producer kind is stamped
    a second time. There is no fourth producing KIND — the runner still
    produces synth, pnr and gds — so the defect this tripwire exists to catch
    (#755: "a fourth producing step added without the key") did not happen.
    The guard was counting TEXT OCCURRENCES, which cannot tell a legitimate
    re-stamp from a new unguarded producer.

    Raising 3 to 4 would freeze an instant into a contract: the next
    re-dispatch expires it again, and it would STILL pass a genuinely new
    `_write_producer_identity(..., "drc")` site, because that is also 4.
    Deleting it would leave the #755 shape unguarded. So the population is
    defined by BEHAVIOUR — which producer kinds does `main()` stamp and
    consult — which is blind to re-stamping and loud about a new kind.

    A call site whose kind is not a readable string literal is returned in
    `unreadable` and is a FAILURE, not a silent skip: a guard that cannot read
    a site cannot vouch for it, and a computed kind is exactly how a new
    producer would arrive unseen.
    """
    kinds, unreadable = [], []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.id if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", None))
        if name != fn:
            continue
        kind = node.args[1] if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "kind":
                kind = kw.value
        if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
            kinds.append(kind.value)
        else:
            unreadable.append(ast.unparse(node))
    return kinds, unreadable


def test_all_three_call_sites_are_wired():
    """Tripwire for a fourth producing KIND being added without the key —
    the #755 shape ('fixed one site' vs 'fixed the class').

    Every kind the runner STAMPS must also be a kind it CONSULTS on reuse, and
    the two sets must be exactly the kinds this runner produces. A kind
    stamped but never consulted is an artefact nothing revalidates; a kind
    consulted but never stamped can never be reused at all.
    """
    src = inspect.getsource(R.main)
    stamped, stamp_bad = _producer_kinds(src, "_write_producer_identity")
    consulted, consult_bad = _producer_kinds(src, "_producer_cache_valid_for")

    assert not stamp_bad and not consult_bad, (
        "a producer call site names a kind this guard cannot read, so it "
        f"cannot vouch for it: {stamp_bad + consult_bad}")
    assert set(stamped) == _PRODUCER_KINDS, (
        f"the runner stamps producer kinds {sorted(set(stamped))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A new producing kind must "
        f"arrive WITH its cache key, not after it")
    assert set(consulted) == _PRODUCER_KINDS, (
        f"the runner consults producer kinds {sorted(set(consulted))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A reuse decision made "
        f"without the producer key is the #755 shape")


def test_the_kind_guard_still_refuses_a_new_unguarded_producer():
    """CONTROL, the direction that must stay RED.

    The counting form could not tell these two apart. This one must: a new
    KIND is a defect, a second stamp of an existing kind is the PDN/EM
    re-dispatch and is not.
    """
    src = inspect.getsource(R.main)

    # (a) a genuinely new producing kind, stamped and never consulted
    grown = src + (
        "\n\ndef _synthetic_new_producer(project):\n"
        "    _write_producer_identity(_pl.drc_dir(project), 'drc')\n")
    kinds, bad = _producer_kinds(grown, "_write_producer_identity")
    assert not bad
    assert set(kinds) != _PRODUCER_KINDS, (
        "a fourth producing KIND did not move the guarded set — the tripwire "
        "would not have caught the #755 shape it exists for")

    # (b) the measured legitimate case: the SAME kind stamped twice
    restamped = src + (
        "\n\ndef _synthetic_redispatch(project):\n"
        "    _write_producer_identity(_pl.gds_dir(project), 'gds')\n")
    kinds, bad = _producer_kinds(restamped, "_write_producer_identity")
    assert not bad
    assert set(kinds) == _PRODUCER_KINDS, (
        "a re-dispatch that stamps an existing kind a second time moved the "
        "guarded set; that is the false red this guard was rebuilt to stop")

    # (c) a kind the guard cannot read is a refusal, never a silent pass
    computed = src + (
        "\n\ndef _synthetic_computed_kind(project, kind):\n"
        "    _write_producer_identity(_pl.pnr_dir(project), kind)\n")
    _kinds, bad = _producer_kinds(computed, "_write_producer_identity")
    assert bad, (
        "a call site whose kind is a variable was read as if it named none; "
        "that is how a new producer arrives unseen")
