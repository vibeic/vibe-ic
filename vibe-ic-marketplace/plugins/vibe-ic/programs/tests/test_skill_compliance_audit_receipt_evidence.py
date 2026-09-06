"""#2048 — a named audit is discharged by its own receipt, not by a header.

MEASURED on origin/main eb541112c840154ca7dc6be8a2602df22d26208e, driving the
issue's two synthetic documents through the PRODUCTION binding
(`skills/rtl-review/compliance.yaml`) rather than through a handler directly:

  document                                     | named audits passing | rc
  ---------------------------------------------|----------------------|----
  compliant prose + three real PASS receipts    |         0/3          |  1
  compliant prose + a typed `// Post-checks:`   |         3/3          |  0
  header and NO receipt anywhere on disk        |                      |

Both rows are the same defect from opposite sides. `X_interface_encoding_audit`,
`X_crc_bitorder_check` and `X_phy_counter_audit` all selected
`postcheck_pass_only`, which reads exactly one string —

    // Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS

— naming two OTHER tools, and reads nothing else. So the three audits were
insensitive to their own evidence and sensitive only to a sentence, and the
one route from red to green on a Markdown review was to type that sentence.

The rule they now select, `audit_receipt_evidence`, never reads the report
text at all. Every assertion below is written in both directions: the
evidence-backed arm must PASS, and the arm that removes or corrupts exactly
one receipt must go non-PASS for a named reason. `test_mutation_*` is the
control on the controls — it re-introduces the header-reading behaviour and
asserts the suite notices, because a check that cannot fail is not a check.

Every receipt written here is SYNTHETIC, is labelled as such inside its own
payload, and is built by `_receipt_set()` below; none is a copy of a real
audit's output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_CHECKER = _PLUGIN / "_shared" / "skill_compliance_check.py"
_RTL_REVIEW_YML = _PLUGIN / "skills" / "rtl-review" / "compliance.yaml"

sys.path.insert(0, str(_PLUGIN / "_shared"))
import skill_compliance_check as scc  # noqa: E402

_NAMED = ("X_interface_encoding_audit",
          "X_crc_bitorder_check",
          "X_phy_counter_audit")

_RTL_HEADER = "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS\n"

# A review satisfying every REQUIRED element of rtl-review's spec, so the
# overall verdict turns on the audit bindings and not on a missing section.
_REVIEW = """# Synthetic rtl-review report

## Summary
Reviewed the synthetic design. This document carries no RTL post-check header.

## Findings
Interface encoding consistency was checked across module boundaries.
TX data content and byte layout were checked against the protocol spec.
The counter approach was checked: time-based, not bus-sampling.

