"""Tests for openroad_tcl_deprecation_check.py (v0.70 Item 4).

Covers the four fixtures specified by the v0.70 commission:

  (a) clean TCL → exit 0
  (b) TCL with `-bottom_routing_layer` → exit 1
  (c) TCL with `write_gds` → exit 1
  (d) missing --search-dir (bad path) → exit 2

Also runs the program against the live plugin tree and asserts it passes,
per the v0.69 Item 4 residual: the plugin itself must already be clean.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "openroad_tcl_deprecation_check.py")


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# --help always works
# ---------------------------------------------------------------------------
def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "search-dir" in out.lower()


# ---------------------------------------------------------------------------
# (a) clean TCL → exit 0
# ---------------------------------------------------------------------------
def test_clean_tcl_exits_zero(tmp_path):
    """A TCL file with no deprecated tokens must produce exit 0."""
    _write(tmp_path, "clean.tcl", """\
# Modern OpenROAD 2024 flow
read_lef tech.lef
read_lef cells.lef
read_def placed.def
set_routing_layers -signal MET1-MET5
global_route -congestion_iterations 30
detailed_route -output_drc drc.rpt
write_def routed.def
""")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 0, f"expected 0, got {code}; stdout={out!r} stderr={err!r}"
    assert "no OpenROAD TCL deprecations" in out


# ---------------------------------------------------------------------------
# (b) TCL with `-bottom_routing_layer` → exit 1
# ---------------------------------------------------------------------------
def test_bottom_routing_layer_exits_one(tmp_path):
    _write(tmp_path, "legacy_pnr.tcl", """\
# Old-style flow
global_route -bottom_routing_layer MET1 -top_routing_layer MET5
""")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1
    # Both hits should be listed (two flags on one line → two findings)
    assert "-bottom_routing_layer" in err
    assert "-top_routing_layer" in err
    assert "legacy_pnr.tcl" in err


# ---------------------------------------------------------------------------
# (c) TCL with `write_gds` → exit 1
# ---------------------------------------------------------------------------
def test_write_gds_exits_one(tmp_path):
    _write(tmp_path, "dump.tcl", """\
# Pre-2023 tail of the flow
write_gds final.gds
""")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1
    assert "write_gds" in err
    assert "def2gds" in err  # replacement hint must be shown
    assert "dump.tcl" in err


# ---------------------------------------------------------------------------
# (d) missing / bad --search-dir → exit 2
# ---------------------------------------------------------------------------
def test_missing_search_dir_exits_two(tmp_path):
    bogus = tmp_path / "does" / "not" / "exist"
    code, _, err = _run(["--search-dir", str(bogus)])
    assert code == 2
    assert "not a directory" in err.lower()


# ---------------------------------------------------------------------------
# Embedded TCL inside non-.tcl files is still flagged
# ---------------------------------------------------------------------------
def test_embedded_tcl_in_python_heredoc(tmp_path):
    _write(tmp_path, "flow.py", '''
def bad():
    return """
        write_gds final.gds
    """
''')
    code, _, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1
    assert "write_gds" in err


# ---------------------------------------------------------------------------
# Deprecations inside line-comments are NOT flagged (explicit doc mentions OK)
# ---------------------------------------------------------------------------
def test_commented_deprecated_tokens_are_skipped(tmp_path):
    """Discussing the deprecated API in a comment must not trip the gate,
    otherwise every CLAUDE.md / PRACTICAL_NOTES.md that documents the
    removal would false-positive."""
    _write(tmp_path, "doc.tcl", """\
