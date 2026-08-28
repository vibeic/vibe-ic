#!/usr/bin/env python3
"""v0.3.2 — ORGANIC-20260606 #497 ROUND-2 (MEDIUM): the gate/lint JSON
identity-stamp coverage gap that round-1 (#497) left open.

ROUND-1 stamped the phase2 CENTRAL manifest writer (step_emit_phase2_manifests'
`w()`) + the complexity-advisory writer, and its self-test (test_v0_3_1_…)
only covered those touched families. But the per-gate report writers under
reports/phase2/gates/*.json and reports/phase2/lint/*.json are NOT the manifest
writer — they are the gate-checker PROGRAMS (cdc_async_input_check,
rtl_hygiene_lint, rom_init_lint, …) run by the YAML workflow via
flow_compliance_check.py during step_final_audit. They write
json.dumps(asdict(result)) (a dict with a PASS-shaped verdict) — or, for the
lint families, a bare findings LIST (`[]`) — with NO identity, and they run
AFTER step_emit_phase2_manifests, OVERWRITING the manifest writer's stamped
copies. A fresh two-design regeneration WITH gate audits therefore still ships
byte-identical-but-honest gate jsons across DIFFERENT chips, and the PASS-shape
is hard-excluded from cross_design_identity_check's honest-N/A exemption, so no
exemption can save them.

ROUND-2 FIX (caller-side, the field agent explicitly allows '呼叫端 stamp'):
design_one_shot_runner gains a generic post-write sweep
(`_stamp_gate_report_dirs`, wired as `step_stamp_gate_reports` AFTER
step_final_audit) that folds the SAME #484 identity field shape into EVERY
*.json under reports/phase2/gates/ + reports/phase2/lint/ — guaranteeing
coverage of all 12+ files however they were produced. A dict gets a
`design_identity` key via setdefault (payload preserved byte-for-byte); a list
is wrapped {"findings": <list>, "design_identity": {...}} (no finding dropped;
these jsons are consumed only as evidence-presence pointers).

THIS TEST CLOSES THE SELF-TEST GAP: it exercises the layer the field agent said
was untested — the gate/lint json families written by the REAL gate-checker
programs via their `--json PATH` — and its acceptance replays the field agent's
failing scenario end-to-end (two-design regen INCLUDING gate audits →
cross_design_identity_check findings == 0).

chip-AGNOSTIC: synthetic generic fixtures only (deny-list-safe invented tokens).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as p2  # noqa: E402
import _path_layout as _pl  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

CDI_PROG = PROGRAMS / "cross_design_identity_check.py"

# The two gate-audit dirs the field agent named (and the runner now sweeps).
GATE_DIR = "reports/phase2/gates"
LINT_DIR = "reports/phase2/lint"


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────
def _run_cdi(projects, allow_honest_na=False):
    args = [sys.executable, str(CDI_PROG)] + [str(p) for p in projects]
    if allow_honest_na:
        args.append("--allow-honest-na")
    r = subprocess.run(args, capture_output=True, text=True)
    return json.loads(r.stdout), r.returncode


def _mk_l_docs(project: Path, ic_name: str, top: str | None = None) -> None:
    gd = _pl.generated_docs_dir(project)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": ic_name}))
    if top:
        (gd / "L9_INTEGRATION_SPEC.json").write_text(
            json.dumps({"top_module": top}))


def _run_real_gate_checkers(project: Path) -> None:
    """Drive the REAL gate-checker programs exactly as flow_compliance_check.py
    does during step_final_audit: subprocess, cwd=project, identity-less
    `--json reports/phase2/{gates,lint}/...`. Produces a representative set of
    the #497-r2 families:

      * reports/phase2/gates/cdc_async_input.json   (dict, PASS-shape verdict)
      * reports/phase2/lint/rtl_hygiene.json        (LIST `[]`)
      * reports/phase2/lint/rom_init_lint.json      (LIST `[]`)

    These are the families the round-1 manifest stamp could not reach (the
    checkers overwrite them), so they are byte-identical across designs absent
    the round-2 caller-side sweep.
    """
    rtl = _pl.rtl_dir(project)
    rtl.mkdir(parents=True, exist_ok=True)
    # identical minimal RTL across designs → identical checker payloads.
    rtl_file = rtl / "top.v"
    rtl_file.write_text(
        "module top(input a, output b); assign b=a; endmodule\n")
    (project / GATE_DIR).mkdir(parents=True, exist_ok=True)
    (project / LINT_DIR).mkdir(parents=True, exist_ok=True)

    invocations = [
        ["cdc_async_input_check.py", ".",
         "--json", f"{GATE_DIR}/cdc_async_input.json"],
        ["rtl_hygiene_lint.py", str(rtl_file.relative_to(project)),
         "--severity", "ERROR", "--json", f"{LINT_DIR}/rtl_hygiene.json"],
        ["rom_init_lint.py", str(rtl_file.relative_to(project)),
         "--json", f"{LINT_DIR}/rom_init_lint.json"],
    ]
    for inv in invocations:
        _pr.run(
            [sys.executable, str(PROGRAMS / inv[0])] + inv[1:],
            cwd=project, capture_output=True, text=True)


def _regen_with_gate_audit(project: Path, ic_name: str,
                           top: str | None = None) -> None:
    """A fresh single-design regeneration INCLUDING the gate audit: build L
    docs + RTL, run the REAL gate checkers (the identity-less writers), then run
    the runner's caller-side stamp sweep — exactly the post-step_final_audit
    sequence the runner performs in main()."""
    _mk_l_docs(project, ic_name, top)
    _run_real_gate_checkers(project)
    p2._stamp_gate_report_dirs(project)


_FAMILIES = (
    f"{GATE_DIR}/cdc_async_input.json",
    f"{LINT_DIR}/rtl_hygiene.json",
    f"{LINT_DIR}/rom_init_lint.json",
)


# ──────────────────────────────────────────────────────────────────────────
# unit: the stamp helper preserves the checker payload + handles dict/list
# ──────────────────────────────────────────────────────────────────────────
def test_r2_stamp_dict_payload_preserved_and_setdefault(tmp_path):
    """A dict gate report keeps every original key; only `design_identity` is
    added (setdefault — a pre-existing stamp is never clobbered)."""
    fp = tmp_path / "g.json"
    original = {"program": "cdc_async_input_check", "passed": True,
                "findings": [], "summary": {"x": 1}}
    fp.write_text(json.dumps(original))
    ident = {"design": "datacore_alpha", "ic_name": "core_alpha"}
    assert p2._stamp_design_identity_in_file(fp, ident) is True
    out = json.loads(fp.read_text())
    # every original key preserved byte-equivalently
    for k, v in original.items():
        assert out[k] == v
    assert out["design_identity"] == ident
    # idempotent — second call is a no-op
    assert p2._stamp_design_identity_in_file(fp, ident) is False
    assert json.loads(fp.read_text()) == out


def test_r2_stamp_list_payload_wrapped_no_finding_dropped(tmp_path):
    """A bare findings LIST (the lint shape) is wrapped so the stamp rides
    along WITHOUT dropping any finding."""
    fp = tmp_path / "lint.json"
    findings = [{"path": "top.v", "sev": "WARN", "rule": "unread-reg"}]
    fp.write_text(json.dumps(findings))
    ident = {"design": "datacore_beta", "ic_name": "core_beta"}
    assert p2._stamp_design_identity_in_file(fp, ident) is True
    out = json.loads(fp.read_text())
    assert out["findings"] == findings  # no finding dropped
    assert out["design_identity"] == ident


def test_r2_stamp_empty_list_still_carries_stamp(tmp_path):
    """The clean-run empty-list lint (`[]`) — the exact byte-identical
    offender — becomes a per-design-stamped dict."""
    fp = tmp_path / "rtl_hygiene.json"
    fp.write_text("[]")
    ident = {"design": "datacore_gamma"}
    assert p2._stamp_design_identity_in_file(fp, ident) is True
    out = json.loads(fp.read_text())
    assert out == {"findings": [], "design_identity": ident}


def test_r2_stamp_scalar_and_parse_error_untouched(tmp_path):
    """A scalar / non-JSON file carries no per-design substance and is left
    untouched (not a report-class artifact)."""
    scalar = tmp_path / "s.json"
    scalar.write_text("42")
    assert p2._stamp_design_identity_in_file(scalar, {"design": "x"}) is False
    assert scalar.read_text() == "42"
    broken = tmp_path / "b.json"
    broken.write_text("{not json")
    assert p2._stamp_design_identity_in_file(broken, {"design": "x"}) is False


def test_r2_stamp_never_clobbers_existing_identity(tmp_path):
    """An already-stamped dict (different design) is never overwritten."""
    fp = tmp_path / "g.json"
    pre = {"verdict": "PASS", "design_identity": {"design": "someone_else"}}
    fp.write_text(json.dumps(pre))
    assert p2._stamp_design_identity_in_file(
        fp, {"design": "datacore_delta"}) is False
    assert json.loads(fp.read_text()) == pre


# ──────────────────────────────────────────────────────────────────────────
# the sweep covers ALL jsons under BOTH dirs (gates AND lint)
# ──────────────────────────────────────────────────────────────────────────
def test_r2_sweep_covers_all_gate_and_lint_jsons(tmp_path):
    proj = tmp_path / "datacore_alpha"
    _mk_l_docs(proj, "core_alpha")
    _run_real_gate_checkers(proj)
    # pre-sweep: NONE carry a stamp (written by the identity-less checkers)
    for rel in _FAMILIES:
        d = json.loads((proj / rel).read_text())
        has = isinstance(d, dict) and "design_identity" in d
        assert not has, f"{rel} unexpectedly pre-stamped"
    stamped = p2._stamp_gate_report_dirs(proj)
    # every family is now covered (gates dict + lint lists)
    for rel in _FAMILIES:
        assert rel in stamped, f"{rel} not stamped by the sweep"
        d = json.loads((proj / rel).read_text())
        assert d["design_identity"]["design"] == "datacore_alpha"
        assert d["design_identity"]["ic_name"] == "core_alpha"


def test_r2_sweep_is_idempotent(tmp_path):
    proj = tmp_path / "datacore_alpha"
    _mk_l_docs(proj, "core_alpha")
    _run_real_gate_checkers(proj)
    first = set(p2._stamp_gate_report_dirs(proj))
    assert first  # something was stamped
    # snapshot bytes, re-run, assert unchanged + nothing re-stamped
    before = {rel: (proj / rel).read_bytes() for rel in _FAMILIES}
    second = p2._stamp_gate_report_dirs(proj)
    assert second == []
    for rel, b in before.items():
        assert (proj / rel).read_bytes() == b


def test_r2_gate_lint_jsons_differ_per_design(tmp_path):
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    _regen_with_gate_audit(a, "core_alpha")
    _regen_with_gate_audit(b, "core_beta")
    for rel in _FAMILIES:
        fa, fb = (a / rel), (b / rel)
        assert fa.is_file() and fb.is_file(), rel
        # identical inputs → identical checker payloads, but the per-design
        # stamp makes the bytes DIFFER (the core fix).
        assert fa.read_bytes() != fb.read_bytes(), rel
        assert json.loads(fa.read_text())["design_identity"]["ic_name"] == \
            "core_alpha"
        assert json.loads(fb.read_text())["design_identity"]["ic_name"] == \
            "core_beta"


# ──────────────────────────────────────────────────────────────────────────
# CONTROL: prove the stamp is what does the work (strip it → collide)
# ──────────────────────────────────────────────────────────────────────────
def test_r2_control_without_stamp_collides(tmp_path):
    """Without the round-2 sweep the gate/lint jsons are byte-identical across
    designs → cross_design_identity_check MUST flag every #497-r2 family."""
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    _mk_l_docs(a, "core_alpha")
    _mk_l_docs(b, "core_beta")
    _run_real_gate_checkers(a)
    _run_real_gate_checkers(b)
    # NO sweep → identity-less, byte-identical.
    rep, rc = _run_cdi([a, b])
    assert rep["verdict"] == "FAIL"
    msgs = " ".join(f["message"] for f in rep["findings"])
    for rel in _FAMILIES:
        assert Path(rel).name in msgs, f"{rel} must collide without the stamp"


