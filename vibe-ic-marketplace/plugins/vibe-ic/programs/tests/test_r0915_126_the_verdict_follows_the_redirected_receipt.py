"""A redirected receipt is where the gate's verdict IS. Read it there.

THE REGRESSION THIS CLOSES, measured. v1.23.23 made a clause's `--json` receipt
go to a scratch path whenever the named target was a document the run had
already produced, so that the audit stops overwriting the run's own evidence
(R-0915-126: producer writes, gate reads). But the verdict READER kept reading
the path the clause NAMES -- which now holds the PRODUCER's document, and a
producer's document carries no gate verdict. On the spm S arm that turned
step 14 (Synthesis handoff gate) from PASS into NOT_MEASURED, moved seven more
steps from FAIL to NOT_MEASURED, and on the subservient replays turned step 7's
NOT_APPLICABLE into NOT_MEASURED.

`NOT_MEASURED` over a gate that ran, exited and wrote a verdict is the worst of
the three answers: it is indistinguishable from a gate that was never wired.

Both directions are pinned here. The receipt is followed when it was
redirected; the clause's own path is still read when it was not; the producer's
document is never read for a verdict and never written; and a receipt that
disagrees with the document proves WHICH of the two was consulted.
"""
from __future__ import annotations

import json
import hashlib
import os
import pathlib
from pathlib import Path
import stat
import pytest
import flow_compliance_check as F


@pytest.mark.parametrize("old_verdict,current_bad", [("FAIL", False), ("PASS", True)])
def test_real_conformance_ledger_binds_the_current_retained_receipt(
        tmp_path, old_verdict, current_bad):
    project = tmp_path / "project"
    rtl = project / "phase2/stage1/rtl"
    docs = project / "phase1/generated_docs"
    canonical = project / "reports/phase2/gates/spec_conformance.json"
    for directory in (rtl, docs, canonical.parent):
        directory.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text(
        "module core(input clk, output gpio); assign gpio=clk; endmodule\n")
    ports = [{"name": "clk", "direction": "input", "width": 1},
             {"name": "gpio", "direction": "output", "width": 1}]
    if current_bad:
        ports.append({"name": "required", "direction": "output", "width": 1})
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "core", "ports": ports}))
    canonical.write_text(json.dumps({"program": "prior_producer",
        "verdict": old_verdict, "design_identity": {"top": "old_child"}}))
    before = canonical.read_bytes()
    F._GATE_LEDGER.clear()
    command = ("spec_conformance_check --rtl-dir phase2/stage1/rtl "
               "--spec phase1/generated_docs/L9_INTEGRATION_SPEC.json "
               "--json reports/phase2/gates/spec_conformance.json")
    result = F._check_program_exit_zero(project, command)
    assert result.exit_code == (1 if current_bad else 0)
    assert result.verdict == ("FAIL" if current_bad else "PASS")
    assert result.structured_verdict is None  # current native findings are a list
    row = F._GATE_LEDGER[-1]
    receipt = Path(row["receipt"]["path"])
    assert receipt != canonical and receipt.is_file()
    assert row["receipt"]["sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert row["executed_argv"][row["executed_argv"].index("--json") + 1] == str(receipt)
    findings = json.loads(receipt.read_text())
    assert bool(findings) is current_bad
    assert canonical.read_bytes() == before

#: A gate that writes a typed verdict to its --json path and exits with a
#: chosen rc. Nothing about it is chip-specific.
GATE = '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
argv = sys.argv[1:]
out = None
for i, tok in enumerate(argv[:-1]):
    if tok in ("--json", "--report"):
        out = Path(argv[i + 1])
if out is not None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"program": "fixture_verdict_gate",
                               "verdict": %(verdict)r,
                               "reason": "the gate's own receipt"}))
