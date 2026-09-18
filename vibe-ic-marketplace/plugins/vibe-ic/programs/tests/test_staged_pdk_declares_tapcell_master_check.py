"""Tests for staged_pdk_declares_tapcell_master_check.py — the guard that a
load-bearing sentinel default may not be INHERITED.

THE LOAD-BEARING ARMS ARE THE ONES THAT MAKE IT NOT-GREEN. A guard that cannot
fail is not a guard, and one that fires in both directions is worse than none:
every arm that asserts a PASS is paired with an arm that asserts a FAIL or a
REFUSAL on the same fixture, one edit apart.

An rc is not a verdict. `rc 1` is also what a Python traceback exits with and
`rc 2` is what argparse exits with, so every non-zero arm asserts the LINE that
names the site as well, through `_assert_is_a_finding_not_a_crash` /
`_assert_is_a_refusal_not_a_crash`.

THREE ARMS EXIST BECAUSE THIS CLASS OF GUARD HAS FAILED BEFORE
  * a comment / a string literal naming the field must not buy a PASS, and a
    comment-only edit must not trip the gate either — a grep-shaped rule is
    satisfiable by prose, in both directions;
  * the guard ships INTO the directory it scans and its own docstring names the
    contracted class, so a gate that found itself would FAIL the day it landed;
  * scanning nothing and finding nothing is what a wrong root looks like, and
    must not be reported the way a clean sweep is.

AND FOUR ARE THE BUY-GREEN AUDIT, PINNED
  * `C(**d)`, `C(*a)` and `C(x, ...)` are CANNOT-CHECK, never PASS: each is a
    one-token edit to a guarded call that leaves the omission exactly where it
    was, so rc 0 over any of them would be a gate you switch off by typing two
    braces;
  * `PdkConfig = None` in dead code must not cancel the rule — an alias can be
    rebound out of the set, the class's own name never can.

The fixtures are REAL MODULES, not snippets: module docstring, `__future__`
import, a dataclass with many fields, a resolver with branches and an early
`return None`, comments interleaved through a call that spans many lines. The
site this gate was written for carries 34 keyword arguments over 50-odd lines.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "staged_pdk_declares_tapcell_master_check.py"
_PLUGIN_ROOT = _PROGRAMS.parent

sys.path.insert(0, str(_PROGRAMS))


def _load():
    spec = importlib.util.spec_from_file_location("_sdtm_check", _GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_sdtm_check"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()

_CLS = "PdkConfig"
_FIELD = "tapcell_master"

_HEADER = '''"""A resolver module, in the shape the real one has.

Docstring, imports, a dataclass, a function with branches. The contracted
field is named right here in prose — which must change nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PdkConfig:
    name: str
    liberty: str
    tech_lef: str
    cell_lef: str
    site: str
    metal_prefix: str = "met"
    tapcell_master: Optional[str] = None
    tapcell_distance_um: float = 14.0
    antenna_diode_cell: Optional[str] = None
    macro_lefs: List[str] = field(default_factory=list)


def _derive(_src):
    """Ask the library itself; returns (value, why)."""
    return None, "NONE: nothing declared it"
'''

_REGISTRY_SITE = '''

def _from_registry(reg) -> Optional[PdkConfig]:
    if not reg:
        return None
    tap, _why = _derive(reg)
    return PdkConfig(
        name=reg["name"],
        liberty=reg["liberty"],
        tech_lef=reg["tech_lef"],
        cell_lef=reg["cell_lef"],
        site=reg.get("site") or "unit",
        metal_prefix=reg.get("metal_prefix") or "met",
        # Declared, or asked of the library's own abstract view.
        tapcell_master=tap,
        tapcell_distance_um=float(reg.get("distance_um") or 14.0),
    )
'''


def _staged_site(*, declare: bool, extra: str = "") -> str:
    """The staged-PDK resolver, with or without the contracted keyword.

    `extra` goes INSIDE the call, so a comment or a string literal naming the
    field sits exactly where a grep would be fooled by it.
    """
    line = f"        {_FIELD}=tap,\n" if declare else ""
    return f'''

