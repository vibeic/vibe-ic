"""A spec-declared artifact must satisfy the spec, not merely exist.

THE DEFECT, MEASURED.  `spec_required_artifact_check` asserted two things of a
declared artifact: the path exists, and `st_size > 0`.  `{}` is three bytes.
Driven over subservient's real run tree (czsubaudit RUN 5, 2026-09-06) the
pre-fix gate returned rc=0 "All 1 declared artifact(s) present and non-empty"
for ALL FOUR of: the real 8-field declaration, `{}`, a truncated file, and a
declaration with one REQUIRED field deleted.

The program that can tell them apart already existed and was invoked by
NOTHING: `spec_declaration_emit --verify`, whose own `--help` says
"This is the SUBSTANCE check the required-artifact gate cannot make: it scores
presence and byte count, and `{}` is 3 bytes."

MUTATIONS THESE TESTS MUST KILL:
  * Restoring `status = "PASS" if exists and non_empty` fails
    `test_an_empty_object_is_refused_with_the_key_named` and its siblings.
  * Answering the contract question but not naming the field fails the
    `key named` assertions — a refusal an author cannot act on is the shape
    this repo has been paying for.
  * Deleting `select_contract` from `spec_declaration_emit` (or letting it
    drift from `main()`'s selection) fails `test_the_emitter_and_the_gate_
    make_the_same_selection`.
  * Making the JSON fall-through refuse a NON-empty artifact fails
    `test_a_real_declaration_still_passes`, the control that the gate was not
    simply switched to "always fail".
  * Turning an unaskable question into a FAIL (rather than NOT_MEASURED)
    fails `test_an_unaskable_question_is_not_a_failure`.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

GATE = PROGRAMS / "spec_required_artifact_check.py"
SDE = importlib.import_module("spec_declaration_emit")
CHK = importlib.import_module("spec_required_artifact_check")

#: A minimal spec that DECLARES an artifact and a field table for it — the
#: same shape subservient's L7 uses. No design, PDK or tool is named.
SPEC = """\
# L7 Verification Plan

The plugin **MUST** declare `plugin_output/declaration.json`.

| Field | Required | Meaning |
|-------|----------|---------|
| `top_module` | yes | the name of the top module |
| `clock_port_name` | yes | the name of the clock port |
| `note` | no | free text |
"""


def _project(tmp_path, declaration):
    root = tmp_path / "proj"
    (root / "input" / "docs").mkdir(parents=True)
    (root / "input" / "docs" / "L7_verification_plan.md").write_text(SPEC)
    (root / "plugin_output").mkdir(parents=True)
    if declaration is not None:
        (root / "plugin_output" / "declaration.json").write_text(declaration)
    return root


def _run(root):
    cp = subprocess.run([sys.executable, str(GATE), str(root)],
                        capture_output=True, text=True, timeout=600)
    rep = json.loads((root / "reports" / "phase2" / "gates"
                      / "spec_required_artifacts.json").read_text())
    return cp.returncode, cp.stdout + cp.stderr, rep


def _the_result(rep):
    hits = [r for r in rep["results"]
            if r["artifact_path"] == "plugin_output/declaration.json"]
    assert hits, rep
    return hits[0]


GOOD = json.dumps({"top_module": "widget_top", "clock_port_name": "i_clk"})


def test_the_gate_finds_the_clause_at_all(tmp_path):
    """A negative control for the FIXTURE, not the gate: if this spec did not
    produce a clause, every refusal below would be vacuous."""
    rc, _txt, rep = _run(_project(tmp_path, GOOD))
    assert rep["clauses_found"] == 1, rep
    assert rc == 0


def test_a_real_declaration_still_passes(tmp_path):
    rc, txt, rep = _run(_project(tmp_path, GOOD))
    assert rc == 0, txt
    r = _the_result(rep)
    assert r["status"] == "PASS"
    assert r["substance_source"] == "CONTRACT"


def test_an_empty_object_is_refused_with_the_key_named(tmp_path):
    rc, txt, rep = _run(_project(tmp_path, "{}"))
    assert rc == 1, txt
    r = _the_result(rep)
    assert r["exists"] is True and r["non_empty"] is True  # presence PASSED
    assert r["status"] != "PASS"
    for key in ("top_module", "clock_port_name"):
        assert key in r["substance_reason"], r["substance_reason"]
        assert key in txt, txt
    # the OPTIONAL field is not demanded
    assert "note" not in r["substance_reason"]


def test_a_truncated_file_is_refused_and_named(tmp_path):
    rc, txt, rep = _run(_project(tmp_path, '{"top_module": "widg'))
    assert rc == 1, txt
    r = _the_result(rep)
    assert r["status"] == "FAIL_UNPARSEABLE", r
    assert "not readable JSON" in r["substance_reason"]


def test_one_missing_required_key_is_refused_and_that_key_is_named(tmp_path):
    rc, txt, rep = _run(_project(tmp_path,
                                 json.dumps({"top_module": "widget_top"})))
    assert rc == 1, txt
    r = _the_result(rep)
    assert "clock_port_name" in r["substance_reason"]
    assert "top_module" not in r["substance_reason"]


def test_an_absent_artifact_still_says_absent(tmp_path):
    """The presence verdicts are unchanged; substance is asked only of a file
    there is something to read."""
    rc, _txt, rep = _run(_project(tmp_path, None))
    assert rc == 1
    r = _the_result(rep)
    assert r["status"] == "FAIL_ABSENT"
    assert "substance_source" not in r


def test_a_zero_byte_artifact_still_says_empty(tmp_path):
    rc, _txt, rep = _run(_project(tmp_path, ""))
    assert rc == 1
    assert _the_result(rep)["status"] == "FAIL_EMPTY"


def test_the_failing_note_names_the_artifact(tmp_path):
    """"1 declared artifact(s) absent or empty." was the whole message, and
    once substance is asked it is not even true — the file is present."""
    _rc, txt, rep = _run(_project(tmp_path, "{}"))
    assert "plugin_output/declaration.json" in rep["note"]
    assert "plugin_output/declaration.json" in txt


# --- the generic fall-through: no contract, so no key to name -------------- #

NO_TABLE_SPEC = """\
# L7 Verification Plan

