"""#2057 item 3 — the four `eda_report_audit` wrappers bind through their own --json.

WHAT #2050 LEFT, AND WHY. `drc_report_check`, `lvs_report_check`,
`ir_drop_report_check` and `sta_report_check` were named in
`UNREGISTERED_AUDITORS`, so every compliance.yaml that binds one of them
reported a blocking configuration error — "No receipt contract is registered
for auditor `sta_report_check`". The reason was recorded, not guessed: all four
write to a caller-chosen `--json` path which is itself a DECLARED phase-3
sign-off output, and giving them the `<auditor>_receipt.json` sibling the six
producers use would add a second artefact to a directory whose contents are
accounted step by step.

THE RULING: no second file. The `--json` document IS the receipt, once it
carries the one field it lacked — a content-addressed subject digest. So:

  * `eda_report_audit.main` emits `subject`, `_audit_receipt.subject_of` over
    exactly the population `summary.files_found` counts. Every mode gets it at
    the one write site, because a field present on some of a program's reports
    and absent on others makes its absence ambiguous.
  * the four are registered with `filename=''` — resolved by CONTENT inside
    the same search roots, on the payload's own
    `program: "eda_report_audit:<mode>"`, which pins the MODE as well as the
    producer. A drc audit lying in the same directory never satisfies
    `sta_report_check`.
  * NOTHING is added to a sign-off directory: `flow/phase1_phase2_phase3.yaml`
    is not touched by this change and every step's `required_outputs` is
    unchanged by name, asserted below against the flow file itself.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve()
_PLUGIN = _HERE.parents[2]
_PROGRAMS = _PLUGIN / "programs"
_SKILLS = _PLUGIN / "skills"
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PLUGIN / "_shared"))
sys.path.insert(0, str(_PROGRAMS))

import skill_compliance_check as scc   # noqa: E402
import _audit_receipt                  # noqa: E402

#: wrapper -> (eda_report_audit mode, a report basename that mode discovers)
_WRAPPERS = {
    'drc_report_check': ('drc', 'drc_signoff.rpt'),
    'lvs_report_check': ('lvs', 'lvs.rpt'),
    'ir_drop_report_check': ('ir_drop', 'ir_drop.rpt'),
    'sta_report_check': ('sta', 'sta.rpt'),
}


# ---------------------------------------------------------------------------
# The registration itself
# ---------------------------------------------------------------------------
def test_the_four_are_registered_and_the_unregistered_tuple_is_empty():
    for auditor in _WRAPPERS:
        assert auditor in scc.AUDIT_RECEIPTS, auditor
        assert (_PROGRAMS / f"{auditor}.py").is_file(), auditor
    assert scc.UNREGISTERED_AUDITORS == (), scc.UNREGISTERED_AUDITORS


def test_the_four_resolve_by_content_and_every_other_auditor_by_name():
    """Two populations, stated. `filename=''` is the content-resolved form and
    must be exactly these four — an existing producer silently losing its
    fixed filename would otherwise start scanning directories."""
    by_content = sorted(a for a, rs in scc.AUDIT_RECEIPTS.items()
                        if not rs.filename)
    assert by_content == sorted(_WRAPPERS), (
        "content-resolved auditors are not the four wrappers: "
        + " ".join(by_content))
    for auditor, rs in scc.AUDIT_RECEIPTS.items():
        if rs.filename:
            assert rs.filename.endswith('.json'), (auditor, rs.filename)
        else:
            assert rs.written_as, auditor


def test_no_skill_still_reports_an_unknown_auditor():
    """The four `X_*_unknown_auditor` configuration errors #2050 shipped are
    the population this change closes. Measured over every compliance.yaml."""
    offenders = {}
    for y in sorted(_SKILLS.glob("*/compliance.yaml")):
        spec = yaml.safe_load(y.read_text()) or {}
        for cc in spec.get("cross_checks") or []:
            if cc.get("rule") != "audit_receipt_evidence":
                continue
            auditor = cc.get("auditor")
            if auditor and auditor not in scc.AUDIT_RECEIPTS:
                offenders.setdefault(y.parent.name, []).append(auditor)
    assert offenders == {}, (
        "compliance.yaml names an unregistered auditor: "
        + "; ".join(f"{k}: {' '.join(v)}" for k, v in sorted(offenders.items())))


# ---------------------------------------------------------------------------
# The producer really writes the subject
# ---------------------------------------------------------------------------
def _run_wrapper(tmp_path, auditor, mode, report_name, body):
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / report_name).write_text(body)
    out = tmp_path / "audit.json"
    subprocess.run([sys.executable, str(_PROGRAMS / f"{auditor}.py"),
                    str(proj), "--mode", mode, "--json", str(out)],
                   capture_output=True, text=True)
    assert out.is_file(), f"{auditor} wrote no --json"
    return proj, out, json.loads(out.read_text())


@pytest.mark.parametrize("auditor", sorted(_WRAPPERS))
def test_each_wrapper_json_carries_a_content_addressed_subject(tmp_path,
                                                               auditor):
    mode, report_name = _WRAPPERS[auditor]
    _proj, _out, doc = _run_wrapper(tmp_path / auditor, auditor, mode,
                                    report_name, "placeholder report\n")
    assert doc["program"] == f"eda_report_audit:{mode}"
    subj = doc["subject"]
    assert subj["basis"] in (_audit_receipt.BASIS_CONTENT,
                             _audit_receipt.BASIS_PATH)
    assert isinstance(subj["sha256"], str) and len(subj["sha256"]) == 64
    names = [i["path"] for i in subj["items"]]
    assert report_name in [Path(n).name for n in names], (
        f"{report_name} absent from the subject: {' '.join(names)}")
    # NEVER the machine it ran on: a declared sign-off artefact is committed.
    for n in names:
        assert not Path(n).is_absolute(), n
    # the subject is the population `files_found` counts, by construction
    assert len(subj["items"]) == doc["summary"]["files_found"]


def test_the_digest_is_the_same_in_another_directory_and_differs_by_content(
        tmp_path):
    """Content-addressed means content-addressed: the same bytes audited under
    a different path give the SAME digest, different bytes give a different
    one. Without that, a stale audit beside a fresh report is undetectable."""
    body = "Circuits match uniquely.\n"
    _p1, _o1, a = _run_wrapper(tmp_path / "a", "lvs_report_check", "lvs",
                               "lvs.rpt", body)
    _p2, _o2, b = _run_wrapper(tmp_path / "b", "lvs_report_check", "lvs",
                               "lvs.rpt", body)
    _p3, _o3, c = _run_wrapper(tmp_path / "c", "lvs_report_check", "lvs",
                               "lvs.rpt", body + "one more line\n")
    assert a["subject"]["sha256"] == b["subject"]["sha256"]
    assert a["subject"]["sha256"] != c["subject"]["sha256"]


# ---------------------------------------------------------------------------
# The checker really binds through it — both directions
# ---------------------------------------------------------------------------
def _audit(tmp_path, auditor, mode, report_name, declared_subject=None,
           write_audit=True, foreign_mode=None):
    """Drive `skill_compliance_check.audit` over a report whose directory does
    or does not hold this auditor's own --json document."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = None
    if write_audit:
        _proj, out, doc = _run_wrapper(tmp_path, auditor,
                                       foreign_mode or mode, report_name,
                                       "placeholder report\n")
        (run_dir / "declared_output.json").write_text(out.read_text())
    report = run_dir / "report.md"
    report.write_text("# report\n")
    cc = {"id": "X_probe", "rule": "audit_receipt_evidence",
          "auditor": auditor, "description": "probe"}
    if declared_subject is not None:
        cc["subject"] = declared_subject
    findings = scc.audit(report.read_text(),
                         {"skill": "probe", "requirements": [],
                          "cross_checks": [cc]},
                         ctx=scc.CheckContext(output_path=report))
    return doc, [f for f in findings if f.id.startswith("X_probe")]