def _from_staged(stage_dir) -> Optional[PdkConfig]:
    """The project-local lane. Many more knobs than the registry lane."""
    if stage_dir is None:
        return None
    if not stage_dir.get("liberty"):
        return None
    tap, _why = _derive(stage_dir)
    return PdkConfig(
        name="custom:" + stage_dir["name"],
        liberty=stage_dir["liberty"],
        tech_lef=stage_dir["tech_lef"],
        # A locally-staged library is host-accessible, so resolve directly.
        cell_lef=stage_dir["cell_lef"],
        site=stage_dir.get("site") or "unit",
        metal_prefix=stage_dir.get("metal_prefix") or "met",
{extra}{line}        tapcell_distance_um=14.0,
        antenna_diode_cell=stage_dir.get("diode"),
        macro_lefs=list(stage_dir.get("macro_lefs") or []),
    )
'''


def _tree(tmp_path: Path, body: str, name: str = "resolver.py") -> Path:
    root = tmp_path / "venue"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body)
    return root


def _run(root: Path, *extra: str):
    """Run the guard as the gates run it: a subprocess, judged by its rc."""
    p = subprocess.run([sys.executable, str(_GUARD), str(root), *extra],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _assert_is_a_finding_not_a_crash(out: str, where: str = "resolver.py:"):
    assert "[FAIL]" in out, f"rc 1 without a [FAIL] line is a crash:\n{out}"
    assert where in out, f"the finding must name the offending site:\n{out}"
    assert "Traceback" not in out, f"the guard raised:\n{out}"


def _assert_is_a_refusal_not_a_crash(out: str, fragment: str):
    assert "[REFUSE]" in out, f"rc 2 without a [REFUSE] line is a crash:\n{out}"
    assert fragment in out, f"the refusal must say WHY ({fragment!r}):\n{out}"
    assert "[PASS]" not in out, f"a refusal is not a PASS:\n{out}"
    assert "Traceback" not in out, f"the guard raised:\n{out}"


def _verdicts(root: Path):
    """{(basename, line): verdict} — what an rc cannot say."""
    rep = mod.audit(Path(root).resolve())
    return {(Path(s["file"]).name, s["line"]): s["verdict"] for s in rep["sites"]}


# ---------------------------------------------------------------------------
# THE DEFECT, AND ITS CORRECTION. These two arms are the whole gate: same
# fixture, one keyword argument apart, opposite verdicts.
# ---------------------------------------------------------------------------
def test_omitting_the_contracted_field_fails_and_names_the_site(tmp_path):
    root = _tree(tmp_path, _HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    rc, out = _run(root)
    assert rc == 1, f"an omitted load-bearing default must FAIL:\n{out}"
    # The LINE must be the staged site, not merely any line in the file.
    src = (root / "resolver.py").read_text().splitlines()
    want = next(i + 1 for i, ln in enumerate(src)
                if ln.strip().startswith('name="custom:'))
    ctor = max(i + 1 for i in range(want) if src[i].rstrip().endswith(_CLS + "("))
    _assert_is_a_finding_not_a_crash(out, f"resolver.py:{ctor}")
    assert _FIELD in out and _CLS in out


def test_the_corrected_shape_passes(tmp_path):
    root = _tree(tmp_path, _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    rc, out = _run(root)
    assert rc == 0, f"every site declaring the field must PASS:\n{out}"
    assert "[PASS]" in out


# ---------------------------------------------------------------------------
# PROSE MUST NOT MOVE THE VERDICT (the grep-shaped-rule defect class).
# ---------------------------------------------------------------------------
def test_a_comment_naming_the_field_does_not_satisfy_the_gate(tmp_path):
    root = _tree(tmp_path, _HEADER + _REGISTRY_SITE + _staged_site(
        declare=False, extra=f"        # {_FIELD}=tap,  # left for later\n"))
    rc, out = _run(root)
    assert rc == 1, (
        "a COMMENT spelling the keyword must not buy a PASS — comments are "
        f"not arguments:\n{out}")
    _assert_is_a_finding_not_a_crash(out)


def test_a_string_literal_naming_the_field_does_not_satisfy_the_gate(tmp_path):
    root = _tree(tmp_path, _HEADER + _REGISTRY_SITE + _staged_site(
        declare=False, extra=f'        name="{_FIELD}=" + str(tap),\n'))
    rc, out = _run(root)
    assert rc == 1, (
        f"a STRING containing {_FIELD!r} is a Constant, never a keyword:\n{out}")
    _assert_is_a_finding_not_a_crash(out)


def test_editing_only_a_comment_does_not_flip_a_passing_tree(tmp_path):
    """The other direction: prose must not TRIP the gate either."""
    clean = _HEADER + _REGISTRY_SITE + _staged_site(declare=True)
    rc_a, _ = _run(_tree(tmp_path / "a", clean))
    rc_b, out = _run(_tree(
        tmp_path / "b",
        clean.replace("def _derive(_src):",
                      f"# NOTE: {_FIELD} used to be omitted here.\n"
                      f"def _derive(_src):")))
    assert rc_a == 0 and rc_b == 0, (
        f"a comment-only edit changed the verdict {rc_a} -> {rc_b}:\n{out}")


# ---------------------------------------------------------------------------
# VENUE. A fixture is not production.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("where", ["tests/resolver.py", "test_resolver.py",
                                   "resolver_test.py", "gate_fixtures/r.py"])
def test_test_source_omitting_the_field_is_out_of_venue(tmp_path, where):
    root = tmp_path / "venue"
    target = root / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    # A production copy so the scan is not vacuous — otherwise this would
    # pass for the wrong reason (rc 2), and prove nothing about the venue.
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    rc, out = _run(root)
    assert rc == 0, f"{where} is fixture intent, not a production site:\n{out}"


def test_an_ancestor_directory_name_does_not_empty_the_venue(tmp_path):
    """The venue is what is BELOW the root. Deciding it from the absolute path
    lets a checkout under any directory called `test` report `0 files scanned`
    — the gate switched off by where somebody cloned it."""
    root = tmp_path / "test" / "proj" / "venue"
    root.mkdir(parents=True)
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    rc, out = _run(root)
    assert rc == 1, f"the venue is what is BELOW the root:\n{out}"
    _assert_is_a_finding_not_a_crash(out)


def test_a_test_directory_below_the_root_is_still_out_of_venue(tmp_path):
    """The pair: relative parts must still exclude a real fixture tree."""
    root = tmp_path / "test" / "proj" / "venue"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    rc, out = _run(root)
    assert rc == 0, f"`tests/` BELOW the root is still fixture intent:\n{out}"


# ---------------------------------------------------------------------------
# THE BUY-GREEN AUDIT, PINNED. Each of these is ONE token away from the
# FAILing fixture and leaves the omission exactly where it was, so rc 0 would
# be a gate anybody can switch off. CANNOT-CHECK is the answer, not PASS.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tail,fragment", [
    ("**extra,", "**kwargs"),
    ("*rest,", "*args"),
], ids=["**kwargs", "*args"])
def test_a_starred_site_is_cannot_check_never_pass(tmp_path, tail, fragment):
    body = _HEADER + _REGISTRY_SITE + _staged_site(
        declare=False, extra=f"        {tail}\n")
    root = _tree(tmp_path, body)
    rc, out = _run(root)
    assert rc == 2, f"a starred site is undecidable, and that is not PASS:\n{out}"
    assert "UNDECIDABLE" in out and fragment in out, out
    _assert_is_a_refusal_not_a_crash(out, "outside what this rule decides")
    assert "UNDECIDABLE" in _verdicts(root).values()


def test_a_positional_argument_is_cannot_check_never_declared(tmp_path):
    """The positional index model is DELETED, not repaired: deriving it from a
    class body fired at sites that DID pass the field (a `ClassVar` shifted it
    up) and stayed silent at sites that did not (a base class shifted it down).
    A positional call is out of this rule's scope — and out of scope is rc 2,
    because rc 0 would make `name=x` -> `x` a one-token way out."""
    body = _HEADER + '''

