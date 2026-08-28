"""Tests for shipped_path_portability_check.py — the shipped-source
path-portability guard.

The guard exists because the plugin once shipped one developer's home directory
as a RUNTIME DEFAULT (a benchmark scorer's designs root, the MCP server's
last-resort programs dir, a runner's search list). The worst symptom was a
phantom directory: the scorer `mkdir(parents=True)`-ed that default into
existence, so a clean install grew a workspace the user never asked for.

The load-bearing test here is the NEGATIVE PROOF
(`test_injecting_personal_path_into_shipped_file_fails`): injecting a personal
path into a shipped file must make the guard FAIL. A guard that cannot fail is
not a guard.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

# --------------------------------------------------------------------------
# Fixture personal paths are ASSEMBLED AT RUNTIME, never written as literals.
#
# This file must itself pass the guard it tests. A literal personal path here
# would (correctly) be flagged, and silencing that by adding these names to the
# guard's allow-list would gut the negative proof below — the injected path has
# to be one the guard genuinely rejects.
# --------------------------------------------------------------------------
_FAKE_USER = "a" + "developer"
_OTHER_USER = "acme" + "bot"


def _home(user: str, tail: str = "") -> str:
    return "/" + "home" + "/" + user + "/" + tail


_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "shipped_path_portability_check.py"
_PLUGIN_ROOT = _PROGRAMS.parent


def _load():
    spec = importlib.util.spec_from_file_location("_spp_check", _GUARD)
    mod = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations via sys.modules[cls.__module__], so the
    # module must be registered BEFORE exec_module or the decorator blows up.
    sys.modules["_spp_check"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --------------------------------------------------------------------------
# Personal paths (R1) — the defect class
# --------------------------------------------------------------------------
def test_personal_home_path_is_flagged(tmp_path):
    f = tmp_path / "runner.py"
    f.write_text('ROOT = os.environ.get("X", "%s")\n' % _home(_FAKE_USER, "workspace"))
    found = mod.scan_file(f, Path("runner.py"))
    assert found, "a personal home path in shipped source must be flagged"
    assert any(x.rule == "R1" for x in found)
    assert _FAKE_USER in found[0].reason


def test_personal_users_path_is_flagged(tmp_path):
    f = tmp_path / "a.js"
    f.write_text('const P = "/Users/%s/proj/programs";\n' % _FAKE_USER)
    found = mod.scan_file(f, Path("a.js"))
    assert any(x.rule == "R1" for x in found)


def test_windows_personal_path_is_flagged(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("See C:" + "\\\\Users\\\\" + _FAKE_USER + "\\\\designs for the workspace.\n")
    found = mod.scan_file(f, Path("a.md"))
    assert any(x.rule == "R1" for x in found), found


# --------------------------------------------------------------------------
# The narrow allow-list
# --------------------------------------------------------------------------
@pytest.mark.parametrize("user_token", ["<your-user>", "<user>", "$USER", "${USER}"])
def test_placeholder_documentation_examples_are_allowed(tmp_path, user_token):
    f = tmp_path / "INSTALL.md"
    f.write_text("Point the mount at `%s`.\n" % _home(user_token, "designs/top.v"))
    assert mod.scan_file(f, Path("INSTALL.md")) == []


def test_synthetic_fixture_username_is_allowed_in_tests(tmp_path):
    f = tmp_path / "test_thing.py"
    f.write_text('DECK = ".include %s"\n' % _home("testuser", "models.lib"))
    assert mod.scan_file(f, Path("tests/test_thing.py")) == []


def test_allow_user_flag_extends_the_list(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("example: %s\n" % _home(_OTHER_USER, "designs"))
    assert mod.scan_file(f, Path("a.md")) != []
    assert mod.scan_file(f, Path("a.md"), extra_allowed=[_OTHER_USER]) == []


def test_detector_regex_is_not_mistaken_for_a_path(tmp_path):
    """`backlog_sanitize_check.py` carries a literal detector pattern. The
    username charclass excludes regex metachars so the PATTERN never trips the
    guard that shares its shape."""
    f = tmp_path / "detector.py"
    f.write_text(r'PAT = r"/home/\w+/|/Users/\w+/"' + "\n")
    assert mod.scan_file(f, Path("detector.py")) == []


# --------------------------------------------------------------------------
# R2 — an absolute home path may not be a VALUE in executable source
# --------------------------------------------------------------------------
def test_generic_home_path_as_value_is_flagged_in_code(tmp_path):
    """Even the 'generic' /home/user/ shape is wrong as a shipped default: it is
    still a path that exists on nobody's machine. This is exactly the MCP
    server's old last-resort fallback."""
    f = tmp_path / "index.js"
    f.write_text('const D = process.env.X || "%s";\n' % _home("user", "proj/programs"))
    found = mod.scan_file(f, Path("mcp-eda/src/index.js"))
    assert any(x.rule == "R2" for x in found), found


