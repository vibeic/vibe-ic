"""The front door's roll-up, at its edges — through main() and through the guard.

R-0915-145. The conjunction rule itself stands (a FAILING completion audit over
passing phases is a FAIL). These are the four edges a pre-landing review confirmed,
each driven through the entry point rather than through a re-implementation.

H1  #505's DEMOTED ROW. The standalone shape (`--skip-phase3`, a phase1 failure
    that is purely doc-extraction coverage) demotes phase1 to COVERAGE-INCOMPLETE
    and KEEPS its rc, because a coverage-only phase1 always exits 1 -- the rc
    belongs to the verdict the row had BEFORE the demotion. The roll-up's "claims
    a pass but exited non-zero" rule is right for an UNDEMOTED row and turned this
    shape into FAIL/exit 1, where the base published PASS_WITH_WAIVERS/exit 0.
    The demotion now records itself, and only the #505 branch may mint the token.

M2  THE AUDIT AXIS MUST NOT FAIL OPEN. `if ca == "FAIL"` meant NOT_MEASURED, an
    unparseable value and an ABSENT audit all read as satisfied -- so a phase3 run
    whose --strict completion refresh raised inside a swallowed try published PASS
    at exit 0. Only PASS satisfies the axis now; waivers cap at the waiver tier;
    anything else, absence included, is NOT_MEASURED with the reason stated.

M3  AND IT MUST BE THIS RUN'S AUDIT. The reader took
    `reports/orchestrator/phase3_one_shot.json` unconditionally, so a leftover FAIL
    from an earlier full run gated a later `--skip-phase3` invocation that never
    touched phase3. A document counts only when phase3 ran in THIS invocation and
    the document was written at or after it started; an older one is named as
    ignored, not used.

L4  ONE IMPLEMENTATION. `vibe_ic_entry_guard` re-derived the verdict with its own
    copy of the old rule and its verdict set had no NOT_MEASURED, so a GENUINE
    report was discarded as forged and `benchmark_dispatch --score` could refuse a
    real run. The guard now replays the runner's own roll-up.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl                                   # noqa: E402
import vibe_ic_entry_guard as GUARD                          # noqa: E402
import vibe_ic_one_shot_runner as V
from _route_fixture import stage_owner_route  # noqa: E402


@pytest.fixture()
def project(tmp_path_factory):
    p = Path(tempfile.mkdtemp(prefix="fdedge_",
                              dir=str(tmp_path_factory.mktemp("fd"))))
    rtl = p / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    return p


#: WHERE EACH PRODUCER REALLY WRITES -- and now that is ONE RULE, which is the point.
#:
#: Round 3 measured three locations and taught the fixtures all three:
#:     reports/phase1_one_shot.json                 <- phase1's runner, NOT routed
#:     reports/orchestrator/phase2_one_shot.json
#:     reports/orchestrator/phase3_one_shot.json
#: and I made the READER learn them too. That was the wrong half to change. `_path_layout`
#: categorises all three `*_one_shot.json` files as `orchestrator`, and the repo says the
#: flat location is not sanctioned, twice, without being asked:
#:   * `reports_subfolder_taxonomy_check` FAILS on it -- measured against a staged layout:
#:     `[FAIL] ... 1 stray file(s): phase1_one_shot.json`;
#:   * `vibe_ic_entry_guard` documents `reports/orchestrator/phase1_one_shot.json` as the
#:     standalone runner's location and calls the flat one "legacy".
#: So the PRODUCER moved onto the router, and both sides now resolve through one call.
#: These fixtures therefore write through the router too -- not because it is convenient,
#: but because a real `phase1_one_shot_runner` invocation was measured landing there, which
#: `test_phase1s_producer_resolves_its_report_through_the_router` pins against the source.
#:
#: The coverage-only sidecar is NOT in that set and is not routed at all: it is declared
#: literally, as `_path_layout.COVERAGE_ONLY_SIDECAR_REL`, and staged through
#: `coverage_only_sidecar_path` like everything else that touches it.
#:
#: CORRECTING WHAT THIS NOTE USED TO SAY. It claimed three locations -- "its producer writes
#: `reports/`, `_phase1_failure_is_coverage_only` reads `reports/phase1/`, and the router's
#: catch-all would say `reports/audit/`". Measured: the producer writes `reports/phase1/`, the
#: same place the reader reads, so there were never three LOCATIONS -- there were FIVE
#: hand-written COPIES of one location, across three programs, which is a different defect and
#: the one next/icslot-sidecarpath closed. The router's catch-all really would say
#: `reports/audit/`, and that remains a live mismatch: moving the file there is a producer move
#: needing a read-side tolerance for the old place, and it is not done.


















def test_rtl_only_evidence_resolves_the_existing_registry():
    import task_nature_route as routes
    for name, row in routes.EVIDENCE_EXIT.items():
        expected = name in ('existence', 'lint_validated', 'behaviour', 'proof')
        assert routes.is_rtl_only_evidence(name) == expected
        assert routes.is_rtl_only_evidence(exit_step=row['exit_step']) == expected
        assert routes.is_rtl_only_evidence(name, exit_step=row['exit_step']) == expected
        assert routes.is_rtl_only_evidence(name, exit_step='unrecognised') is False
    assert routes.is_rtl_only_evidence() is False
    assert routes.is_rtl_only_evidence('unrecognised') is False






@pytest.mark.timeout(300)
def test_bounded_rtl_request_reaches_the_real_lint_consumer(tmp_path):
    """Real retained producer, normal unified entry and real RTL lint in both directions."""
    import hashlib
    import subprocess
    import emit_attestation
    import benchmark_io_adapter as bio
    from programs.tests._hostpaths import require_repo
    fixture = require_repo() / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/librelane_lint_frontend/plain.v'
    source = fixture.read_text()
    project = tmp_path / 'native'
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    prompt = 'Implement this bitwise inverter with the supplied public interface.\n\n```verilog\n' + source + '```\n'
    (docs / 'spec.md').write_text(prompt)
    (project / 'input/phase1_prompt.md').write_text(prompt)
    stage_owner_route(project, 'ic')
    child_env = {key: value for key, value in os.environ.items()
                 if not key.startswith('VIBEIC_EXECUTION')}
    producer = subprocess.run([
        sys.executable, str(PROGRAMS / 'phase1_one_shot_runner.py'), str(project),
        '--mode', 'docs', '--skip-analog', '--ic-name', 'plain'],
        capture_output=True, text=True, env=child_env, timeout=80)
    (tmp_path / 'native-phase1.log').write_text(producer.stdout + producer.stderr)
    provenance = emit_attestation.phase1_provenance(project)
    assert provenance.get('ran') is True, producer.stdout + producer.stderr
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (docs / 'spec.md', project / 'input/phase1_prompt.md')}
    rtl = project / 'phase2/stage1/rtl/plain.v'
    rtl.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(PROGRAMS / 'vibe_ic_one_shot_runner.py'),
               str(project), '--route', 'ic', '--ic-name', 'plain',
               '--skip-phase3', '--skip-analog', '--skip-hardware', '--no-dashboard',
               '--entry-step', '2', '--exit-step', '2', '--max-rtl-repair-retries', '0']
    for valid in (True, False):
        rtl.write_text(source if valid else 'module plain( input [7:0] value_i, output [7:0] value_o); assign value_o = ; endmodule\n')
        result = subprocess.run(command, capture_output=True, text=True,
                                env=child_env, timeout=80)
        (tmp_path / ('native-valid.log' if valid else 'native-invalid.log')).write_text(
            result.stdout + result.stderr)
        report = json.loads(_pl.report_path(project, 'vibe_ic_one_shot.json').read_text())
        phase2 = next(row for row in report['phases'] if row['name'] == 'phase2')
        assert phase2['verdict'] != 'SKIPPED', report
        lint_path = project / 'reports/phase2/lint/rtl_hygiene.json'
        assert lint_path.is_file(), result.stdout + result.stderr
        lint = json.loads(lint_path.read_text())
        assert isinstance(lint, list), lint
        child = json.loads(_pl.report_path(project, 'phase2_one_shot.json').read_text())
        measured = next(row for row in child['steps'] if row['name'] == 'rtl_lint_tool')
        assert measured['status'] == ('PASS' if valid else 'FAIL'), child
        context = measured['extras']['native_context']
        assert isinstance(context['native_returncode'], int), context
        assert (context['native_returncode'] == 0) is valid, context
        assert context['input_sha256'], context
        if valid:
            assert context['status'] == 'MEASURED', context
        else:
            assert lint, 'the compiler rejection must retain its actual findings'
        if valid:
            collected = bio.collect('verilogeval', project.name, project,
                                    supplied_rtl=True, required_top='plain')
            assert collected['ok'] is True, collected
            assert bio.collect('verilogeval', project.name, project,
                               required_top='plain')['ok'] is False
        else:
            assert phase2['verdict'] == 'FAIL' and result.returncode != 0, report
        assert emit_attestation.phase1_provenance(project) == provenance
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in original} == original






























# ── H1: the #505 standalone shape ──────────────────────────────────────────







# ── M2: the audit axis never passes on a token nobody taught it ────────────







# ── M3: the axis belongs to THIS invocation ────────────────────────────────







# ── L4: the guard replays the runner's roll-up ─────────────────────────────

def _orchestrator_report(verdict: str, phases: list, **extra) -> dict:
    doc = {"phase": "vibe-ic", "verdict": verdict, "phases": phases}
    doc.update(extra)
    return doc


def test_the_guard_accepts_a_genuine_new_rule_report():
    """A report that is FAIL because its own completion audit failed, with every
    phase passing. The guard's old copy of the rule derived PASS and discarded it
    as forged."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "FAIL", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) == "FAIL"