@pytest.mark.parametrize("auditor", sorted(_WRAPPERS))
def test_the_json_alone_is_read_as_the_receipt(tmp_path, auditor):
    """DIRECTION ONE — the document IS found and IS read. No second file
    exists anywhere; only the caller's own `--json`, under a name the checker
    was never told. The verdict here is the audit's own (these toy reports do
    not pass a real DRC/LVS/IR/STA audit, and are not meant to); what this
    asserts is that the obligation moved off NOT_MEASURED, which is the state
    #2050 left all four in."""
    mode, report_name = _WRAPPERS[auditor]
    doc, findings = _audit(tmp_path, auditor, mode, report_name)
    f, = findings
    assert f.state == scc.STATE_FAIL, (f.state, f.description)
    assert f.state != scc.STATE_NOT_MEASURED, f.description
    assert "unknown_auditor" not in f.id and f.id == "X_probe"
    assert doc["subject"]["sha256"][:16] in f.detail or "receipt=" in f.detail
    # and there really is no receipt sibling in that directory
    sibs = sorted(q.name for q in (tmp_path / "run").glob("*_receipt.json"))
    assert sibs == [], (
        f"a receipt sibling was written after all: {' '.join(sibs)}")


#: A SYNTHETIC `eda_report_audit` document. Written by hand, and labelled as
#: synthetic, because the PASS path needs an audit whose own verdict is PASS
#: and a toy report cannot make a real DRC/LVS/IR/STA audit pass. Its shape is
#: read off `programs/eda_report_audit.py::main`, exactly as the ReceiptSpec
#: is; the producer half is measured separately, above.
def _synthetic_audit_doc(mode, subject_sha, passed=True, verdict=None):
    doc = {
        "program": f"eda_report_audit:{mode}",
        "passed": passed,
        "findings": [],
        "summary": {"files_found": 1},
        "subject": {"basis": "content", "sha256": subject_sha,
                    "items": [{"path": "reports/phase3/x.rpt",
                               "sha256": "a" * 64, "is_file": True}]},
    }
    if verdict is not None:
        doc["verdict"] = verdict
    return doc


