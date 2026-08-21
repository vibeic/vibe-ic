"""Regression tests — a bolded English MUST is still a MUST.

DEFECT (measured on v1.9.71, with `spec_required_artifact_check` itself):

The clause extractor carried two patterns for the same idea. The Chinese one
spelled out `(?:\\*\\*)?必須(?:\\*\\*)?` and so tolerated markdown emphasis. The
English one did not. Same clause, same table, three spellings:

    `**必須**於 `p/declaration.json` 聲明`   -> clauses_found=1  FAIL
    `**MUST** emit `p/declaration.json``     -> clauses_found=0  VACUOUS_PASS
    `MUST emit `p/declaration.json``         -> clauses_found=1  FAIL

Bolding the requirement word is what bold is FOR, so the middle row is the
ordinary way an English spec writes it. The gate answered "no path-shaped
MUST-emit clauses found — nothing to assert" and passed. That is a silent false
negative in the one gate whose job is to notice that a required artifact is
absent: the artifact was never demanded, so it was never missed.

The root cause is DRIFT — one idea, two spellings, only one maintained. The fix
shares a single `_MD_EMPH` fragment between both patterns, so they cannot drift
again without both moving.

WHAT THIS LICENSES — this makes the gate STRICTER, and it can newly FAIL a run.
A project whose spec bolds an English MUST-emit clause was getting
VACUOUS_PASS; it will now be held to the artifact its own spec demands. That is
the intended direction (the gate exists to demand it), but it is a
green-goes-red change and is declared as such, not slipped in.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_DOC = """\
# L7

## 7.0 Declaration

%s

| Field | Required | Example |
|---|---|---|
| `alpha_port` | YES | `"a_in"` |
"""

# The artifact path is invented; it names no design in this repo.
_CLAUSES = {
    "zh_bold":   "The implementer **必須**於 `out_dir/manifest.json` 聲明:",
    "zh_plain":  "The implementer 必須於 `out_dir/manifest.json` 聲明:",
    "en_bold":   "The implementer **MUST** emit `out_dir/manifest.json` carrying:",
    "en_plain":  "The implementer MUST emit `out_dir/manifest.json` carrying:",
    "en_bold_verb": "The implementer MUST **emit** `out_dir/manifest.json` carrying:",
    "en_underscore": "The implementer __MUST__ emit `out_dir/manifest.json` carrying:",
}


def _run_gate(project: Path) -> int:
    """Invoke the gate exactly as the flow does — as a subprocess on a project
    dir — and return the clause count it recorded."""
    import subprocess
    subprocess.run([sys.executable,
                    str(PROGRAMS / "spec_required_artifact_check.py"),
                    str(project)], capture_output=True, text=True)
    report = (project / "reports" / "phase2" / "gates"
              / "spec_required_artifacts.json")
    return json.loads(report.read_text())["clauses_found"]


def _clauses_found(tmp_path: Path, key: str) -> int:
    project = tmp_path / key
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(
        _DOC % _CLAUSES[key], encoding="utf-8")
    return _run_gate(project)


# ---------------------------------------------------------------------------
# 1. NEGATIVE CONTROL — the bolded English form.
# ---------------------------------------------------------------------------
def test_bolded_english_must_is_detected(tmp_path):
    """NEGATIVE CONTROL: pre-fix this returned 0 and the gate reported
    VACUOUS_PASS ("nothing to assert"). This assertion fails against the
    pre-fix code."""
    assert _clauses_found(tmp_path, "en_bold") == 1, (
        "`**MUST** emit` declares a required artifact; a gate that cannot see "
        "it reports VACUOUS_PASS and the artifact is never demanded")


def test_emphasis_on_the_verb_and_underscore_form_are_detected(tmp_path):
    """The same drift, two more spellings a real spec uses."""
    assert _clauses_found(tmp_path, "en_bold_verb") == 1
    assert _clauses_found(tmp_path, "en_underscore") == 1


# ---------------------------------------------------------------------------
# 2. PARITY — the two languages must agree, which is the actual invariant.
# ---------------------------------------------------------------------------
def test_both_languages_agree_bold_and_plain(tmp_path):
    """The defect was DRIFT between two spellings of one idea. Assert the
    property, not the four data points: emphasis must not change the verdict,
    in either language."""
    seen = {k: _clauses_found(tmp_path, k)
            for k in ("zh_bold", "zh_plain", "en_bold", "en_plain")}
    assert set(seen.values()) == {1}, (
        f"emphasis must not decide whether a MUST-clause exists; got {seen}")


# ---------------------------------------------------------------------------
# 3. PRESERVATION — prose that merely mentions a path is still not a clause.
# ---------------------------------------------------------------------------
def test_prose_without_an_imperative_is_still_not_a_clause(tmp_path):
    """Widening the emphasis tolerance must not widen WHAT COUNTS as a
    requirement. Without MUST/shall/required-to there is no clause, bold or
    not — otherwise this fix would trade a false negative for a false
    positive."""
    project = tmp_path / "prose"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(
        _DOC % "The tool **may** write `out_dir/manifest.json` if configured.",
        encoding="utf-8")
    assert _run_gate(project) == 0