def _positional():
    return PdkConfig("n", "lib", "tlef", "clef", "unit", "met", "MASTER")
'''
    root = _tree(tmp_path, body)
    rc, out = _run(root)
    assert rc == 2, f"a positional argument declares nothing here:\n{out}"
    _assert_is_a_refusal_not_a_crash(out, "positional argument(s)")
    assert "UNDECIDABLE" in _verdicts(root).values()


def test_a_starred_site_that_also_declares_is_still_a_pass(tmp_path):
    """The pair: undecidability is about the FIELD, not about the call shape.
    A site that writes the keyword down is DECLARED however else it is spelled,
    or the rc-2 rule above would have swallowed the rule it protects."""
    body = _HEADER + _REGISTRY_SITE + _staged_site(
        declare=True, extra="        **extra,\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, f"the keyword is written down, so the site declares:\n{out}"
    assert "[PASS]" in out


def test_rebinding_the_class_name_in_dead_code_does_not_disarm_the_rule(tmp_path):
    """An ALIAS may be cancelled by a rebinding; the class's own name may not,
    or `PdkConfig = None` in dead code would be a one-line way to switch every
    site in the file off at once."""
    body = (_HEADER + _REGISTRY_SITE + _staged_site(declare=False)
            + f"\n\n{_CLS} = None  # unused\n")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, f"a dead rebinding must not cancel the rule:\n{out}"
    _assert_is_a_finding_not_a_crash(out)


# ---------------------------------------------------------------------------
# WHAT COUNTS AS A CONSTRUCTION SITE: the name, the attribute, ONE hop.
# ---------------------------------------------------------------------------
def _alias_body(*, binding: str, call: str, declare: bool) -> str:
    line = f'        {_FIELD}="TAPX1",\n' if declare else ""
    return f'''"""A module that constructs the class through another name."""