# Do NOT use write_gds — it was removed in OpenROAD 2023+
# The old -bottom_routing_layer flag is also gone.
read_lef tech.lef
""")
    code, out, _ = _run(["--search-dir", str(tmp_path)])
    assert code == 0, out


# ---------------------------------------------------------------------------
# JSON report shape
# ---------------------------------------------------------------------------
def test_json_report_shape(tmp_path):
    _write(tmp_path, "bad.tcl", "write_gds x.gds\n")
    report = tmp_path / "r.json"
    code, _, _ = _run(["--search-dir", str(tmp_path),
                       "--json", str(report)])
    assert code == 1
    data = json.loads(report.read_text())
    assert data["total"] == 1
    assert data["findings"][0]["token"] == "write_gds"
    assert data["findings"][0]["line"] == 1
    # Replacement hint propagates to JSON
    assert "def2gds" in data["findings"][0]["replacement"]
    # All scanned deprecation tokens are advertised
    assert "-bottom_routing_layer" in data["deprecations_scanned"]
    assert "-top_routing_layer" in data["deprecations_scanned"]
    assert "write_gds" in data["deprecations_scanned"]


# ---------------------------------------------------------------------------
# __pycache__ and .git are skipped
# ---------------------------------------------------------------------------
def test_skip_dirs_are_pruned(tmp_path):
    # Put a deprecated token inside __pycache__ — must NOT be reported.
    _write(tmp_path, "__pycache__/legacy.tcl", "write_gds x.gds\n")
    # A scannable file OUTSIDE the skipped directory, so the walk has a real
    # denominator. Without it the fixture examines zero files, and "pruning
    # worked" becomes indistinguishable from "the scan covered nothing" — the
    # exact conflation the examined-count disclosure exists to prevent.
    _write(tmp_path, "live.tcl", "set_routing_layers -signal met1-met4\n")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    # The property is that the token inside __pycache__ is not reported. Assert
    # that directly rather than through the exit code, which also carries
    # "examined nothing" and would pass this test for the wrong reason.
    assert "write_gds" not in (out + err), (out, err)
    assert "legacy.tcl" not in (out + err), (out, err)
    assert code == 0, (out, err)
    assert "examined 1 file" in out, (
        f"expected exactly the non-pruned file to be examined: {out!r}")


# ---------------------------------------------------------------------------
# Plugin self-check — the live plugin tree must already be clean.
# This enforces v0.69 Item 4's residual: the repo's TCL is deprecation-free.
# ---------------------------------------------------------------------------
def test_plugin_tree_itself_is_clean():
    # flow #486: scan THIS plugin's own tree explicitly via the manifest-
    # anchored plugin root. The program's bare default (--search-dir absent)
    # resolves to parents[2], which on the source monorepo is the
    # single-plugin `plugins/` dir but on the flattened install cache is the
    # version-collection dir (all shipped versions) — a different, wrong
    # target. Pinning --search-dir to the plugin root makes this assertion
    # mean the same thing in both trees.
    from _plugin_tree import plugin_root
    code, out, err = _run(["--search-dir", str(plugin_root())])
    assert code == 0, (
        f"plugin self-check failed: stdout={out!r}\nstderr={err!r}\n"
        "If this fails, one of the plugin's own files still uses a "
        "deprecated OpenROAD TCL token. Fix the source, do not weaken "
        "the gate."
    )


# ---------------------------------------------------------------------------
# Token-boundary discipline: substrings must not false-positive.
# ---------------------------------------------------------------------------
def test_substring_does_not_false_positive(tmp_path):
    """`write_gdsii_for_tapeout` is NOT the same command as `write_gds`;
    the regex uses a word boundary so substring matches are suppressed."""
    _write(tmp_path, "custom.tcl",
           "# some local helper proc\n"
           "proc write_gdsii_for_tapeout {args} { }\n")
    code, out, _ = _run(["--search-dir", str(tmp_path)])
    assert code == 0, out


# ---------------------------------------------------------------------------
# A quoted DATA KEY named after a deprecated command is not a TCL command.
#
# MEASURED 2026-09-03 on live main 637cdf091 (v1.16.82). `4277b34a1` gave the
# dummy-fill spec a dict field literally named `write_gds` (`{"write_gds":
# gds[...]}`, `lay["write_gds"]`) and this gate reported **9 hits** over it; at
# `4277b34a1^` the same scan reported **0**. Those 9 fail a P0 STRUCTURAL gate,
# so phase 2's `final_audit` failed, the orchestrator halted at phase 2, and NO
# design on main reached phase 3 — over a tree with no OpenROAD TCL problem at
# all. The gate already carried the sibling exclusion for Python call/def
# syntax (`write_gds(`, 1910a37ca); this is the same class it missed.
#
# BOTH directions are asserted, because a suppression that only ever suppresses
# is indistinguishable from deleting the rule. The second test is what makes
# the first safe to land: it pins every shape that actually reaches an OpenROAD
# interpreter, INCLUDING ones that merely look quoted.
# ---------------------------------------------------------------------------
def test_a_quoted_dict_key_or_subscript_is_not_a_tcl_command(tmp_path):
    _write(tmp_path, "spec_shape.py", '\n'.join([
        'LEVELS = [{"write_gds": "36/4"}]',
        'name = LEVELS[0]["write_gds"]',
        "other = LEVELS[0]['write_gds']",
        '']))
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 0, f"quoted data keys flagged as TCL: {out!r} {err!r}"
    assert "no OpenROAD TCL deprecations" in out


def test_a_real_tcl_emission_is_still_flagged_after_that_exclusion(tmp_path):
    for i, body in enumerate(('cmd = "write_gds $out"\n',
                              'tcl = f"write_gds {out}"\n',
                              'argv = ["write_gds", out]\n',
                              'run("write_gds " + out)\n')):
        d = tmp_path / f"emit{i}"
        _write(d, "emit.py", body)
        code, out, err = _run(["--search-dir", str(d)])
        assert code == 1, f"a real emission went unflagged: {body!r}"
        assert "write_gds" in (out + err)


# ---------------------------------------------------------------------------
# A PYTHON IDENTIFIER IS NOT A TCL CALL.
#
# MEASURED 2026-09-07 on main 4fc47b3ef (v1.18.13), host 8HD-8, lane czp0.
# v1.18.9 landed
# `programs/tests/test_the_technology_answers_the_precheck_not_the_declaration.py`
# whose line 59 is the continuation line of a plain Python import:
#
#     from test_general_precheck import (
#         write_gds, _rect, _project, _step, _NEVER_RAN)
#
# On the tree as landed this gate reported `FAIL: 1 ... write_gds`, which fails
# a P0 STRUCTURAL gate, so `flow_compliance_check` returned rc=1, phase 2
# halted, and NO design on main reached phase 3 -- over a tree with no OpenROAD
# TCL problem at all. It was the THIRD file of this class, and each earlier
# repair added the offending FILE to a basename allowlist, which cannot see a
# fourth file. The repair is by CONTEXT: in a .py file only a STRING LITERAL
# can carry TCL, and a command token must additionally sit in TCL command
# position.
#
# Both directions are pinned here, because a rule that only ever suppresses is
# indistinguishable from deleting the gate.
# ---------------------------------------------------------------------------
def test_a_python_identifier_is_never_a_tcl_call(tmp_path):
    """Every Python position in which the bare name can legally appear."""
    _write(tmp_path, "ident.py", '\n'.join([
        "from test_general_precheck import (",
        "    write_gds, _rect, _project, _step, _NEVER_RAN)",
        "import helpers",
        "",
        "def use():",
        "    fn = write_gds",
        "    helpers.write_gds",
        "    return dispatch(handler=write_gds)",
        "",
        "def write_gds_wrapper(write_gds=None):",
        "    return write_gds",
        '']))
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 0, (
        "a Python identifier was read as an OpenROAD TCL command: "
        f"{out!r} {err!r}")
    assert "no OpenROAD TCL deprecations" in out


def test_the_exact_v1_18_9_file_shape_is_green(tmp_path):
    """The literal two lines that took main's phase 2 down."""
    _write(tmp_path, "test_the_technology_answers.py",
           "from test_general_precheck import (                # noqa: E402\n"
           "    write_gds, _rect, _project, _step, _NEVER_RAN)\n")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 0, f"the v1.18.9 P0 shape is still red: {out!r} {err!r}"


