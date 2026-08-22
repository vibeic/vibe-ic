"""A value that could have been read or defaulted says which.

WHY
===
MEASURED: a generator emitted a clock period of 24 while the run signed off at
the generator's own last-resort default of 20 — a 20 % over-constraint nobody
requested — and emitted a declared input delay of 4.8 as a fixed 2. Neither
artefact marked which had happened, so the two cases were byte-identical and a
silently unread input produced a complete, plausible run about the wrong
constraint.

WHAT THE RULE ADDS OVER WHAT LANDED
===================================
`declared_clock_period` already returns the disclosure beside the value and marks
TWO values correctly. What did not land is that every CALLER must carry that
disclosure through — a caller that reads `period_ns` and drops `matched_key`,
`source` and `line` re-creates the defect one layer up.

THE HELPERS ARE DISCOVERED BY SHAPE, WHICH IS THE POINT
=======================================================
A hand-list would cover today's two and miss the third.
`test_a_new_helper_is_picked_up_automatically` is the assertion that makes this
a rule rather than two marked values.

chip-AGNOSTIC: provenance plumbing. Numbers below are arbitrary.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "generated_values_state_whether_they_were_read_or_defaulted.py"
_REPO = _PROGRAMS.parents[3]

_spec = importlib.util.spec_from_file_location("gvswtwrod", _TOOL)
gv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gv)

_HELPER = (
    'def declared_period_ns(docs, candidates):\n'
    '    return {"period_ns": None, "matched_key": None, "source": None,\n'
    '            "line": None, "note": ""}\n')

_DROPS = (
    'from helper import declared_period_ns\n'
    'def emit_sdc(docs, cands, out):\n'
    '    rep = declared_period_ns(docs, cands)\n'
    '    period = rep["period_ns"] or 20.0\n'
    '    out.write_text(f"create_clock -period {period}\\n")\n')

_CARRIES = (
    'from helper import declared_period_ns\n'
    'def emit_sdc(docs, cands, out):\n'
    '    rep = declared_period_ns(docs, cands)\n'
    '    period = rep["period_ns"] or 20.0\n'
    '    where = rep["source"] or "no document declared one"\n'
    '    out.write_text(f"# period {period} from {where} line {rep[\'line\']}\\n"\n'
    '                   f"create_clock -period {period}\\n")\n')


def _tree(tmp_path, modules):
    for n, b in modules.items():
        (tmp_path / n).write_text(b)
    return tmp_path


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------------ red control

def test_a_caller_that_drops_the_disclosure_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the value is used, the provenance is discarded, and
    the artefact is identical whether the input was read or defaulted."""
    root = _tree(tmp_path, {"helper.py": _HELPER, "gen.py": _DROPS})
    rc, out = _run(root)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "read or DEFAULTED" in out or "READ or DEFAULTED" in out
    assert "declared_period_ns" in out


def test_the_same_caller_carrying_the_disclosure_passes(tmp_path):
    """BIDIRECTIONAL: the identical value, with its provenance, goes green."""
    root = _tree(tmp_path, {"helper.py": _HELPER, "gen.py": _CARRIES})
    rc, out = _run(root)
    assert rc == 0, out


def test_a_comment_naming_the_disclosure_does_not_count(tmp_path):
    """MEASURED FALSE PASS, now pinned.

    The check was `any(field in <source text>)`, so a caller carrying

        # we deliberately ignore matched_key / source / line here

    reported PASS: a comment stating the provenance is DISCARDED counted as
    carrying it.
    """
    root = _tree(tmp_path, {"helper.py": _HELPER, "gen.py":
        'from helper import declared_period_ns\n'
        'def emit_sdc(docs, c, out):\n'
        '    rep = declared_period_ns(docs, c)\n'
        '    # we deliberately ignore matched_key / source / line here\n'
        '    out.write_text(str(rep["period_ns"] or 20.0))\n'})
    rc, out = _run(root)
    assert rc == 1, f"a comment satisfied the disclosure check:\n{out}"


def test_the_disclosure_may_be_carried_elsewhere_in_the_module(tmp_path):
    """MEASURED FALSE POSITIVE, now pinned the other way.

    At FUNCTION granularity this reported `phase3_one_shot_runner.
    _resolve_clock_spec()` — which returns only the number — as dropping the
    provenance. It is not a defect: the same emitting caller obtains the
    disclosure separately and writes it into the SDC beside the value. The
    obligation belongs to the unit that emits the artefact.
    """
    root = _tree(tmp_path, {"helper.py": _HELPER, "gen.py":
        'from helper import declared_period_ns\n'
        'def resolve(docs, c):\n'
        '    return declared_period_ns(docs, c)["period_ns"] or 20.0\n'
        'def disclosure(docs, c):\n'
        '    rep = declared_period_ns(docs, c)\n'
        '    return f"# period from {rep[\'source\']} line {rep[\'line\']}"\n'
        'def emit(docs, c, out):\n'
        '    out.write_text(disclosure(docs, c) + str(resolve(docs, c)))\n'})
    rc, out = _run(root)
    assert rc == 0, out


def test_a_new_helper_is_picked_up_automatically(tmp_path):
    """The rule is the shape, not a list of two names. A NEW read-or-default
    helper must extend the rule with no edit here."""
    new_helper = (
        'def declared_max_transition_ns(docs):\n'
        '    return {"value_ns": None, "matched_key": None, "source": None,\n'
        '            "line": None, "note": ""}\n')
    dropper = (
        'from h2 import declared_max_transition_ns\n'
        'def emit(docs, out):\n'
        '    rep = declared_max_transition_ns(docs)\n'
        '    out.write_text(str(rep["value_ns"] or 0.5))\n')
    root = _tree(tmp_path, {"h2.py": new_helper, "gen.py": dropper})
    helpers = gv.find_helpers(root)
    assert "declared_max_transition_ns" in helpers, helpers
    rc, out = _run(root)
    assert rc == 1, out


# --------------------------------------------------- what is NOT a finding

def test_a_test_is_not_a_call_site(tmp_path):
    """A test asserting only the value asserts exactly what it means to."""
    (tmp_path / "tests").mkdir()
    root = _tree(tmp_path, {"helper.py": _HELPER})
    (tmp_path / "tests" / "test_x.py").write_text(_DROPS)
    rc, out = _run(root)
    assert rc == 2, out          # no NON-test call site at all


def test_the_helpers_own_module_is_not_a_call_site(tmp_path):
    root = _tree(tmp_path, {"helper.py": _HELPER + "\n" + _DROPS.replace(
        "from helper import declared_period_ns\n", "")})
    rc, out = _run(root)
    assert rc == 2, out


def test_a_dict_without_enough_disclosure_is_not_a_helper(tmp_path):
    thin = ('def get_period(docs):\n'
            '    return {"period_ns": 20.0, "source": "x"}\n')
    root = _tree(tmp_path, {"helper.py": thin,
                            "gen.py": _DROPS.replace("declared_period_ns",
                                                     "get_period")})
    rc, out = _run(root)
    assert rc == 2, out
    assert "no read-or-default helper" in out


# ------------------------------------------- the real tree keeps its marking

def test_the_landed_helpers_are_still_recognised():
    helpers = gv.find_helpers(_REPO)
    assert "declared_period_ns" in helpers, sorted(helpers)
    assert "declared_io_delay_fraction" in helpers, sorted(helpers)


def test_repository_itself_is_clean():
    rc, out = _run(_REPO)
    assert rc == 0, out
    assert "examined 3 call site(s)" in out or "call site(s) of" in out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out