def test_the_guard_rejects_a_forged_pass_over_a_failing_audit():
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    data = _orchestrator_report(
        "PASS", phases, completion_audit_axis={"state": "FAIL", "reason": "x"},
        completion_audit_verdicts=["FAIL"], demoted_phases={})
    assert GUARD._expected_front_door_verdict(data, phases) != "PASS"


def test_not_measured_is_a_front_door_verdict_the_guard_knows():
    assert "NOT_MEASURED" in GUARD._ORCHESTRATOR_VERDICTS, (
        "a genuine NOT_MEASURED report is discarded before any derivation runs")


def test_the_guard_holds_a_legacy_report_to_the_rule_it_was_published_under():
    """A report from before these fields existed carries no axis. It is judged by
    the old derivation — exactly as trusted as it was, and no more — because a
    guard cannot fairly hold a document to a rule it could not have followed."""
    phases = [{"name": "phase1", "verdict": "PASS", "rc": 0},
              {"name": "phase2", "verdict": "PASS", "rc": 0},
              {"name": "analog", "verdict": "SKIPPED", "rc": 0},
              {"name": "phase3", "verdict": "PASS", "rc": 0},
              {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0}]
    legacy = _orchestrator_report("PASS", phases)
    assert "completion_audit_axis" not in legacy
    assert GUARD._expected_front_door_verdict(legacy, phases) == "PASS"