def _audit_with_doc(tmp_path, auditor, doc, declared_subject=None):
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "post_route_summary.json").write_text(json.dumps(doc))
    report = run_dir / "report.md"
    report.write_text("# report\n")
    cc = {"id": "X_probe", "rule": "audit_receipt_evidence",
          "auditor": auditor, "description": "probe"}
    if declared_subject is not None:
        cc["subject"] = declared_subject
    findings = scc.audit(report.read_text(),
                         {"skill": "probe", "requirements": [],
                          "cross_checks": [cc]},
                         ctx=scc.CheckContext(output_path=report))
    return [f for f in findings if f.id.startswith("X_probe")]


def test_a_passing_audit_document_discharges_the_obligation(tmp_path):
    """The green half. A check that cannot pass is not a check."""
    f, = _audit_with_doc(tmp_path, "sta_report_check",
                         _synthetic_audit_doc("sta", "b" * 64))
    assert (f.severity, f.state) == ("INFO", scc.STATE_PASS), f.description
    assert "1 examined" in f.description or "examined" in f.description


def test_a_failing_audit_document_blocks(tmp_path):
    f, = _audit_with_doc(tmp_path / "a", "sta_report_check",
                         _synthetic_audit_doc("sta", "b" * 64, passed=False))
    assert (f.severity, f.state) == ("FAIL", scc.STATE_FAIL), f.description


def test_a_vacuous_pass_is_not_collapsed_onto_pass(tmp_path):
    """`eda_report_audit` sets `verdict: VACUOUS_PASS` when `passed` is true
    but the audit judged nothing. It lands on the FAIL side, deliberately."""
    f, = _audit_with_doc(tmp_path / "b", "sta_report_check",
                         _synthetic_audit_doc("sta", "b" * 64,
                                              verdict="VACUOUS_PASS"))
    assert (f.severity, f.state) == ("FAIL", scc.STATE_FAIL), f.description


def test_a_document_that_examined_nothing_is_not_measured(tmp_path):
    doc = _synthetic_audit_doc("sta", "b" * 64)
    doc["subject"]["items"] = []
    f, = _audit_with_doc(tmp_path / "c", "sta_report_check", doc)
    assert (f.severity, f.state) == ("FAIL", scc.STATE_NOT_MEASURED)
    assert "examined nothing" in f.description


def test_the_declared_subject_gates_a_passing_document_both_ways(tmp_path):
    """The mutation, on the PASS path where it matters: the same passing
    document backs the check when the declared digest is its own and is
    refused when it is another subject's."""
    doc = _synthetic_audit_doc("sta", "b" * 64)
    ok, = _audit_with_doc(tmp_path / "same", "sta_report_check", doc,
                          declared_subject={"sha256": "b" * 64})
    assert (ok.severity, ok.state) == ("INFO", scc.STATE_PASS), ok.description
    bad, = _audit_with_doc(tmp_path / "other", "sta_report_check", doc,
                           declared_subject={"sha256": "c" * 64})
    assert (bad.severity, bad.state) == ("FAIL", scc.STATE_FAIL)
    assert "different subject" in bad.description


