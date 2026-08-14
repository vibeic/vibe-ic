"""#524 — `evidence[] non-empty` is a length test, and length cannot tell
corroboration from the run pointing at its own report.

#519 established that the attestation quartet (`ticket` + `review_required` +
non-empty `evidence` + a substantive `rationale`) stands in for a human
signature in the `waivers` dialect: there is no `approved_at` and no human
`approver`, so `evidence` carries the signature's weight. The check on it is
`evidence[] non-empty`. A list holding one pointer back at the producing run's
own orchestrator report satisfies that exactly as well as a pointer to an
independent artefact, and the verdict a reader sees is identical either way.

MEASURED over the 8 tracked attestation entries, and pinned below:
    5 of 8   cite ONLY the producing run's own orchestrator report
    1 of 8   fills the field with free text that references nothing
    2 of 8   cite artefacts that exist independently of the run's record

WHAT SHIPPED IS A DISCLOSURE, NOT A REFUSAL, and that is a measured decision
rather than a timid one. The ENV_UNAVAILABLE tier's claim is that a tool was
ABSENT; no independent artefact can corroborate a non-execution, because the
artefact whose absence IS the waiver is the one being demanded. Executed
against the real producer, EVERY ENV_UNAVAILABLE waiver
`phase3_one_shot_runner._autogen_waivers_json` can emit is uncorroborated — it
appends the self-reference unconditionally and harvests `extras` scalars (a
tool name, a layer-rule fragment) as though each were a path. Refusing
uncorroborated evidence would therefore make an honest, correctly disclosed,
tool-less-host deferral impossible to honour: "disclosure buys deferral" would
break for precisely the population the tier exists to serve.

So self-reference is acceptable ALONGSIDE something else and never sufficient
ALONE, the waiver is still honoured, and what changes is that the report can no
longer read identically in the two cases.

The tests below pin, by EXECUTION:
  * the classification itself, including the two sub-cases #524 names
    separately (self-reference, and free text that is not a reference);
  * the corpus measurement, so the numbers in the issue cannot drift silently;
  * that an uncorroborated waiver is STILL HONOURED — the step stays WAIVED;
  * that nothing here can take a run down: the finding is a WARNING, the schema
    check still exits 0, and `flow_compliance_check` still produces a report
    with its advisories intact (the #519 failure mode, tested directly);
  * that a corroborated waiver produces NO disclosure, so the signal means
    something.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _evidence_independence as _ei  # noqa: E402
import _waiver_entries as _we  # noqa: E402
import waivers_schema_check as wsc  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
WSC = PROGRAMS / "waivers_schema_check.py"

#: Repo root, from the plugin programs dir. Used only to reach the tracked
#: corpus; the corpus is READ, never written.
REPO_ROOT = PROGRAMS.parents[3]
CORPUS = REPO_ROOT / "benchmark-data/evaluation/phase1_parity"

SELF_REF = "reports/orchestrator/phase3_one_shot.json#steps[name=lvs]"

GOOD_RATIONALE = (
    "lvs step skipped because the netgen binary is not available in the "
    "current environment. ENV gap, NOT a design defect.")


def _attestation(**over):
    entry = {
        "step": "lvs",
        "verdict_tier": "ENV_UNAVAILABLE",
        "rationale": GOOD_RATIONALE,
        "evidence": [SELF_REF],
        "ticket": "TAPEOUT-ENV-LVS-NETGEN",
        "review_required": True,
    }
    entry.update(over)
    return entry


def _project(tmp_path: Path, *entries) -> Path:
    (tmp_path / "waivers.json").write_text(
        json.dumps({"_schema_version": "1", "waivers": list(entries)},
                   indent=2))
    return tmp_path


# ----------------------------------------------------------------------
# 1. The classification — what "independent" means
# ----------------------------------------------------------------------

def test_self_reference_to_the_runs_own_report_is_not_independent(tmp_path):
    """The specific defect #524 names: a pointer at the producing run's own
    orchestrator report is a self-report, never corroboration."""
    assert _ei.classify_item(SELF_REF, tmp_path) == _ei.KIND_SELF_REPORT


def test_self_reference_is_recognised_without_the_fragment_selector(tmp_path):
    """The `#steps[...]` selector is not what makes it self-referential — the
    directory it points into is."""
    assert _ei.classify_item(
        "reports/orchestrator/phase3_one_shot.json",
        tmp_path) == _ei.KIND_SELF_REPORT


def test_an_existing_artefact_outside_the_run_record_is_independent(tmp_path):
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3" / "drc.rpt").write_text("x\n")
    assert _ei.classify_item("phase3/drc.rpt",
                             tmp_path) == _ei.KIND_INDEPENDENT


def test_bare_fragment_is_not_a_reference(tmp_path):
    """#524's second sub-case: the field used as free text. A bare token names
    no artefact, so it cannot make a deferral auditable."""
    for frag in ("stdcell-library-foundry-qualified", "klayout",
                 "TAPEOUT-AUTOGEN-DRC", "magic,netgen"):
        assert _ei.classify_item(frag, tmp_path) == _ei.KIND_UNRESOLVABLE, frag


def test_a_prose_sentence_containing_a_slash_is_not_a_reference(tmp_path):
    """Whitespace is the discriminator. Without it, a rationale paragraph
    mentioning a path separator would read as a dangling artefact citation and
    the free-text sub-case would be under-counted."""
    prose = ("Router metal stack is clean; see the vendor deck under "
             "input/pdk/ before sign-off.")
    assert _ei.classify_item(prose, tmp_path) == _ei.KIND_UNRESOLVABLE


def test_path_shaped_but_absent_artefact_is_dangling_not_independent(tmp_path):
    """A citation of something that is not there reads as corroboration while
    corroborating nothing, so it is named rather than folded into either
    neighbour."""
    assert _ei.classify_item("phase3/stage3/pnr/openroad.log#DRT-0199=0",
                             tmp_path) == _ei.KIND_DANGLING


def test_reference_escaping_the_project_is_not_independent(tmp_path):
    """Absolute paths and `..` escapes cannot be audited from the project, so
    they never count as corroboration however real they are on this host."""
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("real file, wrong side of the boundary\n")
    assert _ei.classify_item(str(outside), tmp_path) == _ei.KIND_DANGLING
    assert _ei.classify_item("../outside.txt",
                             tmp_path) == _ei.KIND_DANGLING


def test_citing_the_waiver_file_itself_is_not_corroboration(tmp_path):
    """The cheapest way to silence a disclosure would be to cite the file the
    waiver is written in — it is guaranteed to exist beside every attestation.
    Same self-reference, one level out."""
    _project(tmp_path, _attestation())
    assert _ei.classify_item(_we.WAIVERS_FILENAME,
                             tmp_path) == _ei.KIND_SELF_REPORT
    assert not _ei.assess([_we.WAIVERS_FILENAME], tmp_path).corroborated


def test_bare_filename_at_the_project_root_still_counts(tmp_path):
    """A separator is sufficient but not necessary: an evidence item naming a
    real file beside the waiver is a legitimate reference."""
    (tmp_path / "drc.rpt").write_text("x\n")
    assert _ei.classify_item("drc.rpt", tmp_path) == _ei.KIND_INDEPENDENT


def test_corroboration_needs_one_independent_item_not_all_of_them(tmp_path):
    """Answering #524's question: acceptable ALONGSIDE something else, never
    ALONE. Demanding that EVERY item be independent would reject the entries
    that cite real artefacts and the run-record index — the ones that got it
    right."""
    (tmp_path / "a.v").write_text("x\n")
    both = _ei.assess(["a.v", SELF_REF], tmp_path)
    assert both.corroborated
    assert both.self_report == 1 and both.independent == 1

    alone = _ei.assess([SELF_REF], tmp_path)
    assert not alone.corroborated
    assert alone.self_referential_only


def test_assess_survives_a_malformed_evidence_field(tmp_path):
    """A classifier that crashed on a bad field would take down the gate that
    only wanted to describe it."""
    for bad in (None, "not-a-list", 7, {"a": 1}):
        a = _ei.assess(bad, tmp_path)
        assert a.total == 0 and not a.corroborated
    mixed = _ei.assess([None, 7, SELF_REF], tmp_path)
    assert mixed.total == 3 and mixed.self_report == 1
    assert mixed.unresolvable == 2


# ----------------------------------------------------------------------
# 2. The corpus measurement, pinned
# ----------------------------------------------------------------------

@pytest.mark.skipif(not CORPUS.is_dir(), reason="tracked corpus not present")
def test_corpus_attestation_entries_measure_as_reported():
    """The 8 tracked attestation entries, classified. These are the numbers the
    disclosure-versus-refusal decision rests on; pinning them means a corpus
    edit that changes the picture cannot pass unnoticed."""
    rows = []
    for wf in sorted(CORPUS.glob("*/waivers.json")):
        doc = json.loads(wf.read_text())
        for entry in _we.entries_by_key(doc).get("waivers", []):
            rows.append((wf.parent.name, entry.get("step"),
                         _ei.assess(entry.get("evidence"), wf.parent)))

    # THE PARTITION, not the census. `8 == 5 + 2 + 1` was four integers and all
    # four are the size of the tracked corpus on the day they were written — a
    # publish or a withdrawal breaks every one of them without telling anyone
    # anything about the classifier. What they stood in for is that the three
    # buckets PARTITION the entries (no entry in two, none in none) and that
    # each is exercised, which is what makes the disclosure-versus-refusal
    # decision rest on measured ground rather than on a hypothesis.
    assert rows, "no tracked attestation entry — nothing was classified"
    corroborated = [r for r in rows if r[2].corroborated]
    self_only = [r for r in rows if r[2].self_referential_only]
    free_text = [r for r in rows
                 if not r[2].corroborated and not r[2].self_referential_only]

    assert (len(corroborated) + len(self_only) + len(free_text)
            == len(rows)), [r[:2] for r in rows]
    assert not (set(map(id, corroborated)) & set(map(id, self_only))), \
        "an entry is both corroborated and self-referential-only"
    for bucket, label in ((self_only, "self-referential-only"),
                          (corroborated, "corroborated"),
                          (free_text, "free-text")):
        assert bucket, (
            f"no tracked entry lands in the {label} bucket, so the three-way "
            f"split above is not exercised and this measurement is vacuous")

    # every entry carries exactly one self-reference — the producer appends it
    # unconditionally, which is why the field could never discriminate.
    assert all(r[2].self_report == 1 for r in rows), \
        [(r[0], r[1], r[2].self_report) for r in rows]

    # the free-text entry is the one whose items are overwhelmingly non-
    # references, not merely uncorroborated.
    assert free_text[0][2].unresolvable >= 10, free_text[0][2].as_dict()


# ----------------------------------------------------------------------
# 3. The honour path — still honoured, now disclosed
# ----------------------------------------------------------------------

def _load(project: Path):
    """Fresh import each call so the module-level advisory lists are read after
    the load they belong to."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_compliance_check as fcc
    waivers = fcc._load_waivers(project)
    return fcc, waivers