sys.exit(%(rc)d)
'''

#: What a PRODUCER's document looks like where a gate clause happens to name the
#: same path: the run's own output, with no gate verdict in it at all.
PRODUCER_DOC = {"program": "fixture_producer", "schema": "fixture/1",
                "measurement": 42}


def stage(tmp_path, monkeypatch, *, verdict="PASS", rc=0,
          target_exists=True, doc=None):
    programs = tmp_path / "programs"
    programs.mkdir()
    gate = programs / "fixture_verdict_gate.py"
    gate.write_text(GATE % {"verdict": verdict, "rc": rc})
    gate.chmod(gate.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(F, "PROGRAMS_DIR", programs)

    project = tmp_path / "proj"
    (project / "reports").mkdir(parents=True)
    rel = "reports/fixture_document.json"
    if target_exists:
        (project / rel).write_text(json.dumps(
            PRODUCER_DOC if doc is None else doc))
    return project, rel


def before(project, rel):
    p = project / rel
    return p.read_bytes() if p.is_file() else None


def test_the_verdict_comes_from_the_redirected_receipt(tmp_path, monkeypatch):
    project, rel = stage(tmp_path, monkeypatch)
    was = before(project, rel)
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert res.structured_verdict == "PASS", res
    # and the producer's document is untouched, which is the whole reason the
    # receipt moved in the first place.
    assert before(project, rel) == was


def test_a_receipt_that_disagrees_with_the_document_proves_which_was_read(
        tmp_path, monkeypatch):
    """THE DISCRIMINATOR. The document claims one thing and the gate's receipt
    another; only reading the receipt can give the receipt's answer."""
    project, rel = stage(tmp_path, monkeypatch, verdict="NOT_APPLICABLE", rc=0,
                         doc={"program": "fixture_producer",
                              "verdict": "FAIL"})
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert res.structured_verdict == "NOT_APPLICABLE", res


def test_a_not_applicable_receipt_survives_the_redirect(tmp_path, monkeypatch):
    """The subservient step-7 shape: NOT_APPLICABLE, not NOT_MEASURED."""
    project, rel = stage(tmp_path, monkeypatch, verdict="NOT_APPLICABLE")
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert res.structured_verdict == "NOT_APPLICABLE", res


@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "NOT_APPLICABLE"])
def test_every_typed_verdict_survives_the_redirect(tmp_path, monkeypatch,
                                                   verdict):
    project, rel = stage(tmp_path, monkeypatch, verdict=verdict,
                         rc=1 if verdict == "FAIL" else 0)
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert res.structured_verdict == verdict, res


def test_an_unredirected_clause_still_reads_the_path_it_names(tmp_path,
                                                             monkeypatch):
    """No redirect happens when the target does not exist yet, and that path is
    still where the verdict is read from. The fix must not move THAT."""
    project, rel = stage(tmp_path, monkeypatch, verdict="PASS",
                         target_exists=False)
    assert not (project / rel).exists()
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert res.structured_verdict == "PASS", res
    # the gate wrote it, because nothing was there to protect
    assert json.loads((project / rel).read_text())["verdict"] == "PASS"


def test_the_receipt_is_still_on_disk_when_the_wrapper_reads_it(tmp_path,
                                                               monkeypatch):
    """The scratch directory is kept on the outcome. Held only by a local in the
    inner function it was destroyed on return, and the verdict read a path that
    no longer existed."""
    project, rel = stage(tmp_path, monkeypatch, verdict="PASS")
    inner = F._ProgramCheckOutcome
    seen = {}
    original = F._receipt_off_a_produced_document

    def spy(argv, prj):
        moved, note, keep = original(argv, prj)
        seen["argv"] = list(moved)
        seen["note"] = note
        return moved, note, keep

    monkeypatch.setattr(F, "_receipt_off_a_produced_document", spy)
    res = F._check_program_exit_zero(project, f"fixture_verdict_gate . --json {rel}")
    assert seen["note"] and "RECEIPT REDIRECTED" in seen["note"]
    scratch = seen["argv"][seen["argv"].index("--json") + 1]
    assert os.path.dirname(scratch) not in ("", str(project))
    assert res.structured_verdict == "PASS"
    del inner


def test_one_document_named_two_ways_shares_its_redirect(tmp_path):
    """`_resolved_key` is what makes the registry a map of DOCUMENTS rather than
    of strings. A clause may name a document absolutely and another relatively;
    both must find the one redirect, or the second reader falls back to the
    document and publishes its older answer.

    (Note for the mutation arm: replacing `resolve()` with `str()` is an
    EQUIVALENT mutant for a single clause, because the writer and the reader
    derive the path from the same verbatim argument -- non-glob args pass through
    `_expand_globs` unchanged. It is THIS case that makes the normalisation
    load-bearing.)"""
    # The project is reached through a SYMLINK, so the real path and the path
    # the clause resolves against are different strings for the same file. That
    # is the divergence `resolve()` exists for.
    real = tmp_path / "real"
    (real / "reports").mkdir(parents=True)
    project = tmp_path / "proj"
    project.symlink_to(real, target_is_directory=True)
    target = real / "reports/shared.json"
    target.write_text(json.dumps({"program": "fixture_producer",
                                  "verdict": "NOT_CHECKED"}))
    assert str(target) != str(project / "reports/shared.json")
    # the WRITER sees the real absolute spelling
    argv = ["python3", "gate.py", ".", "--json", str(target)]
    moved, note, keep = F._receipt_off_a_produced_document(argv, project)
    assert note and moved[-1] != str(target)
    pathlib_write = pathlib.Path(moved[-1])
    pathlib_write.parent.mkdir(parents=True, exist_ok=True)
    pathlib_write.write_text(json.dumps({"verdict": "CLEAN"}))
    try:
        # the READER sees a relative spelling of the SAME document
        got = F._command_json_report(project, "gate . --json reports/shared.json")
        assert got == {"verdict": "CLEAN"}, got
    finally:
        F._RECEIPT_REDIRECTS.pop(F._resolved_key(target), None)
        del keep


def test_the_shared_reader_admits_only_a_nonempty_json_object(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text("")
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    obj = tmp_path / "obj.json"
    obj.write_text('{"verdict": "PASS"}')
    assert F._json_report_at(empty) is None
    assert F._json_report_at(arr) is None
    assert F._json_report_at(bad) is None
    assert F._json_report_at(tmp_path / "absent.json") is None
    assert F._json_report_at(obj) == {"verdict": "PASS"}
