"""`prose_polarity_census` must see what the gate cannot, and must never refuse.

The gate `prose_polarity_consulted_check` may only ever shrink its baseline, so
sharpening ITS predicate would fail CI on 46 extractors that predate the change
and cannot be recorded. The sharper predicate therefore lives in a census that
records debt and never blocks. These tests hold both halves of that: that it
really is sharper, and that it really cannot refuse.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "prose_polarity_census.py"
PROGRAMS_DIR = PROG.parent
RC_OK, RC_UNDETERMINED, RC_USAGE = 0, 2, 3

# A match bound by a `for` TARGET, writing through setdefault(...).add(...).
# Both spellings at once: this is what the gate cannot see and the census must.
BLIND_FOR_TARGET = '''\
import re

PAT = re.compile(r"budget of (\\d+) um")


def extract(text):
    out = {}
    for m in PAT.finditer(text):
        out.setdefault("die_area_budget_um", set()).add(m.group(1))
    return out
'''

# The same extractor, consulting polarity. Must NOT be in either census.
SIGHTED = '''\
import re

from _prose_polarity import is_denied, sentence_scope

PAT = re.compile(r"budget of (\\d+) um")


def extract(text):
    out = {}
    for m in PAT.finditer(text):
        lo, hi = sentence_scope(text, m.start(), m.end())
        if is_denied(text[lo:hi]):
            continue
        out.setdefault("die_area_budget_um", set()).add(m.group(1))
    return out
'''


def _run(programs, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), "--programs", str(programs),
         *[str(x) for x in extra]],
        capture_output=True, text=True, timeout=600)


def _tree(tmp_path, **files):
    d = tmp_path / "programs"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / f"{name}.py").write_text(body, encoding="utf-8")
    return d


def test_it_sees_an_extractor_the_gate_cannot(tmp_path):
    """THE WHOLE POINT. `for m in PAT.finditer(...)` with
    `setdefault(...).add(...)` is polarity-blind and invisible to the gate,
    because of how the match is BOUND and how the write is SPELLED."""
    d = _tree(tmp_path, blind_emit=BLIND_FOR_TARGET)
    r = _run(d, "--json", "-")
    assert r.returncode == RC_OK, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert "blind_emit::extract" in doc["newly_visible"], doc
    assert doc["census"] > doc["gate_census"], doc


def test_an_extractor_that_consults_polarity_is_in_NEITHER_census(tmp_path):
    """Otherwise the census would be counting the shape, not the defect."""
    d = _tree(tmp_path, sighted_emit=SIGHTED)
    r = _run(d, "--json", "-")
    doc = json.loads(r.stdout)
    assert doc["newly_visible"] == [], doc
    assert doc["census"] == 0 and doc["gate_census"] == 0, doc


def test_it_never_refuses_however_large_the_debt(tmp_path):
    """A census that can fail CI is a gate, and a second gate over the same
    corpus with a wider predicate is exactly what may not be wired."""
    files = {f"blind{i}_emit": BLIND_FOR_TARGET for i in range(5)}
    d = _tree(tmp_path, **files)
    r = _run(d)
    assert r.returncode == RC_OK, (
        "the census refused. It records debt; refusing is the gate's job:\n"
        + r.stdout + r.stderr)
    assert "NEVER REFUSES" in r.stdout, r.stdout
    assert r.stdout.count("[DEBT]") == 5, r.stdout


def test_an_empty_corpus_is_UNDETERMINED_and_names_what_it_could_not_read(tmp_path):
    """rc 2, and never a finding about the tree."""
    d = tmp_path / "programs"
    d.mkdir(parents=True)
    r = _run(d)
    out = r.stdout + r.stderr
    assert r.returncode == RC_UNDETERMINED, out
    assert "[CANNOT DETERMINE]" in out and str(d) in out, out
    assert "[DEBT]" not in out, out


def test_a_source_that_will_not_parse_is_named_and_not_counted(tmp_path):
    d = _tree(tmp_path, blind_emit=BLIND_FOR_TARGET)
    (d / "broken.py").write_text("def f(  :::\n", encoding="utf-8")
    r = _run(d, "--json", "-")
    doc = json.loads(r.stdout)
    assert any("broken.py" in u for u in doc["unreadable"]), doc
    assert doc["corpus"]["unreadable"] == 1, doc
    assert "[UNPARSED]" in r.stderr, r.stderr


# Blind via the `for`-TARGET spelling ALONE -- a plain dict assign, no
# setdefault. This is the only shape that distinguishes the two widenings, and
# without it the suite cannot tell an installed widening from a defined one.
BLIND_FOR_TARGET_ONLY = '''\
import re

PAT = re.compile(r"budget of (\\d+) um")


def extract(text):
    out = {}
    for m in PAT.finditer(text):
        out["die_area_budget_um"] = m.group(1)
    return out
'''


def test_the_widening_is_INSTALLED_and_not_merely_defined(tmp_path):
    """The bug this file was written with, and the control that missed it.

    `_writes_a_declared_value` calls `_match_derived_names` ITSELF, so a wider
    version has to REPLACE the one it calls. Defined and passed nowhere, the
    census reported 19 newly visible instead of 46 and looked exactly as though
    it worked.

    The first version of this test called `derived_names` directly, which tests
    the function and not its installation, and the other fixtures were blind via
    BOTH spellings so the setdefault widening covered for the missing one --
    measured: with the install removed, all eight tests still passed. This runs
    the census END TO END over a program blind via the `for`-target spelling
    alone, which is the only shape that can tell the two apart."""
    d = _tree(tmp_path, fortarget_emit=BLIND_FOR_TARGET_ONLY)
    r = _run(d, "--json", "-")
    assert r.returncode == RC_OK, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc["gate_census"] == 0, (
        "the GATE already sees this shape, so the census has nothing to add "
        "and its reason for existing has gone: " + repr(doc))
    assert "fortarget_emit::extract" in doc["newly_visible"], (
        "the `for`-target widening is not installed -- defining it is not "
        "enough, `_writes_a_declared_value` calls the module attribute: "
        + repr(doc))


def test_the_gate_module_is_left_unpatched_afterwards(tmp_path):
    """The widening is installed around the sharp pass only. A module attribute
    left patched is the next reader's mystery, and would silently widen the
    BLOCKING gate for anything importing it in the same process."""
    sys.path.insert(0, str(PROGRAMS_DIR))
    import prose_polarity_census as census
    import prose_polarity_consulted_check as gate

    before = gate._match_derived_names
    census.census_of(_tree(tmp_path, blind_emit=BLIND_FOR_TARGET))
    assert gate._match_derived_names is before, (
        "the census left the gate's `_match_derived_names` replaced")


def test_it_is_not_wired_as_a_blocking_gate():
    """A census wired on a plain `run ` becomes the thing it exists to avoid:
    a second gate over the same corpus with a wider predicate, failing CI on 46
    defects nobody introduced."""
    wiring = None
    for parent in PROG.parents:
        cand = parent / "tools" / "ci" / "repo_hygiene_gates.sh"
        if cand.is_file():
            wiring = cand
            break
    if wiring is None:
        pytest.skip("tools/ci/repo_hygiene_gates.sh is not in this checkout")
    blocking = [ln.strip() for ln in wiring.read_text(encoding="utf-8",
                                                      errors="replace").splitlines()
                if "prose_polarity_census" in ln
                and not ln.lstrip().startswith("#")
                and ln.strip().startswith("run ")]
    assert not blocking, (
        "the census is wired as a BLOCKING gate, which is the one thing it was "
        f"built not to be: {blocking}")


# A blind extractor that ARGUES the omission in its own docstring. The reason
# has to be long enough to be an argument -- `_DECLARED_REASON_MIN` -- because a
# marker on a one-liner is an assertion.
DECLARED = '''\
import re

PAT = re.compile(r"budget of (\\d+) um")


def extract(text):
    """NOT ASKED FOR POLARITY, and the omission is deliberate.

    This set answers "what values does the document state anywhere", and a
    value missing from it makes a correct downstream pin look stale. A sentence
    that also says "no" still states the number, so suppressing it here would
    refuse a correct reader -- the false refusal pointed the other way. The
    polarity question belongs to the consumer that decides, not to this reader.
    """
    out = {}
    for m in PAT.finditer(text):
        out["die_area_budget_um"] = m.group(1)
    return out
'''

# The same marker, with nothing behind it.
BARE_MARKER = '''\
import re

PAT = re.compile(r"budget of (\\d+) um")


def extract(text):
    """NOT ASKED FOR POLARITY."""
    out = {}
    for m in PAT.finditer(text):
        out["die_area_budget_um"] = m.group(1)
    return out
'''


def test_a_declared_omission_is_counted_apart_from_the_debt(tmp_path):
    """"Designed this way, and here is why" and "nobody looked" are different
    facts and had one number."""
    d = _tree(tmp_path, declared_emit=DECLARED)
    r = _run(d, "--json", "-")
    doc = json.loads(r.stdout)
    assert doc["declared_in_place"] == ["declared_emit::extract"], doc
    assert doc["newly_visible"] == [], doc


def test_a_declared_omission_is_still_NAMED_on_every_run(tmp_path):
    """Classified, never hidden. A census that stops printing a thing has
    stopped recording it."""
    d = _tree(tmp_path, declared_emit=DECLARED)
    r = _run(d)
    assert "[DECLARED] declared_emit::extract" in r.stdout, r.stdout
    assert "1 DECLARE the omission in place" in r.stdout, r.stdout


def test_the_marker_alone_does_not_buy_an_escape(tmp_path):
    """A token on a one-line docstring is an assertion, not an argument. If
    that cleared the floor, the classification would be a self-serve exemption
    list with no reviewer -- which is what the GATE's register exists to avoid
    and what this side must not reinvent."""
    d = _tree(tmp_path, bare_emit=BARE_MARKER)
    r = _run(d, "--json", "-")
    doc = json.loads(r.stdout)
    assert doc["declared_in_place"] == [], doc
    assert "bare_emit::extract" in doc["newly_visible"], doc


def test_declaring_it_cannot_change_the_verdict(tmp_path):
    """The reason a self-declared reason is SAFE here: escaping the count buys
    nothing, because the census cannot refuse either way. In a blocking gate the
    same mechanism would be a loophole, which is why the gate keeps a reviewed
    register instead."""
    a = _run(_tree(tmp_path / "x", declared_emit=DECLARED))
    b = _run(_tree(tmp_path / "y", bare_emit=BARE_MARKER))
    assert a.returncode == RC_OK and b.returncode == RC_OK, (a.stdout, b.stdout)


# Blind by the same shape, but pointed at Verilog. `parameter WIDTH = 8;`
# cannot be denied by a surrounding sentence, so the polarity question does not
# arise -- and the census must SAY that without acting on it.
CODE_SHAPED = '''\
import re

PAT = re.compile(r"parameter\\s+([A-Z][A-Z0-9_]+)\\s*=\\s*(\\d+)")


def extract(text):
    out = {}
    for m in PAT.finditer(text):
        out["die_area_budget_um"] = m.group(2)
    return out
'''


def test_a_code_shaped_debt_is_flagged_and_NOT_subtracted(tmp_path):
    """The caveat is printed, never applied. A keyword heuristic that silently
    dropped a third of the count would invent a precision it does not have --
    and would hide any genuine prose extractor that happens to mention a pin."""
    d = _tree(tmp_path, verilog_emit=CODE_SHAPED)
    r = _run(d, "--json", "-")
    doc = json.loads(r.stdout)
    assert "verilog_emit::extract" in doc["code_shaped"], doc
    assert "verilog_emit::extract" in doc["newly_visible"], (
        "the caveat was SUBTRACTED from the count it qualifies: " + repr(doc))


def test_a_prose_debt_is_not_flagged_as_code(tmp_path):
    d = _tree(tmp_path, fortarget_emit=BLIND_FOR_TARGET_ONLY)
    doc = json.loads(_run(d, "--json", "-").stdout)
    assert doc["code_shaped"] == [], doc
    assert "fortarget_emit::extract" not in doc["code_shaped"], doc


def test_the_calibration_is_printed_beside_the_number_it_qualifies(tmp_path):
    """A reader who sees `45 say nothing` and not the split will read a shape
    count as a defect count."""
    d = _tree(tmp_path, verilog_emit=CODE_SHAPED)
    r = _run(d)
    assert "[CALIBRATION]" in r.stdout, r.stdout
    assert "UPPER BOUND on a SHAPE" in r.stdout, r.stdout


def test_wider_asks_a_different_question_and_says_so(tmp_path):
    """`--wider` is the input-based population: what a function is FED, not what
    shape it writes. It reaches PREDICATES, which no write-shape widening can,
    and it is a longer list that is NOT a defect list."""
    blind_predicate = '''\
import re

PAT = re.compile(r"\\bMoore\\b")


def looks_moore(prompt):
    return bool(PAT.search(prompt))
'''
    d = _tree(tmp_path, moore_probe=blind_predicate)
    r = _run(d, "--wider")
    assert r.returncode == RC_OK, r.stdout + r.stderr
    assert "[FED A DOCUMENT] moore_probe::looks_moore" in r.stdout, r.stdout
    assert "not a defect list" in r.stdout, r.stdout


def test_wider_does_not_list_a_function_that_consults(tmp_path):
    sighted = '''\
import re

from _prose_polarity import is_denied

PAT = re.compile(r"\\bMoore\\b")


def looks_moore(prompt):
    m = PAT.search(prompt)
    return bool(m) and not is_denied(prompt)
'''
    d = _tree(tmp_path, moore_probe=sighted)
    r = _run(d, "--wider")
    assert "moore_probe::looks_moore" not in r.stdout, r.stdout


def test_the_census_headline_is_unchanged_by_the_flag(tmp_path):
    """`--wider` answers instead of, never alongside: mixing a 262-entry list
    into the census's own verdict is how the readable number stops being read."""
    d = _tree(tmp_path, blind_emit=BLIND_FOR_TARGET_ONLY)
    assert "[CENSUS]" in _run(d).stdout
    assert "[CENSUS]" not in _run(d, "--wider").stdout