def test_self_referential_waiver_is_still_honoured(tmp_path):
    """DISCLOSURE BUYS DEFERRAL. The uncorroborated waiver keeps its exemption;
    refusing it would make a tool-less-host deferral unhonourable, since that
    is the only evidence such a run can produce."""
    fcc, waivers = _load(_project(tmp_path, _attestation()))
    assert 31 in waivers
    assert waivers[31]["_env_unavailable"] is True
    assert fcc._ENV_WAIVER_REJECTIONS == []


def test_self_referential_waiver_is_disclosed(tmp_path):
    fcc, waivers = _load(_project(tmp_path, _attestation()))
    notes = fcc._ENV_WAIVER_EVIDENCE_NOTES
    assert len(notes) == 1, notes
    assert "UNCORROBORATED" in notes[0]
    assert "own orchestrator report" in notes[0]
    assert waivers[31]["evidence_assessment"]["self_referential_only"] is True
    assert waivers[31]["evidence_assessment"]["corroborated"] is False


def test_corroborated_waiver_is_not_disclosed(tmp_path):
    """The signal has to mean something: an entry citing a real artefact must
    produce NO note, or the advisory is noise."""
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3" / "chip_pnr.v").write_text("module x; endmodule\n")
    fcc, waivers = _load(_project(
        tmp_path, _attestation(evidence=["phase3/chip_pnr.v", SELF_REF])))
    assert 31 in waivers and waivers[31]["_env_unavailable"] is True
    assert fcc._ENV_WAIVER_EVIDENCE_NOTES == []
    assert waivers[31]["evidence_assessment"]["corroborated"] is True


