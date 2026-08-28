"""test_reported_evidence_is_the_reported_run.py

TWO MEASURED PROCESS DEFECTS, ONE SHAPE: a number reported as proof of a run
that belongs to a different run.

(a) A STALE DOCUMENT INSIDE THE REPORTED EVIDENCE.
    A run directory carried a report written at 05:55 asserting one compliance
    tally and describing a step as having produced nothing, while the artefacts
    in the SAME directory were written at 10:12 and that step had produced
    them. Four sibling directories carried byte-identical copies of that one
    document. A reader sent to the directory read the wrong round's numbers
    with nothing to notice it by.

(b) A DIGEST QUOTED AS PROOF THAT NOBODY RECOMPUTES.
    The digests the netlist published were taken over files that embed a
    wall-clock stamp and an absolute path, so they changed on every run of
    byte-identical inputs. Five sibling run trees of the same inputs published
    five different digests and nothing on any of them said which tree it came
    from. Separately, the report checker verified that a 64-hex citation was
    PRESENT and never compared it to the artefact it names.

THE RULE, with no tool or step name in it:

    A directory presented as the evidence for a result must not contain a
    document that contradicts that evidence. A number quoted as proof must be
    recomputable from the directory the document sits in, and a document that
    reports on artefacts older than itself is reporting on a different run.

Fixtures are synthetic throughout.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
RESULT_MD_CHECK = PROGRAMS / "result_md_audit_provenance_check.py"
A3_GATE = PROGRAMS / "analog_a3_netlist_gen_check.py"

from _analog_producer_fixture import (            # noqa: E402
    A1, A2, A3, block, make_project, run_prog, bdir, read_json)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

LDO_SPEC = [{"name": "Vout", "target": 1.8, "unit": "V"},
            {"name": "Vin", "target": 3.0, "unit": "V"}]

TALLY = "**Flow compliance: PASS=27 FAIL=11 MISSING=12 WAIVED-DEFERRED=2**"


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True)


# ═══ (a) a document that contradicts the evidence it sits in ══════════════

def _evidence_tree(tmp_path, *, doc_age_s: float, extra_doc: str = "") -> Path:
    """A run directory holding artefacts and a report. `doc_age_s` is how much
    OLDER than the artefacts the report is."""
    root = tmp_path / "run"
    (root / "reports" / "audit").mkdir(parents=True, exist_ok=True)
    (root / "phase3" / "analog" / "blk_alpha").mkdir(parents=True,
                                                     exist_ok=True)
    audit = root / "reports" / "audit" / "phase23_completion_audit.json"
    audit.write_text(json.dumps({"verdict": "PASS", "steps": []}, indent=2))
    (root / "phase3" / "analog" / "blk_alpha" / "blk_alpha.sp").write_text(
        ".subckt blk_alpha vdd vss\n.ends blk_alpha\n")
    doc = root / "RESULT.md"
    doc.write_text(f"# Run Result\n\n{TALLY}\n\n{extra_doc}\n")
    now = time.time()
    os.utime(doc, (now - doc_age_s, now - doc_age_s))
    for p in root.rglob("*"):
        if p.is_file() and p != doc:
            os.utime(p, (now, now))
    return root


def test_a_report_older_than_the_evidence_it_reports_on_is_a_failure(
        tmp_path):
    """The measured trap. The stale document claims a FAIL, so every rule
    that fires only on a PASS claim skipped it — which is exactly how it
    survived four copies."""
    root = _evidence_tree(tmp_path, doc_age_s=4 * 3600)
    cp = _run(RESULT_MD_CHECK, root)
    assert cp.returncode == 1, (
        f"an evidence directory containing a document that asserts a "
        f"different round's numbers was accepted (rc={cp.returncode}): "
        f"{cp.stdout.strip()[:300]}")
    assert "RESULT_MD_STALE_VS_EVIDENCE" in cp.stdout


def test_a_report_written_after_the_run_is_clean(tmp_path):
    """NEGATIVE CONTROL. Same tree, same document, same tally — only the
    ordering changes. Without this the rule above would also fire on the
    ordinary case of writing the report after the run."""
    root = _evidence_tree(tmp_path, doc_age_s=-60)   # written 60s AFTER
    cp = _run(RESULT_MD_CHECK, root)
    assert "RESULT_MD_STALE_VS_EVIDENCE" not in cp.stdout, cp.stdout
    assert cp.returncode == 0, cp.stdout


def test_a_report_that_quotes_no_tally_is_not_dated(tmp_path):
    """SECOND NEGATIVE CONTROL: the rule is about a document asserting the
    run's NUMBERS, not about every file that happens to be older."""
    root = _evidence_tree(tmp_path, doc_age_s=4 * 3600)
    (root / "RESULT.md").write_text("# Notes\n\nno numbers here.\n")
    old = time.time() - 4 * 3600
    os.utime(root / "RESULT.md", (old, old))
    cp = _run(RESULT_MD_CHECK, root)
    assert "RESULT_MD_STALE_VS_EVIDENCE" not in cp.stdout, cp.stdout