from __future__ import annotations

import defs

{binding}

def _build():
    return {call}(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
        metal_prefix="met",
{line}        tapcell_distance_um=14.0,
    )
'''


_SITE_SHAPES = [
    ("", "defs.PdkConfig", "attribute call"),
    ("Cfg = defs.PdkConfig\n", "Cfg", "one hop from an attribute"),
    (f"from defs import {_CLS} as Cfg\n", "Cfg", "one hop from an import"),
]


@pytest.mark.parametrize("binding,call,_why", _SITE_SHAPES,
                         ids=[s[2] for s in _SITE_SHAPES])
def test_each_recognised_shape_is_a_construction_site(tmp_path, binding, call, _why):
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "defs.py").write_text(_HEADER)
    (root / "user.py").write_text(
        _alias_body(binding=binding, call=call, declare=False))
    rc, out = _run(root)
    assert rc == 1, f"renaming the constructor must not hide the site:\n{out}"
    _assert_is_a_finding_not_a_crash(out, where="user.py:")


@pytest.mark.parametrize("binding,call,_why", _SITE_SHAPES,
                         ids=[s[2] for s in _SITE_SHAPES])
def test_each_recognised_shape_passes_once_it_declares(tmp_path, binding, call, _why):
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "defs.py").write_text(_HEADER)
    (root / "user.py").write_text(
        _alias_body(binding=binding, call=call, declare=True))
    rc, out = _run(root)
    assert rc == 0, f"the same site declaring the field must PASS:\n{out}"


# ---------------------------------------------------------------------------
# THE DOCUMENTED CONSERVATISMS, PINNED SO THAT WIDENING IS A DELIBERATE EDIT.
# Each of these is a FALSE NEGATIVE the docstring names under KNOWN
# CONSERVATISM. They are here so the boundary cannot move by accident — and
# each is paired above with the FP it exists to prevent.
# ---------------------------------------------------------------------------
def test_a_function_local_alias_is_not_a_site(tmp_path):
    """KNOWN CONSERVATISM. Reading bindings inside functions is what made a
    PARAMETER named `cls` in an unrelated function a construction site and
    reported a defect against an object that was not this class at all. The
    second half of this fixture is that false positive; the first is the price
    paid to be rid of it."""
    body = _HEADER + _REGISTRY_SITE + '''

def make_default():
    cls = PdkConfig
    return cls(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
        metal_prefix="met", tapcell_distance_um=14.0,
    )


def build_anything(cls, **kw):
    return cls(kw)
'''
    root = _tree(tmp_path, body)
    rc, out = _run(root)
    assert rc == 0, f"`cls` is a function-local binding, not a site:\n{out}"
    src = (root / "resolver.py").read_text().splitlines()
    foreign = next(i + 1 for i, ln in enumerate(src)
                   if ln.strip() == "return cls(kw)")
    assert ("resolver.py", foreign) not in _verdicts(root), (
        f"line {foreign} is another function's PARAMETER, not this class")


def test_a_name_also_bound_as_a_parameter_is_cannot_check_not_a_finding(tmp_path):
    """THE OTHER FALSE POSITIVE THIS ROUND CLOSED. `build` below works and has
    no field to state: it constructs whatever its caller passed. Telling that
    call apart from a real one needs a scope model, and the two this file has
    carried each shipped a bug, so it refuses at file granularity instead —
    which can only ever become CANNOT-CHECK, never green."""
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    (root / "other.py").write_text(f'''"""A factory whose parameter carries the name."""