The plugin **MUST** emit `plugin_output/inventory.json`.
"""


def _no_contract_project(tmp_path, body):
    root = tmp_path / "proj"
    (root / "input" / "docs").mkdir(parents=True)
    (root / "input" / "docs" / "L7.md").write_text(NO_TABLE_SPEC)
    (root / "plugin_output").mkdir(parents=True)
    (root / "plugin_output" / "inventory.json").write_text(body)
    return root


def test_an_empty_json_with_no_contract_is_still_refused(tmp_path):
    rc, _txt, rep = _run(_no_contract_project(tmp_path, "{}"))
    assert rc == 1
    r = [x for x in rep["results"]
         if x["artifact_path"] == "plugin_output/inventory.json"][0]
    assert r["status"] == "FAIL_VACUOUS"
    assert r["substance_source"] == "JSON"
    # it states the MEASURED byte count of the file it read
    n = (tmp_path / "proj" / "plugin_output" / "inventory.json").stat().st_size
    assert "%d byte(s)" % n in r["substance_reason"], r["substance_reason"]


def test_a_non_empty_json_with_no_contract_passes(tmp_path):
    rc, _txt, rep = _run(_no_contract_project(tmp_path, '{"a": 1}'))
    assert rc == 0
    r = [x for x in rep["results"]
         if x["artifact_path"] == "plugin_output/inventory.json"][0]
    assert r["status"] == "PASS" and r["substance_source"] == "JSON"


def test_an_unaskable_question_is_not_a_failure(tmp_path, monkeypatch):
    """A probe that could not run is NOT_MEASURED and the artifact keeps its
    presence verdict — never a default supplied in either direction."""
    monkeypatch.setattr(CHK, "_SUBSTANCE_CONTRACT_CACHE", {}, raising=False)
    root = tmp_path / "p"
    (root / "plugin_output").mkdir(parents=True)
    f = root / "plugin_output" / "notes.md"
    f.write_text("something")
    status, reason, source = CHK._substance_of(
        root, "plugin_output/notes.md", f)
    assert status is None
    assert source == "NONE"
    assert "not a JSON artifact" in reason


def test_the_emitter_and_the_gate_make_the_same_selection(tmp_path):
    """`select_contract` is the selection `main()` makes; a second copy would
    disagree with it the first time a contract schema changed."""
    root = _project(tmp_path, GOOD)
    contract, why, _paths = SDE.select_contract(root)
    assert why == "OK" and contract is not None
    assert contract["artifact_path"] == "plugin_output/declaration.json"
    required = sorted(f["name"] for f in contract["fields"] if f["required"])
    assert required == ["clock_port_name", "top_module"]
    src = (PROGRAMS / "spec_declaration_emit.py").read_text()
    assert src.count("def select_contract(") == 1
    assert "select_contract(project, args.artifact" in src, (
        "main() must make its selection through the same function")


def test_verify_is_reachable_from_the_gate_in_process(tmp_path):
    """The wiring itself: the gate must actually consult the contract, not
    just be capable of it."""
    root = _project(tmp_path, "{}")
    contract, _why, _p = SDE.select_contract(root)
    rep = SDE.verify_declaration(
        root, contract, root / "plugin_output" / "declaration.json")
    assert rep["verdict"].startswith("FAIL")
    assert sorted(rep["missing_required"]) == ["clock_port_name", "top_module"]


@pytest.mark.parametrize("rc_expect,body", [(0, GOOD), (1, "{}")])
def test_the_gate_exit_code_follows_the_substance(tmp_path, rc_expect, body):
    rc, _txt, _rep = _run(_project(tmp_path, body))
    assert rc == rc_expect