@pytest.mark.parametrize("auditor", sorted(_WRAPPERS))
def test_no_json_is_not_measured_and_blocks(tmp_path, auditor):
    """DIRECTION TWO. Absence of evidence is never a pass."""
    mode, report_name = _WRAPPERS[auditor]
    _doc, findings = _audit(tmp_path, auditor, mode, report_name,
                            write_audit=False)
    f, = findings
    assert (f.severity, f.state) == ("FAIL", scc.STATE_NOT_MEASURED)
    assert auditor in f.description


def test_a_real_wrapper_json_for_another_subject_is_refused(tmp_path):
    """THE MUTATION THE ISSUE ASKS FOR, on a document a real wrapper wrote:
    a genuine `lvs_report_check` audit run over a DIFFERENT subject must not
    back this report. Its digest mismatching is a MEASUREMENT of something
    else, so it is FAIL rather than NOT_MEASURED."""
    doc, _f = _audit(tmp_path / "real", "lvs_report_check", "lvs", "lvs.rpt")
    other_digest = "0" * 64
    assert doc["subject"]["sha256"] != other_digest
    _doc2, findings = _audit(tmp_path / "probe", "lvs_report_check", "lvs",
                             "lvs.rpt",
                             declared_subject={"sha256": other_digest})
    f, = findings
    assert f.severity == "FAIL" and f.state == scc.STATE_FAIL, (
        f.state, f.description)
    assert "different subject" in f.description


def test_a_json_from_another_wrapper_is_not_this_ones_evidence(tmp_path):
    """The MODE is part of the identity. A drc audit sitting in the sign-off
    directory must not discharge `sta_report_check`."""
    _doc, findings = _audit(tmp_path, "sta_report_check", "sta", "drc.rpt",
                            foreign_mode="drc")
    f, = findings
    assert (f.severity, f.state) == ("FAIL", scc.STATE_NOT_MEASURED), (
        f.state, f.description)