def test_free_text_evidence_is_disclosed_as_uncorroborated(tmp_path):
    """#524's separate sub-case: the field used as free text. It is non-empty,
    so the length test passes; it references nothing, so it corroborates
    nothing — and the report now says which."""
    fcc, waivers = _load(_project(tmp_path, _attestation(
        evidence=["stdcell-library-foundry-qualified", "klayout", SELF_REF])))
    assert 31 in waivers and waivers[31]["_env_unavailable"] is True
    assert len(fcc._ENV_WAIVER_EVIDENCE_NOTES) == 1
    assess = waivers[31]["evidence_assessment"]
    assert assess["corroborated"] is False
    assert assess["counts"][_ei.KIND_UNRESOLVABLE] == 2
    # NOT the self-referential-only shape — a different sub-case, said
    # differently, so a reader can tell them apart.
    assert assess["self_referential_only"] is False


def test_disclosure_list_is_cleared_between_loads(tmp_path):
    """Repeated calls in one process must not accumulate — the same contract
    `_ENV_WAIVER_REJECTIONS` already keeps."""
    project = _project(tmp_path, _attestation())
    fcc, _ = _load(project)
    fcc, _ = _load(project)
    assert len(fcc._ENV_WAIVER_EVIDENCE_NOTES) == 1