## Next step
Next: run /vibe-ic-phase2
"""

_SYNTHETIC = "SYNTHETIC FIXTURE — not produced by a real audit run"


def _receipt_set(*, encoding_mismatches=0, encoding_total=2,
                 crc_status="PASS", crc_findings=1,
                 phy_verdict="PASS", phy_total=3):
    """Synthetic receipts in the shape each producer actually emits.

    Shapes read off programs/interface_encoding_audit.py::main,
    programs/crc_bitorder_check.py::main and
    programs/phy_counter_audit.py::generate_report.
    """
    return {
        "encoding_audit_report.json": {
            "_fixture": _SYNTHETIC,
            "summary": {"total_interfaces": encoding_total,
                        "mismatches": encoding_mismatches,
                        "matches": encoding_total - encoding_mismatches,
                        "unknowns": 0,
                        "top_module": "syn_top",
                        "rtl_dir": "syn/rtl"},
            "interfaces": [{"wire_name": f"w{i}"} for i in range(encoding_total)],
        },
        "crc_bitorder_report.json": {
            "_fixture": _SYNTHETIC,
            "crc_signal": "syn_crc8",
            "files_scanned": ["syn/rtl/tx.v"],
            "findings": [{"file": "syn/rtl/tx.v", "line": 1, "status": "PASS"}
                         for _ in range(crc_findings)],
            "summary_status": crc_status,
            "summary_message": _SYNTHETIC,
        },
        "phy_counter_audit_report.json": {
            "_fixture": _SYNTHETIC,
            "tool": "phy_counter_audit",
            "version": "1.0.0",
            "summary": {"total_counters_analyzed": phy_total,
                        "bus_sampled_warnings": 0 if phy_verdict == "PASS" else 1,
                        "time_based_clean": phy_total,
                        "verdict": phy_verdict},
            "findings": [{"file": "syn/rtl/phy.v", "line": 1,
                          "severity": "CLEAN"}],
        },
    }


def _drive(tmp_path, doc_text, receipts, yml=None):
    """Run the real CLI over a document and a receipt directory."""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    doc = tmp_path / "review.md"
    doc.write_text(doc_text)
    for name, payload in (receipts or {}).items():
        if payload is not None:
            (tmp_path / name).write_text(json.dumps(payload, indent=2))
    out = tmp_path / "audit.json"
    r = subprocess.run(
        [sys.executable, str(_CHECKER),
         "--requirements", str(yml or _RTL_REVIEW_YML),
         "--json", str(out), str(doc)],
        capture_output=True, text=True)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, data


def _state(data, check_id):
    """(severity, state) for one cross-check id, or ('ABSENT', 'ABSENT').

    ABSENT is its own answer and never collapses into a pass: on the pre-fix
    engine the three named audits returned NO finding at all when the header
    was present, which is exactly how a typed string bought three green rows.
    """
    for f in data.get("findings", []):
        if f["id"] == check_id:
            return f["severity"], f.get("state", "")
    return "ABSENT", "ABSENT"


# ---------------------------------------------------------------------------
# The inversion the issue asks for
# ---------------------------------------------------------------------------
def test_evidence_backed_prose_passes_without_any_rtl_header(tmp_path):
    """The headline: real receipts, no header, rc=0."""
    r, data = _drive(tmp_path, _REVIEW, _receipt_set())
    assert _RTL_HEADER.strip() not in _REVIEW
    for cid in _NAMED:
        assert _state(data, cid) == ("INFO", "PASS"), (
            f"{cid} should PASS on its own receipt; got {_state(data, cid)}")
    assert data["verdict"] == "PASS", data.get("findings")
    assert r.returncode == 0, r.stdout


def test_typed_header_without_receipts_buys_nothing(tmp_path):
    """The other side: the string that used to buy 3/3 now buys 0/3."""
    r, data = _drive(tmp_path, _REVIEW + _RTL_HEADER, receipts=None)
    for cid in _NAMED:
        sev, state = _state(data, cid)
        assert state == "NOT_MEASURED", f"{cid}: got {(sev, state)}"
        assert sev == "FAIL", (
            f"{cid}: NOT_MEASURED must block — a check that did not run is "
            f"reported, never counted as a pass; got severity {sev}")
    assert r.returncode == 1


def test_header_changes_nothing_about_the_three_audits(tmp_path):
    """With receipts held fixed, adding the header must not move any audit.

    This is the assertion the pre-fix engine cannot satisfy in either
    configuration, and it is stated as MEMBERSHIP over (id -> state) rather
    than as a count, so a substitution between two ids cannot hide inside a
    total that happens to match.
    """
    _, without = _drive(tmp_path / "a", _REVIEW, _receipt_set())
    _, with_hdr = _drive(tmp_path / "b", _REVIEW + _RTL_HEADER, _receipt_set())
    assert ({c: _state(without, c) for c in _NAMED}
            == {c: _state(with_hdr, c) for c in _NAMED})


def test_fabricated_header_is_still_a_failure(tmp_path):
    """Binding the audits to evidence must not legalise the fabrication."""
    r, data = _drive(tmp_path, _REVIEW + _RTL_HEADER, _receipt_set())
    sev, _ = _state(data, "X_text_only_skill")
    assert sev == "FAIL", "a prose report claiming an RTL post-check verdict"
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# One receipt at a time: every non-PASS state, named
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("subject,kwargs,expected", [
    ("X_phy_counter_audit", {"phy_verdict": "FAIL"}, "FAIL"),
    ("X_interface_encoding_audit", {"encoding_mismatches": 1}, "FAIL"),
    ("X_crc_bitorder_check", {"crc_status": "WARN"}, "FAIL"),
    ("X_crc_bitorder_check", {"crc_findings": 0, "crc_status": "INFO"},
     "NOT_MEASURED"),
    ("X_interface_encoding_audit", {"encoding_total": 0}, "NOT_MEASURED"),
    ("X_phy_counter_audit", {"phy_total": 0}, "NOT_MEASURED"),
])
def test_one_bad_receipt_reddens_exactly_that_audit(tmp_path, subject,
                                                    kwargs, expected):
    _, data = _drive(tmp_path, _REVIEW, _receipt_set(**kwargs))
    sev, state = _state(data, subject)
    assert (sev, state) == ("FAIL", expected)
    for other in _NAMED:
        if other != subject:
            assert _state(data, other) == ("INFO", "PASS"), (
                f"{other} moved when only {subject}'s receipt changed")


@pytest.mark.parametrize("filename,cid", [
    ("encoding_audit_report.json", "X_interface_encoding_audit"),
    ("crc_bitorder_report.json", "X_crc_bitorder_check"),
    ("phy_counter_audit_report.json", "X_phy_counter_audit"),
])
def test_absent_receipt_is_not_measured_and_names_what_it_looked_for(
        tmp_path, filename, cid):
    receipts = _receipt_set()
    receipts[filename] = None
    _, data = _drive(tmp_path, _REVIEW, receipts)
    assert _state(data, cid) == ("FAIL", "NOT_MEASURED")
    finding = next(f for f in data["findings"] if f["id"] == cid)
    assert filename in finding["detail"], (
        "a NOT_MEASURED finding must name the artefact it could not read")
    assert str(tmp_path.resolve()) in finding["detail"], (
        "and every directory it searched")
    assert cid in data["not_measured"]


@pytest.mark.parametrize("filename,cid", [
    ("encoding_audit_report.json", "X_interface_encoding_audit"),
    ("crc_bitorder_report.json", "X_crc_bitorder_check"),
    ("phy_counter_audit_report.json", "X_phy_counter_audit"),
])
def test_another_producers_payload_is_no_evidence(tmp_path, filename, cid):
    receipts = _receipt_set()
    receipts[filename] = {"_fixture": _SYNTHETIC, "tool": "some_other_tool",
                          "summary": {"verdict": "PASS"}}
    _, data = _drive(tmp_path, _REVIEW, receipts)
    assert _state(data, cid) == ("FAIL", "NOT_MEASURED"), (
        "a payload from another producer must not be read as this audit's "
        "clean verdict just because it sits at the right filename")


def test_unparseable_receipt_is_not_measured_not_empty(tmp_path):
    doc = tmp_path / "review.md"
    doc.write_text(_REVIEW)
    for name, payload in _receipt_set().items():
        (tmp_path / name).write_text(json.dumps(payload))
    (tmp_path / "crc_bitorder_report.json").write_text("{ this is not json")
    out = tmp_path / "audit.json"
    subprocess.run([sys.executable, str(_CHECKER),
                    "--requirements", str(_RTL_REVIEW_YML),
                    "--json", str(out), str(doc)],
                   capture_output=True, text=True)
    data = json.loads(out.read_text())
    assert _state(data, "X_crc_bitorder_check") == ("FAIL", "NOT_MEASURED")


def test_skip_receipt_is_not_a_pass(tmp_path):
    receipts = _receipt_set()
    receipts["phy_counter_audit_report.json"] = {
        "_fixture": _SYNTHETIC, "verdict": "SKIP",
        "reason": "no RTL files in syn/rtl/", "pass": True}
    _, data = _drive(tmp_path, _REVIEW, receipts)
    assert _state(data, "X_phy_counter_audit") == ("FAIL", "NOT_MEASURED"), (
        'the producer\'s own SKIP payload carries "pass": True; a skipped '
        "auditor is a fact about the invocation, not a verdict about the RTL")


def test_receipt_finding_carries_the_bytes_it_read(tmp_path):
    """A PASS must be traceable to the exact receipt it came from."""
    _, data = _drive(tmp_path, _REVIEW, _receipt_set())
    from hashlib import sha256
    for cid, fname in zip(_NAMED, ("encoding_audit_report.json",
                                   "crc_bitorder_report.json",
                                   "phy_counter_audit_report.json")):
        finding = next(f for f in data["findings"] if f["id"] == cid)
        digest = sha256((tmp_path / fname).read_bytes()).hexdigest()
        assert digest[:16] in finding["detail"]


# ---------------------------------------------------------------------------
# Output-type binding: the two contradicting rules, each on its own type
# ---------------------------------------------------------------------------
def _spec(tmp_path, body):
    y = tmp_path / "compliance.yaml"
    y.write_text(body)
    return y


def test_postcheck_pass_only_under_output_type_report_is_a_config_error(
        tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: report\n"
                          "requirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'names an audit'\n"
                          "    rule: postcheck_pass_only\n")
    r, data = _drive(tmp_path, _REVIEW + _RTL_HEADER, None, yml=yml)
    ids = [f["id"] for f in data["findings"] if f["severity"] == "FAIL"]
    assert "X_probe_rule_misbound" in ids, (
        "the header must no longer satisfy a report-typed spec")
    assert r.returncode == 1


def test_postcheck_pass_only_under_output_type_rtl_still_demands_the_header(
        tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: rtl\n"
                          "requirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'genuine RTL output'\n"
                          "    rule: postcheck_pass_only\n")
    r_ok, ok = _drive(tmp_path / "ok", "module m; endmodule\n" + _RTL_HEADER,
                      None, yml=yml)
    r_no, no = _drive(tmp_path / "no", "module m; endmodule\n", None, yml=yml)
    assert r_ok.returncode == 0, ok.get("findings")
    assert r_no.returncode == 1, "an RTL output missing its header is still red"


def test_undeclared_output_type_is_not_guessed(tmp_path):
    """Absence of the field must not silently reinterpret 36 existing IDs."""
    yml = _spec(tmp_path, "skill: probe\nrequirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'undeclared'\n"
                          "    rule: postcheck_pass_only\n")
    r, _ = _drive(tmp_path, "module m; endmodule\n" + _RTL_HEADER, None, yml=yml)
    assert r.returncode == 0


def test_unknown_output_type_is_reported_not_ignored(tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: parchment\n"
                          "requirements: []\ncross_checks: []\n")
    r, data = _drive(tmp_path, _REVIEW, None, yml=yml)
    assert "output_type_unknown" in [f["id"] for f in data["findings"]]
    assert r.returncode == 1


def test_missing_auditor_field_is_a_config_error_not_a_pass(tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: report\n"
                          "requirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'no auditor named'\n"
                          "    rule: audit_receipt_evidence\n")
    r, data = _drive(tmp_path, _REVIEW, _receipt_set(), yml=yml)
    assert "X_probe_no_auditor" in [f["id"] for f in data["findings"]]
    assert r.returncode == 1


def test_unregistered_auditor_is_not_assumed_to_have_passed(tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: report\n"
                          "requirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'unknown producer'\n"
                          "    rule: audit_receipt_evidence\n"
                          "    auditor: no_such_audit\n")
    r, data = _drive(tmp_path, _REVIEW, _receipt_set(), yml=yml)
    assert "X_probe_unknown_auditor" in [f["id"] for f in data["findings"]]
    assert r.returncode == 1


def test_subject_mismatch_is_a_fail(tmp_path):
    yml = _spec(tmp_path, "skill: probe\noutput_type: report\n"
                          "requirements: []\ncross_checks:\n"
                          "  - id: X_probe\n"
                          "    description: 'wrong subject'\n"
                          "    rule: audit_receipt_evidence\n"
                          "    auditor: interface_encoding_audit\n"
                          "    subject:\n"
                          "      top_module: a_different_top\n")
    _, data = _drive(tmp_path, _REVIEW, _receipt_set(), yml=yml)
    sev, state = _state(data, "X_probe")
    assert (sev, state) == ("FAIL", "FAIL")
    finding = next(f for f in data["findings"] if f["id"] == "X_probe")
    assert "syn_top" in finding["detail"], "must name what the receipt says"


# ---------------------------------------------------------------------------
# Structural: the repointing itself, and the tooling that used to undo it
# ---------------------------------------------------------------------------
def test_rtl_review_binds_all_three_audits_to_their_own_receipts():
    spec = scc._load_yaml(_RTL_REVIEW_YML)
    assert spec.get("output_type") == "report"
    bound = {c["id"]: (c.get("rule"), c.get("auditor"))
             for c in spec["cross_checks"]}
    assert bound["X_interface_encoding_audit"] == (
        "audit_receipt_evidence", "interface_encoding_audit")
    assert bound["X_crc_bitorder_check"] == (
        "audit_receipt_evidence", "crc_bitorder_check")
    assert bound["X_phy_counter_audit"] == (
        "audit_receipt_evidence", "phy_counter_audit")


def test_unregistered_auditors_are_named_and_all_exist():
    """The obligations that cannot be evidence-bound yet, by name.

    They are enumerated rather than left implicit so that registering one is a
    diff against this list, and so that nobody can quietly add another.

    #2050 emptied and refilled this tuple. The four that used to be here got a
    producer-written receipt (`programs/_audit_receipt.py`) and are asserted
    below to have LEFT the list — so this test fails in both directions: if a
    registered auditor is put back on the unregistered list, and if a member
    of the list is registered without being removed from it.
    """
    assert scc.UNREGISTERED_AUDITORS == (
        "drc_report_check",
        "ir_drop_report_check",
        "lvs_report_check",
        "sta_report_check")
    for name in scc.UNREGISTERED_AUDITORS:
        assert (_PLUGIN / "programs" / f"{name}.py").is_file(), name
        assert name not in scc.AUDIT_RECEIPTS, (
            f"{name} is registered now — remove it from UNREGISTERED_AUDITORS")
    for name in ("gds_size_check", "synth_netlist_check",
                 "tapeout_signoff_check",
                 "fpga_async_input_synchronizer_check"):
        assert name in scc.AUDIT_RECEIPTS, (
            f"{name} was given a producer receipt by #2050 and must stay "
            "registered")
        assert name not in scc.UNREGISTERED_AUDITORS, name


def test_every_audit_receipt_evidence_id_names_a_known_or_declared_auditor():
    """No cross-check may name an auditor this module has never heard of."""
    known = set(scc.AUDIT_RECEIPTS) | set(scc.UNREGISTERED_AUDITORS)
    unknown = []
    for yml in sorted((_PLUGIN / "skills").glob("*/compliance.yaml")):
        for c in (scc._load_yaml(yml).get("cross_checks") or []):
            if c.get("rule") != "audit_receipt_evidence":
                continue
            if c.get("auditor") not in known:
                unknown.append(f"{yml.parent.name}:{c.get('id')}"
                               f"->{c.get('auditor')}")
    assert unknown == [], unknown


def test_repointed_sibling_ids_cannot_pass_on_a_header(tmp_path):
    """The repointed sibling IDs must not be able to pass on a header.

    #2050 changed the STATE these four report, not the outcome. Their auditors
    now have a registered receipt contract, so with no receipt on disk each one
    is NOT_MEASURED — naming the file it looked for — instead of a
    `_unknown_auditor` configuration error. Both block; the second says what to
    fix in the yaml, the first says what to run.
    """
    yml = _PLUGIN / "skills" / "tapeout-checklist" / "compliance.yaml"
    r, data = _drive(tmp_path, _REVIEW + _RTL_HEADER, None, yml=yml)
    for cid in ("X_gds_size_check", "X_synth_netlist_check",
                "X_tapeout_signoff_check", "X_mcp_execution_verify"):
        assert _state(data, cid) == ("FAIL", "NOT_MEASURED"), cid
    ids = [f["id"] for f in data["findings"] if f["severity"] == "FAIL"]
    assert "X_text_only_skill" in ids, "the fabricated header is still a failure"
    assert r.returncode == 1


def test_a_still_unregistered_auditor_blocks_and_says_what_is_missing(tmp_path):
    """The other half: an auditor with NO registered contract is a config
    error naming what is missing, and is never assumed to have passed."""
    yml = _PLUGIN / "skills" / "drc-fix" / "compliance.yaml"
    r, data = _drive(tmp_path, _REVIEW + _RTL_HEADER, None, yml=yml)
    ids = [f["id"] for f in data["findings"] if f["severity"] == "FAIL"]
    assert "X_drc_report_check_unknown_auditor" in ids
    assert "X_text_only_skill" in ids, "the fabricated header is still a failure"
    assert r.returncode == 1


def test_every_registered_auditor_names_a_program_that_exists():
    for name, rs in scc.AUDIT_RECEIPTS.items():
        assert (_PLUGIN / "programs" / f"{name}.py").is_file(), name
        assert rs.emitted_by.startswith("programs/"), name


def test_no_report_typed_spec_selects_the_rtl_header_rule():
    """The sweep, as a standing assertion rather than a one-off list."""
    offenders = []
    for yml in sorted((_PLUGIN / "skills").glob("*/compliance.yaml")):
        spec = scc._load_yaml(yml)
        if str(spec.get("output_type") or "").lower() != "report":
            continue
        for c in (spec.get("cross_checks") or []):
            if c.get("rule") == "postcheck_pass_only":
                offenders.append(f"{yml.parent.name}:{c.get('id')}")
    assert offenders == [], (
        "a report-typed spec cannot discharge an audit obligation with an "
        f"RTL header: {offenders}")


def test_regenerated_fixtures_carry_no_manufactured_header():
    """The repo's own tooling used to write the unmeasured claim for you.

    MEASURED on origin/main: `gen_integration_fixtures.build_fixture` appended
    the RTL header to any fixture whose yaml selected `postcheck_pass_only`,
    which flipped all seven named audit cross-checks of `rtl-review` and
    `tapeout-checklist` from FAIL to PASS with zero receipts on disk.

    This asserts the OUTCOME for the two real skills. It holds because those
    nine IDs are repointed, not because of the generator guard — reverting the
    generator alone leaves this green, which is measured and is why
    `test_fixture_generator_suppresses_the_header_for_report_specs` exists
    below to put a falsifiable test on the guard itself.
    """
    sys.path.insert(0, str(_PLUGIN / "_shared"))
    import gen_integration_fixtures as gif
    for skill in ("rtl-review", "tapeout-checklist"):
        text, _, _ = gif.build_fixture(skill)
        assert "// Post-checks: rtl_hygiene_lint" not in text, (
            f"{skill}: fixture generator still manufactures the header")


def test_fixture_generator_suppresses_the_header_for_report_specs(
        tmp_path, monkeypatch):
    """Drive the guard directly, with a spec that would trip the old code.

    A report-typed spec that still selects `postcheck_pass_only` is exactly
    the shape the standing sweep forbids in `skills/`, so no real skill can
    reach this branch any more — which is precisely why the guard needs its
    own input. Both directions: the same spec typed `rtl` must still get the
    header, or this test would pass against a generator that had simply
    stopped emitting headers altogether.
    """
    sys.path.insert(0, str(_PLUGIN / "_shared"))
    import gen_integration_fixtures as gif

    def _spec_for(output_type):
        root = tmp_path / output_type
        (root / "probe").mkdir(parents=True, exist_ok=True)
        (root / "probe" / "compliance.yaml").write_text(
            f"skill: probe\noutput_type: {output_type}\n"
            "requirements:\n"
            "  - id: R_x\n"
            "    description: 'x'\n"
            "    pattern: 'x'\n"
            "    positive_sample: 'x'\n"
            "cross_checks:\n"
            "  - id: X_probe\n"
            "    description: 'names an audit'\n"
            "    rule: postcheck_pass_only\n")
        monkeypatch.setattr(gif, "SKILLS", root)
        return gif.build_fixture("probe")[0]

    assert "// Post-checks: rtl_hygiene_lint" not in _spec_for("report"), (
        "generator manufactured the header for an output_type: report spec")
    assert "// Post-checks: rtl_hygiene_lint" in _spec_for("rtl"), (
        "generator stopped emitting the header for genuine RTL output too — "
        "the guard must be about the output type, not about the header")


# ---------------------------------------------------------------------------
# The control on the controls
# ---------------------------------------------------------------------------
def test_mutation_reading_the_header_again_reddens_these_tests(tmp_path,
                                                               monkeypatch):
    """Re-introduce the defect in-process and confirm the suite reacts.

    Without this, every assertion above could be passing for a reason that has
    nothing to do with the header, and nobody would know.
    """
    def header_reading_rule(spec, text, ctx=None):
        return scc._cc_postcheck_pass_only(spec, text)

    monkeypatch.setitem(scc.CROSS_CHECK_RULES,
                        "audit_receipt_evidence", header_reading_rule)
    compliance = scc._load_yaml(_RTL_REVIEW_YML)

    mutated = scc.audit(_REVIEW + _RTL_HEADER, compliance,
                        scc.CheckContext(output_path=tmp_path / "r.md"))
    ids = {f.id for f in mutated if f.severity == "FAIL"}
    assert not (set(_NAMED) & ids), (
        "mutation did not take effect — the header should buy all three back")

    honest = scc.audit(_REVIEW + _RTL_HEADER, compliance,
                       scc.CheckContext(output_path=tmp_path / "r.md"))
    monkeypatch.undo()
    honest = scc.audit(_REVIEW + _RTL_HEADER, compliance,
                       scc.CheckContext(output_path=tmp_path / "r.md"))
    ids2 = {f.id for f in honest if f.severity == "FAIL"}
    assert set(_NAMED) <= ids2, (
        "with the real rule restored, all three must be blocking again")
