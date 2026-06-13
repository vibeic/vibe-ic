"""Tests for v0.1.57 R6 capture: score_cocotb_mcp.py must classify
harness-substitution errors as Cat-D candidates so consumers don't have
to parse log_tail by eye.

Captured from v0.1.56 CVDP run (Project 2 priority_encoder): iverilog build
succeeded but cocotb-tools' runner.test() raised `TypeError: int() argument
must be a string, a bytes-like object or a real number, not 'NoneType'` at
harness_library.py:24, with TESTS=0. The scorer should emit a `harness_error`
field so the consumer knows this is Cat-D (tool gap), not a DUT bug.

Honesty constraint: the detector scans ONLY the SCORER OUTPUT (stdout/stderr),
NOT the contents of score/src/harness_library.py — blind rule preserved.
"""
import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_cocotb_mcp.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_cocotb_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detect_cocotb_tools_typeerror_pattern():
    """The v0.1.56 CVDP priority_encoder symptom."""
    mod = _load()
    out = """
collecting tests…
test_runner.py:23: in test_pri_enc
    runner.test(hdl_toplevel=toplevel, ...)
E   TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
harness_library.py:24: TypeError
=========================== 1 failed in 0.05s ===============================
"""
    err = mod._detect_harness_error(out, tests=0, returncode=1)
    assert err is not None
    assert err["kind"] == "cocotb-tools-typeerror"


def test_detect_module_not_found():
    mod = _load()
    out = "ModuleNotFoundError: No module named 'cocotb_test'"
    err = mod._detect_harness_error(out, tests=0, returncode=1)
    assert err is not None
    assert err["kind"] == "cocotb-import-missing-module"


def test_detect_import_error():
    mod = _load()
    out = "ImportError: cannot import name 'X' from 'cocotb_tools'"
    err = mod._detect_harness_error(out, tests=0, returncode=1)
    assert err is not None
    assert err["kind"] == "cocotb-import-error"


def test_detect_iverilog_elaboration_error():
    mod = _load()
    out = "error: Module `foo` not found in design.\n"
    err = mod._detect_harness_error(out, tests=0, returncode=1)
    assert err is not None
    assert err["kind"] == "iverilog-elaboration-error"


def test_detect_harness_library_internal_error():
    """A traceback line touching harness_library.py is a harness-side issue."""
    mod = _load()
    out = "Traceback ...\nharness_library.py:42: TypeError: ..."
    err = mod._detect_harness_error(out, tests=0, returncode=1)
    assert err is not None
    assert "harness" in err["kind"] or err["kind"] == "harness-library-internal-error"


def test_no_classification_when_tests_ran():
    """If at least one cocotb test ran, FAIL is a DUT-level signal — don't
    misclassify as Cat-D even if the log contains TypeError text."""
    mod = _load()
    out = "TypeError: int() ... (but tests ran)"
    err = mod._detect_harness_error(out, tests=1, returncode=1)
    assert err is None


def test_no_classification_when_clean_exit():
    """returncode==0 with tests==0 might just be 'no tests collected' — don't
    fabricate a Cat-D label."""
    mod = _load()
    out = "no tests collected"
    err = mod._detect_harness_error(out, tests=0, returncode=0)
    assert err is None


def test_no_classification_when_log_is_clean():
    """Empty log + tests==0 + non-zero exit doesn't match any known pattern."""
    mod = _load()
    err = mod._detect_harness_error("", tests=0, returncode=1)
    assert err is None


def test_detector_does_not_read_score_dir(tmp_path, monkeypatch):
    """Anti-blind-violation regression: the detector must not perform any
    filesystem access at all — it works purely on the pre-supplied stdout."""
    mod = _load()
    # No project/score path is even passed to the detector signature
    import inspect
    sig = inspect.signature(mod._detect_harness_error)
    param_names = set(sig.parameters.keys())
    assert "project" not in param_names
    assert "score_path" not in param_names
    assert "score_src" not in param_names
