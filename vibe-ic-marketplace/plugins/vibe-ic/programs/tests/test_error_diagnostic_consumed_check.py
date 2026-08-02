"""Tests for error_diagnostic_consumed_check.

The gate's contract: a diagnostic emitted at severity=ERROR must be consumed by
SOME verdict. These tests pin BOTH directions — it must fire on an inert ERROR,
and it must stay silent on each of the three ways an ERROR can legitimately be
consumed. A gate that only ever fires is not a gate, it is a lint that says no.

NDA: no chip, PDK, foundry, vendor or part-number token appears here. The
fixtures use invented diagnostic names.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs.error_diagnostic_consumed_check import audit, main

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/vibe-ic


def _mk_plugin(tmp_path: Path, files: dict) -> Path:
    """files: {relative_path_under_programs: source}"""
    root = tmp_path / "plugin"
    for rel, body in files.items():
        p = root / "programs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


# A library: no `if __name__` guard, so no exit status of its own.
_LIB_EMITS = '''
    def classify(x):
        if x:
            return {"verdict": "WIDGET_UNUSABLE", "severity": "ERROR",
                    "reason": "the staged part is unusable"}
        return {"verdict": "WIDGET_OK", "severity": "INFO"}
'''

# A gate: `if __name__` guard plus a non-zero return.
_GATE_EMITS = '''
    import sys

    def run():
        return {"verdict": "WIDGET_UNUSABLE", "severity": "ERROR"}

    def main(argv=None):
        if run()["verdict"] != "WIDGET_OK":
            return 1
        return 0

    if __name__ == "__main__":
        sys.exit(main())
'''


# ---------------------------------------------------------------------------
# It fires
# ---------------------------------------------------------------------------
def test_inert_error_in_a_library_is_flagged(tmp_path):
    root = _mk_plugin(tmp_path, {"emitter.py": _LIB_EMITS})
    verdict, findings, _undec, _census = audit(root)
    assert verdict == "FAIL"
    assert [f.token for f in findings] == ["WIDGET_UNUSABLE"]
    assert findings[0].emitter_is_gate is False


def test_inert_error_exits_one(tmp_path, capsys):
    root = _mk_plugin(tmp_path, {"emitter.py": _LIB_EMITS})
    assert main([str(root)]) == 1
    assert "WIDGET_UNUSABLE" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# It stays silent on each real consumption mode
# ---------------------------------------------------------------------------
def test_self_consumed_when_emitter_is_a_gate(tmp_path):
    """The emitter can exit non-zero, so emitting IS failing."""
    root = _mk_plugin(tmp_path, {"gate.py": _GATE_EMITS})
    verdict, findings, _u, census = audit(root)
    assert verdict == "PASS", findings
    assert "self-consumed" in census["WIDGET_UNUSABLE"]


def test_cross_consumed_when_another_module_names_the_token(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS,
        "runner.py": '''
            from emitter import classify

            def step(x):
                d = classify(x)
                if d["verdict"] == "WIDGET_UNUSABLE":
                    return "FAIL"
                return "PASS"
        ''',
    })
    verdict, findings, _u, census = audit(root)
    assert verdict == "PASS", findings
    assert "cross-consumed" in census["WIDGET_UNUSABLE"]


def test_self_compared_library_steers_control_flow(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS + '''
    def gate(x):
        if classify(x)["verdict"] == "WIDGET_UNUSABLE":
            raise RuntimeError("refusing")
''',
    })
    verdict, findings, _u, census = audit(root)
    assert verdict == "PASS", findings
    assert "self-compared" in census["WIDGET_UNUSABLE"]


# ---------------------------------------------------------------------------
# Prose is not consumption
# ---------------------------------------------------------------------------
def test_a_comment_is_not_a_consumer(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS,
        "runner.py": '''
            # TODO: one day handle WIDGET_UNUSABLE here
            def step(x):
                return "PASS"
        ''',
    })
    verdict, findings, _u, _c = audit(root)
    assert verdict == "FAIL"
    assert [f.token for f in findings] == ["WIDGET_UNUSABLE"]


def test_a_docstring_is_not_a_consumer(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS,
        "runner.py": '''
            """This module reacts to WIDGET_UNUSABLE eventually."""
            def step(x):
                return "PASS"
        ''',
    })
    verdict, findings, _u, _c = audit(root)
    assert verdict == "FAIL"


def test_a_test_file_is_not_a_consumer(tmp_path):
    """A test asserting the string exists does not make a gate act on it."""
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS,
        "tests/test_emitter.py": '''
            from emitter import classify
            def test_it():
                assert classify(1)["verdict"] == "WIDGET_UNUSABLE"
        ''',
    })
    verdict, findings, _u, _c = audit(root)
    assert verdict == "FAIL"


# ---------------------------------------------------------------------------
# Undecidable is never silently a pass
# ---------------------------------------------------------------------------
def test_non_literal_severity_is_undecidable_not_passing(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": '''
            def classify(x, sev):
                return {"verdict": "WIDGET_MAYBE", "severity": sev}
        ''',
    })
    _v, findings, undec, _c = audit(root)
    assert findings == []
    assert len(undec) == 1
    assert "not a literal" in undec[0].why


def test_error_with_no_token_key_is_undecidable(tmp_path):
    root = _mk_plugin(tmp_path, {
        "emitter.py": '''
            def classify(x):
                return {"severity": "ERROR", "reason": "something went wrong"}
        ''',
    })
    _v, findings, undec, _c = audit(root)
    assert findings == []
    assert len(undec) == 1
    assert "no token key" in undec[0].why


# ---------------------------------------------------------------------------
# Anti-vacuity
# ---------------------------------------------------------------------------
def test_empty_scan_is_not_a_pass(tmp_path, capsys):
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    assert main([str(root)]) == 2
    assert "NOTHING_SCANNED" in capsys.readouterr().err


def test_no_error_emissions_is_not_a_pass(tmp_path, capsys):
    root = _mk_plugin(tmp_path, {
        "quiet.py": 'def f():\n    return {"verdict": "OK", "severity": "INFO"}\n',
    })
    assert main([str(root)]) == 2
    assert "NOTHING_SCANNED" in capsys.readouterr().err


def test_allowlist_exempts_a_token(tmp_path):
    root = _mk_plugin(tmp_path, {"emitter.py": _LIB_EMITS})
    verdict, findings, _u, census = audit(root, allow={"WIDGET_UNUSABLE"})
    assert verdict == "PASS", findings
    assert census["WIDGET_UNUSABLE"] == "allowlisted"


# ---------------------------------------------------------------------------
# The gate on the real tree
# ---------------------------------------------------------------------------
def test_real_plugin_tree_is_scanned_substantively():
    """Guards against a green result produced by scanning nothing."""
    _v, _f, _u, census = audit(_PLUGIN_ROOT)
    from programs.error_diagnostic_consumed_check import SCAN_CENSUS
    assert SCAN_CENSUS["files_read"] > 500
    assert SCAN_CENSUS["error_emissions"] > 100
    # and the consumed set must be substantive, not empty
    assert len(census) > 100


def test_unparsable_file_is_recorded_not_silently_skipped(tmp_path):
    """A file the gate cannot parse must not become an invisible hiding place."""
    root = _mk_plugin(tmp_path, {
        "emitter.py": _LIB_EMITS,
        "broken.py": "def f(:\n    pass\n",
    })
    _v, _f, undec, _c = audit(root)
    assert any("could not be parsed" in u.why and u.file.endswith("broken.py")
               for u in undec)
