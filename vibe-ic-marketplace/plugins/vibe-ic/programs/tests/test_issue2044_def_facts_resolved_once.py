"""#2044 — a DEF's physical facts are resolved ONCE, so streamout, LVS and a
fresh OpenROAD session cannot grow independent interpretations of the same file.

WHAT WAS TRUE BEFORE. `phase3_one_shot_runner` carried THREE independent
COMPONENTS readers, each with its own accepted grammar:

  * `_parse_def_components`      — `^COMPONENTS\\b .*? ^END COMPONENTS`, then
                                   `^\\s*-\\s+(\\S+)\\s+(\\S+)` over the match;
  * `_padring_def_components`    — a line state machine keyed on the literal
                                   prefixes `"COMPONENTS "` and `"- "`;
  * `_def_net_orphan_instances`  — `^COMPONENTS\\s+\\d+\\s*;(.*?)^END COMPONENTS\\s*$`.

DEF is a token language: whitespace between tokens is not significant and a
statement may be terminated with a `;` the next reader does not expect. Each
grammar above is significant about a DIFFERENT piece of that whitespace, so the
three CAN return different component sets for one file — and nothing said so.

MEASURED ON THE PRE-FIX TREE (d5be9124d9, 8HD-9), one DEF, three readers:

    -\\tu_a MASTER_A ...       END COMPONENTS ;
    _parse_def_components     -> [(u_a, MASTER_A), (u_b, MASTER_B)]
    _padring_def_components   -> [(u_b, MASTER_B)]              # u_a dropped
    _def_net_orphan_instances -> []  "no COMPONENTS section in DEF"

Three answers. The consequences are not cosmetic: the dropped instance is one
the pad-ring deck then never creates in odb, and the empty read is the same-net
heal's orphan precondition reporting a MEASURED ZERO for a population it in
fact could not read at all.

WHAT IS TRUE NOW. One resolver (`_def_reopen_resolution` /
`_def_resolution_from_text`) produces one frozen `_DefReopenResolution(design,
components)`, and every reader above is a wrapper over it. The design half keeps
`_def_design_name` as THE authority — the resolver calls it; no second
design-name parser exists.

These tests are the both-directions proof:
  * the ambiguous fixtures — one answer, per reader, by VALUE;
  * the unambiguous control — every reader's output is IDENTICAL to the value
    the pre-fix tree produced (recorded here as literals, not as counts);
  * the non-vacuity guard — each reader's own source must still delegate; make
    one of them parse on its own again and these tests re-redden.

Chip/PDK-AGNOSTIC: the fixtures name no design, vendor, PDK or cell library.
"""
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ── the fixtures ─────────────────────────────────────────────────────────
# One unambiguous DEF, and the same DEF perturbed ONLY in whitespace /
# statement termination — every perturbation below is legal DEF, and none of
# them changes which instances the file declares.

_PLAIN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 2 ;
    - u_a MASTER_A + PLACED ( 0 0 ) N ;
    - u_b MASTER_B + PLACED ( 10 0 ) N ;
