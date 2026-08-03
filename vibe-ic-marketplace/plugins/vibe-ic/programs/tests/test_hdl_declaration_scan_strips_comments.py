"""vibe-ic#731 — the controls ARE the test.

Three detectors were built for this and retracted, each producing a confident
population that did not contain the known instance. The acceptance criterion
recorded in the issue is therefore not "does it find something" but:

    POSITIVE  `fmeda_fault_injection_coverage.detect_safety_mechanism` at the
              commit BEFORE its fix MUST be flagged.
    NEGATIVE  the same function AFTER the fix must NOT be.

Both are driven here against the real git objects, not a fixture.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import hdl_declaration_scan_strips_comments_check as G  # noqa: E402

_FIX_COMMIT_SUBJECT = "read code, not comments"
_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/fmeda_fault_injection_coverage.py"


def _repo() -> Path:
    p = PROGRAMS
    for base in p.parents:
        if (base / ".git").exists():
            return base
    return p


def _blob(rev: str) -> str:
    r = subprocess.run(["git", "show", f"{rev}:{_REL}"], cwd=_repo(),
                       capture_output=True, text=True, timeout=55)
    return r.stdout if r.returncode == 0 else ""


def _fix_sha() -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%H", "--grep",
                        _FIX_COMMIT_SUBJECT], cwd=_repo(),
                       capture_output=True, text=True, timeout=55)
    return r.stdout.strip()


# ── the two controls ────────────────────────────────────────────────────────

def test_POSITIVE_the_known_instance_is_flagged():
    """The one that killed three earlier detectors.

    `detect_safety_mechanism` CALLS `_strip_hdl_comments(t)` for one variable
    and runs `_MODULE_RE.findall(t)` on the raw `t`. Any detector asking
    "does this function reach a stripper" answers YES and misses it."""
    sha = _fix_sha()
    if not sha:
        pytest.skip("the #729 fix commit is not in this checkout's history")
    src = _blob(f"{sha}~1")
    if not src:
        pytest.skip("pre-fix blob unavailable")
    hits = G.scan_source(src, "fmeda")
    assert any("detect_safety_mechanism" in h and "_MODULE_RE" in h
               for h in hits), (
        f"the known instance is NOT flagged — this detector is not measuring "
        f"the right thing. got: {hits}")


def test_NEGATIVE_the_fixed_version_is_clean_for_that_call():
    sha = _fix_sha()
    if not sha:
        pytest.skip("the #729 fix commit is not in this checkout's history")
    src = _blob(sha)
    if not src:
        pytest.skip("post-fix blob unavailable")
    hits = G.scan_source(src, "fmeda")
    assert not any("detect_safety_mechanism" in h and "_MODULE_RE" in h
                   for h in hits), (
        f"the fix is not recognised — the gate would re-report a repaired "
        f"call site forever. got: {hits}")


# ── the dataflow property, in isolation ─────────────────────────────────────

_SIBLING = '''
import re
_MODULE_RE = re.compile(r"\\bmodule\\s+([A-Za-z_]\\w*)")
def detect(t):
    code = _strip_hdl_comments(t)      # a SIBLING is stripped
    other = len(code)
    return [m for m in _MODULE_RE.findall(t)], other   # ...this one is not
'''

_STRIPPED = '''
import re
_MODULE_RE = re.compile(r"\\bmodule\\s+([A-Za-z_]\\w*)")
def detect(t):
    code = _strip_hdl_comments(t)
    return _MODULE_RE.findall(code)
'''


def test_a_stripped_SIBLING_does_not_make_this_value_safe():
    """The distinction the whole program turns on."""
    assert G.scan_source(_SIBLING, "m") == ["m::detect::_MODULE_RE(t)"]


def test_scanning_the_stripped_value_is_clean():
    assert G.scan_source(_STRIPPED, "m") == []


def test_the_strip_is_followed_through_one_more_hop():
    src = _STRIPPED.replace("return _MODULE_RE.findall(code)",
                            "body = code.strip()\n    return _MODULE_RE.findall(body)")
    assert G.scan_source(src, "m") == []


# ── reading the pattern ─────────────────────────────────────────────────────

def test_the_keyword_is_found_in_an_escaped_pattern():
    """`ast.unparse` re-escapes, so `\\bmodule` puts `b` before `module` and a
    word-boundary probe fails. That artefact produced two retracted populations
    of 252 and 10, neither containing the known instance."""
    assert G.declares_hdl(r"\bmodule\s+([A-Za-z_]\w*)")
    assert G.declares_hdl(r"^\s*module\s+(\w+)")
    assert G.declares_hdl(r"\binput\b\s+wire")


def test_a_pattern_that_names_no_declaration_is_out_of_scope():
    assert not G.declares_hdl(r"total\s+violations?\s*:\s*(\d+)")
    assert not G.declares_hdl(r"Runtime:\s*([\d.]+)s")


def test_the_keyword_test_is_SHALLOW_and_that_is_why_the_baseline_is_large():
    """Stated rather than hidden. `Chip area for module 'x'` is yosys OUTPUT,
    not HDL, and this test admits it — the keyword is there.

    That imprecision is why the recorded set is ~171 rather than a handful, and
    why the set is a debt register instead of a blocking list on day one. The
    gate's job is to catch anything NEW; sharpening the population is separate
    work and should be measured against the same controls above."""
    assert G.declares_hdl(r"^\s*Chip area for module\s+'(.+)':"), (
        "if this ever stops matching, the baseline can be re-cut smaller")