# ═══ (b) a digest quoted as proof must recompute in THIS tree ═════════════

def test_a_cited_audit_digest_from_another_run_is_a_failure(tmp_path):
    """PRESENCE was checked; identity was not. A 64-hex string copied from any
    other run satisfied the citation rule."""
    root = _evidence_tree(tmp_path, doc_age_s=-60)
    foreign = hashlib.sha256(b"a different run entirely").hexdigest()
    (root / "RESULT.md").write_text(
        f"# Run Result\n\n{TALLY}\n\n"
        f"## Burn provenance\n"
        f"audit_sha256: {foreign}\n"
        f"program_response: error_code: success\n"
        f"audit_verdict: PASS\n")
    cp = _run(RESULT_MD_CHECK, root)
    assert cp.returncode == 1, (
        f"a digest quoted as proof of THIS run, belonging to a different "
        f"run, was accepted (rc={cp.returncode}): {cp.stdout.strip()[:300]}")
    assert "RESULT_MD_AUDIT_SHA_MISMATCH" in cp.stdout


def test_the_matching_digest_is_accepted(tmp_path):
    """NEGATIVE CONTROL for the same rule: the citation the tree can back."""
    root = _evidence_tree(tmp_path, doc_age_s=-60)
    audit = root / "reports" / "audit" / "phase23_completion_audit.json"
    real = hashlib.sha256(audit.read_bytes()).hexdigest()
    (root / "RESULT.md").write_text(
        f"# Run Result\n\n{TALLY}\n\n"
        f"## Burn provenance\n"
        f"audit_sha256: {real}\n"
        f"program_response: error_code: success\n"
        f"audit_verdict: PASS\n")
    cp = _run(RESULT_MD_CHECK, root)
    assert cp.returncode == 0, cp.stdout


# ═══ (b) the artefact's own published digest ══════════════════════════════

def _emit(root, name="vreg_alpha"):
    p = make_project(root, [block(name, "ldo", LDO_SPEC)])
    run_prog(A1, p)
    run_prog(A2, p)
    cp = run_prog(A3, p)
    return p, cp


HEX64 = __import__("re").compile(r"\b[0-9a-f]{64}\b")


def _published_digests(project, name="vreg_alpha") -> set:
    """EVERY 64-hex token the artefact publishes about itself — in the netlist
    header and in the sidecar beside it. Read generically on purpose: the
    property under test is about what the artefact publishes as proof, not
    about one field name."""
    d = bdir(project, name)
    blob = (d / f"{name}.sp").read_text()
    blob += (d / "netlist_provenance.json").read_text()
    return set(HEX64.findall(blob))


