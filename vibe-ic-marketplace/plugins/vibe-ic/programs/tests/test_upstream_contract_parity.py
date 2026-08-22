#!/usr/bin/env python3
"""A re-implementation must be pinned to the thing it re-implements.

Every test here breaks ONE property of the register and watches
`upstream_contract_parity_check` go red, then restores it and watches it go
green again. The three-state shape is deliberate: a test that only ever
observes red cannot tell a working detector from one that refuses everything.

THE TWO REDS THAT MATTER, and why they are the first two tests:

  `test_an_upstream_name_in_no_class_is_a_finding` removes exactly one name
  from the register -- the one through which a distribution declares its pad
  sites when the abstract views carry no site record. That is the omission
  that made a step report a declared thing ABSENT, and it had never been
  written down anywhere. With this check in place it cannot be un-written
  down again.

  `test_a_computation_with_neither_a_pin_nor_a_declared_gap_is_a_finding`
  removes the pin from a registered computation. That is the shape that let
  an along-the-row extent read the wrong dimension of a cell for the whole
  life of a module, with nothing anywhere comparing it against the upstream
  it mirrors.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
CHECK = PROGRAMS / "upstream_contract_parity_check.py"
SHIPPED = PROGRAMS / "upstream_contract_parity.json"


def run(register: Path):
    p = subprocess.run(
        [sys.executable, str(CHECK), "--register", str(register)],
        capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def shipped_doc() -> dict:
    return json.loads(SHIPPED.read_text(encoding="utf-8"))


def write(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "register.json"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def contract_entry(doc: dict) -> dict:
    return next(e for e in doc["entries"] if e.get("kind") == "contract")


def computation_entry(doc: dict) -> dict:
    return next(e for e in doc["entries"] if e.get("kind") == "computation")


# ── the shipped state, both directions ──────────────────────────────────────

def test_the_shipped_register_passes():
    """GREEN. Without this the reds below prove only that the check refuses."""
    rc, out = run(SHIPPED)
    assert rc == 0, out
    assert "every upstream name" in out


def test_the_denominator_is_printed_at_every_verdict():
    """A pass that does not say how much it looked at is the shape that made
    all of this necessary in the first place."""
    rc, out = run(SHIPPED)
    assert rc == 0, out
    assert "upstream_names=" in out


# ── the two reds this lane exists for ───────────────────────────────────────

def test_an_upstream_name_in_no_class_is_a_finding(tmp_path):
    # The name is taken from `implemented`, which every contract entry has by
    # construction. It used to be taken from `known_gap`, which made the test
    # depend on the shipped register still HAVING an open gap: closing the
    # last one turned this red with an IndexError, in a test whose subject has
    # nothing to do with gaps. A test that borrows its fixture from live data
    # asserts today's contents, not the rule.
    doc = shipped_doc()
    ent = contract_entry(doc)
    impl = ent["classification"]["implemented"]
    dropped = sorted(impl)[0]
    impl.remove(dropped)

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert dropped in out
    assert "no class" in out

    impl.append(dropped)
    rc, out = run(write(tmp_path, doc))
    assert rc == 0, out


def test_a_computation_with_neither_a_pin_nor_a_declared_gap_is_a_finding(
        tmp_path):
    doc = shipped_doc()
    ent = computation_entry(doc)
    ent["pin_test"] = {"status": ""}

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "neither" in out

    ent["pin_test"] = {"status": "known_gap", "reason": "r", "reference": "x"}
    rc, out = run(write(tmp_path, doc))
    assert rc == 0, out


# ── the register cannot lie about our own source ────────────────────────────

def test_an_implemented_name_absent_from_the_module_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    ent["snapshot"]["names"].append("PAD_NAME_NO_MODULE_MENTIONS")
    ent["classification"]["implemented"].append("PAD_NAME_NO_MODULE_MENTIONS")

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "claims an implementation the module does not contain" in out


def test_a_known_gap_the_module_now_implements_is_a_finding(tmp_path):
    """When the gap closes, the register must say so in the same change."""
    doc = shipped_doc()
    ent = contract_entry(doc)
    implemented = ent["classification"]["implemented"][0]
    ent["classification"]["implemented"].remove(implemented)
    ent["classification"]["known_gap"][implemented] = {
        "reason": "claimed still open", "reference": "somewhere"}

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "move it to" in out


def test_a_declared_unperformed_name_must_be_recorded_in_the_module(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    ent["snapshot"]["names"].append("PAD_NAME_NO_MODULE_MENTIONS")
    ent["classification"]["declared_unperformed"].append(
        "PAD_NAME_NO_MODULE_MENTIONS")

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "where a reader of the artefact meets it" in out


# ── the classes cannot become an excuse list ────────────────────────────────

def test_a_known_gap_without_a_reference_is_a_finding(tmp_path):
    # The gap is INJECTED rather than borrowed from the shipped register, so
    # the rule is tested whether or not the repo currently has an open gap —
    # and a green repo is the state we want this to keep working in. The name
    # comes from `omitted_by_design`, whose members are by definition NOT
    # consumed by the module, so the staleness rule ("classified known_gap and
    # DOES appear") cannot also fire and make the assertion below pass for the
    # wrong reason.
    doc = shipped_doc()
    ent = contract_entry(doc)
    cls = ent["classification"]
    name = sorted(cls["omitted_by_design"])[0]
    del cls["omitted_by_design"][name]
    cls.setdefault("known_gap", {})[name] = {"reason": "injected by the test",
                                             "reference": "  "}

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "excuse list" in out


def test_an_omission_without_a_reason_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    name = sorted(ent["classification"]["omitted_by_design"])[0]
    ent["classification"]["omitted_by_design"][name] = ""

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "indistinguishable from an oversight" in out


def test_a_name_classified_twice_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    name = ent["classification"]["implemented"][0]
    ent["classification"]["declared_unperformed"].append(name)

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "classified twice" in out


def test_a_classification_upstream_does_not_declare_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    ent["classification"]["omitted_by_design"]["PAD_UPSTREAM_DROPPED_THIS"] = (
        "a name that is no longer upstream")

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "the upstream snapshot does not declare it" in out


# ── zero denominator: rc 2, never rc 0 ──────────────────────────────────────

def test_an_empty_register_is_not_a_pass(tmp_path):
    rc, out = run(write(tmp_path, {"entries": []}))
    assert rc == 2, out
    assert "one verdict this program must never return" in out


def test_a_missing_register_is_not_a_pass(tmp_path):
    rc, out = run(tmp_path / "there-is-no-register-here.json")
    assert rc == 2, out
    assert "nothing was checked" in out


def test_an_entry_with_no_upstream_names_is_not_a_pass(tmp_path):
    doc = shipped_doc()
    contract_entry(doc)["snapshot"]["names"] = []

    rc, out = run(write(tmp_path, doc))
    assert rc == 2, out
    assert "every one of our omissions as accounted for" in out


def test_an_unknown_entry_kind_is_not_a_pass(tmp_path):
    doc = shipped_doc()
    doc["entries"][0]["kind"] = "something-nobody-implemented"

    rc, out = run(write(tmp_path, doc))
    assert rc == 2, out


# ── the pin, when a real one is named ───────────────────────────────────────

def test_a_named_pin_test_that_does_not_exist_is_a_finding(tmp_path):
    doc = shipped_doc()
    computation_entry(doc)["pin_test"] = {
        "status": "test",
        "test": "programs/tests/test_upstream_contract_parity.py::"
                "test_no_such_function_is_defined_here"}

    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "no such test is defined there" in out


def test_a_named_pin_test_that_exists_passes(tmp_path):
    doc = shipped_doc()
    computation_entry(doc)["pin_test"] = {
        "status": "test",
        "test": "programs/tests/test_upstream_contract_parity.py::"
                "test_the_shipped_register_passes"}

    rc, out = run(write(tmp_path, doc))
    assert rc == 0, out


# ── snapshot drift, measured against a root we build ────────────────────────

def _fake_root(tmp_path: Path, body: str) -> Path:
    """A distribution that satisfies EVERY registered entry by construction.

    It used to hard-code the two pad files. Registering a third entry — a
    Magic LEF-write sequence, the first with no pad in it — then made three
    unrelated tests fail with rc 2, because the new entry's upstream file was
    not under this root and the checker correctly reported NOT DETERMINED. The
    tests were right, the checker was right, and the helper was the thing that
    knew a fixed list.

    It now reads the register, so the next entry costs nothing here. Each test
    still perturbs only the entry it is about.
    """
    root = tmp_path / "root"
    (root / "librelane" / "config").mkdir(parents=True)
    (root / "librelane" / "config" / "flow.py").write_text(body,
                                                           encoding="utf-8")
    (root / "librelane" / "scripts" / "openroad" / "common").mkdir(
        parents=True)
    (root / "librelane" / "scripts" / "openroad" / "common"
     / "pad_cfg.tcl").write_text(
        "incr sum_of_cell_widths $width\n[[$inst getMaster] getWidth]\n",
        encoding="utf-8")

    for entry in shipped_doc()["entries"]:
        rel = (entry.get("upstream") or {}).get("file")
        if not rel:
            continue
        path = root / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        anchors = (entry.get("upstream") or {}).get("anchors") or []
        path.write_text("\n".join(anchors) + "\n", encoding="utf-8")
    return root


def run_against(register: Path, root: Path):
    p = subprocess.run(
        [sys.executable, str(CHECK), "--register", str(register),
         "--distribution-root", str(root)],
        capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _minimal_upstream(names) -> str:
    return "\n".join(f'    Variable(\n        "{n}",' for n in names) + "\n"


def test_an_upstream_name_the_snapshot_never_recorded_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    ent["snapshot"]["file_sha256"] = ""
    body = _minimal_upstream(list(ent["snapshot"]["names"])
                             + ["PAD_ARRIVED_UPSTREAM_TODAY"])

    rc, out = run_against(write(tmp_path, doc), _fake_root(tmp_path, body))
    assert rc == 1, out
    assert "PAD_ARRIVED_UPSTREAM_TODAY" in out
    assert "a name nobody classified" in out


def test_a_changed_upstream_file_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    body = _minimal_upstream(ent["snapshot"]["names"])

    rc, out = run_against(write(tmp_path, doc), _fake_root(tmp_path, body))
    assert rc == 1, out
    assert "has changed since the snapshot" in out


def test_an_upstream_anchor_that_moved_is_a_finding(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    ent["snapshot"]["file_sha256"] = ""
    root = _fake_root(tmp_path, _minimal_upstream(ent["snapshot"]["names"]))
    (root / "librelane" / "scripts" / "openroad" / "common"
     / "pad_cfg.tcl").write_text("the computation moved elsewhere\n",
                                 encoding="utf-8")
    computation_entry(doc)["snapshot"]["file_sha256"] = ""

    rc, out = run_against(write(tmp_path, doc), root)
    assert rc == 1, out
    assert "points at nothing" in out


def test_an_unreachable_distribution_is_not_a_pass(tmp_path):
    rc, out = run_against(SHIPPED, tmp_path / "no-distribution-here")
    assert rc == 2, out
    assert "could not be re-measured" in out


# ── an argument that is accepted must not be silently inert ─────────────────

def test_a_supplied_project_path_is_announced_not_silently_ignored(tmp_path):
    """The population drivers pass a project positionally. This gate does not
    read one, and the whole subject of the register beside it is that a knob
    which changes nothing must say so out loud."""
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    p = subprocess.run([sys.executable, str(CHECK), "."],
                       cwd=proj, capture_output=True, text=True)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "is not read" in out
    assert "upstream_names=" in out


# ── the verdict must say what it was measured against ───────────────────────

def test_a_pass_without_a_distribution_says_it_compared_against_its_own_record():
    """The rule this register exists for, turned on its own verdict.

    Absent a distribution root, what is compared is our code against OUR OWN
    RECORD of upstream — the snapshot in the register. That is a useful check
    and it is NOT a statement about upstream, and the two print identically
    unless the verdict says which. This was missing until someone asked what
    the PASS was over.
    """
    rc, out = run(SHIPPED)
    assert rc == 0, out
    assert "BASIS:" in out, out
    assert "NOT re-read" in out, out
    assert "our own record" in out, out


def test_a_pass_with_a_distribution_says_how_many_entries_it_re_read(tmp_path):
    doc = shipped_doc()
    ent = contract_entry(doc)
    root = _fake_root(tmp_path, _minimal_upstream(ent["snapshot"]["names"]))
    for e in doc["entries"]:          # the shas are of the REAL upstream files
        e.get("snapshot", {})["file_sha256"] = ""
    rc, out = run_against(write(tmp_path, doc), root)
    assert "BASIS:" in out, out
    assert "re-read under" in out, out
    assert f"for {len(doc['entries'])} of {len(doc['entries'])}" in out, out


def test_the_basis_is_printed_at_a_failing_verdict_too(tmp_path):
    """A disclosure present only on the happy path is not a disclosure."""
    doc = shipped_doc()
    impl = contract_entry(doc)["classification"]["implemented"]
    impl.remove(sorted(impl)[0])
    rc, out = run(write(tmp_path, doc))
    assert rc == 1, out
    assert "BASIS:" in out, out
