"""The ESM/CJS scope defect, pinned.

WHAT HAPPENED (2026-09-17). The server package declares ``"type":"module"``,
so ``src/index.js`` is an ES module and the CommonJS free variable ``require``
does not exist in it. The file called ``require(...)`` at five sites anyway.
Eight of the 56 registered tools answered ``require is not defined`` for ANY
input, for 400+ commits — and two of the eight failed SILENTLY (one returned a
manifest path for a file it never wrote; the other was wrapped in
``catch { return false }``, so a netlist canonicalisation step stopped running
while synthesis went on reporting success).

WHY NOTHING CAUGHT IT. Every existing test asserted the tool was REGISTERED,
and a tool that throws the moment it is CALLED is registered. Registration is a
property of the server's tool table; reachability is a property of the file's
scope, and nothing looked at the scope.

WHAT THIS FILE ASSERTS. Every arm was cross-checked against node v22.22.0
before it was written: an arm that says PASS names a module node runs with
rc=0, and an arm that says FAIL names one node stops with ``ReferenceError:
require is not defined``.

  * POSITIVE — the pre-fix shape must FAIL, naming each ``file:line``. The REAL
    pre-fix file is pinned too, straight out of git.
  * CONTROL — every legal way to bind the name must PASS. A rule that
    recognises one spelling of a correct fix fires on correct code.
  * DEFINITION IS NOT A CALL — ``function require(id) {}`` and a method written
    ``require(id) {}`` are parameter lists. A file with ZERO calls must not
    FAIL. But a CALL disguised by a following block must still be caught: both
    overrides are pinned, because each was a measured hole.
  * DEREFERENCE IS A USE — ``require.resolve(`` / ``.main`` / ``.cache`` throw
    the identical ReferenceError; ``typeof require`` is the one safe mention.
  * KNOWN CONSERVATISM — the rule is FILE-SCOPED, so a binding made inside one
    function satisfies it for the whole file. That is a DOCUMENTED MISS, and it
    is asserted here rather than left unmeasured: these arms pin PASS on code
    node throws in, so the boundary is a fact in the suite, not a hope.
  * NOT DISARMABLE — the arms that matter most. A comment, a string, a
    template, a pragma, a near-miss identifier, an unlexable file, a manifest
    edit, a bare call hidden behind a block: none of them may turn a live
    defect green.
  * VENUE — ``.cjs`` is never ESM, ``.mjs`` always is, nearest-manifest wins,
    a scan root INSIDE a package still sees that manifest, and the ``.js``
    test is on the COMMONJS side: only an EXACT ``"commonjs"`` excludes a file,
    and everything else — absent, misspelt, any other string — goes to syntax
    detection, the way node does it. Eleven measured manifest values are
    pinned, because reading the rule the other way round was a one-line disarm.
  * CANNOT-CHECK — a missing root, a tree with no ES-module source, an
    unparseable ``package.json`` and an unlexable source each exit 2, never 0.
  * LIVE PIN — the shipped tree passes, and the real ``index.js`` proves the
    rule is not vacuous.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent          # .../programs
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import mcp_esm_require_binding_check as C              # noqa: E402


def _find_plugin_root() -> Path | None:
    """The plugin root, IDENTIFIED rather than assumed.

    ``parent.parent`` is only the plugin root when this file sits in
    ``programs/tests/``. Run from anywhere else it resolves to some unrelated
    directory, and the live pins below then audit whatever happens to be
    there — measured: in a shared scratchpad they went red on another agent's
    fixtures. Locate the tree by a fact about it instead, and skip when it is
    genuinely absent.
    """
    env = os.environ.get("VIBE_IC_PLUGIN_ROOT")
    candidates = [Path(env)] if env else []
    candidates.append(PROG.parent)
    candidates.extend(Path(__file__).resolve().parents)
    for cand in candidates:
        try:
            if (cand / "mcp-eda" / "package.json").is_file():
                return cand
        except OSError:                              # pragma: no cover
            continue
    return None


PLUGIN_ROOT = _find_plugin_root()
_NO_PLUGIN = pytest.mark.skipif(
    PLUGIN_ROOT is None,
    reason="no plugin tree with mcp-eda/package.json above this test file")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
#: The defect, reconstructed. Five bare require() calls, no binding — and the
#: prose above them mentions `require` on purpose, because the real file did.
PRE_FIX_INDEX_JS = """\
import { readFileSync, existsSync } from "fs";
import { dirname, join } from "path";

// The SILENT one: wrapped in catch-return-false, so the caller kept
// reporting success while this step quietly stopped running.
function canonicalizeNetlistSrcCoords(netlistPath) {
  try {
    const fs = require("fs");
    if (!netlistPath || !fs.existsSync(netlistPath)) return false;
    return true;
  } catch { return false; }
}

async function runWorkflow(project_dir) {
  const manifestPath = `${project_dir}/workflow_manifest.json`;
  const fs = require("fs");
  fs.writeFileSync(manifestPath, "{}");
  return { success: true, manifest_path: manifestPath };
}

function runProgram(script, argv) {
  const path = require("path");
  const { execFileSync } = require("child_process");
  return execFileSync("python3", [path.resolve(script), ...argv]);
}

function readDeviceRegistry(p) {
  const os = require("os");
  return os.homedir() + p;
}
"""

#: How it was actually fixed: a real CJS resolver bound at module scope.
CREATE_REQUIRE_PREAMBLE = (
    'import { createRequire } from "node:module";\n'
    "const require = createRequire(import.meta.url);\n"
)

#: The other legitimate fix: no require() at all, top-level imports instead.
TOP_LEVEL_IMPORT_FIX = """\
import * as fs from "fs";
import * as path from "path";
import { execFileSync } from "child_process";