def test_the_guard_does_not_keep_its_own_copy_of_the_rule():
    """SOURCE PIN, on the thing that drifted: the guard must delegate to the
    runner's roll-up for a report carrying its inputs."""
    src = (PROGRAMS / "vibe_ic_entry_guard.py").read_text()
    assert "_roll_up(" in src, (
        "the guard no longer calls the runner's roll-up; a second copy of the "
        "conjunction rule is what discarded genuine reports as forged")
    assert "import vibe_ic_one_shot_runner" in src


def test_main_always_supplies_the_axis():
    """THE PIN THAT KEEPS THE STRICT PATH FROM BEING BYPASSED.

    `_roll_up` applies the fail-closed audit rule only when an axis is SUPPLIED,
    because a caller passing none is not talking about the completion audit (#505's
    properties are stated that way). That scoping is only safe while the real
    front door always supplies one — so this asserts main's call site does, by AST,
    on the keyword rather than on surrounding text.
    """
    import ast
    tree = ast.parse((PROGRAMS / "vibe_ic_one_shot_runner.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_roll_up"]
    assert calls, "main no longer rolls up through `_roll_up`"
    kwargs = [{k.arg for k in c.keywords} for c in calls]
    assert any("audit_axis" in kw and "demoted" in kw for kw in kwargs), (
        f"main's roll-up call does not supply `audit_axis`/`demoted`, so the "
        f"fail-closed audit rule and the #505 demotion exemption are both "
        f"unreachable on a real run; keywords seen: {kwargs}")
    # and the axis it supplies is the one tied to this invocation
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "_completion_audit_axis(" in src and "phase3_ran=_phase3_ran" in src
    # PHASE 3's start, not the run's: a document written before phase3 began
    # cannot be phase3's refresh of it.
    assert 'started_at=_phase_started.get("phase3", t0)' in src


# ── R-0915-151: freshness on the CARRIED verdict, and on the rows ───────────



WHOLE = {"whole_flow": True, "step_count": 70, "flow_step_total": 70}




















def test_a_blocking_return_the_classifier_did_not_classify_drops_the_sidecar():
    """THE OTHER HALF OF THE DEMOTION, in phase1's own runner.

    The sidecar is written BEFORE three later blocking returns — the L8 clock-period
    conflict, the extraction gap, the semantic layer gates — and its classifier knows
    nothing about any of them. All three `return 1`, the same rc the coverage-only path
    returns, so no reader can separate them by exit code: the #505 demotion would take
    a NON-coverage phase1 failure and publish PASS_WITH_WAIVERS at exit 0. My rc==1
    guard alone does NOT close that, which is why this half is here.

    Each of those returns now removes the sidecar it would otherwise leave. Pinned by
    AST on the call, and by position: the drop must precede the return it guards.
    """
    import ast
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert src.count("_drop_v0_3_7_exit_reason(project)") >= 3, (
        "fewer than three unclassified blocking returns drop the sidecar")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_drop_v0_3_7_exit_reason")
    assert "unlink" in ast.unparse(fn), "the drop does not remove anything"
    # every drop sits immediately before a `return 1`, never after it
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "_drop_v0_3_7_exit_reason(project)" in line and "def " not in line:
            nxt = next((l.strip() for l in lines[i + 1:i + 3] if l.strip()), "")
            assert nxt.startswith("return"), (i + 1, nxt)






def test_phase1s_producer_resolves_its_report_through_the_router():
    """The premise, pinned against the producer itself, in BOTH directions.

    No flat write may remain, and every write of this report must go through the router --
    so if anyone reintroduces `reports / "phase1_one_shot.json"`, this arm says so instead
    of the front door silently reading a path nothing writes again.
    """
    import ast
    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text()
    assert 'reports / "phase1_one_shot.json"' not in src, (
        "phase1's runner writes the flat path again; `reports_subfolder_taxonomy_check` "
        "FAILS on that location and the front door resolves only the router's")

    tree = ast.parse(src)
    routed = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "report_path"
                and any(isinstance(a, ast.Constant) and a.value == "phase1_one_shot.json"
                        for a in node.args)):
            routed += 1
    assert routed >= 3, (
        f"only {routed} of phase1's writes of this report resolve through the router; "
        f"measured, the runner has three write sites")




