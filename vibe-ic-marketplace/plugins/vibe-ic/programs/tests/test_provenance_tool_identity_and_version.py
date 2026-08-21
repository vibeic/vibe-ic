"""The provenance chain is the anti-fabrication backbone. Two defects let it
record a row that names the WRONG program and gives it a FAKE version, while
every honesty marker on the row said the value was measured.

MEASURED on a real run (verbatim from the project's provenance.jsonl):

    tool            = '<a data file>.lef"'
    version         = 'bash: line 1: <a data file>.lef": command not found'
    version_capture = 'probed'
    exit_code       = 0
    measured        = True

Two independent causes, both asserted below.

1. `_tool_from_command` split the command chain on `&&`/`||`/`;` with a regex
   that does not know about quoting. This runner builds commands that join
   multi-valued arguments with `;` INSIDE double quotes
   (`VAR="/a/one.ext;/a/two.ext"`), so the split cut through the quoted value.
   Each half then carried one dangling quote, `shlex.split` raised, the
   whitespace fallback broke `VAR="a` off from `b"`, and the trailing path was
   read as the command word.

2. `_tool_version` probed with `<tool> --version 2>&1 | head -3` and tested
   the PIPELINE's exit status — which is `head`'s, and is 0 whenever head runs.
   So `if rc != 0: continue` could never fire, and the shell's own
   `command not found` was accepted as the tool's version.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "p3run", PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_spec)
sys.modules["p3run"] = p3
_spec.loader.exec_module(p3)


# -- defect 1: the tool name -----------------------------------------------

def _runner_shaped_command(joiner):
    """The shape this runner builds at its DEF->GDS streamout call site: a
    multi-valued argument joined by `joiner`, wrapped in double quotes."""
    vals = joiner.join(["/pdk/libs/techlef/LIB.tech.lef",
                        "/pdk/libs/lef/LIB.lef"])
    return ('export QT_QPA_PLATFORM=offscreen && '
            'export TOP=t DEF=/p/t.def GDS_OUT=/p/t.gds '
            f'LEFS="{vals}" CELL_GDS="/pdk/gds/LIB.gds" MACRO_GDS="" && '
            'python3 /p/stream_out.py')


def test_semicolon_joined_quoted_argument_is_not_the_tool():
    """THE defect. A `;` inside quotes must not end a command segment."""
    got = p3._tool_from_command(_runner_shaped_command(";"))
    assert got == "python3", (
        "the program that ran is `python3`; the ledger would have recorded "
        "%r — a fragment of a quoted data-file argument" % (got,))


def test_space_joined_control_is_unchanged():
    """The same command with the argument joined by spaces already worked and
    must keep working — this is the control that the fix did not simply
    special-case the failing input."""
    assert p3._tool_from_command(_runner_shaped_command(" ")) == "python3"


def test_ordinary_chains_are_unchanged():
    """Every shape that resolved correctly before must still resolve."""
    cases = [
        ("export PATH=/x:$PATH && openroad -exit s.tcl", "openroad"),
        ("cd /w; yosys -p 'synth -top t'", "yosys"),
        ("FOO=1 BAR=2 klayout -b -r deck.lydrc", "klayout"),
        ("/usr/bin/magic -dnull -noconsole", "magic"),
        ("export A=1 && export B=2", "export"),
        ("", "sh"),
    ]
    for cmd, want in cases:
        got = p3._tool_from_command(cmd)
        assert got == want, "%r -> %r, expected %r" % (cmd, got, want)


def test_separator_inside_single_quotes_is_not_a_separator():
    """A `;` inside a single-quoted script body is script text, not a chain
    separator. This is how every `yosys -p '...; ...'` command is written."""
    cmd = ("export PATH=/x:$PATH && "
           "yosys -p 'read_verilog a.v; synth -top t; write_verilog o.v'")
    assert p3._tool_from_command(cmd) == "yosys"


def test_splitter_honours_quotes_directly():
    """The splitter itself, so a future edit cannot regress it silently."""
    parts = p3._split_shell_chain('a=1 && b="x;y" c=2 && run.sh')
    assert parts == ['a=1', 'b="x;y" c=2', 'run.sh'], parts
    parts = p3._split_shell_chain("tool -p 'one; two' && next")
    assert parts == ["tool -p 'one; two'", "next"], parts


# -- defect 2: the version probe -------------------------------------------

def test_pipeline_rc_belongs_to_head_not_the_tool():
    """Pure shell semantics — the reason the old guard could never fire.
    This test does not touch the plugin; it pins the fact the fix rests on."""
    piped = subprocess.run(
        ["bash", "-lc", "no_such_tool_xyz --version 2>&1 | head -3"],
        capture_output=True, text=True)
    direct = subprocess.run(
        ["bash", "-lc", "no_such_tool_xyz --version 2>&1"],
        capture_output=True, text=True)
    assert piped.returncode == 0, (
        "if this ever becomes non-zero the old code was not broken; it was")
    assert direct.returncode != 0, (
        "asking the tool directly must surface the tool's own failure")
    assert "command not found" in piped.stdout


def test_version_probe_asks_the_tool_directly():
    """The probe must not wrap the tool in a pipeline, because the pipeline's
    exit status masks the tool's."""
    import inspect
    src = inspect.getsource(p3._tool_version)
    probe_lines = [ln for ln in src.splitlines()
                   if "_VERSION_FLAGS" not in ln and "{flag}" in ln]
    assert probe_lines, "could not locate the probe command in _tool_version"
    for ln in probe_lines:
        assert "head" not in ln and "|" not in ln.split("#")[0], (
            "the version probe still runs through a pipeline, so the rc it "
            "tests is not the tool's: %s" % ln.strip())


def test_failed_probe_is_not_reported_as_a_version(monkeypatch):
    """End to end: a tool that does not exist must yield NO version, so
    `_log_invocation` records `version_capture: NOT CAPTURED` rather than
    presenting a shell diagnostic as a measured build string."""
    p3._VERSION_CACHE.clear()

    def fake_exec(container, cmd, timeout=None):
        # What the shell really does for an unknown command, WITHOUT a pipe.
        return 127, "bash: line 1: nope: command not found\n", ""

    monkeypatch.setattr(p3, "_docker_exec_raw", fake_exec)
    assert p3._tool_version("some-container", "nope") is None, (
        "a failed probe was accepted as a version string")


def test_successful_probe_still_captured(monkeypatch):
    """The narrowness control: a tool that DOES answer must still be
    captured, banner filtering intact."""
    p3._VERSION_CACHE.clear()

    def fake_exec(container, cmd, timeout=None):
        return 0, "[INFO] banner line\nSomeTool 1.2.3\n", ""

    monkeypatch.setattr(p3, "_docker_exec_raw", fake_exec)
    assert p3._tool_version("some-container", "sometool") == "SomeTool 1.2.3"