# ----------------------------------------------------------------------
# 4. Nothing here may take a run down (#519's failure mode)
# ----------------------------------------------------------------------

def test_uncorroborated_evidence_is_a_warning_never_an_error(tmp_path):
    """The severity is load-bearing. `waivers_schema_check` errors become
    `SystemExit(1)` inside `flow_compliance_check._load_waivers`; an ERROR here
    would stop killing one step's exemption and start killing the whole
    report."""
    findings, _ = wsc.validate(_project(tmp_path, _attestation()))
    rules = {f.rule for f in findings}
    assert "attestation-evidence-uncorroborated" in rules
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], [(f.rule, f.message) for f in errors]


def test_dangling_citation_is_reported_even_when_corroborated(tmp_path):
    """An entry can cite a real artefact AND a missing one. The missing
    citation reads as corroboration — it is path-shaped — so it is named,
    rather than being hidden by the item that happened to resolve. This is the
    shape one tracked entry actually has."""
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3" / "drc.rpt").write_text("x\n")
    findings, _ = wsc.validate(_project(tmp_path, _attestation(evidence=[
        "phase3/drc.rpt", "phase3/stage3/pnr/openroad.log#DRT-0199=0",
        SELF_REF])))
    rules = [f.rule for f in findings]
    assert "attestation-evidence-dangling" in rules, rules
    assert "attestation-evidence-uncorroborated" not in rules, rules
    assert [f for f in findings if f.severity == "error"] == []