# ── the round-2 M, now that 70 sits on 77 ────────────────────────────────────









# ── a phase whose PROCESS failed and left no report ──────────────────────────







# ── the RE-RUN cases (R-0915-160 second cut) ─────────────────────────────────









# ── H5: the AI-backup re-invocation, driven END TO END ──────────────────────
#
# THE DEFECT (review wjn67aev3, MEDIUM #2). The front door may demote a coverage-only phase-1
# FAIL, and for a FIRST pass it decides the sidecar is this invocation's by mtime against the
# phase-1 start. On the expert SECOND pass that is wrong -- the pass carries pass 1's record and
# never rewrites the sidecar -- so the record NAMES the sidecar by content instead.
#
# r7 got the producer half backwards: the second pass named it only when
# `sidecar.mtime >= record.mtime`, while pass 1 writes the sidecar FIRST (in-process, from inside
# D1) and its record LAST. So on every real re-invocation nothing was named, the front door read
# "NOT demoting", and a `--skip-phase3` coverage-only project that was PASS_WITH_WAIVERS flipped
# to FAIL and halted at phase 1.
#
# AND NEITHER HALF'S ARMS COULD SEE IT: the producer fixture staged the sidecar at `record + 10s`,
# the reverse of the real order, and the reader arm asserted source substrings without ever
# calling `main()`. These three arms drive the REAL `main()`, in the REAL write order, with the
# REAL `run_second_pass_only` doing the carrying.

