# ──────────────────────────────────────────────────────────────────────────
# ACCEPTANCE (field): fresh two-design regen INCLUDING gate audits → findings 0
# ──────────────────────────────────────────────────────────────────────────
def test_r2_acceptance_two_design_regen_with_gate_audits_findings_zero(
        tmp_path):
    """ACCEPTANCE (verbatim field 驗收): fresh two-design regeneration
    INCLUDING gate audits → cross_design_identity_check findings == 0 for the
    gate/lint families, WITHOUT the honest-N/A exemption crutch (PASS-shaped
    gate jsons can never ride it) — the per-design stamp alone differentiates
    them."""
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    _regen_with_gate_audit(a, "core_alpha", "top_alpha")
    _regen_with_gate_audit(b, "core_beta", "top_beta")

    rep, rc = _run_cdi([a, b])
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["identical_artifacts"] == 0
    assert rc == 0
    # none of the gate/lint families appear in findings
    msgs = " ".join(f["message"] for f in rep["findings"])
    for rel in _FAMILIES:
        assert Path(rel).name not in msgs


# ──────────────────────────────────────────────────────────────────────────
# ADVERSARIAL (field): a byte-identical canned PASS pair (outside the stamped
# flow) is STILL flagged — the fix is NOT a blanket exemption.
# ──────────────────────────────────────────────────────────────────────────
def test_r2_adversarial_canned_pass_pair_still_flagged(tmp_path):
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    _regen_with_gate_audit(a, "core_alpha")
    _regen_with_gate_audit(b, "core_beta")

    # A canned cross-design coverage PASS planted OUTSIDE the swept dirs (so it
    # is never stamped) — the #436 violation class.
    canned_pass = {
        "verdict": "PASS",
        "evidence": "reports/some_log.txt",
        "scenarios_covered": ["get_id", "get_state"],
        "note": "canned cross-design coverage (the #436 violation class)",
    }
    for proj in (a, b):
        fp = proj / "reports" / "phase2" / "coverage" / "coverage_actual.json"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(canned_pass, indent=2) + "\n")

    for flag in (False, True):
        rep, rc = _run_cdi([a, b], allow_honest_na=flag)
        assert rep["verdict"] == "FAIL", f"canned PASS must FAIL (flag={flag})"
        assert rc == 1
        assert any("coverage_actual.json" in f["message"]
                   for f in rep["findings"]), flag
        # never silently exempted
        assert not any("coverage_actual.json" in e["path"]
                       for e in rep.get("honest_na_exempt", [])), flag
        # the honest #497-r2 gate/lint families are NOT among the findings
        for rel in _FAMILIES:
            assert not any(Path(rel).name in f["message"]
                           for f in rep["findings"]), (rel, flag)


# ──────────────────────────────────────────────────────────────────────────
# step wrapper: never fails the run, reports the stamped count
# ──────────────────────────────────────────────────────────────────────────
def test_r2_step_stamp_gate_reports_status_and_count(tmp_path):
    proj = tmp_path / "datacore_alpha"
    _mk_l_docs(proj, "core_alpha")
    _run_real_gate_checkers(proj)
    sr = p2.step_stamp_gate_reports(proj)
    assert sr.status == "PASS"
    assert sr.extras["stamped_count"] == len(_FAMILIES)
    # second call: idempotent — still PASS, zero freshly stamped
    sr2 = p2.step_stamp_gate_reports(proj)
    assert sr2.status == "PASS"
    assert sr2.extras["stamped_count"] == 0


def test_r2_step_stamp_no_dirs_is_noop_pass(tmp_path):
    """A project with no gate/lint dirs (e.g. a precheck-FAIL run) → PASS,
    zero stamped, never raises."""
    proj = tmp_path / "datacore_empty"
    proj.mkdir()
    sr = p2.step_stamp_gate_reports(proj)
    assert sr.status == "PASS"
    assert sr.extras["stamped_count"] == 0


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", __file__]))