# ---------------------------------------------------------------------------
# The control the issue names: nothing new in a sign-off directory
# ---------------------------------------------------------------------------
def test_no_step_required_output_changed_and_step_23_is_named():
    """`required_outputs` is the accounting this change refused to disturb.
    Step 23's list is pinned by name here; the flow file itself is not touched
    by this change, which `git diff` shows and this asserts independently."""
    flow = yaml.safe_load(_FLOW.read_text())
    outs = {}

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "required_outputs" in o:
                outs[str(o["id"])] = list(o["required_outputs"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(flow)
    assert outs["23"] == [
        "phase3/stage3/sta/post_route_timing.rpt",
        "reports/phase3/sta_spef_based.rpt",
        "reports/phase3/sta/post_route_summary.json",
        "reports/phase3/sta/sta_corner_record_completeness.json",
        "reports/phase3/sta/post_route_signoff_corner.json",
    ], outs["23"]
    # and no step declares a `*_receipt.json` for any of the four wrappers
    every = [o for lst in outs.values() for o in lst]
    for auditor in _WRAPPERS:
        assert f"{auditor}_receipt.json" not in [Path(o).name for o in every]


# ---------------------------------------------------------------------------
# ELOOP — found by running BOTH arms of the selection, not by inspection
# ---------------------------------------------------------------------------
def test_a_symlink_loop_in_the_subject_is_a_verdict_not_a_traceback(tmp_path):
    """MEASURED at #2057, on the FINAL arm only: once the `--json` document
    started carrying a subject digest, a mutually-pointing pair of
    report-named symlinks turned `drc_report_check . --mode drc` from a
    verdict about 11 DRC items into a traceback and NO verdict document —
    reddening `test_report_audit_symlink_dedup.py::
    test_symlink_loop_returns_a_verdict_not_a_traceback[extra0-project-wide]`,
    which is green on the base arm.

    `_audit_receipt.subject_of` guarded only `OSError`, and the tree already
    records why that is not enough (`eda_report_audit._in_scope`: CPython
    raises a BARE `RuntimeError` for ELOOP). BOTH DIRECTIONS below: the raw
    `Path.resolve()` on this input really does raise, and `subject_of` really
    does return a subject anyway.
    """
    a = tmp_path / "drc_a.rpt"
    b = tmp_path / "drc_b.rpt"
    a.symlink_to(b)
    b.symlink_to(a)
    real = tmp_path / "drc_real.rpt"
    real.write_text("total violations: 0\n")

    with pytest.raises((OSError, RuntimeError)):
        a.resolve()

    subj = _audit_receipt.subject_of([a, b, real])
    assert len(subj["items"]) == 3, subj
    # the unreadable pair is RECORDED, not dropped, and the digest says so
    assert subj["basis"] == _audit_receipt.BASIS_PATH
    assert [i["sha256"] for i in subj["items"] if i["is_file"]], subj
    assert isinstance(subj["sha256"], str) and len(subj["sha256"]) == 64


def test_the_subject_of_an_unreadable_item_still_separates_two_subjects():
    """A `path`-basis digest is weaker than a `content` one and says so, but it
    must still be a digest: two different subjects may not collide."""
    one = _audit_receipt.subject_of(["/nonexistent/a.rpt"])
    two = _audit_receipt.subject_of(["/nonexistent/b.rpt"])
    assert one["basis"] == two["basis"] == _audit_receipt.BASIS_PATH
    assert one["sha256"] != two["sha256"]


# ---------------------------------------------------------------------------
# Reachable is not asserted — the three item-3 paths nothing pinned
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("auditor", sorted(_WRAPPERS))
def test_written_as_really_reaches_the_message_it_exists_for(auditor):
    """`written_as` is only ever read when `filename` is empty, and only into
    the NOT_MEASURED *detail*. Nothing asserted it, so it could be emptied or
    left describing the wrong file and every test would stay green — which is
    the "field nobody reads" shape #2050's dead `postchecks:` key had.

    It must name the DECLARED step output, because that string is the only
    thing telling a reader which artefact to go and produce.
    """
    rs = scc.AUDIT_RECEIPTS[auditor]
    assert rs.filename == "", auditor
    assert rs.written_as, auditor
    spec = {"skill": "p", "requirements": [],
            "cross_checks": [{"id": "X", "rule": "audit_receipt_evidence",
                              "auditor": auditor, "description": "d"}]}
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        rep = Path(t) / "r.md"
        rep.write_text("# r\n")
        f, = [x for x in scc.audit("# r\n", spec,
                                   ctx=scc.CheckContext(output_path=rep))
              if x.id == "X"]
    assert rs.written_as in f.detail, f.detail
    assert "matched by content, not by name" in f.detail
    assert auditor in rs.written_as
    assert "reports/phase3" in rs.written_as, (
        f"{auditor}: written_as must name the declared step output a reader "
        f"has to produce, got {rs.written_as!r}")


def test_both_configuration_error_suffixes_are_still_producible():
    """The generated test strips `_unknown_auditor` / `_no_auditor` before
    comparing the receipt set. #2057 emptied UNREGISTERED_AUDITORS, so if
    those suffixes were no longer producible that stripping would be dead
    code. They are: the rule still emits them for an auditor with no contract
    and for a cross-check with no `auditor:` key at all."""
    unknown, = [x for x in scc.audit("# r\n", {
        "skill": "p", "requirements": [],
        "cross_checks": [{"id": "X", "rule": "audit_receipt_evidence",
                          "auditor": "no_such_auditor", "description": "d"}]})
        if x.id.startswith("X")]
    assert unknown.id == "X_unknown_auditor"
    missing, = [x for x in scc.audit("# r\n", {
        "skill": "p", "requirements": [],
        "cross_checks": [{"id": "X", "rule": "audit_receipt_evidence",
                          "description": "d"}]})
        if x.id.startswith("X")]
    assert missing.id == "X_no_auditor"


def test_relative_to_falls_back_rather_than_raising_when_the_item_is_outside(
        tmp_path):
    """The MISS branch of `relative_to`, which nothing asserted. An item that
    is not under the base keeps its resolved path — the alternative would be
    to drop it or to raise, and a subject that quietly loses an item is a
    digest about a different subject."""
    (tmp_path / "a.rpt").write_text("x")
    hit = _audit_receipt.subject_of([tmp_path / "a.rpt"],
                                    relative_to=tmp_path)
    miss = _audit_receipt.subject_of([tmp_path / "a.rpt"],
                                     relative_to=tmp_path / "not_a_parent")
    assert hit["items"][0]["path"] == "a.rpt"
    assert Path(miss["items"][0]["path"]).is_absolute()
    assert len(miss["items"]) == 1, "the item must never be dropped"
    # and the digest is unmoved either way, because the path is not in it
    assert hit["sha256"] == miss["sha256"]
    # an unusable `relative_to` degrades to no rebasing, never to an exception
    weird = _audit_receipt.subject_of([tmp_path / "a.rpt"],
                                      relative_to="\0not-a-path")
    assert weird["sha256"] == hit["sha256"]