# #3168 — the bounded publisher writes a token-scoped terminal account. Drive
# BOTH real main branches; stage only external execution/admission boundaries.
def _drive_bounded_phase3_receiver(front, project, monkeypatch, *, route="entry",
                                  child_document=None, child_rc=0,
                                  canonical_bytes=None, parent_token=None,
                                  published_token=None, report_mtime=None,
                                  phase_clock=None):
    """Reusable receiver replay, compatible with base and candidate main().

    `child_document(token)` returns bytes, or None to publish nothing. A caller
    may feed unchanged historical sender bytes and control token/clock/mtime:
    that proves receiver behavior, never new native execution. No new product
    helper is called here, so a base reversal fails on values, not a missing API.
    Use only an owned temporary project; admission and image I/O are fixtures.
    """
    from types import SimpleNamespace
    import secrets

    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    stage_owner_route(project, "ic")
    monkeypatch.setattr(front, "_configure_execution_policy",
                        lambda _args: {"mode": "default"})
    monkeypatch.setattr(front, "_capture_container_image",
                        lambda *_args: {"verdict": "PASS",
                                         "scope": "SOURCE_CONTROL: image I/O fixture"})
    monkeypatch.setattr(front._canonical_admission, "admit_span", lambda *a, **k:
                        SimpleNamespace(admitted=True, identity_sha256="source-control"))
    monkeypatch.setattr(front._canonical_admission, "child_env",
                        lambda _identity, env: dict(env))
    monkeypatch.setattr(front, "_phase1_decision", lambda *a, **k: (True, "docs"))
    if parent_token is not None:
        monkeypatch.setattr(secrets, "token_hex", lambda _n: parent_token)
    if phase_clock is not None:
        monkeypatch.setattr(front.time, "time", lambda: phase_clock)
    monkeypatch.delenv("VIBEIC_RUNNER_INVOCATION_CONTEXT", raising=False)
    trace = []
    published = {}

    def child(label, runner, args, env=None):
        trace.append({"label": label, "runner": str(runner), "argv": args})
        if runner.name in ("phase1_one_shot_runner.py", "phase2_one_shot_runner.py",
                           "design_one_shot_runner.py"):
            name = ("phase1_one_shot.json" if runner.name.startswith("phase1")
                    else "phase2_one_shot.json")
            p = _pl.report_path(project, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"verdict":"PASS","scope":"SOURCE_CONTROL child fixture"}\n')
            return 0
        if runner.name == "flow_compliance_check.py" and "stage_analog" in args:
            p = Path(args[args.index("--json") + 1])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"verdict":"PASS","scope":"SOURCE_CONTROL child fixture"}\n')
            return 0
        assert runner.name == "phase3_one_shot_runner.py", trace
        token = env["VIBEIC_PHASE3_WINDOW_RUN_ID"]
        canonical = project / "reports/orchestrator/phase3_one_shot.json"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_bytes(canonical_bytes if canonical_bytes is not None else
                              b'{"program":"phase3_one_shot_runner","record":"in-progress","steps":[]}\n')
        published["canonical_before"] = canonical.read_bytes().hex()
        published["parent_token"] = token
        raw = child_document(token) if child_document is not None else None
        if raw is not None:
            # Publisher contract is staged on disk independently of the reader.
            path = project / "reports/orchestrator/windows" / (published_token or token) / "phase3_one_shot.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            if report_mtime is not None:
                os.utime(path, (report_mtime, report_mtime))
            published["scoped_path"] = str(path)
            published["scoped_before"] = raw.hex()
        return child_rc

    monkeypatch.setattr(front, "_run_phase", child)
    flags = (["--entry-step", "15", "--exit-step", "16"] if route == "entry"
             else ["--exit-step", "16"])
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner", str(project),
                                     "--no-dashboard", "--skip-analog", *flags])
    rc = front.main()
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    report = json.loads(out.read_text())
    canonical = project / "reports/orchestrator/phase3_one_shot.json"
    published["canonical_after"] = canonical.read_bytes().hex()
    if "scoped_path" in published:
        published["scoped_after"] = Path(published["scoped_path"]).read_bytes().hex()
    observation = {"scope": "SOURCE_CONTROL receiver replay; no native child",
                   "route": route, "rc": rc, "summary": report,
                   "child_rc": child_rc, "trace": trace, "published": published}
    (project / "receiver.observation.json").write_text(
        json.dumps(observation, indent=2) + "\n")
    return observation


def _bounded_terminal(token, *, verdict="PASS", route="entry", stale=True):
    return json.dumps({"program": "phase3_one_shot_runner", "bounded": True,
                       "window_run_id": token,
                       "declared_window": {"entry_step": "15" if route == "entry" else "9",
                                           "exit_step": "16"},
                       "verdict": verdict, "audit_verdict": verdict,
                       "audit_scope": "bounded; full declared gates for selected steps",
                       "stale_downstream": ({"17": {"status": "NOT_MEASURED"}}
                                            if stale else {}),
                       "bounded_disclosures": [{"refresh": "whole-flow", "kind": "skipped"}]
                       }).encode() + b"\n"


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_consumes_its_exact_terminal_report(project, monkeypatch, route):
    other = project / "reports/orchestrator/windows/newer-unrelated/phase3_one_shot.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(_bounded_terminal("newer-unrelated", verdict="FAIL"))
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, route=route))
    doc = obs["summary"]
    assert obs["rc"] == 0, obs
    assert doc["bounded"] is True and doc["dispatched_verdict"] == "PASS", doc
    assert doc["verdict"] == "NOT_MEASURED" and doc["audit_verdict"] == "NOT_MEASURED", doc
    assert doc["stale_downstream"] == {"17": {"status": "NOT_MEASURED"}}, doc
    assert obs["published"]["canonical_before"] == obs["published"]["canonical_after"]
    assert obs["published"]["scoped_before"] == obs["published"]["scoped_after"]
    p3 = next(t for t in obs["trace"] if Path(t["runner"]).name == "phase3_one_shot_runner.py")
    assert p3["argv"][p3["argv"].index("--entry-step") + 1] == ("15" if route == "entry" else "9")


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_propagates_terminal_failure(project, monkeypatch, route):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict="FAIL", route=route),
        child_rc=1)
    assert obs["rc"] == 1, obs
    assert obs["summary"]["dispatched_verdict"] == "FAIL", obs
    assert obs["summary"]["verdict"] == "FAIL", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("damage", ["missing", "malformed", "nonobject", "wrong-id",
                                     "wrong-directory", "stale", "missing-verdict", "unknown-verdict",
                                     "unbounded-account"])
