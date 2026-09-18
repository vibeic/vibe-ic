"""Tests for mcp_tool_program_path_resolves_check.py.

WHAT THE GUARD IS FOR.  One MCP tool handler built the path to its gate out
of a directory segment naming a plugin edition this repo retired.  The path
existed in NEITHER shipped layout, so the tool never once ran the program it
is named after, while staying registered, advertised and documented.

WHAT IT DOES NOT COVER, AND WHY THIS FILE SAYS SO OUT LOUD.  The same defect
had a second half — the handler answered "could not run" with a value in the
exit-status domain, so "never started" and "ran and failed" left identical
evidence.  That half needs dataflow this checker does not carry, and every
attempt to approximate it with name heuristics mis-fired on correct code in
this very tree.  It is OUT OF SCOPE, and `test_the_collapse_is_not_this_gates
_business` asserts that a PASS here is not a statement about it, so nobody
reads a green as covering it.

WHAT MAKES THIS FILE A TEST AND NOT A CEREMONY.  Every rule is exercised in
BOTH directions against the SAME tree: the defective shape must FAIL and must
NAME the file, the line and the resolved path — and the corrected shape,
differing only in the defect, must PASS.  An assertion that holds in both
directions proves nothing, so the control arms are as load-bearing as the
positive ones.

The prose-immunity arms are the third direction.  The guard reads source
text, so a token in a comment or inside a string literal must be unable to
create a finding or to clear one; both are asserted.

The fourth direction is the SCOPE.  Each conjunct that narrows the rule gets
a pair: the shape the conjunct excludes must not FAIL, and the shape just
outside it must still be decided.  A scope cut asserted only on the side it
excludes is a hole nobody measured.

WHAT CHANGED IN THE LAST ROUND, AND WHAT THE NEW ARMS ARE FOR.

  * A WRITE IS A WRITE, WHATEVER SPELLED IT.  Sites were collected off
    `const` declarations alone, so changing that ONE TOKEN to `let` took rc
    from 1 to 0 *and deleted the site from the report* — no finding, no
    undecided row, nothing to notice.  `test_string_concatenation_builds_a
    _path_this_gate_reads` now runs all six spellings (`const`, `let`,
    `var`, bare assignment, `export const`, `export let`) in both
    directions, and `test_the_prefix_keyword_does_not_hide_the_site_either`
    is the arm that stops the same disarm moving one line up onto the
    PREFIX declaration.  `test_an_rhs_this_evaluator_cannot_read_is_named
    _not_dropped` covers the object literal and the class field: whichever
    verdict they get, the site must APPEAR.
    The (A) arm that pays for it is `test_a_name_some_other_line_rewrites
    _binds_nothing` — `let` and `var` REBIND, so a name a second line
    rewrites must bind nothing at all, or the statement-form layout probe
    (`let dir = <absent>; if (!existsSync(dir)) dir = <live>;`) would be
    failed on a path it never computes.
  * NEVER RESOLVE THROUGH A BRANCH.  The guard used to walk `||` / `??`
    chains and take the first alternative that named an EXISTING path.  In
    JS the non-empty LEFT operand wins, so that model was backwards: a
    one-line `|| <fallback>` appended to a dead path either made the site
    VANISH from the report or printed it as DECIDED and RESOLVED to a path
    the running code never computes.  `test_a_branch_is_undecided_and_named
    _never_resolved` asserts the required answer for all four spellings —
    undecided, counted, named, and in NO decided entry — and
    `test_the_unbranched_dead_path_is_the_control` is the arm that keeps
    the exemption honest.  Two further controls
    (`test_a_question_mark_in_prose_is_not_a_branch`,
    `test_optional_chaining_is_not_a_ternary`) pin the branch test to CODE.
  * AN ABSENT MEMBER OF A PRESENT DIRECTORY IS NOT DECIDED (conjunct 7).
    `programs/optional_extra.py` missing while `programs/` is right there
    is what an optional program, a guarded read and a file written on first
    use all look like; detecting the guard needs dataflow this checker does
    not carry, so the venue is narrowed instead.  Its control arm is the
    identical file name under a directory the tree does NOT have — which is
    the historical defect and still a finding.
  * A DERIVED TREE IS NOT DECIDED (conjunct 8) — `vendor/`, `.venv/`,
    `build/generated/`.  Same pairing.

WHY THE SHIPPED-TREE ARMS LOOK DIFFERENT NOW.  The server builds every
program path out of a directory it chooses at RUNTIME
(`process.env.… || <probe> || <fallback>`), so after the change above this
checker decides NONE of the shipped sites.  `test_current_tree_is_clean` no
longer asserts a resolved count it cannot honestly have;
`test_the_pass_line_never_claims_more_than_it_decided` asserts the verdict
line leads with the DECIDED count instead of "every program path resolves";
and `test_current_tree_still_discriminates` INJECTS the historical defect
into a copy of the real sources rather than deleting a program, because
deleting a program is now (deliberately) undecided.

WHERE THESE TWO FILES HAVE TO SIT.  The guard is located as
`_TESTS_DIR.parent / "<guard>.py"` and the tree it checks as
`_TESTS_DIR.parent.parent`, i.e. the SHIPPED layout:
`programs/mcp_tool_program_path_resolves_check.py` and
`programs/tests/test_mcp_tool_program_path_resolves_check.py`.  Flat in one
directory, collection itself fails.  `test_current_tree_is_clean` and
`test_current_tree_still_discriminates` SKIP when `<plugin root>/mcp-eda/src`
is absent, so a green run must be checked for those skips.

NO RETIRED-PLUGIN TOKEN IS WRITTEN HERE.  The fixtures use a neutral dead
segment.  The rule is "this path resolves nowhere", not "this path spells a
particular name", so neutralising it does not weaken the test.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_PROGRAMS = _TESTS_DIR.parent
_PLUGIN_ROOT = _PROGRAMS.parent
_GUARD = _PROGRAMS / "mcp_tool_program_path_resolves_check.py"

_MODNAME = "_mcp_tool_program_path_resolves_check_under_test"


def _load():
    spec = importlib.util.spec_from_file_location(_MODNAME, _GUARD)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module: @dataclass resolves its annotations through
    # sys.modules[cls.__module__], and a module that is not yet registered
    # makes the decorator raise on import.
    sys.modules[_MODNAME] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()

RC_PASS, RC_FAIL, RC_CANNOT = 0, 1, 2

# --------------------------------------------------------------------------
# A neutral segment that exists in no layout.  Assembled, so that no tool
# searching this repo for a path-shaped literal mistakes the fixture for one.
# --------------------------------------------------------------------------
DEAD_SEGMENT = "retired" + "-" + "edition"


# ==========================================================================
# Fixture builder: the smallest tree the guard reads
# ==========================================================================

_HEADER = """
import { existsSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";
const __dirname_eda = dirname(fileURLToPath(import.meta.url));
const _programsCandidates = [
  resolve(__dirname_eda, "..", "..", "programs"),
  resolve(__dirname_eda, "..", "..", "..", "%(dead)s", "programs"),
];
const VIBE_IC_PROGRAMS_DIR = process.env.VIBE_IC_PROGRAMS_DIR
  || _programsCandidates.find(existsSync)
  || _programsCandidates[0];
const PROGRAMS_DIR = resolve(__dirname_eda, "..", "..", "programs");
const LEGACY_PROGRAMS = resolve(__dirname_eda, "..", "..", "%(dead)s",
                                "programs");
"""


def _tree(tmp_path: Path, handler_js: str, header: str = None,
          programs=("real_gate.py",)) -> Path:
    """Build <root>/programs/*.py plus <root>/mcp-eda/src/index.js."""
    root = tmp_path / "plug"
    (root / "programs").mkdir(parents=True)
    for name in programs:
        (root / "programs" / name).write_text("# a real program\n")
    src = root / "mcp-eda" / "src"
    src.mkdir(parents=True)
    head = (header if header is not None else _HEADER) % {"dead": DEAD_SEGMENT}
    (src / "index.js").write_text(head + handler_js)
    return root


def _run(root: Path):
    """Run the guard as the CLI a caller actually invokes."""
    return subprocess.run(
        [sys.executable, str(_GUARD), str(root), "--json", "-"],
        capture_output=True, text=True, timeout=300)


def _payload(res) -> dict:
    """The `--json -` document, decoded off the FRONT of stdout.

    Scanning to the last `}` in the output was wrong once the human-readable
    lines started quoting source expressions: a `${Date.now()}` in a reported
    expression carries a brace, and the slice then ran past the end of the
    document.  `raw_decode` stops where the document stops.
    """
    text = res.stdout[res.stdout.index("{"):]
    obj, _end = json.JSONDecoder().raw_decode(text)
    return obj


def _rules(res) -> set:
    return {f["rule"] for f in _payload(res)["findings"]}


# ==========================================================================
# The pre-fix shape, reconstructed
# ==========================================================================

_PREFIX_HANDLER = """
server.tool(
  "eda_completion_audit",
  "Run the completion gate.",
  { project_dir: z.string() },
  async ({ project_dir }) => {
    const path = await import("path");
    const here = path.dirname(new URL(import.meta.url).pathname);
    const gate = path.resolve(here, "..", "..", "%(dead)s", "programs",
                              "real_gate.py");
    let output, exitCode;
    {
      const r = _spawnSync("python3", [gate, project_dir, "--json", "-"], {
        encoding: "utf-8", timeout: 300000,
      });
      output = (r.stdout || "") + (r.stderr || "");
      exitCode = r.error ? 1 : (r.status ?? 1);
    }
    let parsed;
    try { parsed = JSON.parse(output); } catch { parsed = { raw_output: output }; }
    return { content: [{ type: "text", text: JSON.stringify({
      ...parsed, exit_code: exitCode, audit_complete: exitCode === 0,
    }, null, 2) }] };
  },
);
"""

#: The SAME handler with the dead segment removed and nothing else changed.
_FIXED_HANDLER = _PREFIX_HANDLER.replace(
    '"..", "..", "%(dead)s", "programs",\n                              "real_gate.py"',
    '"..", "..", "programs", "real_gate.py"')


def test_prefix_shape_fails_and_names_the_site(tmp_path):
    """POSITIVE — the real pre-fix handler, reported at its own line."""
    root = _tree(tmp_path, _PREFIX_HANDLER % {"dead": DEAD_SEGMENT})
    res = _run(root)
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    (finding,) = _payload(res)["findings"]
    assert finding["rule"] == "program-path-does-not-resolve"
    assert finding["file"] == "mcp-eda/src/index.js"
    lines = (root / "mcp-eda" / "src" / "index.js").read_text().splitlines()
    assert "path.resolve(here" in lines[finding["line"] - 1]
    assert DEAD_SEGMENT in finding["message"]
    assert "real_gate.py" in finding["message"]
    assert "mcp-eda/src/index.js:%d:" % finding["line"] in res.stdout


def test_fixed_shape_passes(tmp_path):
    """CONTROL — same handler, only the dead segment gone."""
    res = _run(_tree(tmp_path, _FIXED_HANDLER))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["resolved"] >= 1


def test_the_collapse_is_not_this_gates_business(tmp_path):
    """SCOPE — `r.error ? 1 : (r.status ?? 1)` is NOT decided here.

    It is the other half of the same historical defect and it is a real
    invariant, but deciding it needs dataflow this checker does not carry.
    The gate must therefore stay SILENT about it rather than guess: the
    fixed-path handler still carries the collapse verbatim and must PASS,
    and no finding may mention it.  If a later change starts flagging this
    shape, this test goes red and the docstring's claim has to be revisited.
    """
    root = _tree(tmp_path, _FIXED_HANDLER)
    src = (root / "mcp-eda" / "src" / "index.js").read_text()
    assert "r.error ? 1 : (r.status ?? 1)" in src, "fixture lost the collapse"
    res = _run(root)
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["findings"] == []


# ==========================================================================
# The dead path, in isolation — both arms
# ==========================================================================

_DEAD_PATH_ONLY = """
server.tool(
  "eda_thing", "d", { p: z.string() },
  async ({ p }) => {
    const gate = resolve(__dirname_eda, "..", "..", "%(dead)s", "programs",
                         "real_gate.py");
    const r = _spawnSync("python3", [gate, p], { encoding: "utf-8" });
    return { content: [{ type: "text", text: r.stdout || "" }] };
  },
);
"""

_LIVE_PATH_ONLY = _DEAD_PATH_ONLY.replace(
    '"..", "..", "%(dead)s", "programs",\n                         "real_gate.py"',
    '"..", "..", "programs", "real_gate.py"')


def test_dead_path_fails_and_names_file_line_and_resolved_path(tmp_path):
    root = _tree(tmp_path, _DEAD_PATH_ONLY % {"dead": DEAD_SEGMENT})
    res = _run(root)
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    (finding,) = _payload(res)["findings"]
    lines = (root / "mcp-eda" / "src" / "index.js").read_text().splitlines()
    assert "resolve(__dirname_eda" in lines[finding["line"] - 1]
    assert DEAD_SEGMENT in finding["message"]


def test_live_path_passes(tmp_path):
    res = _run(_tree(tmp_path, _LIVE_PATH_ONLY))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["resolved"] >= 1


def test_template_literal_path_is_evaluated(tmp_path):
    """A `${dir}/name.py` template is a path expression, not opaque text."""
    bad = ('\nserver.tool("t", "d", { p: z.string() }, async ({ p }) => {\n'
           '  const args = [`${LEGACY_PROGRAMS}/real_gate.py`, p];\n'
           '  return { content: [{ type: "text", text: args[0] }] };\n'
           '});\n')
    good = bad.replace("LEGACY_PROGRAMS", "PROGRAMS_DIR")
    r_bad = _run(_tree(tmp_path / "a", bad))
    r_good = _run(_tree(tmp_path / "b", good))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout
    assert DEAD_SEGMENT in r_bad.stdout
    assert r_good.returncode == RC_PASS, r_good.stdout + r_good.stderr
    assert [d for d in _payload(r_good)["decided"]
            if d["resolved"].endswith("/real_gate.py")]


@pytest.mark.parametrize("write", ["const gate =", "let gate =", "var gate =",
                                   "gate =", "export const gate =",
                                   "export let gate ="])
def test_string_concatenation_builds_a_path_this_gate_reads(tmp_path, write):
    """`DIR + "/gate.py"` has no join() and no template — and the KEYWORD in
    front of the `=` has nothing to do with what the RHS builds.

    REGRESSION.  Collecting these sites off `const` alone meant that
    changing that ONE TOKEN to `let` took rc from 1 to 0 *and deleted the
    site from the report* — no finding, no undecided row, nothing.  A
    disarm that erases the site is strictly worse than a disclosed blind
    spot, so all six spellings are asserted in both directions."""
    bad = ('\nserver.tool("t", "d", {}, async () => {\n'
           '  %s LEGACY_PROGRAMS + "/real_gate.py";\n'
           '  return { content: [{ type: "text", text: gate }] };\n'
           '});\n') % write
    good = bad.replace("LEGACY_PROGRAMS", "PROGRAMS_DIR")
    r_bad = _run(_tree(tmp_path / "a", bad))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout
    assert DEAD_SEGMENT in r_bad.stdout
    r_good = _run(_tree(tmp_path / "b", good))
    assert r_good.returncode == RC_PASS, r_good.stdout + r_good.stderr
    assert [d for d in _payload(r_good)["decided"]
            if d["resolved"].endswith("/real_gate.py")], r_good.stdout


@pytest.mark.parametrize("kw", ["const", "let", "var"])
def test_the_prefix_keyword_does_not_hide_the_site_either(tmp_path, kw):
    """CONTROL for the one above — the disarm must not simply move one line
    up.  Binding only `const` names meant respelling the PREFIX declaration
    `let` un-bound it, the gate expression became UNKNOWN, and pattern 4
    dropped the site.  A name written ONCE is bound whatever declared it."""
    js = ('\n%s pdir = __dirname_eda + "/../../%s/programs";\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  const gate = pdir + "/real_gate.py";\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % (kw, DEAD_SEGMENT)
    r_bad = _run(_tree(tmp_path / "a", js))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout
    assert DEAD_SEGMENT in r_bad.stdout
    r_good = _run(_tree(tmp_path / "b",
                        js.replace("/../../%s/programs" % DEAD_SEGMENT,
                                   "/../../programs")))
    assert r_good.returncode == RC_PASS, r_good.stdout + r_good.stderr
    assert [d for d in _payload(r_good)["decided"]
            if d["resolved"].endswith("/real_gate.py")], r_good.stdout


@pytest.mark.parametrize("rhs,label", [
    ('let d = %s + "/programs"; d = pickDir(d);', "reassigned to an unknown"),
    ('let d = %s + "/programs"; if (!x) { d = "/other"; }', "probed and replaced"),
    ('let d = %s; d += "/programs";', "built up with +="),
])
def test_a_name_some_other_line_rewrites_binds_nothing(tmp_path, rhs, label):
    """(A) — `let dir = <absent>; if (!existsSync(dir)) dir = <live>;` is a
    LAYOUT PROBE written as statements, i.e. WORKING code.  Reading `let`
    and `var` without also vetoing on the second write would bind the
    probe's first arm and fail the handler on a path it never computes.
    Every write must agree on one definite string or the name is dropped."""
    js = ('\n' + rhs % ('__dirname_eda + "/../../%s"' % DEAD_SEGMENT) + '\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  const gate = d + "/real_gate.py";\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, f"{label}: {res.stdout}{res.stderr}"
    payload = _payload(res)
    assert payload["findings"] == [], label
    assert [u for u in payload["undecided"] if "real_gate.py" in u["expr"]], \
        f"{label}: the site VANISHED — a rebound name must still be counted"


@pytest.mark.parametrize("body,label", [
    ('const o = { gate: LEGACY_PROGRAMS + "/real_gate.py" };', "object literal"),
    ('class G { gate = LEGACY_PROGRAMS + "/real_gate.py"; }', "class field"),
])
def test_an_rhs_this_evaluator_cannot_read_is_named_not_dropped(tmp_path,
                                                                body, label):
    """A path buried in a shape the evaluator does not model must still
    APPEAR.  The class field evaluates — it is a plain write — so it is a
    FINDING; the object literal does not, so it is UNDECIDED and printed.
    Either answer is honest; a site that vanishes is the hole."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n  %s\n'
           '  return { content: [{ type: "text", text: "x" }] };\n'
           '});\n') % body
    res = _run(_tree(tmp_path, js))
    payload = _payload(res)
    named = [r for r in payload["findings"] + payload["undecided"]
             if "real_gate.py" in (r.get("expr") or r.get("message", ""))]
    assert named, f"{label}: the site VANISHED from the report\n{res.stdout}"


def test_a_hoisted_program_name_does_not_hide_the_site(tmp_path):
    """The decision is on the EVALUATED value, not on where the `.py`
    literal sits: hoisting the name into a `const` one line up is a
    one-line refactor and must not delete the site."""
    bad = ('\nserver.tool("t", "d", {}, async () => {\n'
           '  const GATE_NAME = "real_gate.py";\n'
           '  const gate = join(LEGACY_PROGRAMS, GATE_NAME);\n'
           '  return { content: [{ type: "text", text: gate }] };\n'
           '});\n')
    good = bad.replace("LEGACY_PROGRAMS", "PROGRAMS_DIR")
    r_bad = _run(_tree(tmp_path / "a", bad))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout
    assert "GATE_NAME" in r_bad.stdout
    assert _run(_tree(tmp_path / "b", good)).returncode == RC_PASS


def test_a_hex_escaped_spelling_of_a_live_path_is_not_a_finding(tmp_path):
    r"""REGRESSION — `"real\x5Fgate.py"` is a legal spelling of a path that
    EXISTS.  A decoder that dropped the `\x` and kept the digits produced
    `realx5Fgate.py` and the gate called a live program dead: a wrong
    verdict on working code, which is the one thing it must never do."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = join(PROGRAMS_DIR, "real\\x5Fgate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["resolved"] >= 1


# ==========================================================================
# SCOPE — each conjunct, from BOTH sides
# ==========================================================================

def test_a_container_path_is_not_resolved_against_the_host(tmp_path):
    """SCOPE — a path on a hard-coded absolute prefix names another
    filesystem.  The whole plugin runs its EDA tools inside an image; a
    verdict about that image's contents would be a statement about the
    wrong machine."""
    js = ('\nconst TOOLS = "/foss/tools";\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  const deck = `${TOOLS}/openroad/scripts/mk_deck.py`;\n'
          '  return { content: [{ type: "text", text: deck }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["findings"] == []
    (u,) = [x for x in _payload(res)["undecided"] if "mk_deck.py" in x["expr"]]
    assert "hard-coded absolute prefix" in u["why"]


def test_an_own_tree_path_is_still_decided(tmp_path):
    """CONTROL for the conjunct above — the SAME dead file name, rooted at
    this source instead of at a container.  Without this arm the exclusion
    could be swallowing everything."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const deck = join(__dirname_eda, "..", "..", "%(dead)s",'
          ' "mk_deck.py");\n'
          '  return { content: [{ type: "text", text: deck }] };\n'
          '});\n') % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "mk_deck.py" in res.stdout


def test_climbing_further_up_does_not_escape_the_rule(tmp_path):
    """SCOPE — rooting follows the expression, not the resolved location.
    One more `".."` climbs above the plugin but is still rooted here, so
    adding one must not buy a green."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = resolve(__dirname_eda, "..", "..", "..", "..",\n'
          '                       "%(dead)s", "programs", "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


def test_a_candidate_list_with_one_live_member_is_not_a_finding(tmp_path):
    """SCOPE — a list of paths is a list of ALTERNATIVES.  This is the
    shape the shipped server uses to find its programs across layouts, and
    a member that is absent is exactly what the list is written for."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const cands = [join(LEGACY_PROGRAMS, "real_gate.py"),\n'
          '                 join(PROGRAMS_DIR, "real_gate.py")];\n'
          '  const chosen = cands.find(existsSync);\n'
          '  return { content: [{ type: "text", text: chosen }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["findings"] == []


def test_a_candidate_list_with_no_live_member_still_fails(tmp_path):
    """CONTROL — when EVERY alternative is decided and every one is dead
    the probe falls through on every machine, so the exclusion lifts.
    Without this arm, writing a second dead path beside the first would
    buy a green."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const cands = [join(LEGACY_PROGRAMS, "absent_a.py"),\n'
          '                 join(LEGACY_PROGRAMS, "absent_b.py")];\n'
          '  const chosen = cands.find(existsSync);\n'
          '  return { content: [{ type: "text", text: chosen }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "absent_a.py" in res.stdout and "absent_b.py" in res.stdout


def test_an_argv_list_is_not_an_alternation(tmp_path):
    """CONTROL — a list holding ONE path is a spawn's argv, and that path
    must exist.  Treating every list member as an alternative silently
    exempted every `[script, dir, "--json"]` in the server."""
    js = ('\nserver.tool("t", "d", { p: z.string() }, async ({ p }) => {\n'
          '  const r = _spawnSync("python3",\n'
          '    [join(LEGACY_PROGRAMS, "absent_gate.py"), p, "--json"],\n'
          '    { encoding: "utf-8" });\n'
          '  return { content: [{ type: "text", text: r.stdout || "" }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "absent_gate.py" in res.stdout


def test_a_live_path_in_an_argv_list_is_DECIDED_not_merely_unflagged(tmp_path):
    """CONTROL for the arm above, from the other side.

    A rule that quietly moved every list member into the undecided pile
    would still pass the arm above (a dead single-member list is unflagged
    either way) while silently exempting every `[script, dir, "--json"]` in
    the server.  So assert the POSITIVE: the live one is counted as decided
    and the report names it.
    """
    js = ('\nserver.tool("t", "d", { p: z.string() }, async ({ p }) => {\n'
          '  const r = _spawnSync("python3",\n'
          '    [join(PROGRAMS_DIR, "real_gate.py"), p, "--json"],\n'
          '    { encoding: "utf-8" });\n'
          '  return { content: [{ type: "text", text: r.stdout || "" }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    decided = _payload(res)["decided"]
    assert [d for d in decided if d["resolved"].endswith("/real_gate.py")], \
        "the argv's script was not decided: " + res.stdout


def test_a_template_climbing_out_of_the_sources_is_still_judged(tmp_path):
    """`join`/`resolve` normalise their result; a template and a `+` chain
    do not, so the same path arrives spelled two ways.  Comparing the
    UN-normalised spelling against the server's own source directory said a
    path climbing out of it with `../..` was still inside it — and rewriting
    the expression as a template then bought a green on a dead path."""
    bad = ('\nserver.tool("t", "d", {}, async () => {\n'
           '  const gate = `${__dirname_eda}/../../%(dead)s/real_gate.py`;\n'
           '  return { content: [{ type: "text", text: gate }] };\n'
           '});\n') % {"dead": DEAD_SEGMENT}
    good = bad.replace("/" + DEAD_SEGMENT + "/", "/programs/")
    r_bad = _run(_tree(tmp_path / "a", bad))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout + r_bad.stderr
    assert DEAD_SEGMENT in r_bad.stdout
    r_good = _run(_tree(tmp_path / "b", good))
    assert r_good.returncode == RC_PASS, r_good.stdout + r_good.stderr
    assert [d for d in _payload(r_good)["decided"]
            if d["resolved"].endswith("/real_gate.py")]


def test_a_py_inside_the_servers_own_sources_is_out_of_scope(tmp_path):
    """SCOPE — the server's own source directory is the helper area it
    manages: it reads helpers there at startup and generates others.  A
    gate that demanded a generator's own output already exist would fire
    on every correct generator."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gen = join(__dirname_eda, "lib", "generated_deck.py");\n'
          '  writeFileSync(gen, "x");\n'
          '  return { content: [{ type: "text", text: gen }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    (u,) = [x for x in _payload(res)["undecided"]
            if "generated_deck.py" in x["expr"]]
    assert "own source directory" in u["why"]


def test_the_same_name_outside_the_sources_is_decided(tmp_path):
    """CONTROL for the conjunct above — identical file name, one directory
    out of the server's own sources."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gen = join(__dirname_eda, "..", "..", "%(dead)s",\n'
          '                   "generated_deck.py");\n'
          '  return { content: [{ type: "text", text: gen }] };\n'
          '});\n') % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "generated_deck.py" in res.stdout


def test_a_name_bound_both_to_the_own_dir_and_to_a_literal_refuses(tmp_path):
    """A contradiction this checker cannot resolve is CANNOT-CHECK.

    Preferring the anchor can flag a path the flagged line never computes;
    preferring the literal lets ONE inserted declaration silence a real
    finding.  Neither is acceptable, so the run refuses — and rc=2 is not a
    pass, which is what stops the insertion from buying a green.
    """
    js = ('\nconst here = "/foss/tools";\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  const here2 = dirname(fileURLToPath(import.meta.url));\n'
          '  const gate = resolve(here2, "..", "..", "%(dead)s", "programs",\n'
          '                       "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % {"dead": DEAD_SEGMENT}
    # `here` is bound to the own dir by the header and to a literal here.
    head = _HEADER + 'const here = dirname(fileURLToPath(import.meta.url));\n'
    root = _tree(tmp_path, js, header=head)
    res = _run(root)
    assert res.returncode == RC_CANNOT, res.stdout + res.stderr
    assert _payload(res)["status"] == "CANNOT_CHECK"
    assert "here" in _payload(res)["cannot_check_reason"]
    assert "[REFUSE]" in res.stdout


def test_without_the_contradiction_the_same_tree_is_decided(tmp_path):
    """CONTROL — the same handler, with the contradicting declaration
    removed.  The refusal must be caused by the contradiction and by
    nothing else."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const here2 = dirname(fileURLToPath(import.meta.url));\n'
          '  const gate = resolve(here2, "..", "..", "%(dead)s", "programs",\n'
          '                       "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


# ==========================================================================
# Blind spots are PRINTED, never dropped
# ==========================================================================

def test_every_undecided_site_is_named_not_merely_counted(tmp_path):
    """A blind spot that is only a number can swallow a whole tool."""
    js = ('\nserver.tool("t", "d", { p: z.string() }, async ({ p }) => {\n'
          '  const stamp = Date.now();\n'
          '  const gate = `${VIBE_IC_PROGRAMS_DIR}/gen_${stamp}.py`;\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    root = _tree(tmp_path, js)
    res = _run(root)
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    (u,) = [x for x in payload["undecided"] if "gen_" in x["expr"]]
    lines = (root / "mcp-eda" / "src" / "index.js").read_text().splitlines()
    assert "gen_${stamp}.py" in lines[u["line"] - 1]
    assert f"{u['file']}:{u['line']}: [undecided]" in res.stdout


def test_a_builder_under_another_name_is_disclosed_not_dropped(tmp_path):
    """The rule only reads calls spelled `join` / `resolve`.  Aliasing the
    builder therefore defeats the DECISION — but it must not defeat the
    REPORT: a call carrying a program filename as its own argument is
    collected and printed as undecided, so a tool the checker stopped
    looking at cannot leave a green with no signal at all."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const R = resolveAlias;\n'
          '  const gate = R(__dirname_eda, "..", "..", "programs",\n'
          '                 "absent_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    (u,) = [x for x in _payload(res)["undecided"]
            if "absent_gate.py" in x["expr"]]
    assert f"{u['file']}:{u['line']}: [undecided]" in res.stdout


def test_a_helper_dispatch_is_disclosed_not_dropped(tmp_path):
    """Same requirement for the other way out: handing a bare program NAME
    to a helper that builds the path from its own parameter."""
    js = ('\nfunction _runPy(n, args) { return _spawnSync("python3", [n]); }\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  _runPy("absent_gate.py", []);\n'
          '  return { content: [] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert [x for x in _payload(res)["undecided"]
            if "absent_gate.py" in x["expr"]]


@pytest.mark.parametrize("kw", ["const", "let", "var"])
def test_the_anchor_and_the_candidate_array_read_every_keyword(tmp_path, kw):
    """The own-dir ANCHOR and the candidate-ARRAY bindings come off the same
    write set as everything else.  Keying either on `const` alone let one
    token un-bind the name: the expression dropped to UNKNOWN and rc went
    from 1 to 0 — the same disarm, one step further back."""
    header = ('\nimport { dirname } from "path";\n'
              'import { fileURLToPath } from "url";\n'
              '%s __dirname_eda = dirname(fileURLToPath(import.meta.url));\n'
              '%s cands = [__dirname_eda + "/../../%s/programs",\n'
              '            __dirname_eda + "/../../%s/b/programs"];\n')
    bad = header % (kw, kw, DEAD_SEGMENT, DEAD_SEGMENT)
    good = header % (kw, kw, ".", ".")
    js = ('server.tool("t", "d", {}, async () => {\n'
          '  const gate = cands[0] + "/real_gate.py";\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    r_bad = _run(_tree(tmp_path / "a", js, header=bad))
    assert r_bad.returncode == RC_FAIL, r_bad.stdout + r_bad.stderr
    assert DEAD_SEGMENT in r_bad.stdout
    r_good = _run(_tree(tmp_path / "b", js, header=good))
    assert r_good.returncode == RC_PASS, r_good.stdout + r_good.stderr
    assert [d for d in _payload(r_good)["decided"]
            if d["resolved"].endswith("/real_gate.py")], r_good.stdout


def test_a_parameter_default_supplies_no_value_but_keeps_its_site(tmp_path):
    """(A) — a JS parameter default is a PARAMETER, and BINDINGS says a
    parameter is never bound.  Reading every `NAME =` as a binding made
    `async ({ pdir = <absent layout> })` FAIL a handler whose callers pass
    a live directory.  It must be undecided — and still COUNTED, which is
    what `const`-only collection never managed for this shape."""
    js = ('\nserver.tool("t", "d", {}, async ({ pdir = LEGACY_PROGRAMS }) => {\n'
          '  const gate = pdir + "/real_gate.py";\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == []
    assert [u for u in payload["undecided"] if "real_gate.py" in u["expr"]], \
        f"the site VANISHED\n{res.stdout}"


def test_a_sentence_mentioning_a_program_is_not_a_site(tmp_path):
    """CONTROL for the two arms above — the disclosure rule must key on a
    FILENAME-shaped literal, not on any string containing `.py`.  A tool
    description is prose."""
    js = ('\nserver.tool("t", "this tool runs absent_gate.py for you", {},\n'
          '  async () => ({ content: [] }));\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["program_path_sites"] == 0


# ==========================================================================
# NEVER RESOLVE THROUGH A BRANCH — the round-4 blocker, from both sides
# ==========================================================================

_DEAD_CONCAT = 'LEGACY_PROGRAMS + "/real_gate.py"'
_LIVE_CONCAT = 'PROGRAMS_DIR + "/real_gate.py"'


def _branch_tree(tmp_path, rhs):
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = %s;\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % rhs
    return _tree(tmp_path, js)


def test_the_unbranched_dead_path_is_the_control(tmp_path):
    """CONTROL for every arm below.  The SAME declaration with no branch
    is a FINDING, so the exemptions below are caused by the branch and by
    nothing else."""
    res = _run(_branch_tree(tmp_path, _DEAD_CONCAT))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


@pytest.mark.parametrize("rhs,label", [
    (f'{_DEAD_CONCAT} || (__dirname_eda + "/../../programs")', "|| a directory"),
    (f'{_DEAD_CONCAT} || ({_LIVE_CONCAT})', "|| a live path"),
    (f'{_DEAD_CONCAT} ?? ({_LIVE_CONCAT})', "?? a live path"),
    (f'true ? ({_LIVE_CONCAT}) : ({_DEAD_CONCAT})', "a ternary"),
])
def test_a_branch_is_undecided_and_named_never_resolved(tmp_path, rhs, label):
    """THE BLOCKER.  Each of these is a ONE-LINE edit to the dead
    declaration above, and each one used to do something worse than lose
    the finding:

      * `|| <directory>` made the site VANISH — the chain evaluated to a
        directory, the declaration stopped looking like a program path, and
        the run reported one fewer place it had looked with no signal.
      * `|| <live path>` and `?? <live path>` printed the site as DECIDED
        and RESOLVED to the live path.  In JS the non-empty left operand
        wins, so the handler spawns the DEAD one: a green CERTIFICATE for a
        path the running code never computes.

    The required behaviour is neither: the site is UNDECIDED, it is
    counted, it is printed with the branch named as the reason, and it
    appears in NO decided entry.
    """
    root = _branch_tree(tmp_path, rhs)
    res = _run(root)
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == []
    hits = [u for u in payload["undecided"] if "real_gate.py" in u["expr"]]
    assert hits, f"{label}: the site VANISHED from the report\n" + res.stdout
    for u in hits:
        assert "BRANCHES" in u["why"], u["why"]
        assert f"{u['file']}:{u['line']}: [undecided]" in res.stdout
    assert not [d for d in payload["decided"] if "real_gate.py" in d["expr"]], \
        f"{label}: the branch was RESOLVED — a false green certificate"


@pytest.mark.parametrize("kw", ["const", "let", "var"])
def test_the_branch_test_does_not_care_which_keyword_declared_it(tmp_path, kw):
    """CONTROL — whether a name is `const`, `let` or `var` has nothing to do
    with whether its initialiser branches.  Keying the span scan on `const`
    alone left `let gate = <dead> || <live>;` resolving through the branch,
    which is the same hole under a different keyword."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  %s gate = %s || (%s);\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % (kw, _DEAD_CONCAT, _LIVE_CONCAT)
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == []
    assert [u for u in payload["undecided"] if "BRANCHES" in u["why"]], res.stdout
    assert not [d for d in payload["decided"] if "real_gate.py" in d["expr"]]


def test_a_branch_over_a_probe_is_undecided_too(tmp_path):
    """`[p].find(existsSync) || fallback` is a probe with a fallback, i.e.
    WORKING code: at runtime `find` returns undefined and the fallback is
    what spawns.  Deciding the probed member would be a wrong verdict, and
    deciding the fallback would certify the wrong operand, so the whole
    initialiser is undecided."""
    rhs = f'[{_DEAD_CONCAT}].find(existsSync) || ({_LIVE_CONCAT})'
    res = _run(_branch_tree(tmp_path, rhs))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert [u for u in _payload(res)["undecided"] if "BRANCHES" in u["why"]]


def test_a_comment_inside_the_expression_is_not_a_branch(tmp_path):
    """CONTROL — the branch test is LEXICAL, so it must run on the MASKED
    source.  This puts the prose INSIDE the very span the test reads: a
    block comment between the builder's own parentheses.  Reading the raw
    bytes there would let a sentence buy the exemption."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = join(LEGACY_PROGRAMS,\n'
          '                    /* which layout? this one || that one ?? */\n'
          '                    "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


def test_a_string_inside_the_declaration_is_not_a_branch(tmp_path):
    """CONTROL — same requirement for a STRING literal.  The branch tokens
    sit inside the declaration whose initialiser the test reads, and string
    CONTENT is masked, so they are not there to be seen."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = join(LEGACY_PROGRAMS, "real_gate.py"),\n'
          '        note = "pick a ? b : c || d ?? e";\n'
          '  return { content: [{ type: "text", text: gate + note }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


@pytest.mark.parametrize("rhs,label", [
    ("LEGACY_PROGRAMS || PROGRAMS_DIR", "||"),
    ("LEGACY_PROGRAMS ?? PROGRAMS_DIR", "??"),
    ("existsSync(LEGACY_PROGRAMS) ? LEGACY_PROGRAMS : PROGRAMS_DIR", "? :"),
])
def test_a_branch_never_supplies_a_BINDING_either(tmp_path, rhs, label):
    """THE SAME BLOCKER, one level down.

    The path expression here does not branch — `join(CHOSEN, "...")` is as
    plain as it gets.  What branches is the DECLARATION of `CHOSEN`, which
    is the shipped server's own shape (`process.env.… || <probe> ||
    <fallback>`).  If the evaluator walks that chain, the site is reported
    DECIDED and RESOLVED to a directory chosen by a walk rather than by the
    code — a green certificate one indirection away from the one the blocker
    named.  Nothing may resolve through a branch, including a binding.
    """
    js = ('\nconst CHOSEN = %s;\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  const gate = join(CHOSEN, "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n') % rhs
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == [], f"{label}: wrong verdict via a binding"
    assert not [d for d in payload["decided"] if "real_gate.py" in d["expr"]], \
        f"{label}: the binding was resolved THROUGH the branch"
    assert [u for u in payload["undecided"] if "real_gate.py" in u["expr"]], \
        f"{label}: the site vanished"


def test_an_inline_probe_across_layouts_is_not_a_finding(tmp_path):
    """SCOPE — `existsSync(<legacy>) ? <legacy> : <current>` is how this
    venue asks whether a layout is present, and the legacy layout is
    deliberately absent on most installs.  The probed arm is an OPERAND of
    the branch, so deciding it on its own is a wrong verdict on working
    code even though that arm contains no branch of its own."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = existsSync(join(LEGACY_PROGRAMS, "real_gate.py"))\n'
          '    ? join(LEGACY_PROGRAMS, "real_gate.py")\n'
          '    : join(PROGRAMS_DIR, "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == []
    assert [u for u in payload["undecided"] if "BRANCHES" in u["why"]]


def test_the_same_probe_without_the_branch_is_still_decided(tmp_path):
    """CONTROL for the arm above — the legacy arm on its own, with no
    branch anywhere near it, is the historical defect and still a
    finding."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const gate = join(LEGACY_PROGRAMS, "real_gate.py");\n'
          '  return { content: [{ type: "text", text: gate }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


def test_optional_chaining_is_not_a_ternary(tmp_path):
    """CONTROL — `?.` is a member access, not a branch, and must not buy
    the exemption either."""
    js = ('\nserver.tool("t", "d", {}, async () => {\n'
          '  const opts = cfg?.paths;\n'
          '  const gate = %s;\n'
          '  return { content: [{ type: "text", text: gate + opts }] };\n'
          '});\n') % _DEAD_CONCAT
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert DEAD_SEGMENT in res.stdout


# ==========================================================================
# SCOPE — an absent MEMBER of a present directory (conjunct 7)
# ==========================================================================

def test_an_optional_program_guarded_by_an_existence_check_is_not_a_finding(
        tmp_path):
    """SCOPE — `programs/` is right there and this one file is not in it.
    That is what an optional program looks like, and the handler here
    HANDLES the miss.  Detecting the guard needs dataflow this checker does
    not carry, so the venue is narrowed instead: an absent member of a
    present directory is undecided."""
    js = ('\nconst opt = join(PROGRAMS_DIR, "optional_extra_gate.py");\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  if (!existsSync(opt)) return { skipped: true };\n'
          '  return { content: [{ type: "text", text: opt }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    (u,) = [x for x in _payload(res)["undecided"]
            if "optional_extra_gate.py" in x["expr"]]
    assert "absent from a directory this tree DOES hold" in u["why"]
    assert f"{u['file']}:{u['line']}: [undecided]" in res.stdout


def test_the_same_name_under_an_absent_directory_is_still_decided(tmp_path):
    """CONTROL for the conjunct above — the identical file name, one
    directory over, in a LAYOUT the tree does not have.  Without this arm
    conjunct 7 could be swallowing the defect the gate exists for."""
    js = ('\nconst opt = join(LEGACY_PROGRAMS, "optional_extra_gate.py");\n'
          'server.tool("t", "d", {}, async () => {\n'
          '  if (!existsSync(opt)) return { skipped: true };\n'
          '  return { content: [{ type: "text", text: opt }] };\n'
          '});\n')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "optional_extra_gate.py" in res.stdout


# ==========================================================================
# SCOPE — a directory an install or a build PRODUCES (conjunct 8)
# ==========================================================================

@pytest.mark.parametrize("segs", [
    '"vendor", "openlane", "scripts"',
    '".venv", "bin"',
    '"build", "generated"',
])
def test_a_derived_tree_is_not_decided(tmp_path, segs):
    """SCOPE — `vendor/`, `.venv/` and `build/generated/` hold files an
    install or a build produces.  They are legitimately absent from a
    source checkout, so their absence says nothing about whether the tool
    can reach the program on an installed tree."""
    js = ('\nconst v = join(__dirname_eda, "..", "..", %s, "flow_runner.py");\n'
          'server.tool("t", "d", {}, async () => '
          '({ content: [{ type: "text", text: v }] }));\n') % segs
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    (u,) = [x for x in _payload(res)["undecided"]
            if "flow_runner.py" in x["expr"]]
    assert "install or a build PRODUCES" in u["why"]


def test_the_same_name_outside_a_derived_tree_is_still_decided(tmp_path):
    """CONTROL for the conjunct above — the identical file name under a
    directory nobody generates."""
    js = ('\nconst v = join(__dirname_eda, "..", "..", "%(dead)s",\n'
          '                "flow_runner.py");\n'
          'server.tool("t", "d", {}, async () => '
          '({ content: [{ type: "text", text: v }] }));\n'
          ) % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert "flow_runner.py" in res.stdout


# ==========================================================================
# Prose immunity
# ==========================================================================

def test_a_comment_cannot_create_a_finding(tmp_path):
    js = ('\n// const gate = resolve(__dirname_eda, "..", "..", "%(dead)s",\n'
          '//                      "programs", "real_gate.py");\n'
          'server.tool("t", "d", {}, async () => ({ content: [] }));\n'
          ) % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["program_path_sites"] == 0


def test_a_string_literal_cannot_create_a_finding(tmp_path):
    js = ('\nconst doc = "resolve(__dirname_eda, \'..\', \'%(dead)s\','
          ' \'real_gate.py\')";\n'
          'server.tool("t", "d", {}, async () => ({ content: [doc] }));\n'
          ) % {"dead": DEAD_SEGMENT}
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    assert _payload(res)["findings"] == []


def test_a_comment_cannot_clear_a_finding(tmp_path):
    """The dead path, with every plausible suppression token written beside
    it.  There is no comment, marker or pragma that changes a verdict."""
    js = _DEAD_PATH_ONLY % {"dead": DEAD_SEGMENT}
    js = js.replace(
        '"real_gate.py");',
        '"real_gate.py");  // eslint-disable-line nolint waived checked-ok\n'
        '    // mcp_tool_program_path_resolves_check: ignore\n'
        '    /* istanbul ignore next */ // @ts-ignore')
    res = _run(_tree(tmp_path, js))
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert _rules(res) == {"program-path-does-not-resolve"}


# ==========================================================================
# CANNOT-CHECK is not PASS
# ==========================================================================

@pytest.mark.parametrize("build,why", [
    (lambda tp: tp / "no_such_root", "missing plugin root"),
    (lambda tp: (tp / "empty").mkdir() or (tp / "empty"), "no mcp-eda/src"),
])
def test_absent_input_refuses_instead_of_passing(tmp_path, build, why):
    res = _run(Path(build(tmp_path)))
    assert res.returncode == RC_CANNOT, why + ": " + res.stdout
    payload = _payload(res)
    assert payload["status"] == "CANNOT_CHECK"
    assert payload["cannot_check_reason"]
    assert "[REFUSE]" in res.stdout


def test_source_dir_with_no_js_refuses(tmp_path):
    root = tmp_path / "plug"
    (root / "mcp-eda" / "src").mkdir(parents=True)
    (root / "mcp-eda" / "src" / "README.md").write_text("no sources here\n")
    res = _run(root)
    assert res.returncode == RC_CANNOT, res.stdout
    assert _payload(res)["status"] == "CANNOT_CHECK"


def test_an_internal_error_refuses_instead_of_reporting_a_finding(tmp_path):
    """An exception inside this checker is CANNOT-CHECK, not FAIL.

    Letting it escape ends the process with rc=1 — the same code a real FAIL
    uses — and prints a traceback instead of a verdict, so a caller reading
    rc=1 as "FAIL" gets a failure with zero findings.
    """
    root = _tree(tmp_path, _FIXED_HANDLER)
    saved = mod.scan_js
    try:
        def boom(_src):
            raise ValueError("substring not found")
        mod.scan_js = boom
        rc = mod.main([str(root)])
    finally:
        mod.scan_js = saved
    assert rc == RC_CANNOT
    assert _run(root).returncode == RC_PASS


# ==========================================================================
# The tree this ships in
# ==========================================================================

_HAVE_SOURCES = (_PLUGIN_ROOT / "mcp-eda" / "src").is_dir()


@pytest.mark.skipif(not _HAVE_SOURCES, reason="no MCP sources in this checkout")
def test_current_tree_is_clean():
    """A guard that fires on legitimate existing state is a bug, not a
    finding.  Every blind spot it does carry must be LOCATABLE: file, line,
    expression and reason, echoed on stdout."""
    res = _run(_PLUGIN_ROOT)
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    assert payload["findings"] == []
    assert payload["files_scanned"] >= 1
    assert payload["program_path_sites"] >= 1
    for u in payload["undecided"]:
        assert u["file"] and u["line"] >= 1 and u["expr"] and u["why"]
        assert f"{u['file']}:{u['line']}: [undecided]" in res.stdout


@pytest.mark.skipif(not _HAVE_SOURCES, reason="no MCP sources in this checkout")
def test_the_pass_line_never_claims_more_than_it_decided():
    """HONESTY — the shipped server builds every program path out of a
    directory it chooses at RUNTIME (`process.env.… || <probe> ||
    <fallback>`), so this checker decides none of them.  A verdict line
    reading "every program path resolves" over a run that decided nothing
    is a sentence that is true and useless, and it reads as an all-clear.
    The line must lead with the DECIDED count, and the undecided sites must
    be named above it."""
    res = _run(_PLUGIN_ROOT)
    assert res.returncode == RC_PASS, res.stdout + res.stderr
    payload = _payload(res)
    decided = payload["resolved"] + len(payload["findings"])
    verdict = [l for l in res.stdout.splitlines() if l.startswith("[PASS]")]
    assert len(verdict) == 1, res.stdout
    assert f"{decided} DECIDED" in verdict[0], verdict[0]
    assert (f"{payload['unresolved_by_construction']} undecided"
            in verdict[0]), verdict[0]
    assert "every in-scope program path resolves" not in verdict[0]


@pytest.mark.skipif(not _HAVE_SOURCES, reason="no MCP sources in this checkout")
def test_current_tree_still_discriminates(tmp_path):
    """The anti-vacuity arm, on the REAL sources.

    A green on the shipped tree means nothing unless the same tree goes RED
    when the historical defect is put back into it.  Earlier this arm
    deleted a program a decided site named; it cannot any more, because the
    shipped sites are all undecided and because an absent MEMBER of a
    present directory is deliberately no longer a finding (conjunct 7).  So
    this arm injects the defect in its own shape instead — a path rooted at
    this source file that climbs into a LAYOUT the tree does not have —
    which is the thing the gate exists for.
    """
    res = _run(_PLUGIN_ROOT)
    assert res.returncode == RC_PASS, res.stdout + res.stderr

    root = tmp_path / "plug"
    (root / "mcp-eda").mkdir(parents=True)
    shutil.copytree(_PLUGIN_ROOT / "mcp-eda" / "src", root / "mcp-eda" / "src")
    (root / "programs").mkdir()
    for prog in sorted(_PROGRAMS.glob("*.py")):
        (root / "programs" / prog.name).symlink_to(prog)
    assert _run(root).returncode == RC_PASS, "the copy must start clean"

    index = root / "mcp-eda" / "src" / "index.js"
    clean = index.read_text()
    injected = clean + (
        '\nserver.tool("eda_injected_probe", "d", {}, async () => {\n'
        '  const _here = dirname(fileURLToPath(import.meta.url));\n'
        '  const _gate = resolve(_here, "..", "..", "%s", "programs",\n'
        '                        "phase23_completion_self_audit_check.py");\n'
        '  return { content: [{ type: "text", text: _gate }] };\n'
        '});\n' % DEAD_SEGMENT)
    index.write_text(injected)
    res = _run(root)
    assert res.returncode == RC_FAIL, res.stdout + res.stderr
    assert any(DEAD_SEGMENT in f["message"]
               for f in _payload(res)["findings"]), res.stdout
    # ...and taking it back out restores the green, so the FAIL was caused
    # by the injection and not by the copy.
    index.write_text(clean)
    assert _run(root).returncode == RC_PASS