def test_generic_home_path_in_a_comment_is_not_flagged(tmp_path):
    """Comments are cosmetic — R2 strips them. R1 still covers a personal name."""
    f = tmp_path / "a.js"
    f.write_text('// historical note: we used to hardcode %s\n'
                 'const D = resolve(__dirname, "..", "programs");\n'
                 % _home("user", "proj"))
    assert mod.scan_file(f, Path("a.js")) == []


def test_generic_home_path_in_a_docstring_is_not_flagged(tmp_path):
    f = tmp_path / "a.py"
    f.write_text('"""A deck with `.include %s` is '
                 'non-portable."""\nX = 1\n' % _home("user", "models.lib"))
    assert mod.scan_file(f, Path("a.py")) == []


def test_r2_does_not_apply_to_test_fixtures(tmp_path):
    f = tmp_path / "test_x.py"
    f.write_text('SAMPLE = "%s"\n' % _home("user", "project/top.v"))
    assert mod.scan_file(f, Path("programs/tests/test_x.py")) == []


def test_r2_flags_python_string_literal_default(tmp_path):
    f = tmp_path / "score.py"
    f.write_text('import os\n'
                 'R = os.environ.get("V", "%s")\n' % _home("user", "designs"))
    found = mod.scan_file(f, Path("benchmark/score.py"))
    assert any(x.rule == "R2" for x in found), found


# --------------------------------------------------------------------------
# The guard, wired end to end
# --------------------------------------------------------------------------
def _run_guard(root: Path, *extra):
    return subprocess.run(
        [sys.executable, str(_GUARD), str(root), *extra],
        capture_output=True, text=True)