def test_bounded_main_never_takes_unusable_or_other_terminal_as_dispatch_pass(
        project, monkeypatch, route, damage):
    def sender(token):
        if damage == "missing":
            return None
        if damage == "malformed":
            return b"{"
        if damage == "nonobject":
            return b"[]"
        if damage == "wrong-id":
            return _bounded_terminal("not-this-parent", route=route)
        d = json.loads(_bounded_terminal(token, route=route))
        if damage == "missing-verdict":
            del d["verdict"]
        if damage == "unknown-verdict":
            d["verdict"] = "UNRECOGNIZED"
        if damage == "unbounded-account":
            d["bounded"] = False
        return json.dumps(d).encode()
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=sender,
        published_token="different-window" if damage == "wrong-directory" else None,
        report_mtime=1 if damage == "stale" else None)
    assert obs["summary"].get("dispatched_verdict") != "PASS", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] != "PASS", obs
    assert obs["summary"]["verdict"] != "PASS", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
def test_bounded_main_canonical_pass_cannot_replace_its_missing_window(
        project, monkeypatch, route):
    token = "1" * 32
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        parent_token=token, canonical_bytes=_bounded_terminal(token, route=route),
        child_document=None)
    assert obs["summary"].get("dispatched_verdict") != "PASS", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] != "PASS", obs
    assert obs["rc"] != 0, obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("valid_identity", [True, False], ids=["current", "wrong-id"])
def test_bounded_main_retains_nonzero_child_rc(project, monkeypatch, route, valid_identity):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(
            token if valid_identity else "not-this-parent", route=route), child_rc=7)
    assert obs["rc"] == 7, obs
    phase = next(r for r in obs["summary"]["phases"] if r["name"] == "phase3")
    assert phase["rc"] == 7, phase
    assert phase["verdict"] == ("PASS" if valid_identity else
                                "FAIL" if route == "forwarded" else "NOT_MEASURED"), phase






@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("verdict", ["UNRECOGNIZED", ["PASS"]])
def test_bounded_invalid_verdict_is_unmeasured_non_success(
        project, monkeypatch, route, verdict):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict=verdict, route=route))
    assert obs["rc"] != 0, obs
    assert obs["summary"]["dispatched_verdict"] == "NOT_MEASURED", obs
    assert next(r for r in obs["summary"]["phases"]
                if r["name"] == "phase3")["verdict"] == "NOT_MEASURED", obs


@pytest.mark.parametrize("route", ["entry", "forwarded"])
@pytest.mark.parametrize("verdict", ["PASS", "PASS_WITH_WAIVERS"])
def test_bounded_success_keeps_whole_flow_unmeasured_without_stale_rows(
        project, monkeypatch, route, verdict):
    obs = _drive_bounded_phase3_receiver(V, project, monkeypatch, route=route,
        child_document=lambda token: _bounded_terminal(token, verdict=verdict,
                                                       route=route, stale=False))
    assert obs["rc"] == 0, obs
    assert obs["summary"]["dispatched_verdict"] == verdict, obs
    assert obs["summary"]["verdict"] == "NOT_MEASURED", obs
    assert obs["summary"]["whole_flow_verdict"] == "NOT_MEASURED", obs






















# The checkpoint consumer is a software boundary here, not an IC producer.
# Its real retained inputs, signed review, identity and output recorder still
# run; the leaf supplies the existing pass-with-note tier and its exact reason.
