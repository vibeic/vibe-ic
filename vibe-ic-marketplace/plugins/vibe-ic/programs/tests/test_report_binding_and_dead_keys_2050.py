"""#2050 items 1-3 — the 27 sibling IDs, phase1's dead key, and the skip.

ITEM 1. v1.17.76 (#2048) made the shared skill-compliance checker
output-type-aware and repointed nine audit IDs on the three report-typed specs.
Twenty-seven `postcheck_pass_only` IDs remained, all on specs whose
`testability` is `structured` — which is a TEST-FIXTURE TIER (see
`_shared/TESTING_STRATEGY.md`), not a statement about the deliverable, so it
never licensed the RTL header contract.

Read per skill, from its own `## Output format`, all fifteen deliverables are
documents. Two independent measurements agree:

  * every one of the fifteen names a `.md` (or an inline Markdown template) as
    its deliverable, and
  * ZERO of the 70 SKILL.md files in this plugin — measured, not sampled —
    documents emitting `// Post-checks: rtl_hygiene_lint=...`, which is the
    only string `postcheck_pass_only` reads.

So the "kept" bucket is empty and every one of the 27 is repointed. That is a
finding, not an oversight: after this change NO compliance.yaml selects
`postcheck_pass_only`. The rule stays in the engine, still tested directly, and
is still the right contract the day an RTL-emitting skill declares
`output_type: rtl`.

ITEM 2. `skills/phase1/compliance.yaml` carried two cross-checks under a
top-level `postchecks:` key. `audit()` reads `output_type`, `requirements` and
`cross_checks`; it has never read `postchecks`. The entries were DEAD — not
no-op-passing, as the note beside them claimed — and phase1's own compliance
run was green while asserting neither of them. The key is deleted and the class
of defect is closed by a new blocking finding, `compliance_yaml_unread_key`.

ITEM 3. `test_good_output_passes_all_required` called `pytest.skip()` before
its assert. Measured on v1.17.79: of the 69 skills shipping that generated
test, 53 skipped and 16 asserted. The blanket skip is replaced by a NAMED
per-skill list in `_shared/synthetic_fixture_limits.py`, checked in BOTH
directions.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_SKILLS = _PLUGIN / "skills"
_CHECKER = _PLUGIN / "_shared" / "skill_compliance_check.py"

sys.path.insert(0, str(_PLUGIN / "_shared"))
import skill_compliance_check as scc  # noqa: E402
import synthetic_fixture_limits as limits  # noqa: E402

# The 27, by (skill, cross-check id, auditor), as MEASURED on v1.17.79 before
# the change. Enumerated so the repointing is a membership statement rather
# than a count: a substitution cannot disturb a set.
_THE_27 = {
    ("ams-sim", "X_eda_log_check", "eda_log_check"),
    ("ams-sim", "X_corner_coverage_audit", "corner_coverage_audit"),
    ("analog-layout", "X_output_artifact_check", "output_artifact_check"),
    ("analog-sizing", "X_output_artifact_check", "output_artifact_check"),
    ("drc-fix", "X_gds_size_check", "gds_size_check"),
    ("drc-fix", "X_mcp_execution_verify", "mcp_execution_verify"),
    ("drc-fix", "X_drc_report_check", "drc_report_check"),
    ("equivalence-check", "X_eda_log_check", "eda_log_check"),
    ("formal-verify", "X_eda_log_check", "eda_log_check"),
    ("fpga-hps-bridge", "X_output_artifact_check", "output_artifact_check"),
    ("fpga-signaltap", "X_output_artifact_check", "output_artifact_check"),
    ("hls-c2rtl", "X_output_artifact_check", "output_artifact_check"),
    ("hold-fix", "X_eda_log_check", "eda_log_check"),
    ("ir-drop-triage", "X_eda_log_check", "eda_log_check"),
    ("ir-drop-triage", "X_mcp_execution_verify", "mcp_execution_verify"),
    ("ir-drop-triage", "X_ir_drop_report_check", "ir_drop_report_check"),
    ("lvs-triage", "X_synth_netlist_check", "synth_netlist_check"),
    ("lvs-triage", "X_mcp_execution_verify", "mcp_execution_verify"),
    ("lvs-triage", "X_lvs_report_check", "lvs_report_check"),
    ("rtl-repair", "X_output_artifact_check", "output_artifact_check"),
    ("sta-review", "X_corner_coverage_audit", "corner_coverage_audit"),
    ("sta-review", "X_mcp_execution_verify", "mcp_execution_verify"),
    ("sta-review", "X_sta_report_check", "sta_report_check"),
    ("synth-doctor", "X_synth_netlist_check", "synth_netlist_check"),
    ("synth-doctor", "X_sv_compat_check", "sv_compat_check"),
    ("synth-doctor", "X_mcp_execution_verify", "mcp_execution_verify"),
    ("synth-doctor", "X_eda_log_check", "eda_log_check"),
}
_THE_15 = sorted({s for s, _, _ in _THE_27})


def _spec(skill):
    return scc._load_yaml(_SKILLS / skill / "compliance.yaml")


# ---------------------------------------------------------------------------
# Item 1 — the 27
# ---------------------------------------------------------------------------
def test_all_twenty_seven_are_bound_to_their_own_auditors_receipt():
    got = set()
    for skill in _THE_15:
        for c in (_spec(skill).get("cross_checks") or []):
            if c.get("rule") == "audit_receipt_evidence":
                got.add((skill, c["id"], c.get("auditor")))
    assert got >= _THE_27, sorted(_THE_27 - got)


def test_the_fifteen_declare_the_output_type_that_binding_rests_on():
    for skill in _THE_15:
        assert _spec(skill).get("output_type") == "report", skill


def test_no_compliance_yaml_selects_the_rtl_header_rule_any_more():
    """The kept bucket is EMPTY and that is the measured outcome, not a
    slip. Every deliverable in the tree is a document today."""
    offenders = []
    for y in sorted(_SKILLS.glob("*/compliance.yaml")):
        for c in (scc._load_yaml(y).get("cross_checks") or []):
            if c.get("rule") == "postcheck_pass_only":
                offenders.append(f"{y.parent.name}:{c.get('id')}")
    assert offenders == [], offenders


def test_the_rtl_header_rule_is_still_present_and_still_strict():
    """Nothing selects it; nothing deleted it either. Removing a correct
    contract because it is currently unused is how the next RTL-emitting
    skill ships with no post-check gate at all."""
    assert "postcheck_pass_only" in scc.CROSS_CHECK_RULES
    f, = scc._cc_postcheck_pass_only({"id": "t"}, "no header here")
    assert f.severity == "FAIL"
    assert scc._cc_postcheck_pass_only(
        {"id": "t"},
        "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS") == []


def test_no_skill_md_documents_emitting_the_rtl_post_check_header():
    """The measurement the repointing rests on, as a standing assertion.
    If a skill ever DOES document emitting it, this fails and the decision for
    that skill must be revisited rather than inherited."""
    carriers = [p.parent.name for p in sorted(_SKILLS.glob("*/SKILL.md"))
                if "Post-checks:" in p.read_text(errors="replace")]
    assert carriers == [], carriers


@pytest.mark.parametrize("skill", _THE_15)
def test_each_repointed_skill_still_rejects_a_fabricated_header(skill):
    """Repointing removes the reason to paste the header; this keeps pasting
    one a failure, or the string would become unremarked now that nothing
    else reacts to it."""
    ids = {c["id"]: c.get("rule")
           for c in (_spec(skill).get("cross_checks") or [])}
    assert ids.get("X_text_only_skill") == "text_only_report", skill


def _drive(tmp_path, skill, text, receipts=None):
    d = tmp_path / "w"
    d.mkdir(parents=True, exist_ok=True)
    for name, payload in (receipts or {}).items():
        (d / name).write_text(json.dumps(payload))
    rep = d / "report.md"
    rep.write_text(text)
    oj = d / "audit.json"
    r = subprocess.run(
        [sys.executable, str(_CHECKER),
         "--requirements", str(_SKILLS / skill / "compliance.yaml"),
         "--json", str(oj), str(rep)], capture_output=True, text=True)
    return r, json.loads(oj.read_text())


_HLS_REPORT = """# HLS report

