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

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import hdl_declaration_scan_strips_comments_check as G  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_FIX_COMMIT_SUBJECT = "read code, not comments"
_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/fmeda_fault_injection_coverage.py"


def _repo() -> Path:
    p = PROGRAMS
    for base in p.parents:
        if (base / ".git").exists():
            return base
    return p


def _blob(rev: str) -> str:
    r = _pr.run(["git", "show", f"{rev}:{_REL}"], cwd=_repo(),
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _fix_sha() -> str:
    r = _pr.run(["git", "log", "-1", "--format=%H", "--grep",
                        _FIX_COMMIT_SUBJECT], cwd=_repo(),
                       capture_output=True, text=True)
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


# ── the binding form must not decide the answer ─────────────────────────────
#
# A value reaches a name three ways: assignment, a `for` target, and a
# comprehension target. Only assignment propagated, so the commonest shape for
# a declaration scan -- strip once, then walk the lines -- read as unstripped.
# MEASURED: 7 sites across 6 regexes, 2 of them among the 5 the gate was
# BLOCKING on, so a third of the blocking list was the analyser's own limit.
#
# Every clean case below is paired with the same code over RAW text. Without
# that pair, a "fix" that simply stopped flagging would pass all of them.

_FOR_OVER_STRIPPED = r"""
import re
_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
def detect(t):
    code = _strip_hdl_comments(t)
    for line in code.splitlines():
        _MODULE_RE.findall(line)
"""

_FOR_OVER_RAW = _FOR_OVER_STRIPPED.replace("_strip_hdl_comments(t)", "t")


def test_a_for_target_inherits_the_strip_of_its_iterable():
    assert G.scan_source(_FOR_OVER_STRIPPED, "m") == []


def test_and_a_for_target_over_RAW_text_is_still_flagged():
    """The pair. This is what stops the fix above from being 'flag nothing'."""
    assert G.scan_source(_FOR_OVER_RAW, "m") == ["m::detect::_MODULE_RE(line)"]


def test_a_comprehension_target_inherits_it_too():
    src = _FOR_OVER_STRIPPED.replace(
        "    for line in code.splitlines():\n        _MODULE_RE.findall(line)",
        "    return [_MODULE_RE.findall(l) for l in code.splitlines()]")
    assert G.scan_source(src, "m") == []
    assert G.scan_source(src.replace("_strip_hdl_comments(t)", "t"),
                         "m") == ["m::detect::_MODULE_RE(l)"]


def test_every_name_in_a_tuple_target_inherits_it():
    src = _FOR_OVER_STRIPPED.replace(
        "for line in code.splitlines():",
        "for i, line in enumerate(code.splitlines()):")
    assert G.scan_source(src, "m") == []


def test_the_strip_survives_two_nested_loops():
    """Transitivity must hold ACROSS the binding forms, not only within one."""
    src = _FOR_OVER_STRIPPED.replace(
        "    for line in code.splitlines():\n        _MODULE_RE.findall(line)",
        "    for blk in code.split(';'):\n        for line in blk.splitlines():\n"
        "            _MODULE_RE.findall(line)")
    assert G.scan_source(src, "m") == []
    assert G.scan_source(src.replace("_strip_hdl_comments(t)", "t"),
                         "m") == ["m::detect::_MODULE_RE(line)"]


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


def test_non_hdl_exemptions_are_exact_live_and_argued():
    root = PROGRAMS.parent
    raw = G.scan(root)
    filtered, problems = G.apply_exemptions(raw, root)
    assert problems == []
    for name, reason in G._NOT_HDL_DECLARATION.items():
        assert name in raw
        assert name not in filtered
        assert len(reason.strip()) >= G._EXEMPT_REASON_MIN


def test_non_hdl_exemption_does_not_hide_a_neighbouring_declaration_scan(
        tmp_path):
    programs = tmp_path / "programs"
    programs.mkdir()
    source = _SIBLING.replace("def detect", "def other")
    (programs / "neighbour.py").write_text(source)
    raw = G.scan(tmp_path)
    filtered, problems = G.apply_exemptions(raw, tmp_path)
    assert problems == []
    assert filtered == ["neighbour::other::_MODULE_RE(t)"]


def test_the_keyword_test_is_SHALLOW_and_that_is_why_the_baseline_is_large():
    """Stated rather than hidden. `Chip area for module 'x'` is yosys OUTPUT,
    not HDL, and this test admits it — the keyword is there.

    That imprecision is why the recorded set is ~171 rather than a handful, and
    why the set is a debt register instead of a blocking list on day one. The
    gate's job is to catch anything NEW; sharpening the population is separate
    work and should be measured against the same controls above."""
    assert G.declares_hdl(r"^\s*Chip area for module\s+'(.+)':"), (
        "if this ever stops matching, the baseline can be re-cut smaller")


# ── stripping is an OPERATION, not a function name ──────────────────────────
#
# The gate first shipped recognising strippers only by NAME (`strip_comments`,
# `_strip_hdl`, ...). Two call sites in this tree remove comments with an inline
# `re.sub` and were reported as unstripped when they were already correct —
# `phase1_doc_one_shot_runner.gen_l9_integration_spec` (caught blocking a PR)
# and `phase3_one_shot_runner._c4_top_module_ports` (sat in the baseline as a
# false positive from day one). A gate that fails correct code gets switched
# off, so this is the same severity as missing a defect.

_INLINE_SUB = '''
import re
_MODULE_RE = re.compile(r"\\bmodule\\s+([A-Za-z_]\\w*)")
def read(f):
    txt = f.read_text()
    txt = re.sub(r"//[^\\n]*", " ", txt)
    txt = re.sub(r"/\\*.*?\\*/", " ", txt, flags=re.S)
    return _MODULE_RE.findall(txt)
'''

_INLINE_SUB_NOT_A_COMMENT = '''
import re
_MODULE_RE = re.compile(r"\\bmodule\\s+([A-Za-z_]\\w*)")
def read(f):
    txt = f.read_text()
    txt = re.sub(r"\\s+", " ", txt)
    return _MODULE_RE.findall(txt)
'''


def test_inline_re_sub_of_a_comment_pattern_counts_as_stripped():
    """`txt = re.sub(r"//[^\\n]*", ...)` removes comments as surely as a helper."""
    assert G.scan_source(_INLINE_SUB, "m") == [], (
        "an inline comment-strip is not recognised, so a correct call site is "
        "reported — the false positive that made this fix necessary")


def test_a_non_comment_re_sub_does_NOT_count_as_stripped():
    """The guard: the rule is 'a comment pattern', not 'any re.sub'.

    Whitespace collapsing leaves every comment in place. If this passes as
    stripped, the fix above has blinded the gate rather than sharpened it."""
    hits = G.scan_source(_INLINE_SUB_NOT_A_COMMENT, "m")
    assert any("_MODULE_RE" in h for h in hits), (
        f"collapsing whitespace was accepted as removing comments — any "
        f"re.sub now silences the gate. got: {hits}")


def test_the_comment_pattern_is_read_from_the_ast_constant():
    """`/\\*.*?\\*/` carries `/\\*` in SOURCE, not `/*`.

    Reading it via `ast.unparse` re-escapes and the match is lost — the exact
    trap that produced two retracted populations for this gate."""
    assert G._strips_comments_inline(
        __import__("ast").parse('re.sub(r"/\\*.*?\\*/", " ", t)').body[0].value)
    assert not G._strips_comments_inline(
        __import__("ast").parse('re.sub(r"\\s+", " ", t)').body[0].value)


# --- the path-token rule ----------------------------------------------------
#
# A keyword glued to a character class containing a PATH SEPARATOR is matching a
# path token, not a declaration. Both directions are asserted: a rule that only
# excluded things could be satisfied by excluding everything, which is exactly
# what the two rejected candidates did (243 -> 90 and 243 -> 238, each losing a
# real HDL scan). The NEGATIVE half below is the half that catches that.

_PATH_MATCHER = r"input[\\/]+docs|input_doc|\.(?:txt|pdf|docx?|md|csv)"


def test_a_path_matcher_is_not_a_declaration_scan():
    """The measured false positive: a FILE-PATH and EXTENSION matcher.

    `_META` blanks the class brackets, so this normalises to `input \\/  docs`
    and the bare `input` used to match. The value it scans is a provenance
    SOURCE LABEL, never HDL, so no comment can ever reach it.
    """
    assert G.declares_hdl(_PATH_MATCHER) is False


def test_the_path_rule_keeps_every_real_declaration_shape():
    """The NEGATIVE control. Each of these was lost by a rejected candidate."""
    for pattern in (
        r"\bmodule\s+(\w*)",                        # the known true positive
        r"\bmodule\s+([A-Za-z_]\w*)",
        r"^[ \t]*inout[ \t]+(?:(?:wire|reg)[ \t]+)?(\w+)",   # lost by cand. 2
        r"(?m)^[ \t]*module[ \t]+([A-Za-z_]\w*)",            # lost by cand. 2
        r"(?i)module[\s_-]?list",                            # lost by cand. 2
        r"\binput\s+(\w+)",
        r"(input|output|inout)\s+(?:wire|logic|reg)?\s*(\w+)",
    ):
        assert G.declares_hdl(pattern) is True, pattern


def test_a_whitespace_class_is_not_a_path_separator():
    """`[ \\t]` and `[\\s_-]` carry a BACKSLASH but no path separator.

    Candidate 2 tested for any backslash inside the class and so silently
    reclassified three real HDL scans as paths. The separator must be a
    literal `/`.
    """
    assert G.declares_hdl(r"module[ \t]+(\w+)") is True
    assert G.declares_hdl(r"module[\s_-]?list") is True
    assert G.declares_hdl(r"module[\\/]+x") is False