function runProgram(script, argv) {
  return execFileSync("python3", [path.resolve(script), ...argv]);
}
function writeManifest(p) {
  fs.writeFileSync(p, "{}");
  return true;
}
"""


def _pkg(root: Path, name: str = "mcp-eda", pkg_type: str | None = "module",
         extra: dict | None = None) -> Path:
    """Create a package directory with a package.json."""
    d = root / name
    (d / "src").mkdir(parents=True, exist_ok=True)
    manifest: dict = {"name": name, "version": "1.0.0"}
    if pkg_type is not None:
        manifest["type"] = pkg_type
    manifest.update(extra or {})
    (d / "package.json").write_text(json.dumps(manifest, indent=2),
                                    encoding="utf-8")
    return d


def _index(root: Path, source: str, name: str = "index.js") -> Path:
    pkg = _pkg(root)
    (pkg / "src" / name).write_text(source, encoding="utf-8")
    return pkg


def _lines_of(text: str, needle: str) -> list[int]:
    return [i for i, ln in enumerate(text.splitlines(), 1) if needle in ln]


# ---------------------------------------------------------------------------
# POSITIVE ARM — the defect must FAIL, by name and by line
# ---------------------------------------------------------------------------
def test_pre_fix_shape_fails(tmp_path, capsys):
    _index(tmp_path, PRE_FIX_INDEX_JS)
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == C.RC_FAIL
    expected = _lines_of(PRE_FIX_INDEX_JS, "require(")
    assert len(expected) == 5, "fixture must carry the five real call sites"
    for lineno in expected:
        assert f"mcp-eda/src/index.js:{lineno}:" in out, (
            f"the failure must NAME src/index.js line {lineno}; got:\n{out}")


def test_failure_message_names_the_remedy(tmp_path, capsys):
    _index(tmp_path, PRE_FIX_INDEX_JS)
    assert C.main([str(tmp_path)]) == C.RC_FAIL
    out = capsys.readouterr().out
    assert "createRequire(import.meta.url)" in out
    assert "ReferenceError" in out


def test_json_report_carries_file_and_line(tmp_path):
    _index(tmp_path, PRE_FIX_INDEX_JS)
    report = tmp_path / "report.json"
    assert C.main([str(tmp_path), "--json", str(report)]) == C.RC_FAIL
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["verdict"] == "FAIL"
    assert data["count"] == 5
    assert {f["line"] for f in data["findings"]} == set(
        _lines_of(PRE_FIX_INDEX_JS, "require("))
    assert {f["file"] for f in data["findings"]} == {"mcp-eda/src/index.js"}


# ---------------------------------------------------------------------------
# THE REAL DEFECT, out of git — the strongest form of the positive arm
# ---------------------------------------------------------------------------
_FIX_COMMIT = "504cb4574"
_INDEX_IN_REPO = "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/index.js"
_PRE_FIX_CALL_LINES = [1086, 6962, 8096, 8097, 8111]


def _git_show(repo: Path, rev_path: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "show", rev_path],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):    # pragma: no cover
        return None
    if out.returncode != 0:                          # pragma: no cover
        return None
    return out.stdout.decode("utf-8", "replace")


@_NO_PLUGIN
def test_the_real_pre_fix_file_is_still_caught_at_the_right_lines(tmp_path):
    """The true positive, from history rather than from a fixture.

    Every narrowing in the checker was written against cases that must NOT
    fire. This arm proves none of them deleted the case it was built for."""
    repo = PLUGIN_ROOT
    while not (repo / ".git").exists():
        if repo == repo.parent:
            pytest.skip("not inside a git checkout")
        repo = repo.parent
    src = _git_show(repo, f"{_FIX_COMMIT}^:{_INDEX_IN_REPO}")
    if src is None:
        pytest.skip(f"{_FIX_COMMIT} is not in this checkout's history")

    result = C.analyze_source(src)
    assert [u["line"] for u in result["uses"]] == _PRE_FIX_CALL_LINES
    assert result["binding"] is None, "the pre-fix file bound nothing"

    # ... and end to end, from every root, including one INSIDE the package.
    pkg = _index(tmp_path, src)
    (pkg / "src" / "sibling.mjs").write_text("export const a = 1;\n",
                                             encoding="utf-8")
    for root in (tmp_path, pkg, pkg / "src"):
        assert C.main([str(root)]) == C.RC_FAIL, f"root={root}"


# ---------------------------------------------------------------------------
# CONTROL ARM — the corrected shapes must PASS
# ---------------------------------------------------------------------------
def test_create_require_binding_passes(tmp_path, capsys):
    _index(tmp_path, CREATE_REQUIRE_PREAMBLE + PRE_FIX_INDEX_JS)
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_PASS, out
    assert "read 1 ES-module file(s)" in out


def test_top_level_import_fix_passes(tmp_path):
    _index(tmp_path, TOP_LEVEL_IMPORT_FIX)
    assert C.main([str(tmp_path)]) == C.RC_PASS


#: Every one of these was RUN under node v22.22.0 and exits 0 with no
#: ReferenceError. A gate that FAILs any of them reports a throw the runtime
#: says does not happen.
LEGAL_BINDINGS = [
    pytest.param('import { createRequire } from "module";\n'
                 "const require = createRequire(import.meta.url);\n",
                 id="unprefixed-specifier"),
    pytest.param('import { createRequire as _mk } from "node:module";\n'
                 "const require = _mk(import.meta.url);\n",
                 id="aliased-named-import"),
    pytest.param('import * as nodeModule from "node:module";\n'
                 "const require = nodeModule.createRequire(import.meta.url);\n",
                 id="namespace-member-call"),
    pytest.param('import require from "./cjs-require.js";\n',
                 id="import-binds-the-name"),
    pytest.param('import{createRequire}from"node:module";'
                 "const require=createRequire(import.meta.url);\n",
                 id="minified-no-whitespace"),
    pytest.param('import { createRequire } from "node:module";\n'
                 "const _req = createRequire(import.meta.url);\n"
                 "const require = _req;\n",
                 id="bound-through-an-alias-variable"),
    pytest.param('import { createRequire } from "node:module";\n'
                 "let require;\n"
                 "require = createRequire(import.meta.url);\n",
                 id="declare-then-assign"),
    pytest.param('const { createRequire } = await import("node:module");\n'
                 "const require = createRequire(import.meta.url);\n",
                 id="dynamic-import-destructure"),
    pytest.param("const require = "
                 '(await import("node:module")).createRequire(import.meta.url);\n',
                 id="dynamic-import-member"),
    pytest.param('import { createRequire } from "node:module";\n'
                 "globalThis.require = createRequire(import.meta.url);\n",
                 id="global-object-binding"),
    pytest.param('import { createRequire } from "node:module";\n'
                 'globalThis["require"] = createRequire(import.meta.url);\n',
                 id="global-computed-key-binding"),
    pytest.param('import { createRequire } from "node:module";\n'
                 "const { require } = { require: createRequire(import.meta.url) };\n",
                 id="destructuring-declaration"),
]


@pytest.mark.parametrize("preamble", LEGAL_BINDINGS)
def test_legitimate_binding_variants_pass(tmp_path, preamble):
    _index(tmp_path, preamble + PRE_FIX_INDEX_JS)
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_a_binding_from_an_unrelated_module_still_counts(tmp_path):
    """The rule is about the NAME, and this is a deliberate boundary.

    ``import { createRequire } from "./my-helpers.js"`` binds ``require`` to
    something that may not be a CJS resolver — but the name IS bound, so
    nothing throws ``ReferenceError``. MEASURED under node: binding the name to
    a non-function and calling it gives ``TypeError: require is not a
    function`` — a LOUD failure, a different defect class, and not the silent
    one this gate exists for. Requiring the binding to come from
    ``node:module`` was what made ten legal modules FAIL."""
    _index(tmp_path,
           'import { createRequire } from "./my-helpers.js";\n'
           "const require = createRequire(import.meta.url);\n"
           + PRE_FIX_INDEX_JS)
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_an_import_that_renames_require_away_does_not_count(tmp_path, capsys):
    """``import { require as r }`` binds ``r``. The LOCAL name is what counts;
    reading the imported name as the binding would let one word disarm it."""
    _index(tmp_path, 'import { require as r } from "./m.js";\n'
                     'const fs = require("fs");\n')
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_FAIL
    assert "mcp-eda/src/index.js:2:" in capsys.readouterr().out


def test_self_is_not_a_binding(tmp_path, capsys):
    """MEASURED: ``self`` is NOT defined in node's ESM scope, so
    ``self.require = ...`` is a line that throws, not a binding. Accepting it
    would be accepting a token that binds nothing."""
    _index(tmp_path, 'self.require = 1;\n'
                     'export function go() { return require("fs"); }\n')
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_FAIL
    assert "mcp-eda/src/index.js:2:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# A DEFINITION IS NOT A CALL — and a CALL is not a definition
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", [
    pytest.param('import { existsSync } from "fs";\n'
                 "function require(id) { return { id, existsSync }; }\n"
                 'export function load(p) { return require("fs").id; }\n',
                 id="function-declaration-named-require"),
    pytest.param("export const loader = { require(id) { return id; }, };\n",
                 id="object-method-shorthand"),
    pytest.param("export class Loader { require(id) { return id; } }\n",
                 id="class-method"),
    pytest.param("export const gen = { *require(id) { yield id; } };\n",
                 id="generator-method"),
    pytest.param('export const o = { require(id = "fs") { return id; } };\n',
                 id="method-with-a-string-default"),
    pytest.param('export const o1 = { require(id = process.env.M || "fs")'
                 " { return id; } };\n",
                 id="method-default-through-an-or"),
    pytest.param("export class L { require(id = process.env.X ? \"fs\" :"
                 ' "path") { return id; } }\n',
                 id="method-default-through-a-ternary"),
    pytest.param("export const o2 = { require(id = `${process.env.X || \"\"}"
                 'fs`) { return id; } };\n',
                 id="method-default-that-is-a-template"),
    pytest.param('export const o3 = { require(a, id = "fs") { return [a, id];'
                 " } };\n",
                 id="method-default-after-another-parameter"),
    pytest.param('export function withLoader(require) { return require("os"); }\n',
                 id="parameter-name"),
    pytest.param('export const make = (require) => require("os");\n',
                 id="arrow-parameter-name"),
])
def test_a_definition_is_not_an_unbound_call(tmp_path, source, capsys):
    """``require(id) { ... }`` is a PARAMETER LIST. Reading it as a call
    reports a file with zero call sites as a file that throws — measured, node
    runs every one of these with rc=0."""
    assert C.main([str(_index(tmp_path, source).parent)]) == C.RC_PASS, \
        capsys.readouterr().out


def test_a_method_named_require_produces_no_use_at_all():
    """The sharpest form: this source has nothing that could throw."""
    assert C.analyze_source(
        "export const loader = { require(id) { return id; }, };\n")["uses"] == []


@pytest.mark.parametrize("source,lineno", [
    pytest.param('export const fs = require("fs")\n'
                 "{ /* an unrelated block statement */ }\n", 1,
                 id="expression-position-then-block"),
    pytest.param("export function go() {\n"
                 '  require("./side-effect.js")\n'
                 "  { }\n}\n", 2,
                 id="bare-call-with-an-argument-then-block"),
])
def test_a_following_block_does_not_disguise_a_call(tmp_path, source, lineno,
                                                    capsys):
    """MEASURED HOLES, both of them one-line edits on valid JS.

    The definition exclusion is keyed on ``)`` followed by ``{``. Left at that,
    a call could be hidden by appending a block: ``const fs = require("fs")``
    with the semicolon omitted, and — the second and worse one — a bare
    ``require("./x")`` statement, which needs no ``=`` at all. Two facts
    override the exclusion: what PRECEDES demands an expression, and what the
    group CONTAINS is an argument literal (a parameter list can only hold a
    literal as a DEFAULT, which is why the method-with-a-string-default arm
    above still passes)."""
    _index(tmp_path, source)
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert f"mcp-eda/src/index.js:{lineno}:" in out


# ---------------------------------------------------------------------------
# A DEREFERENCE THROWS THE SAME ReferenceError
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("line", [
    pytest.param('export const p = require.resolve("fs");', id="resolve"),
    pytest.param("export const m = require.main;", id="main"),
    pytest.param("export const c = require.cache;", id="cache"),
    pytest.param('export const q = require?.resolve("fs");', id="optional"),
])
def test_member_access_on_an_unbound_require_is_a_finding(tmp_path, line,
                                                          capsys):
    """MEASURED under node v22.22.0: each stops the module with
    ``ReferenceError: require is not defined`` — the same error, and the same
    silence inside a catch, as a bare call."""
    _index(tmp_path, line + "\n")
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_FAIL
    assert "mcp-eda/src/index.js:1:" in capsys.readouterr().out


def test_typeof_require_is_not_a_finding(tmp_path):
    """The one mention that is SAFE: ``typeof`` is the only operator in JS that
    does not throw on an undeclared name. Measured: node runs it."""
    _index(tmp_path, 'export const ok = typeof require === "function";\n')
    assert C.main([str(tmp_path)]) == C.RC_PASS


#: A `.` or a `#` in front of the name means the OBJECT supplies the binding —
#: measured under node v22.22.0, every one of these runs with rc=0. The dot
#: that ends a line is the one that matters: a fixed-width lookbehind saw the
#: whitespace, not the dot, and read a working member call as a free variable.
MEMBER_NOT_FREE_VARIABLE = [
    pytest.param('export const fs = holder.require("fs");\n',
                 id="member-call-on-one-line"),
    pytest.param('export const fs = holder.\n  require("fs");\n',
                 id="member-call-with-the-dot-at-end-of-line"),
    pytest.param('export const fs = holder?.\n  require("fs");\n',
                 id="optional-member-call-across-a-newline"),
    pytest.param('export const p = holder.\n  require.resolve("fs");\n',
                 id="member-dereference-across-a-newline"),
    pytest.param('export const fs = holder. /* why not */ require("fs");\n',
                 id="member-call-with-a-comment-after-the-dot"),
]


@pytest.mark.parametrize("source", MEMBER_NOT_FREE_VARIABLE)
def test_a_member_named_require_is_not_the_free_variable(tmp_path, source,
                                                         capsys):
    """MEASURED rc=0 on node v22.22.0. `holder.require(...)` reads a property
    off an object that has it; the free variable is never consulted, so there
    is nothing here that can throw ReferenceError."""
    _index(tmp_path, 'import { createRequire } from "node:module";\n'
                     "const holder = { require: createRequire(import.meta.url),"
                     " };\n" + source)
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().out


@pytest.mark.parametrize("source,lineno", [
    pytest.param('require("fs");\nexport const a = 1;\n', 1,
                 id="a-call-in-the-very-first-column"),
    pytest.param('require.resolve("fs");\nexport const b = 1;\n', 1,
                 id="a-dereference-in-the-very-first-column"),
])
def test_a_use_at_the_start_of_the_file_is_still_a_finding(tmp_path, source,
                                                           lineno, capsys):
    """The other edge of the member test: there is NO character in front of the
    name at all. `prev_char` is then the empty string, and `"" in ".#"` is True
    in Python, so a membership test written against a string silently excused
    every file that BEGINS with the call. MEASURED: node stops both of these
    with `ReferenceError: require is not defined`."""
    _index(tmp_path, source)
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert f"mcp-eda/src/index.js:{lineno}:" in out


def test_a_private_field_named_require_is_not_the_free_variable(tmp_path,
                                                                capsys):
    """`this.#require(id)` is a private method call — MEASURED rc=0, printing
    `fs`. `#require` is a different name from `require`."""
    _index(tmp_path,
           "export class A {\n"
           "  #require(id) { return id; }\n"
           '  run() { return this.#require("fs"); }\n'
           "}\n")
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().out


def test_a_postfix_increment_before_a_slash_is_a_division(tmp_path, capsys):
    """MEASURED rc=0. `i++ / total` DIVIDES. Read as the start of a regex it
    swallowed the rest of the line — and the line carried the binding, so a
    correctly fixed file reported five throws it does not have."""
    source = ('import { createRequire } from "node:module";\n'
              "let i = 1; const total = 2;\n"
              "export const pct = i-- / total; "
              "const require = createRequire(import.meta.url);\n"
              'export const fs = require("fs");\n')
    assert C.analyze_source(source)["binding"] is not None, \
        "the `/` ate the binding that follows it on the same line"
    _index(tmp_path, source)
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().out


# ---------------------------------------------------------------------------
# KNOWN CONSERVATISM — the documented MISSES, asserted rather than assumed
# ---------------------------------------------------------------------------
HALF_FIX = """\
import { createRequire } from "node:module";
function canonicalize(p) {
  const require = createRequire(import.meta.url);
  return require("fs").existsSync(p);
}
export function writeManifest(p) {
  try { const fs = require("fs"); fs.writeFileSync(p, "{}"); return true; }
  catch { return false; }
}
"""


@pytest.mark.parametrize("source", [
    pytest.param(HALF_FIX, id="binding-inside-one-function"),
    pytest.param('import { createRequire } from "node:module";\n'
                 "if (globalThis.__never) "
                 "{ const require = createRequire(import.meta.url); }\n"
                 'export function go() { return require("fs"); }\n',
                 id="binding-in-a-dead-block"),
    pytest.param('export function withLoader(require) { return require("os"); }\n'
                 'export function other() { return require("fs"); }\n',
                 id="parameter-binding-and-a-sibling-call"),
    pytest.param("export const pick = (require) => require;\n"
                 'export function other() { return require("fs"); }\n',
                 id="arrow-parameter-and-a-sibling-call"),
])
def test_a_binding_narrower_than_the_file_still_satisfies_the_rule(tmp_path,
                                                                   source):
    """THIS IS A DOCUMENTED MISS, asserted so it cannot drift unnoticed.

    MEASURED under node v22.22.0: every one of these throws
    ``ReferenceError`` at the sibling call — and with the original ``catch``
    around it, SILENTLY, returning ``false``. The rule is FILE-SCOPED and
    reports PASS. Deciding it needs hoisting and closure analysis, which needs
    a parser; the span machinery that tried it without one computed
    ``(0, end-of-file)`` for a concise-body arrow and certified whole files of
    unbound calls. A miss is allowed; a false FAIL on working code is not.

    If a future revision ever decides this case for real, THIS ARM GOES RED
    first, which is the point of asserting a miss instead of describing it."""
    _index(tmp_path, source)
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_a_binding_and_its_uses_in_the_same_function_pass(tmp_path, capsys):
    """The other direction: a nested binding that DOES cover every use is
    correct code, and node runs it."""
    _index(tmp_path,
           'import { createRequire } from "node:module";\n'
           "export function canonicalize(p) {\n"
           "  const require = createRequire(import.meta.url);\n"
           '  return require("fs").existsSync(p);\n'
           "}\n")
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().err


def test_a_call_that_looks_like_a_default_parameter_is_a_documented_miss(
        tmp_path, capsys):
    """A DOCUMENTED MISS, pinned so it cannot drift unnoticed.

    `require(x = "fs")` followed by a block on the NEXT line is a call plus a
    block statement — MEASURED under node v22.22.0: `ReferenceError: require is
    not defined`. It reads here as a method definition, because `x = "fs"` is
    exactly the shape of a default parameter, and separating the two needs the
    enclosing context, which needs a parser. (On the SAME line node rejects it
    outright: `SyntaxError: Unexpected token '{'` — no ASI without a newline —
    so only the two-line spelling is a live shape at all, and reaching it means
    rewriting every call site by hand.) The control below keeps the plain
    version caught."""
    _index(tmp_path, 'import { existsSync } from "fs";\n'
                     "export function go() {\n"
                     '  require(x = "fs")\n'
                     "  { }\n"
                     "}\n")
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().out


def test_the_same_call_without_the_default_shape_is_still_caught(tmp_path,
                                                                 capsys):
    """The control for the miss above: drop the `x =` and it is a finding
    again, so the exclusion is narrow rather than a blanket."""
    _index(tmp_path, 'import { existsSync } from "fs";\n'
                     "export function go() {\n"
                     '  require("fs")\n'
                     "  { }\n"
                     "}\n")
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert "mcp-eda/src/index.js:3:" in out


# ---------------------------------------------------------------------------
# NOT DISARMABLE — prose cannot trip the rule, and cannot satisfy it either
# ---------------------------------------------------------------------------
COMMENTED_AND_QUOTED_ONLY = """\
import * as fs from "fs";

// Historical note: this file used to call require("fs") here, which threw
// because the package is "type":"module".
/* block comment: const fs = require("fs"); */
const doc = "run require('fs') in a CommonJS file, never here";
const help = 'the require("path") form is CommonJS only';
const script = `
import sys
# a Python heredoc that says require("os") in prose
print("require(\\"os\\") is not JavaScript")
`;
export function ok() { return fs.existsSync(script); }
"""


def test_require_only_in_comments_and_strings_is_not_a_finding(tmp_path,
                                                               capsys):
    _index(tmp_path, COMMENTED_AND_QUOTED_ONLY)
    assert C.main([str(tmp_path)]) == C.RC_PASS, capsys.readouterr().out


def test_editing_only_a_comment_cannot_flip_the_verdict(tmp_path):
    """The whole point of stripping: prose is not a lever on the verdict."""
    pkg = _index(tmp_path, TOP_LEVEL_IMPORT_FIX)
    before = C.main([str(tmp_path)])
    (pkg / "src" / "index.js").write_text(
        TOP_LEVEL_IMPORT_FIX + '// once: const fs = require("fs");\n',
        encoding="utf-8")
    assert before == C.main([str(tmp_path)]) == C.RC_PASS


#: Each of these is ONE line added to a file that calls `require` and binds it
#: nowhere. Not one of them introduces the name, so not one of them may turn
#: the file green. This is the buy-green arm: the class that killed the
#: previous revision.
NON_BINDING_ONE_LINERS = [
    pytest.param('// const require = createRequire(import.meta.url);',
                 id="line-comment-claims-the-binding"),
    pytest.param('/* const require = createRequire(import.meta.url); */',
                 id="block-comment-claims-the-binding"),
    pytest.param('const HELP = "const require = createRequire(import.meta.url)";',
                 id="string-holds-the-binding"),
    pytest.param('const T = `const require = createRequire(import.meta.url)`;',
                 id="template-holds-the-binding"),
    pytest.param('// globalThis["require"] = createRequire(import.meta.url);',
                 id="comment-holds-the-computed-binding"),
    pytest.param("/* eslint-disable no-undef */", id="eslint-disable"),
    pytest.param("// @ts-nocheck", id="ts-nocheck"),
    pytest.param("// esm-require-binding: ok", id="an-invented-pragma"),
    pytest.param("const requireHelper = 1;", id="near-miss-identifier"),
    pytest.param('import { createRequire } from "node:module";',
                 id="the-import-without-the-binding"),
    pytest.param('const hasReq = typeof require === "function";',
                 id="a-typeof-guard"),
    pytest.param('const cfg = { require: "yes" };', id="a-property-key"),
    pytest.param('const holder = {}; holder.require = 1;',
                 id="a-member-on-a-plain-object"),
    pytest.param(r'const RE = /require\(/g;', id="a-regex-mentioning-require"),
    pytest.param("const RE = /[`]/;", id="a-regex-holding-a-backtick"),
    pytest.param("const A = `a${`b${\"c\"}`}d`;", id="nested-templates"),
    pytest.param("const n = 1 /* c */ / 2;", id="a-comment-then-a-division"),
    pytest.param("export function t(x) { if (x) /[`]/.test(x); }",
                 id="a-regex-after-a-condition-header"),
    pytest.param('const cfg2 = { "require": 1 };', id="a-quoted-property-key"),
    pytest.param("export const RATIO = (10 + 4) / 2;", id="a-division"),
]


@pytest.mark.parametrize("line", NON_BINDING_ONE_LINERS)
def test_one_line_that_binds_nothing_cannot_buy_green(tmp_path, line, capsys):
    """MEASURED against node: with any of these lines added, the module still
    stops with ``ReferenceError: require is not defined``. A gate that goes
    green on one of them is a gate anyone can switch off."""
    _index(tmp_path, line + "\n" + PRE_FIX_INDEX_JS)
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_FAIL, f"{line!r} bought green:\n{capsys.readouterr().out}"


#: A body with NO template literal of its own, so an opening backtick really
#: does run to end of file. (When the body HAS one, the stray backtick pairs
#: with it, the scan re-synchronises, and the verdict stays FAIL — pinned
#: below. Either way the answer is not PASS, which is the property that
#: matters.)
UNBOUND_NO_TEMPLATE = """\
export function go(p) {
  const fs = require("fs");
  return fs.existsSync(p);
}
"""


@pytest.mark.parametrize("line,what", [
    pytest.param("/*", "block comment", id="unterminated-block-comment"),
    pytest.param("const BROKEN = `", "template literal",
                 id="unterminated-template-literal"),
])
def test_an_unlexable_file_is_refused_not_passed(tmp_path, line, what, capsys):
    """MEASURED HOLE: either of these swallows the rest of the file, so every
    remaining call vanished and the gate printed PASS. Node stops such a file
    with a SyntaxError, so nothing stays live behind it — but a file that was
    never lexed has not been checked, and CANNOT-CHECK is the only honest word
    for that."""
    _index(tmp_path, line + "\n" + UNBOUND_NO_TEMPLATE)
    rc = C.main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == C.RC_CANNOT_CHECK
    assert "cannot be lexed" in err and what in err


def test_a_stray_backtick_over_a_body_with_a_template_still_fails(tmp_path,
                                                                  capsys):
    """The other half of the same measurement, so the boundary is pinned from
    both sides: when the file already contains a template literal, the stray
    backtick pairs with it and the scan re-synchronises. Some sites are lost
    inside the swallowed span, but the verdict is still FAIL — the one thing a
    disarming edit must never achieve is PASS."""
    _index(tmp_path, "const BROKEN = `\n" + PRE_FIX_INDEX_JS)
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_FAIL, capsys.readouterr().out


# ---------------------------------------------------------------------------
# VENUE — which files Node actually loads as ES modules
# ---------------------------------------------------------------------------
def test_cjs_extension_is_never_esm(tmp_path):
    """`.cjs` stays CommonJS inside a "type":"module" package."""
    pkg = _pkg(tmp_path)
    (pkg / "src" / "legacy.cjs").write_text('const fs = require("fs");\n',
                                            encoding="utf-8")
    (pkg / "src" / "ok.mjs").write_text("export const a = 1;\n",
                                        encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_mjs_is_esm_even_under_a_commonjs_package(tmp_path, capsys):
    pkg = _pkg(tmp_path, name="legacy", pkg_type="commonjs")
    (pkg / "src" / "worker.mjs").write_text('const fs = require("fs");\n',
                                            encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_FAIL
    assert "legacy/src/worker.mjs:1:" in capsys.readouterr().out


def test_js_under_an_explicit_commonjs_package_is_not_esm(tmp_path):
    pkg = _pkg(tmp_path, name="legacy", pkg_type="commonjs")
    (pkg / "src" / "index.js").write_text(PRE_FIX_INDEX_JS, encoding="utf-8")
    other = _pkg(tmp_path, name="modern")
    (other / "src" / "ok.mjs").write_text("export const a = 1;\n",
                                          encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_nested_commonjs_package_inside_an_esm_package_is_not_esm(tmp_path):
    """NEAREST manifest wins — Node's own rule. 'Any ancestor' would fire on a
    correct nested CommonJS package."""
    pkg = _pkg(tmp_path)
    nested = pkg / "vendor" / "legacy"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text(
        json.dumps({"name": "legacy", "type": "commonjs"}), encoding="utf-8")
    (nested / "index.js").write_text(PRE_FIX_INDEX_JS, encoding="utf-8")
    (pkg / "src" / "ok.mjs").write_text("export const a = 1;\n",
                                        encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_deleting_type_module_from_the_manifest_cannot_buy_green(tmp_path,
                                                                 capsys):
    """MEASURED HOLE — the cheapest disarm there was: DELETE one line from
    package.json and the gate went rc=1 -> rc=0.

    It worked because a typeless `.js` used to be dropped from the venue. But
    node v22.22.0 does not drop it: it parses the file as CommonJS, detects
    module syntax, and REPARSES it as an ES module ("Reparsing as ES module
    because module syntax was detected") — in which `typeof require` is
    `undefined`. MEASURED: the package went on working as ESM and went on
    throwing ReferenceError at the same call sites while the gate said PASS."""
    _pkg(tmp_path, pkg_type=None)
    (tmp_path / "mcp-eda" / "src" / "index.js").write_text(
        PRE_FIX_INDEX_JS, encoding="utf-8")
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert "mcp-eda/src/index.js:8:" in out


def test_a_typeless_js_without_module_syntax_stays_commonjs(tmp_path):
    """The other direction of node's detection: no ``import``/``export`` means
    node runs it as CommonJS, where ``require`` really is defined. Flagging it
    would libel every plain CommonJS file in existence."""
    pkg = _pkg(tmp_path, pkg_type=None)
    (pkg / "src" / "legacy.js").write_text(
        'const fs = require("fs");\nmodule.exports = { fs };\n',
        encoding="utf-8")
    (pkg / "src" / "ok.mjs").write_text("export const a = 1;\n",
                                        encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_node_modules_is_not_scanned(tmp_path):
    pkg = _pkg(tmp_path)
    dep = pkg / "node_modules" / "some-dep"
    dep.mkdir(parents=True)
    (dep / "package.json").write_text(
        json.dumps({"name": "d", "type": "module"}), encoding="utf-8")
    (dep / "stream.js").write_text(
        "module.exports = require('./dist/stream.cjs')\n", encoding="utf-8")
    (pkg / "src" / "ok.mjs").write_text("export const a = 1;\n",
                                        encoding="utf-8")
    assert C.main([str(tmp_path)]) == C.RC_PASS


def test_a_scan_root_inside_the_package_still_sees_the_manifest(tmp_path,
                                                               capsys):
    """MEASURED false PASS, fixed. Bounding the manifest walk at the scan root
    re-classified the package's own `.js` as non-ESM and dropped it — and a
    sibling `.mjs` kept ``files_read > 0``, so the empty-scan guard never
    fired. Same broken code, one directory deeper, rc 1 -> 0."""
    pkg = _index(tmp_path, PRE_FIX_INDEX_JS)
    (pkg / "src" / "sibling.mjs").write_text("export const a = 1;\n",
                                             encoding="utf-8")
    rc = C.main([str(pkg / "src")])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert "index.js:8:" in out
    assert "read 2 ES-module file(s)" in out


#: No `import`, no `export` — nothing node's syntax detection could latch on
#: to. Only the MANIFEST makes this an ES module, so it is the shape that pins
#: the walk-to-the-filesystem-root on its own. MEASURED under node v22.22.0:
#: `ReferenceError: require is not defined in ES module scope ... because ...
#: package.json contains "type": "module"`.
MANIFEST_ONLY_ESM = """\
function go(p) {
  const fs = require("fs");
  return fs.existsSync(p);
}
go(".");
"""


def test_a_manifest_above_the_scan_root_is_the_only_thing_that_classifies(
        tmp_path, capsys):
    """The walk-to-root defence, pinned where nothing else can cover it.

    The file carries no module syntax, so syntax detection says nothing about
    it; only the manifest one directory up makes it an ES module. Stop the walk
    at the scan root and it is silently reclassified as CommonJS and dropped —
    which is exactly how the same tree used to read rc=1 from the package and
    rc=0 from one directory deeper."""
    pkg = _index(tmp_path, MANIFEST_ONLY_ESM)
    (pkg / "src" / "sibling.mjs").write_text("export const a = 1;\n",
                                             encoding="utf-8")
    rc = C.main([str(pkg / "src")])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, out
    assert "index.js:2:" in out


#: MEASURED on node v22.22.0, one package per value, each holding a `.js` that
#: calls `require`: EVERY ONE of these manifest `"type"` values left node
#: loading the file as an ES module and throwing `ReferenceError: require is
#: not defined` at the call. Only an EXACT `"commonjs"` takes a file out.
UNRECOGNISED_TYPES = [
    pytest.param("Module", id="capitalised"),
    pytest.param("MODULE", id="upper-case"),
    pytest.param("module ", id="trailing-space"),
    pytest.param("esm", id="esm"),
    pytest.param("modules", id="plural"),
    pytest.param("", id="empty-string"),
    pytest.param("true", id="true"),
    pytest.param("Commonjs", id="capitalised-commonjs"),
    pytest.param("commonjs ", id="commonjs-with-a-trailing-space"),
    pytest.param("banana", id="nonsense"),
]


@pytest.mark.parametrize("value", UNRECOGNISED_TYPES)
def test_an_unrecognised_manifest_type_cannot_buy_green(tmp_path, value,
                                                        capsys):
    """MEASURED HOLE — the widest one-line disarm this gate had.

    While `"type":"module"` was the thing that opted a file IN, ONE edit to
    package.json took every `.js` in the package out of the venue. Node does
    the opposite: it takes a file out only on an EXACT `"commonjs"`, and
    anything else falls to syntax detection. Measured for each value here: node
    kept loading the file as an ES module and kept throwing at the same call
    sites while the gate printed PASS."""
    _pkg(tmp_path, pkg_type=value)
    (tmp_path / "mcp-eda" / "src" / "index.js").write_text(
        PRE_FIX_INDEX_JS, encoding="utf-8")
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, f"type={value!r} bought green:\n{out}"
    assert "mcp-eda/src/index.js:8:" in out


@pytest.mark.parametrize("value", ["esm", "module", "banana", None])
def test_a_nested_manifest_that_is_not_commonjs_cannot_buy_green(tmp_path,
                                                                 value, capsys):
    """The second spelling of the same disarm: drop ONE new `package.json` next
    to the source. Only an exact `"commonjs"` in it may take the file out —
    which the arm below pins from the other side."""
    pkg = _index(tmp_path, PRE_FIX_INDEX_JS)
    manifest: dict = {"name": "inner"}
    if value is not None:
        manifest["type"] = value
    (pkg / "src" / "package.json").write_text(json.dumps(manifest),
                                              encoding="utf-8")
    rc = C.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == C.RC_FAIL, f"nested type={value!r} bought green:\n{out}"
    assert "src/index.js:8:" in out


def test_only_the_exact_string_commonjs_takes_a_js_out_of_the_venue(tmp_path):
    """The rule stated as a census fact, both directions in one run: two
    packages, one saying `"commonjs"` and one saying `"Commonjs"`. Node
    excludes the first and not the second, and so does this."""
    exact = _pkg(tmp_path, name="exact", pkg_type="commonjs")
    (exact / "src" / "a.js").write_text('export const a = require("fs");\n',
                                        encoding="utf-8")
    near = _pkg(tmp_path, name="near", pkg_type="Commonjs")
    (near / "src" / "b.js").write_text('export const b = require("fs");\n',
                                       encoding="utf-8")
    findings, census = C.audit(str(tmp_path))
    assert census["js_seen"] == 2
    assert census["js_excluded"] == 1
    assert census["files_read"] == 1
    assert [f.file for f in findings] == ["near/src/b.js"]


def test_the_census_never_invents_a_commonjs_package(tmp_path, capsys):
    """The same run used to print ``excluded 2 .js under a CommonJS package``
    when there was no CommonJS package anywhere — the walk had simply been
    stopped. A census that states a reason must state a true one."""
    pkg = _index(tmp_path, TOP_LEVEL_IMPORT_FIX)
    (pkg / "src" / "sibling.mjs").write_text("export const a = 1;\n",
                                             encoding="utf-8")
    assert C.main([str(pkg / "src")]) == C.RC_PASS
    assert "excluded 0 .js" in capsys.readouterr().out


def test_the_excluded_count_is_real(tmp_path):
    """A census number nothing produces is a number nothing can contradict."""
    governed = _pkg(tmp_path, name="legacy", pkg_type="commonjs")
    (governed / "src" / "a.js").write_text("export const a = 1;\n",
                                           encoding="utf-8")
    (governed / "src" / "ok.mjs").write_text("export const c = 1;\n",
                                             encoding="utf-8")
    _findings, census = C.audit(str(tmp_path))
    assert census["js_seen"] == 1
    assert census["js_excluded"] == 1
    assert census["files_read"] == 1


# ---------------------------------------------------------------------------
# CANNOT-CHECK — "I could not look" is never 0
# ---------------------------------------------------------------------------
def test_missing_root_is_cannot_check(tmp_path, capsys):
    rc = C.main([str(tmp_path / "does-not-exist")])
    err = capsys.readouterr().err
    assert rc == C.RC_CANNOT_CHECK
    assert "CANNOT-CHECK" in err and "not a directory" in err


def test_tree_with_no_esm_source_is_cannot_check(tmp_path, capsys):
    (tmp_path / "notes.md").write_text("no javascript here\n", encoding="utf-8")
    rc = C.main([str(tmp_path)])
    assert rc == C.RC_CANNOT_CHECK
    assert "no ES-module source" in capsys.readouterr().err


def test_unparseable_package_json_is_cannot_check_not_pass(tmp_path, capsys):
    """The manifest decides whether its .js files are ES modules. If it will
    not parse, their module kind is UNKNOWN — that is not a clean bill."""
    pkg = tmp_path / "mcp-eda"
    (pkg / "src").mkdir(parents=True)
    (pkg / "package.json").write_text('{"name": "mcp-eda", "type":\n',
                                      encoding="utf-8")
    (pkg / "src" / "index.js").write_text(PRE_FIX_INDEX_JS, encoding="utf-8")
    rc = C.main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == C.RC_CANNOT_CHECK
    assert "package.json" in err and "UNKNOWN" in err


# ---------------------------------------------------------------------------
# LIVE PIN — the shipped tree, and the proof the rule is not vacuous
# ---------------------------------------------------------------------------
@_NO_PLUGIN
def test_shipped_tree_has_no_unbound_require():
    findings, census = C.audit(str(PLUGIN_ROOT))
    assert findings == [], "\n".join(
        f"{f.file}:{f.line}: {f.snippet}" for f in findings[:20])
    assert census["files_read"] > 0, (
        "a clean result over an empty scan is not a clean result")


@_NO_PLUGIN
def test_the_real_server_module_actually_uses_require_and_binds_it():
    """Not vacuous: the file this gate was written for genuinely uses
    require() in code and genuinely binds the name. If a refactor ever removes
    the binding, the pin above stops being 0."""
    index = PLUGIN_ROOT / "mcp-eda" / "src" / "index.js"
    if not index.is_file():                      # pragma: no cover
        pytest.skip(f"{index} is not present in this layout")
    original = index.read_text(encoding="utf-8")
    result = C.analyze_source(original)
    assert result["uses"], "no use of require in code — the pin would be vacuous"
    assert result["binding"] is not None, "no binding — the pin would be vacuous"
    assert result["unterminated"] is None
    # Line fidelity: the stripper must not move anything.
    assert len(result["code"]) == len(original)
    assert result["code"].count("\n") == original.count("\n")


@_NO_PLUGIN
def test_the_package_really_declares_type_module():
    """The premise of the whole rule, asserted rather than assumed."""
    manifest = PLUGIN_ROOT / "mcp-eda" / "package.json"
    if not manifest.is_file():                   # pragma: no cover
        pytest.skip(f"{manifest} is not present in this layout")
    assert json.loads(manifest.read_text(encoding="utf-8")).get("type") == \
        "module"