## Output
Directive log and PPA estimate for the synthetic module.
The generated RTL is written to hls/synthetic_module.v.

## Summary
**STATUS**: OK

Next: run /vibe-ic-phase2
"""
_RTL_HEADER = "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS\n"

# The shape `programs/output_artifact_check.py` writes through
# `programs/_audit_receipt.py::build_receipt`. SYNTHETIC — not from a real run.
_OA_RECEIPT = {
    "receipt_version": 1,
    "auditor": "output_artifact_check",
    "verdict": "PASS",
    "examined": 2,
    "subject": {"basis": "content", "items": [], "sha256": "0" * 64},
    "note": "SYNTHETIC FIXTURE — not produced by a real audit run",
}


def test_compliant_prose_with_a_real_receipt_passes(tmp_path):
    """Control, direction one."""
    r, data = _drive(tmp_path, "hls-c2rtl", _HLS_REPORT,
                     {"output_artifact_check_receipt.json": _OA_RECEIPT})
    st, = [f for f in data["findings"] if f["id"] == "X_output_artifact_check"]
    assert st["state"] == "PASS", data["findings"]
    assert r.returncode == 0


def test_the_same_prose_with_only_a_typed_header_is_not_measured(tmp_path):
    """Control, direction two — the exact pair #2050 asks for. Before this
    change the header made this ID PASS and its absence made it FAIL, so the
    check was reading the header."""
    r, data = _drive(tmp_path, "hls-c2rtl", _RTL_HEADER + _HLS_REPORT)
    st, = [f for f in data["findings"] if f["id"] == "X_output_artifact_check"]
    assert (st["severity"], st["state"]) == ("FAIL", "NOT_MEASURED")
    assert "output_artifact_check_receipt.json" in st["detail"]
    assert r.returncode == 1


def test_the_header_does_not_move_the_audit_either_way(tmp_path):
    """With the receipt present, adding the header changes the audit's state
    not at all — it only trips `text_only_report`, which is a different
    finding about a different thing."""
    rec = {"output_artifact_check_receipt.json": _OA_RECEIPT}
    _, plain = _drive(tmp_path / "a", "hls-c2rtl", _HLS_REPORT, rec)
    _, hdr = _drive(tmp_path / "b", "hls-c2rtl", _RTL_HEADER + _HLS_REPORT, rec)

    def state(d):
        f, = [x for x in d["findings"] if x["id"] == "X_output_artifact_check"]
        return f["severity"], f["state"]
    assert state(plain) == state(hdr) == ("INFO", "PASS")
    assert "X_text_only_skill" in [f["id"] for f in hdr["findings"]
                                   if f["severity"] == "FAIL"]


# ---------------------------------------------------------------------------
# Item 2 — the dead key, and the rule that stops the next one
# ---------------------------------------------------------------------------
def test_phase1_has_no_dead_postchecks_key():
    src = (_SKILLS / "phase1" / "compliance.yaml").read_text()
    assert "postchecks" not in scc._load_yaml(
        _SKILLS / "phase1" / "compliance.yaml")
    assert "#2050" in src, "the deletion must say where the obligations went"


def test_no_compliance_yaml_carries_a_key_nothing_reads():
    offenders = {}
    for y in sorted(_SKILLS.glob("*/compliance.yaml")):
        extra = sorted(k for k in scc._load_yaml(y)
                       if k not in scc._READ_TOPLEVEL_KEYS)
        if extra:
            offenders[y.parent.name] = extra
    assert offenders == {}, offenders


def test_an_unread_top_level_key_is_a_blocking_finding(tmp_path):
    """Both directions, on the rule itself."""
    clean = {"skill": "s", "requirements": [], "cross_checks": []}
    assert [f for f in scc.audit("x", clean)
            if f.id == "compliance_yaml_unread_key"] == []
    dirty = dict(clean, postchecks=[{"id": "X", "rule": "postcheck_pass_only"}])
    f, = [f for f in scc.audit("x", dirty)
          if f.id == "compliance_yaml_unread_key"]
    assert f.severity == "FAIL"
    assert "postchecks" in f.description


def test_the_cli_importable_obligation_is_really_discharged():
    """X_cli_importable moved from a dead yaml key to something executable.
    Naming it here is what makes the deletion a move and not a drop."""
    repo = _PLUGIN.parents[2]
    sys.path.insert(0, str(repo))
    import importlib
    for mod in ("cli", "ingest", "render", "schema", "gap_detect"):
        importlib.import_module(f"tools.phase1_engine.{mod}")


def test_the_round_trip_obligation_is_measured_and_currently_short():
    """X_round_trip_byte_identical was the other dead entry, and it does NOT
    hold. `from_existing_docs` iterates ALL_LAYER_CODES (14) while
    `render_layers` can write GENERATABLE_LAYER_CODES (28), so the opt-in
    advanced layers are written by Phase 1 and dropped by the reverse-extract.

    This pins the shortfall by NAME rather than asserting a green that is not
    there. Shrink the list when the round trip is fixed; do not extend it.
    """
    repo = _PLUGIN.parents[2]
    sys.path.insert(0, str(repo))
    from tools.phase1_engine.schema import (ALL_LAYER_CODES,
                                            GENERATABLE_LAYER_CODES)
    dropped = [c for c in GENERATABLE_LAYER_CODES if c not in ALL_LAYER_CODES]
    assert dropped == ["L14", "L15", "L16", "L17", "L18", "L19", "L20",
                       "L21", "L22", "L23", "L24", "L25", "L26", "L27"], dropped


# ---------------------------------------------------------------------------
# Item 3 — the skip
# ---------------------------------------------------------------------------
def _generated_compliance_tests():
    return [p for p in sorted(_SKILLS.glob("*/tests/test_compliance.py"))
            if "Auto-generated" in p.read_text()[:200]]


def test_no_generated_compliance_test_skips_before_its_assert():
    """The defect itself, as a standing assertion. Parsed with `ast` rather
    than grepped, so a skip reintroduced under any spelling is caught."""
    offenders = []
    for p in _generated_compliance_tests():
        tree = ast.parse(p.read_text())
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef)
                    and fn.name == "test_good_output_passes_all_required"):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "skip"):
                    offenders.append(p.parent.parent.name)
    assert offenders == [], offenders


def test_every_generated_test_asserts_the_limitation_list_both_ways():
    missing = [p.parent.parent.name for p in _generated_compliance_tests()
               if "SYNTHETIC_FIXTURE_LIMITATIONS" not in p.read_text()]
    assert missing == [], missing


def test_the_limitation_list_names_only_real_skills_and_real_requirements():
    for skill, ids in limits.SYNTHETIC_FIXTURE_LIMITATIONS.items():
        y = _SKILLS / skill / "compliance.yaml"
        assert y.is_file(), skill
        declared = {r["id"] for r in (scc._load_yaml(y).get("requirements")
                                      or [])}
        unknown = sorted(set(ids) - declared)
        assert unknown == [], f"{skill}: {unknown}"
        assert ids, f"{skill}: an empty entry must be deleted, not left"


def test_every_named_limitation_carries_a_reason():
    for skill, ids in limits.SYNTHETIC_FIXTURE_LIMITATIONS.items():
        for i in ids:
            assert i in limits.REASONS, f"{skill}: {i} has no recorded cause"
        assert limits.reason_for(skill).startswith("synthetic good-output")


def test_the_limitation_list_size_is_pinned_so_it_can_be_watched_shrinking():
    """53 named entries stand in for a blanket skip over the same 53.

    Both numbers are pinned so neither can move without somebody saying so:

      * the FIRST going DOWN is the point of this whole list — update it here
        and delete the entries you repaired;
      * the FIRST going UP means a required pattern just became unreachable for
        the synthetic generator. Fix the pattern or the generator; the
        per-skill both-ways assert already names which skill;
      * the SECOND moving means a skill gained or lost a generated compliance
        test, which is a real change to the population and belongs in the diff
        that made it.
    """
    assert len(limits.SYNTHETIC_FIXTURE_LIMITATIONS) == 53, (
        "the named synthetic-fixture limitation list changed size")
    assert len(_generated_compliance_tests()) == 69, (
        "the number of skills shipping a GENERATED tests/test_compliance.py "
        "changed")