def test_a_real_tcl_file_is_still_flagged_after_the_context_rule(tmp_path):
    """.tcl is TCL source everywhere; the context rule gives up no power."""
    _write(tmp_path, "dump.tcl",
           "read_def routed.def\n"
           "write_gds $::env(RESULT_GDS)\n")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1, f"a real .tcl call went unflagged: {out!r} {err!r}"
    assert "write_gds" in (out + err)


def test_emitted_tcl_in_a_python_string_is_still_flagged(tmp_path):
    """The shape the runners actually emit into their scripts."""
    for i, body in enumerate((
            'script = """\nread_def routed.def\nwrite_gds $out\n"""\n',
            'fh.write("write_gds %s\\n" % out)\n',
            'tcl = f"write_gds {out}"\n',
            'line = "read_def d.def; write_gds out.gds"\n',
            'cmd = "puts [write_gds out.gds]"\n')):
        d = tmp_path / f"emit{i}"
        _write(d, "emit.py", body)
        code, out, err = _run(["--search-dir", str(d)])
        assert code == 1, f"emitted TCL went unflagged: {body!r}"
        assert "write_gds" in (out + err)


def test_a_flag_token_inside_an_emitted_string_is_still_flagged(tmp_path):
    """A `kind="flag"` token is an OPTION word, so it never sits in command
    position -- the string-literal restriction is its whole context rule and
    must not have made it unreachable."""
    _write(tmp_path, "gr.py",
           'cmd = "global_route -bottom_routing_layer MET1 '
           '-top_routing_layer MET5"\n')
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1, f"an emitted deprecated flag went unflagged: {err!r}"
    assert "-bottom_routing_layer" in (out + err)
    assert "-top_routing_layer" in (out + err)