def build({_CLS}):
    return {_CLS}(a=1)
''')
    rc, out = _run(root)
    assert rc == 2, f"a parameter of that name constructs who-knows-what:\n{out}"
    _assert_is_a_refusal_not_a_crash(out, "also binds as a PARAMETER")
    assert "[FAIL]" not in out, f"a refusal is never a finding:\n{out}"


def test_the_parameter_rule_does_not_switch_the_module_off(tmp_path):
    """The pair: the same module with the parameter renamed must be JUDGED,
    or `def _(PdkConfig): pass` would be a one-line way to silence a file."""
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    (root / "other.py").write_text('''"""A factory with an ordinary parameter name."""


def build(ctor):
    return ctor(a=1)
''')
    rc, out = _run(root)
    assert rc == 1, f"an ordinary parameter name changes nothing:\n{out}"
    _assert_is_a_finding_not_a_crash(out)


def test_a_transitive_alias_is_not_followed(tmp_path):
    """KNOWN CONSERVATISM: ONE hop. `Y = X` where `X` is itself an alias is
    not a site. Chasing chains to a fixpoint is machinery this rule does not
    carry — the pair to this arm is the one-hop arm above, which must stay
    green or the narrowing has deleted the rule."""
    body = _HEADER + _REGISTRY_SITE + f'''

Alias = {_CLS}
Again = Alias


def _build():
    return Again(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
    )
'''
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, f"two hops is out of scope, and it says so:\n{out}"


def test_one_hop_from_the_bare_name_is_still_followed(tmp_path):
    """The pair to the arm above: cutting transitivity must not cut aliases."""
    body = _HEADER + _REGISTRY_SITE + f'''

Alias = {_CLS}


def _build():
    return Alias(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
    )
'''
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 1, f"one module-level hop IS a construction site:\n{out}"
    _assert_is_a_finding_not_a_crash(out)


def test_an_alias_rebound_to_something_else_is_not_a_site(tmp_path):
    """A module-level name assigned the class in one place and something else
    in another is a question about FLOW. Judging its calls would report a
    defect against an object that may be a `dict`."""
    body = _HEADER + _REGISTRY_SITE + f'''

Alias = {_CLS}
Alias = dict


def _build():
    return Alias(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
    )
'''
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 0, f"a name bound both ways constructs who-knows-what:\n{out}"


# ---------------------------------------------------------------------------
# CANNOT-CHECK IS NOT PASS.
# ---------------------------------------------------------------------------
def test_no_construction_site_is_cannot_check_not_pass(tmp_path):
    rc, out = _run(_tree(tmp_path, _HEADER))
    assert rc == 2, f"0 sites means the rule was applied to nothing:\n{out}"
    _assert_is_a_refusal_not_a_crash(out, "0 construction sites")


def test_a_renamed_class_is_cannot_check_not_pass(tmp_path):
    """A stale contract must announce itself. Renaming the class away is how a
    ratchet like this one dies quietly green."""
    body = (_HEADER + _REGISTRY_SITE).replace(_CLS, "PdkSettings")
    rc, out = _run(_tree(tmp_path, body))
    assert rc == 2, f"a stale contract must not report a PASS:\n{out}"
    _assert_is_a_refusal_not_a_crash(out, "not DEFINED")


_SECOND_CLASS = '''"""An unrelated class that happens to share the name."""
from __future__ import annotations


class PdkConfig:
    def __init__(self, a=None):
        self.a = a


def make():
    return PdkConfig(a=1)
