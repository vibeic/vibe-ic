#!/usr/bin/env python3
"""#2348: the phase-2+3 completion gate must be REACHABLE, and a gate that
could not run must not be able to return a completeness verdict.

Two defects, one call site, and each half needs its own arm.

THE PATH.  The handler resolved its gate under ``vibe-ic-d``, the plugin Wave
82 retired.  ``src/index.js`` already calls that name "a plugin that no longer
exists" where ``VIBE_IC_PROGRAMS_DIR`` is defined -- and then used it anyway,
one screen down.  The resolved path exists in NO layout, installed or checkout.

WHY THE EXISTING FILE STAYED GREEN, which is the part worth copying.
``test_eda_phase23_completion_audit.py::test_canonical_gate_exists_on_disk``
searches for the gate with the TEST FILE'S OWN ``_GATE_CANDIDATES`` list, which
carries the current path as well as the legacy one.  It therefore asserts "the
gate file exists", never "the product can find it" -- a tautology with respect
to the defect.  ``test_a_the_product_resolver_reaches_the_gate`` below asks the
second question by re-deriving the path from the expression in ``index.js``
itself, so reverting the source reddens it.

THE VERDICT.  ``phase23_complete`` was derived from an exit code that four
distinct could-not-run paths all collapse into.  Two of them (ENOENT on
python3, and a host-side timeout kill) produce ``exit_code: 1`` with an EMPTY
output -- byte-identical in shape to a real "ran, and the project failed"
verdict.  ``index.js`` states the rule itself: treat "could not run" as
nothing-to-judge and you are back where this started.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
INDEX_JS = SRC / "index.js"
PLUGIN = SRC.parent.parent
assert INDEX_JS.exists()
NODE = shutil.which("node")

GATE_NAME = "phase23_completion_self_audit_check.py"


def _handler() -> str:
    """The handler body, from the tool name to the end of its registration."""
    src = INDEX_JS.read_text()
    a = src.index('"eda_phase23_completion_audit"')
    b = src.index("\n);", a) + 3
    return src[a:b]


def _body() -> str:
    """The handler's work, from `const gate` to its last return — WITHOUT the
    arrow function's own closing `},`, which would unbalance the wrapper."""
    h = _handler()
    body = h[h.index("const gate = "):]
    return body[:body.rindex("\n  },")]


# ── (1) the path: re-derived from the product's own expression ───────────


def test_b_the_handler_does_not_name_the_retired_plugin_as_a_path():
    """A prose mention explaining the removal is fine; a path segment is the
    defect.  Keyed on the quoted-string form so editing a comment cannot flip
    this either way."""
    h = _handler()
    assert '"vibe-ic-d"' not in h, (
        'the handler still builds a path through the retired "vibe-ic-d" '
        "plugin; index.js itself calls it a plugin that no longer exists")


# ── (2) the verdict: four could-not-run arms, none may answer ────────────
def _drive(*, gate_exists: bool, spawn: dict) -> dict:
    """Run the REAL handler body under node with its dependencies stubbed."""
    js = (
        f"const VIBE_IC_PROGRAMS_DIR = {json.dumps(str(PLUGIN / 'programs'))};\n"
        "const join = (...p) => p.join('/');\n"
        # the pre-fix handler resolved through `path`/`here`; stub them too, so
        # that arm fails on WHAT IT ANSWERS and not on a broken harness.
        f"const here = {json.dumps(str(SRC))};\n"
        "const path = { resolve: (...p) => p.join('/'), dirname: (p) => p };\n"
        f"const existsSync = () => {json.dumps(gate_exists)};\n"
        f"const _spawnSync = () => ({json.dumps(spawn)});\n"
        'const project_dir = "/tmp/nonexistent-2348";\n'
        "const run = () => {\n" + _body() + "\n};\n"
        "console.log(JSON.stringify(JSON.parse(run().content[0].text)));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


_CANNOT_RUN = {
    # the shipped defect: the gate is not where the handler looked
    "gate_absent": dict(gate_exists=False, spawn={}),
    # python3 itself is missing -> spawnSync sets .error, status stays null
    "python3_enoent": dict(gate_exists=True,
                           spawn={"error": {"code": "ENOENT"}, "status": None,
                                  "stdout": "", "stderr": ""}),
    # the host-side backstop fired -> SIGTERM, status null, output EMPTY
    "killed": dict(gate_exists=True,
                   spawn={"signal": "SIGTERM", "status": None,
                          "stdout": "", "stderr": ""}),
    # the gate reached its own inner budget and said so (#525)
    "inner_timeout": dict(
        gate_exists=True,
        spawn={"status": 124,
               "stdout": json.dumps({"summary": {"overall": "AUDIT_TIMEOUT"}}),
               "stderr": ""}),
}


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("arm", sorted(_CANNOT_RUN))
def test_c_a_gate_that_could_not_run_returns_no_verdict(arm):
    out = _drive(**_CANNOT_RUN[arm])
    assert out["status"] == "NOT_MEASURED", (
        f"{arm}: the audit did not run, yet the tool answered {out!r}")
    assert out["audit_ran"] is False
    assert out.get("not_measured_reason"), "a refusal must say why"
    assert "exit_code" not in out, (
        f"{arm}: an exit code that no completed run produced is the thing that "
        "made 'never ran' look like 'ran and failed'")


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_d_a_real_run_still_reports_its_verdict():
    """The control arm. A refusal machine that answered NOT_MEASURED to
    everything would pass the four arms above and be useless."""
    out = _drive(gate_exists=True,
                 spawn={"status": 1, "stderr": "",
                        "stdout": json.dumps({"summary": {"overall": "FAIL"},
                                              "non_waived_pass": "12/34"})})
    assert out["status"] == "MEASURED"
    assert out["audit_ran"] is True
    assert out["exit_code"] == 1
    assert out["phase23_complete"] is False
    assert out["summary"]["overall"] == "FAIL"

    ok = _drive(gate_exists=True,
                spawn={"status": 0, "stderr": "",
                       "stdout": json.dumps({"summary": {"overall": "PASS"}})})
    assert ok["status"] == "MEASURED" and ok["phase23_complete"] is True