def test_schema_check_still_exits_zero_on_uncorroborated_evidence(tmp_path):
    r = subprocess.run([sys.executable, str(WSC), str(
        _project(tmp_path, _attestation()))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "attestation-evidence-uncorroborated" in r.stdout


def test_a_run_with_uncorroborated_evidence_still_produces_a_report(tmp_path):
    """The direct #519 regression: the run must not die. A report is written,
    the waived step is present as WAIVED, and the disclosure is in it."""
    project = _project(tmp_path, _attestation())
    out = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, str(FCC), str(project), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    assert out.is_file(), (
        "no report at all — the #519 failure mode\n" + r.stdout + r.stderr)
    report = json.loads(out.read_text())
    assert report.get("steps"), "report has no steps"

    step31 = [s for s in report["steps"] if str(s.get("id")) == "31"]
    assert step31 and step31[0]["status"] == "WAIVED", step31

    disclosed = [a for a in (report.get("advisories") or [])
                 if "UNCORROBORATED" in a]
    assert len(disclosed) == 1, report.get("advisories")


def test_incomplete_waiver_still_gets_its_216_advisory(tmp_path):
    """#519's exact lesson, re-pinned: the incomplete-waiver path must keep
    emitting its rejection advisory. A disclosure added next to it must not
    displace it, and must not fire for a waiver that was never honoured."""
    project = _project(tmp_path, _attestation(evidence=[]))
    out = tmp_path / "report.json"
    subprocess.run([sys.executable, str(FCC), str(project), "--json",
                    str(out)], capture_output=True, text=True, timeout=60)
    assert out.is_file(), "no report at all — the #519 failure mode"
    advisories = json.loads(out.read_text()).get("advisories") or []

    rejected = [a for a in advisories if "was NOT applied" in a]
    assert len(rejected) == 1, advisories
    assert "a non-empty `evidence` list" in rejected[0]

    # the waiver was refused, so there is no honoured-but-uncorroborated one
    assert [a for a in advisories if "UNCORROBORATED" in a] == []


# ----------------------------------------------------------------------
# 5. Why the disclosure, and not a refusal — pinned against the producer
# ----------------------------------------------------------------------

def test_producer_always_appends_the_self_reference(tmp_path):
    """`_autogen_waivers_json` appends the run-record index unconditionally, so
    the self-reference is on EVERY auto-generated entry. This is the reason
    `evidence[] non-empty` could never discriminate, and the reason a refusal
    would hit every honestly-disclosed deferral rather than the dishonest
    ones."""
    import phase3_one_shot_runner as p3

    plan = [p3.StepResult(
        "lvs", "ENV_UNAVAILABLE", 0.1,
        "open-source LVS needs magic+netgen in container PATH",
        extras={"missing_tool": "magic,netgen"})]
    p3._autogen_waivers_json(tmp_path, plan)
    emitted = json.loads((tmp_path / "waivers.json").read_text())

    entry = emitted["waivers"][0]
    assert entry["verdict_tier"] == "ENV_UNAVAILABLE", entry
    assessment = _ei.assess(entry["evidence"], tmp_path)
    assert assessment.self_report == 1, entry["evidence"]
    # and the harvested `extras` scalar is a tool name, not a path — the same
    # shape as the corpus's free-text sub-case, from the same harvester.
    assert assessment.unresolvable >= 1, entry["evidence"]
    assert not assessment.corroborated, entry["evidence"]


def test_that_producers_output_is_honoured_not_refused(tmp_path):
    """The consequence, stated as a test: what the runner emits on a host
    missing the tool is honoured. If a future change made uncorroborated
    evidence a refusal, this run would lose its deferral and the tier would
    stop working for the case it exists for."""
    import phase3_one_shot_runner as p3

    p3._autogen_waivers_json(tmp_path, [p3.StepResult(
        "lvs", "ENV_UNAVAILABLE", 0.1, "needs netgen in PATH",
        extras={"missing_tool": "netgen"})])
    fcc, waivers = _load(tmp_path)
    assert 31 in waivers and waivers[31]["_env_unavailable"] is True
    assert len(fcc._ENV_WAIVER_EVIDENCE_NOTES) == 1