'''


def test_a_second_class_of_the_same_name_is_cannot_check_not_a_finding(tmp_path):
    """THE FALSE POSITIVE THIS PRECONDITION EXISTS FOR. `make()` above works,
    and it has no field to state — but this rule keys on a NAME, so without the
    precondition it reported a defect against a class that is not the
    contracted one at all. Refusing is the only sound answer: rc 2, named, and
    never a [FAIL]."""
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    (root / "other.py").write_text(_SECOND_CLASS)
    rc, out = _run(root)
    assert rc == 2, f"two classes, one name — this rule cannot tell:\n{out}"
    _assert_is_a_refusal_not_a_crash(out, "denotes 2 different classes")
    assert "[FAIL]" not in out, f"a refusal is never a finding:\n{out}"


def test_the_precondition_does_not_switch_the_rule_off(tmp_path):
    """The pair: the same tree with the name belonging to ONE class again must
    be JUDGED — a precondition that refused a bit too eagerly would be a
    ratchet that anybody can disable by adding a class."""
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=False))
    (root / "other.py").write_text(_SECOND_CLASS.replace(_CLS, "OtherConfig"))
    rc, out = _run(root)
    assert rc == 1, f"one class, one name — the rule applies:\n{out}"
    _assert_is_a_finding_not_a_crash(out)


def test_an_unparseable_module_is_disclosed_not_dropped(tmp_path):
    """A file that would not parse used to leave the scan without a word while
    the verdict still counted it as scanned — a clean answer over a venue that
    was never read, which is this gate's own defect class one level up."""
    root = tmp_path / "venue"
    root.mkdir(parents=True)
    (root / "a_class.py").write_text(_HEADER + _REGISTRY_SITE)
    (root / "b_site.py").write_text('''"""The omitting site, in a broken module."""
from a_class import PdkConfig


def _omits():
    return PdkConfig(
        name="n", liberty="lib", tech_lef="t", cell_lef="c", site="unit",
        metal_prefix="met", tapcell_distance_um=14.0,
    )


def broken(:
''')
    rc, out = _run(root)
    assert rc == 2, f"a venue that was not fully read is CANNOT-CHECK:\n{out}"
    assert "UNPARSEABLE" in out and "b_site.py" in out, (
        f"the unreadable file must be NAMED:\n{out}")
    _assert_is_a_refusal_not_a_crash(out, "would not parse")


def test_a_missing_root_refuses(tmp_path):
    rc, out = _run(tmp_path / "does-not-exist")
    assert rc == 2 and "not a directory" in out
    assert "Traceback" not in out, out


def test_the_verdict_names_how_the_files_were_enumerated(tmp_path):
    """`filesystem-walk` is legitimate; being unable to TELL is not. A working
    checkout and a tracked enumeration give different file sets for
    byte-identical code."""
    root = _tree(tmp_path, _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    rc, out = _run(root)
    assert rc == 0
    assert "filesystem-walk" in out or "git-tracked" in out, (
        f"the verdict must name its enumeration:\n{out}")


# ---------------------------------------------------------------------------
# THE SUBJECT SHIPS INTO THE TREE IT SCANS.
# ---------------------------------------------------------------------------
def test_the_checkers_own_source_is_not_a_construction_site(tmp_path):
    """The guard names the contracted class in its docstring AND in its
    contract constant. Neither is a call, and a gate that found itself would
    FAIL on the day it landed."""
    root = tmp_path / "venue"
    root.mkdir()
    (root / _GUARD.name).write_text(_GUARD.read_text())
    (root / "resolver.py").write_text(
        _HEADER + _REGISTRY_SITE + _staged_site(declare=True))
    rc, out = _run(root)
    assert rc == 0, f"the guard must not find itself:\n{out}"
    assert all(_GUARD.name not in s["file"]
               for s in mod.audit(root)["sites"]), mod.audit(root)["sites"]


# ---------------------------------------------------------------------------
# THE SHIPPED TREE. Asserts the VERDICT and non-vacuity, never a site count —
# a count is a bet on code that is allowed to change.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def shipped_sweep(tmp_path_factory):
    if not (_PLUGIN_ROOT / "programs").is_dir():
        pytest.skip("no shipped plugin root beside this test")
    out_json = tmp_path_factory.mktemp("sweep") / "rep.json"
    rc, out = _run(_PLUGIN_ROOT, "--json", str(out_json))
    return rc, out, json.loads(out_json.read_text())


def test_the_shipped_plugin_tree_is_clean(shipped_sweep):
    rc, out, rep = shipped_sweep
    assert rc == 0, f"the shipped tree must satisfy its own contract:\n{out}"
    assert rep["omitted"] == []
    assert rep["examined"] > 0, (
        "a PASS over zero construction sites is not a PASS — the contract "
        "would be stale and this assertion is what says so")
    assert rep["files_scanned"] > 0


def test_the_shipped_tree_reports_no_unparseable_file(shipped_sweep):
    """The disclosure is only worth something if the number is real."""
    rc, out, rep = shipped_sweep
    assert rep["unparseable"] == [], rep["unparseable"]
    assert rep["undecidable"] == [], rep["undecidable"]
    assert rc == 0, out