def test_clean_tree_passes(tmp_path):
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "ok.py").write_text(
        'from pathlib import Path\nROOT = Path(__file__).resolve().parent\n')
    r = _run_guard(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_json_report_is_written(tmp_path):
    (tmp_path / "a.py").write_text('X = "%s"\n' % _home(_FAKE_USER, "x"))
    out = tmp_path / "report.json"
    r = _run_guard(tmp_path, "--json", str(out))
    assert r.returncode == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL" and data["count"] >= 1
    assert data["findings"][0]["file"] == "a.py"


def test_missing_root_is_arg_error(tmp_path):
    r = _run_guard(tmp_path / "nope")
    assert r.returncode == 2


# --------------------------------------------------------------------------
# NEGATIVE PROOF — the load-bearing test
# --------------------------------------------------------------------------
def test_injecting_personal_path_into_shipped_file_fails(tmp_path):
    """Copy a real shipped program, inject a personal absolute path into it as a
    runtime default, and prove the guard FAILs on it — and that the same file
    without the injection PASSes. Without this, a guard that silently never
    fires would look identical to a clean tree."""
    shipped = _PROGRAMS / "shipped_path_portability_check.py"
    clean_text = shipped.read_text()

    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    target = root / "programs" / "victim.py"

    # 1. baseline: the pristine file PASSes
    target.write_text(clean_text)
    baseline = _run_guard(root)
    assert baseline.returncode == 0, (
        "the pristine shipped file must PASS before the injection is "
        "meaningful:\n" + baseline.stdout)

    # 2. inject the defect: a personal absolute path as a runtime DEFAULT
    injected = clean_text + (
        '\n\n_HOST_ROOT = os.environ.get("VIBEIC_DESIGNS_HOST_ROOT",\n'
        '                              "%s")\n' % _home(_FAKE_USER, "AI_workspace"))
    target.write_text(injected)
    r = _run_guard(root)
    assert r.returncode == 1, (
        "GUARD DID NOT FIRE on an injected personal path — the regression "
        "guard is not load-bearing:\n" + r.stdout + r.stderr)
    assert "victim.py" in r.stdout
    assert _FAKE_USER in r.stdout


def test_injecting_generic_home_default_into_shipped_code_fails(tmp_path):
    """Second negative proof, for the OTHER defect shape: a non-personal but
    still-invented `/home/user/...` fallback in executable source."""
    root = tmp_path / "plugin"
    (root / "mcp-eda" / "src").mkdir(parents=True)
    victim = root / "mcp-eda" / "src" / "index.js"

    victim.write_text('const D = process.env.VIBE_IC_PROGRAMS_DIR '
                      '|| candidates.find(existsSync);\n')
    assert _run_guard(root).returncode == 0

    victim.write_text('const D = process.env.VIBE_IC_PROGRAMS_DIR '
                      '|| candidates.find(existsSync) '
                      '|| "%s";\n' % _home("user", "AI_workspace/plugins/x/programs"))
    r = _run_guard(root)
    assert r.returncode == 1, r.stdout
    assert "R2" in r.stdout


# --------------------------------------------------------------------------
# The real tree
# --------------------------------------------------------------------------
def test_real_plugin_tree_is_portable():
    """The shipped plugin itself must be clean. This is the regression lock."""
    r = _run_guard(_PLUGIN_ROOT)
    assert r.returncode == 0, (
        "shipped plugin source contains non-portable personal paths:\n"
        + r.stdout)


# ── #447 convention: state the denominator ─────────────────────────────────
def test_a_pass_reports_how_many_files_it_read(tmp_path):
    """This guard was wired into CI and the repo's own empty-tree probe
    refused it: PASS over an empty tree, indistinguishable from a real scan.
    That probe working is why this exists."""
    import sys
    from pathlib import Path
    prog = Path(__file__).resolve().parents[1] / "shipped_path_portability_check.py"
    (tmp_path / "a.py").write_text("x = 1\n")
    r = _pr.run([sys.executable, str(prog), str(tmp_path)],
               capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "file(s) scanned" in (r.stdout + r.stderr)


def test_scanning_zero_files_is_NOT_a_pass(tmp_path):
    """A clean result over an empty scan is what a WRONG ROOT looks like."""
    import sys
    from pathlib import Path
    prog = Path(__file__).resolve().parents[1] / "shipped_path_portability_check.py"
    (tmp_path / "sub").mkdir()          # no scannable extensions at all
    r = _pr.run([sys.executable, str(prog), str(tmp_path)],
               capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOTHING_SCANNED" in (r.stdout + r.stderr)


def test_a_real_violation_is_still_reported(tmp_path):
    """The paired half that stops the denominator becoming a way to soften the
    guard: a personal home path in shipped source still FAILs."""
    import sys
    from pathlib import Path
    prog = Path(__file__).resolve().parents[1] / "shipped_path_portability_check.py"
    (tmp_path / "leaky.py").write_text('P = "/home/someuser/x/y.rpt"\n')
    r = _pr.run([sys.executable, str(prog), str(tmp_path)],
               capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