def test_an_unparsable_python_file_is_not_a_blind_spot(tmp_path):
    """If tokenize cannot read the file we fall back to the unrestricted line
    scan. A file the gate cannot parse must stay VISIBLE, never exempt."""
    _write(tmp_path, "broken.py",
           "def broken(:\n"
           "write_gds $out\n")
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 1, f"an unparsable .py became a blind spot: {out!r}"
    assert "write_gds" in (out + err)


def test_only_two_files_are_exempt_and_neither_by_bare_basename(tmp_path):
    """The allowlist that caused this P0 is gone. What remains is the two
    files whose literals context genuinely cannot separate from an emission --
    this program and this program's own test -- and NEITHER is matched by a
    bare basename, so a new file cannot inherit an exemption by name."""
    sys.path.insert(0, str(PROG.parent))
    import openroad_tcl_deprecation_check as OTD     # noqa: E402

    # This program: by file IDENTITY, so a copy elsewhere is NOT exempt.
    assert OTD._self_exempt(str(PROG))
    copy = _write(tmp_path, "openroad_tcl_deprecation_check.py",
                  PROG.read_text())
    assert not OTD._self_exempt(str(copy)), (
        "a same-named copy elsewhere inherited the exemption")

    # This program's own test: by FULL RELATIVE PATH, not basename.
    own_test = PROG.parent / "tests" / "test_openroad_tcl_deprecation_check.py"
    assert OTD._self_exempt(str(own_test))
    assert not OTD._self_exempt(
        str(tmp_path / "test_openroad_tcl_deprecation_check.py"))

    # The file that took main down is judged, not exempted.
    assert not OTD._self_exempt(
        "programs/tests/"
        "test_the_technology_answers_the_precheck_not_the_declaration.py")


def test_a_mid_expression_mention_inside_a_string_is_not_a_command(tmp_path):
    """A string literal is TCL only where a TCL interpreter reads a COMMAND
    WORD. A token named mid-expression -- in a diagnostic message, a regex, a
    path -- is a mention, not an invocation. This is the clause that lets the
    string-literal rule be narrow instead of trading one false-positive class
    for another; its opposite direction is
    `test_emitted_tcl_in_a_python_string_is_still_flagged`."""
    _write(tmp_path, "mention.py", '\n'.join([
        'raise RuntimeError("unsupported command write_gds in %s" % f)',
        'PAT = re.compile(r"^\\\\s*write_gds\\\\b")',
        'path = "artifacts/write_gds.log"',
        '']))
    code, out, err = _run(["--search-dir", str(tmp_path)])
    assert code == 0, f"a mid-expression mention was read as a call: {err!r}"
