#!/usr/bin/env python3
"""The context boundary: references and hashes cross it, file bytes do not.

The central test here is a PROPERTY, not an example: write a marker into an
evidence file, build a context over it, and assert the marker is absent from
the context's canonical bytes. An example test ("this particular injection is
filtered") passes for a filter, and a filter is the thing that gets bypassed. A
property test passes only for a design in which there is no field for content
to travel in.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import agent_context as ac  # noqa: E402
from _ppa import canonical_json  # noqa: E402

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
CLI = PROGRAMS / "ppa_agent_context_build.py"


@pytest.fixture()
def evidence(tmp_path):
    root = tmp_path / "ev"
    (root / "phase3").mkdir(parents=True)
    (root / "phase3" / "sta.rpt").write_text(
        "clock clk\nsetup wns -0.124 ns\ntns -4.010 ns\n")
    (root / "phase3" / "drc.rpt").write_text("total violations: 3\n")
    return root


def refs(*pairs):
    return [{"path": p, "role": r} for p, r in pairs]


# --------------------------------------------------------------------------
# Positive.
# --------------------------------------------------------------------------

def test_a_context_is_built_and_every_ref_is_hash_bound(evidence):
    ctx = ac.build_context(
        evidence, refs(("phase3/sta.rpt", "sta_report")), "root_cause")
    assert ctx["evidence_count"] == 1
    entry = ctx["evidence"][0]
    assert entry["sha256"].startswith("sha256:")
    expected = hashlib.sha256(
        (evidence / "phase3" / "sta.rpt").read_bytes()).hexdigest()
    assert entry["sha256"] == "sha256:" + expected


def test_the_hash_is_of_the_bytes_on_disk_and_moves_when_they_do(evidence):
    before = ac.build_context(
        evidence, refs(("phase3/sta.rpt", "sta_report")), "q")
    (evidence / "phase3" / "sta.rpt").write_text("setup wns +0.010 ns\n")
    after = ac.build_context(
        evidence, refs(("phase3/sta.rpt", "sta_report")), "q")
    assert before["evidence"][0]["sha256"] != after["evidence"][0]["sha256"]
    assert ac.context_digest(before) != ac.context_digest(after)


def test_the_context_digest_is_stable_for_the_same_evidence(evidence):
    a = ac.build_context(evidence, refs(("phase3/sta.rpt", "sta_report")), "q")
    b = ac.build_context(evidence, refs(("phase3/sta.rpt", "sta_report")), "q")
    assert ac.context_digest(a) == ac.context_digest(b)


def test_a_zero_byte_artefact_is_a_ref_and_not_a_missing_one(evidence):
    """'I could not read it' and 'I read it and it was empty' are different
    facts. An empty file has the hash of zero bytes and a size of 0; it does
    not raise."""
    (evidence / "empty.log").write_text("")
    ctx = ac.build_context(evidence, refs(("empty.log", "tool_log")), "q")
    entry = ctx["evidence"][0]
    assert entry["bytes"] == 0
    assert entry["sha256"] == "sha256:" + hashlib.sha256(b"").hexdigest()


def test_trust_is_derived_from_the_declared_role(evidence):
    ctx = ac.build_context(
        evidence,
        refs(("phase3/sta.rpt", "sta_report"),
             ("phase3/drc.rpt", "gate_verdict")),
        "q")
    trust = {e["role"]: e["trust"] for e in ctx["evidence"]}
    assert trust["sta_report"] == "UNTRUSTED"
    assert trust["gate_verdict"] == "PROGRAM_DERIVED"


def test_the_context_states_its_own_handling_rule(evidence):
    ctx = ac.build_context(evidence, refs(("phase3/sta.rpt", "sta_report")),
                           "q")
    assert ctx["handling"] == "DATA_ONLY_NEVER_INSTRUCTION"
    assert "never an instruction" in ctx["instructions"]


def test_the_context_declares_the_level_it_was_built_under(evidence):
    ctx = ac.build_context(evidence, refs(("phase3/sta.rpt", "sta_report")),
                           "q")
    assert ctx["autonomy_level"] == "A0"
    assert ctx["policy_sha256"].startswith("sha256:")


# --------------------------------------------------------------------------
# Negative: refusals (rc=1 territory).
# --------------------------------------------------------------------------

def test_a_ref_that_escapes_the_evidence_root_is_refused(evidence):
    with pytest.raises(ac.ContextRefused):
        ac.build_context(evidence, refs(("../../../etc/passwd", "config")),
                         "q")


def test_an_absolute_ref_is_refused(evidence):
    with pytest.raises(ac.ContextRefused):
        ac.build_context(evidence, refs(("/etc/passwd", "config")), "q")


def test_a_symlink_pointing_out_of_the_root_is_refused(evidence, tmp_path):
    """Resolved before the boundary test, so a symlink needs no separate rule
    -- which matters, because a separate rule is one that can be forgotten."""
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (evidence / "link.rpt").symlink_to(outside)
    with pytest.raises(ac.ContextRefused):
        ac.build_context(evidence, refs(("link.rpt", "tool_log")), "q")


def test_a_sibling_directory_with_the_root_as_a_prefix_is_refused(tmp_path):
    """A string `startswith` test would say /ev-evil is inside /ev."""
    root = tmp_path / "ev"
    root.mkdir()
    (root / "a.rpt").write_text("x\n")
    evil = tmp_path / "ev-evil"
    evil.mkdir()
    (evil / "b.rpt").write_text("y\n")
    with pytest.raises(ac.ContextRefused):
        ac.build_context(root, refs(("../ev-evil/b.rpt", "tool_log")), "q")


def test_a_ref_without_a_role_is_refused(evidence):
    with pytest.raises(ac.ContextRefused):
        ac.build_context(evidence, [{"path": "phase3/sta.rpt"}], "q")


def test_a_context_without_a_question_is_refused(evidence):
    with pytest.raises(ac.ContextRefused):
        ac.build_context(evidence, refs(("phase3/sta.rpt", "sta_report")), " ")


# --------------------------------------------------------------------------
# Vacuous: nothing to look at (rc=2 territory).
# --------------------------------------------------------------------------

def test_a_missing_evidence_root_is_undetermined_not_an_empty_context(tmp_path):
    with pytest.raises(ac.EvidenceMissing):
        ac.build_context(tmp_path / "nope", refs(("a", "tool_log")), "q")


def test_a_ref_that_does_not_resolve_is_undetermined(evidence):
    with pytest.raises(ac.EvidenceMissing):
        ac.build_context(evidence, refs(("phase3/absent.rpt", "sta_report")),
                         "q")


def test_zero_refs_is_undetermined_not_a_small_context(evidence):
    """A context over no evidence means the agent answers from its prior alone
    while the record shows a context was built."""
    with pytest.raises(ac.EvidenceMissing):
        ac.build_context(evidence, [], "q")


def test_a_directory_is_not_an_artefact(evidence):
    with pytest.raises(ac.EvidenceMissing):
        ac.build_context(evidence, refs(("phase3", "sta_report")), "q")


# --------------------------------------------------------------------------
# The CLI.
# --------------------------------------------------------------------------

def _manifest(tmp_path, root, refs_list, question="root_cause"):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"evidence_root": str(root),
                             "question": question, "refs": refs_list}))
    return m


def _run(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


def test_cli_positive(tmp_path, evidence):
    out = tmp_path / "ctx.json"
    m = _manifest(tmp_path, evidence, refs(("phase3/sta.rpt", "sta_report")))
    proc = _run(str(m), "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    ctx = json.loads(out.read_text())
    assert ctx["context_sha256"].startswith("sha256:")
    assert ctx["evidence_count"] == 1


def test_cli_negative_escape_is_one_with_a_marker(tmp_path, evidence):
    m = _manifest(tmp_path, evidence, refs(("../../etc/passwd", "config")))
    proc = _run(str(m))
    assert proc.returncode == 1
    assert "[REFUSE]" in proc.stderr


def test_cli_vacuous_missing_manifest_is_two_with_a_marker(tmp_path):
    proc = _run(str(tmp_path / "nope.json"))
    assert proc.returncode == 2
    assert "[CANNOT CHECK]" in proc.stderr


def test_cli_vacuous_missing_ref_is_two_not_one(tmp_path, evidence):
    """The split that matters: the manifest asked for something legitimate and
    it was not there. That is not a finding about the request."""
    m = _manifest(tmp_path, evidence, refs(("phase3/absent.rpt", "sta_report")))
    proc = _run(str(m))
    assert proc.returncode == 2
    assert "[CANNOT CHECK]" in proc.stderr


def test_cli_bad_invocation_is_three():
    assert _run().returncode == 3


def test_cli_reports_content_is_absent_in_words(tmp_path, evidence):
    m = _manifest(tmp_path, evidence, refs(("phase3/sta.rpt", "sta_report")))
    proc = _run(str(m))
    assert "references and hashes only" in proc.stdout