END COMPONENTS
END DESIGN
"""

# The two components every fixture below declares. This is the ANSWER, and it
# is the answer `_parse_def_components` already gave on the pre-fix tree for
# every one of them — so the fix moves the other two readers ONTO the shipped
# reader's answer and never invents a third.
_EXPECTED = [("u_a", "MASTER_A"), ("u_b", "MASTER_B")]

# A TAB between the entry dash and the instance name. Legal DEF (whitespace is
# whitespace); pre-fix `_padring_def_components` required the two-byte literal
# "- " and silently dropped the entry.
_TAB_AFTER_DASH = _PLAIN.replace("    - u_a MASTER_A", "    -\tu_a MASTER_A")

# A TAB between the COMPONENTS keyword and its count. Pre-fix
# `_padring_def_components` required the literal "COMPONENTS " and never
# entered the section at all -> the whole pad ring read as EMPTY.
_TAB_IN_HEADER = _PLAIN.replace("COMPONENTS 2 ;", "COMPONENTS\t2 ;")

# `END COMPONENTS ;`. Pre-fix `_def_net_orphan_instances` anchored
# `^END COMPONENTS\\s*$` and found no section -> "no COMPONENTS section in DEF",
# i.e. a measured-looking zero for a file it could not read.
_END_TERMINATED = _PLAIN.replace("END COMPONENTS\n", "END COMPONENTS ;\n")

# The COMPONENTS header without its count. Same failure as above for the
# `\\d+`-anchored reader.
_HEADER_NO_COUNT = _PLAIN.replace("COMPONENTS 2 ;", "COMPONENTS ;")

# An entry wrapped across a line break, which DEF permits.
_WRAPPED = _PLAIN.replace("    - u_a MASTER_A + PLACED ( 0 0 ) N ;",
                          "    - u_a\n      MASTER_A + PLACED ( 0 0 ) N ;")

# THE THREE-WAY FIXTURE: two legal perturbations at once. On the pre-fix tree
# this ONE file produced THREE different component sets.
_THREE_WAY = _TAB_AFTER_DASH.replace("END COMPONENTS\n", "END COMPONENTS ;\n")

_AMBIGUOUS = {
    "tab_after_dash": _TAB_AFTER_DASH,
    "tab_in_header": _TAB_IN_HEADER,
    "end_terminated": _END_TERMINATED,
    "header_no_count": _HEADER_NO_COUNT,
    "wrapped_entry": _WRAPPED,
    "three_way": _THREE_WAY,
}


def _reader_a(tmp_path, text, name):
    """`_parse_def_components` — the path-taking reader (fresh-session re-open,
    PERC structural facts, the corpus sweep)."""
    f = tmp_path / (name + "_a.def")
    f.write_text(text)
    return [tuple(t) for t in R._parse_def_components(f)]


def _reader_b(tmp_path, text, name):
    """`_padring_def_components` — the text-taking reader (pad-ring physical
    instance creation, BTerm exclusion)."""
    return [tuple(t) for t in R._padring_def_components(text)]


def _reader_c(tmp_path, text, name):
    """The COMPONENTS half of `_def_net_orphan_instances`, driven through the
    step it belongs to. The function returns (n_orphans, detail); with no NETS
    section every declared instance is an orphan, so the count IS the component
    population and the detail names its denominator."""
    proj = tmp_path / (name + "_c")
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    d = R._pl.pnr_dir(proj)
    d.mkdir(parents=True, exist_ok=True)
    (d / "routed.def").write_text(text)
    return R._def_net_orphan_instances(proj)


_READERS = {
    "_parse_def_components": _reader_a,
    "_padring_def_components": _reader_b,
}


# ── 1. the ambiguous fixtures: ONE answer ────────────────────────────────

@pytest.mark.parametrize("fixture", sorted(_AMBIGUOUS))
@pytest.mark.parametrize("reader", sorted(_READERS))
def test_every_reader_returns_the_same_components(tmp_path, reader, fixture):
    """Every reader in the table returns the SAME component list — by value,
    not by count — for a DEF whose whitespace two of them used to read
    differently."""
    got = _READERS[reader](tmp_path, _AMBIGUOUS[fixture], f"{reader}_{fixture}")
    assert got == _EXPECTED, (
        f"{reader} read {got!r} from the {fixture!r} DEF; the file declares "
        f"{_EXPECTED!r}")


@pytest.mark.parametrize("fixture", sorted(_AMBIGUOUS))
def test_orphan_precondition_sees_the_same_population(tmp_path, fixture):
    """The same-net heal's orphan precondition counts the same instances the
    other readers see. A DEF it cannot read must never reach the caller as a
    measured zero."""
    n, detail = _reader_c(tmp_path, _AMBIGUOUS[fixture], fixture)
    assert n == len(_EXPECTED), (
        f"orphan precondition read {n} placed instances from the {fixture!r} "
        f"DEF ({detail!r}); the file declares {len(_EXPECTED)}")
    assert "no COMPONENTS section in DEF" not in detail


def test_one_def_no_longer_yields_three_answers(tmp_path):
    """The headline: the three-way fixture, all three readers, one answer."""
    a = _reader_a(tmp_path, _THREE_WAY, "hdr")
    b = _reader_b(tmp_path, _THREE_WAY, "hdr")
    n_c, _detail = _reader_c(tmp_path, _THREE_WAY, "hdr")
    assert a == b == _EXPECTED
    assert n_c == len(_EXPECTED)


# ── 2. the control: an unambiguous DEF is handled identically ────────────
#
# The literals below are the values the PRE-FIX tree produced for this exact
# input, recorded per reader. They are not derived from the code under test.

def test_unambiguous_def_reader_a_unchanged(tmp_path):
    assert _reader_a(tmp_path, _PLAIN, "ctl") == [("u_a", "MASTER_A"),
                                                  ("u_b", "MASTER_B")]


def test_unambiguous_def_reader_b_unchanged(tmp_path):
    assert _reader_b(tmp_path, _PLAIN, "ctl") == [("u_a", "MASTER_A"),
                                                  ("u_b", "MASTER_B")]


def test_unambiguous_def_reader_c_unchanged(tmp_path):
    n, detail = _reader_c(tmp_path, _PLAIN, "ctl")
    assert n == 2
    assert detail == "2/2 placed instances participate in no net (MASTER_A x1, MASTER_B x1)"


def test_unambiguous_def_design_name_unchanged(tmp_path):
    f = tmp_path / "ctl_design.def"
    f.write_text(_PLAIN)
    assert R._def_design_name(f) == "chip_top"
    assert R._streamout_top(f, "chip_top") == ("chip_top", "")
    cell, note = R._streamout_top(f, "core")
    assert cell == "chip_top"
    assert "chip_top" in note


def test_def_without_components_still_reads_empty(tmp_path):
    """A DEF with no COMPONENTS block: [] from every reader, as before. The
    ABSENCE of a block and a block that could not be parsed must not have
    become the same thing."""
    text = "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"
    assert _reader_a(tmp_path, text, "empty") == []
    assert _reader_b(tmp_path, text, "empty") == []
    n, detail = _reader_c(tmp_path, text, "empty")
    assert (n, detail) == (0, "no COMPONENTS section in DEF")


def test_unreadable_def_is_not_an_empty_def(tmp_path):
    """An unreadable path resolves to no design and no components without
    raising — the pre-fix contract of every reader in the table."""
    missing = tmp_path / "does_not_exist.def"
    assert R._parse_def_components(missing) == []
    assert R._def_design_name(missing) is None
    assert R._streamout_top(missing, "core") == ("core", "")


# ── 3. the one record, and the design authority ──────────────────────────

def test_resolution_is_one_frozen_record(tmp_path):
    f = tmp_path / "rec.def"
    f.write_text(_THREE_WAY)
    res = R._def_reopen_resolution(f)
    assert isinstance(res.components, tuple)
    assert res.design == R._def_design_name(f)
    assert list(res.components) == _EXPECTED
    with pytest.raises(Exception):
        res.design = "somethingelse"       # frozen


def test_streamout_and_reopen_read_the_same_record(tmp_path):
    """The two facts the issue names — which design is the top, which masters
    are instantiated — come out of ONE resolution of ONE file."""
    f = tmp_path / "both.def"
    f.write_text(_THREE_WAY)
    res = R._def_reopen_resolution(f)
    assert R._streamout_top(f, "core")[0] == res.design
    assert [m for _i, m in R._parse_def_components(f)] == \
           [m for _i, m in res.components]


def test_design_half_has_exactly_one_parser():
    """`_def_design_name` stays THE design-name authority: the resolver calls
    it, and no second DESIGN-line pattern was introduced into the runner.

    Counted structurally (module-level `re.compile` calls whose pattern names
    the DESIGN keyword), not by grepping prose."""
    import ast
    tree = ast.parse(Path(R.__file__).read_text())
    patterns = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compile"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "DESIGN" in node.args[0].value):
            patterns.append(node.args[0].value)
    assert patterns == [r"(?m)^\s*DESIGN\s+(\S+)\s*;"], (
        f"the runner now compiles {len(patterns)} DESIGN-line patterns: "
        f"{patterns!r}")


# ── 4. non-vacuity: each reader must still DELEGATE ──────────────────────

_RESOLVERS = {"_def_reopen_resolution", "_def_resolution_from_text",
              "_def_components_from_text"}


@pytest.mark.parametrize("fn_name", ["_parse_def_components",
                                     "_padring_def_components",
                                     "_def_net_orphan_instances"])
def test_reader_delegates_to_the_shared_resolution(fn_name):
    """Each reader must CALL the shared resolution, not merely mention it.

    Two of the three re-redden the value assertions above the moment they parse
    on their own again. The third — `_parse_def_components` — is the reader
    whose grammar the resolver adopted, so restoring its private parser is
    value-identical and NOTHING above can see it; it would leave the file with
    two copies of one grammar and the next edit to either would re-open the
    divergence silently. That is what this test is for, and it is why the check
    is over the CALL GRAPH and not over the source text: MEASURED — a substring
    check passed the mutation, because the docstring says the word.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(R, fn_name))))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert called & _RESOLVERS, (
        f"{fn_name} calls {sorted(called)!r} and none of them is the shared "
        f"DEF resolution — it parses the DEF on its own again")