def test_the_published_digest_identifies_content_not_the_moment_of_the_run(
        tmp_path):
    """The measurement that made the quoted digests useless.

    Two runs, two directories, byte-identical inputs, byte-identical circuit.
    Of everything the artefact publishes as proof, SOMETHING has to be the
    same — otherwise every digest it offers is a per-run nonce that a reader
    can neither recompute nor compare, which is exactly what five sibling run
    trees of the same inputs demonstrated by publishing five different sets.
    """
    a, ca = _emit(tmp_path / "a")
    b, cb = _emit(tmp_path / "b")
    assert ca.returncode == 0 and cb.returncode == 0, (ca.stderr, cb.stderr)

    # PRECONDITION — the two runs really did produce the same circuit, so any
    # digest that differs is a fact about the run and not about the design.
    def body(project):
        return [ln for ln in (bdir(project, "vreg_alpha")
                              / "vreg_alpha.sp").read_text().splitlines()
                if not ln.lstrip().startswith("* _provenance:")]
    assert body(a) == body(b), "the fixture produced two different circuits"

    da, db = _published_digests(a), _published_digests(b)
    assert da and db, "PRECONDITION: the artefact publishes no digest at all"
    assert da & db, (
        f"two runs of identical inputs over an identical circuit publish "
        f"{len(da)} and {len(db)} digests and NOT ONE of them is the same. "
        f"Every digest this artefact offers as proof is a per-run nonce: a "
        f"reader cannot recompute it, and a report quoting one cannot be "
        f"checked against the tree it names.")

    pa = read_json(bdir(a, "vreg_alpha")
                   / "netlist_provenance.json")["_provenance"]
    pb = read_json(bdir(b, "vreg_alpha")
                   / "netlist_provenance.json")["_provenance"]
    assert pa.get("content_sha256") == pb.get("content_sha256") \
        and pa.get("content_sha256"), (pa, pb)
    assert pa.get("run_ref") != pb.get("run_ref"), (
        "two sibling run trees publish the same run reference, so a number "
        "quoted from one cannot be told from a number quoted from the other")
    assert pa["provenance_ref"].startswith(pa["run_ref"] + "/")
    assert pa["provenance_ref"] != pb["provenance_ref"]


def test_a_provenance_record_from_another_run_does_not_survive_the_gate(
        tmp_path):
    """By construction: a shipped gate recomputes the published proof against
    the tree it is standing in. A record carried over from another run cannot
    last one gate run."""
    a, _ = _emit(tmp_path / "a")
    b, _ = _emit(tmp_path / "b")

    ok = _run(A3_GATE, a, "--block", "vreg_alpha")
    assert ok.returncode == 0, ok.stdout + ok.stderr    # PRECONDITION

    # The whole of run B's self-report, dropped into run A's tree. The netlist
    # bytes in A are untouched — only the record that claims to describe them.
    side_a = bdir(a, "vreg_alpha") / "netlist_provenance.json"
    side_a.write_text(
        (bdir(b, "vreg_alpha") / "netlist_provenance.json").read_text())

    cp = _run(A3_GATE, a, "--block", "vreg_alpha")
    assert cp.returncode == 1, (
        f"a provenance record belonging to a different run was accepted as "
        f"this run's proof (rc={cp.returncode}): {cp.stdout.strip()[:200]}")
    assert "A3_PROVENANCE_REF_MISMATCH" in (cp.stdout + cp.stderr)


def test_a_run_tree_copied_intact_still_verifies(tmp_path):
    """NEGATIVE CONTROL for the rule above, and the reason the run reference
    is not derived from the run's PATH.

    Deriving it from the path catches the sibling-directory mixup and also
    fails every `cp -a` — and a gate that fires on an ordinary copy is a gate
    that gets waived, which would close nothing. A whole tree copied intact
    still agrees with itself; only a record lifted OUT of one run and dropped
    into another disagrees."""
    a, _ = _emit(tmp_path / "a")
    assert _run(A3_GATE, a, "--block", "vreg_alpha").returncode == 0

    copy = tmp_path / "archived"
    shutil.copytree(a, copy)
    cp = _run(A3_GATE, copy, "--block", "vreg_alpha")
    assert cp.returncode == 0, (
        f"a run tree copied byte-for-byte fails its own provenance gate "
        f"(rc={cp.returncode}): {(cp.stdout + cp.stderr).strip()[:300]}")
