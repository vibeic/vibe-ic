"""A tool that can reach its own text console must be stopped by the command.

The incident, measured 2026-09-09 in `ghcr.io/vibeic/vibeic-eda`: a single
`pos.out.log` of 102 GB -- 1,619,420,055 lines whose last 2000 held NINE
distinct lines. netgen had fallen into its interactive console and re-printed
the menu for every byte of stdin it could not parse.

Throughput, measured with stdin fed unparseable bytes:

    netgen, no -batch                          9.9 MB / 5 s
    magic -dnull -noconsole, script w/o quit   4.0 MB / 6 s

Two things each stop it, and they are not equally durable. stdin at EOF works
-- and today that is the ONLY thing protecting the shipped magic calls,
because `docker_exec_argv` omits `-i`. That is the caller's argv, in another
file. `netgen -batch` and a magic script ending in `quit` travel with the
command. This guard requires the second.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import console_tool_termination_check as C  # noqa: E402


def _mod(tmp_path, name, body):
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# One injected defect per rule. A guard that has never rejected anything is a
# bug report about the guard.
# --------------------------------------------------------------------------

def test_netgen_without_batch_is_rejected(tmp_path):
    _mod(tmp_path, "a", '''
        def go(container, tcl):
            return _docker_exec(container, f"netgen -source {tcl}")
    ''')
    r = C.run(tmp_path)
    assert r["verdict"] == "FAIL"
    assert [f["tool"] for f in r["findings"]] == ["netgen"]
    assert r["findings"][0]["requirement"] == "-batch"


def test_klayout_without_b_is_rejected(tmp_path):
    _mod(tmp_path, "a", '''
        def go(container, script):
            return _docker_exec(container, f"klayout -r {script}")
    ''')
    r = C.run(tmp_path)
    assert [f["tool"] for f in r["findings"]] == ["klayout"]


def test_magic_without_a_script_terminator_is_rejected(tmp_path):
    """THE REGRESSION. `digital_hardmacro_gen` shipped exactly this shape:
    the script ends on a `puts` marker and magic then falls to its console."""
    _mod(tmp_path, "a", '''
        def build(top):
            return f"gds read x.gds\\nload {top}\\nlef write out.lef\\n"
        def go(container, script):
            return _docker_exec(container,
                                f"magic -dnull -noconsole -rcfile rc {script}")
    ''')
    r = C.run(tmp_path)
    assert [f["tool"] for f in r["findings"]] == ["magic"]
    assert "quit" in r["findings"][0]["requirement"]


# --------------------------------------------------------------------------
# The other direction. Each correct form must pass.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    'f"netgen -batch source {tcl}"',
    'f"netgen -batch lvs \\"a.spice A\\" \\"b.spice B\\" setup rpt"',
    'f"export PATH=/x:$PATH && netgen -batch source {tcl}"',
])
def test_a_terminated_netgen_passes(tmp_path, cmd):
    _mod(tmp_path, "a", f'''
        def go(container, tcl):
            return _docker_exec(container, {cmd})
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


@pytest.mark.parametrize("cmd", ['f"klayout -b -r {s}"', 'f"klayout -zz -b -r {s}"'])
def test_a_batch_klayout_passes(tmp_path, cmd):
    _mod(tmp_path, "a", f'''
        def go(container, s):
            return _docker_exec(container, {cmd})
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


def test_magic_with_a_quit_in_its_script_passes(tmp_path):
    _mod(tmp_path, "a", '''
        def build(top):
            return f"gds read x.gds\\nload {top}\\nquit -noprompt\\n"
        def go(container, script):
            return _docker_exec(container,
                                f"magic -dnull -noconsole -rcfile rc {script}")
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


def test_the_terminator_may_live_one_import_hop_away(tmp_path):
    """THE FALSE POSITIVE THIS GUARD ALREADY HAD. `analog_hardmacro_gds_emit`
    executes magic and contains no `quit` of its own -- it runs a script built
    by `magic_port_extract_emit`, which emits one. Flagging it was wrong."""
    _mod(tmp_path, "builder", '''
        def build_gds_write_tcl(top):
            return f"load {top}\\ngds write out.gds\\nquit -noprompt\\n"
    ''')
    _mod(tmp_path, "runner", '''
        from builder import build_gds_write_tcl
        def go(container, script):
            cmd = f"magic -dnull -noconsole -rcfile rc {script}"
            return _docker_exec(container, cmd)
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


# --------------------------------------------------------------------------
# What must NOT be read as a command.
# --------------------------------------------------------------------------

def test_a_failure_message_quoting_a_command_is_not_an_invocation(tmp_path):
    """THE FALSE POSITIVE A TEXT SCAN HAS. `analog_hardmacro_gds_emit` carries

        detail=(f"magic -rcfile {magicrc} {tcl_name} returned ")

    inside an error message. grep flags it; reading the call graph does not,
    because nothing executes it."""
    _mod(tmp_path, "a", '''
        def go(rec, magicrc, tcl_name, rc):
            rec.update(status="FAIL",
                       detail=f"magic -rcfile {magicrc} {tcl_name} returned {rc}")
            return rec
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


def test_prose_naming_a_tool_is_not_an_invocation(tmp_path):
    _mod(tmp_path, "a", '''
        """netgen -batch lvs is how sign-off LVS runs; klayout -b -r for DRC."""
        HELP = "netgen -json structured E1 report (file or dir)."
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


# --------------------------------------------------------------------------
# The binding hop, which decides whether this guard sees real code at all.
# --------------------------------------------------------------------------

def test_a_command_built_into_a_variable_is_still_read(tmp_path):
    """THE MISS AN EARLIER DRAFT HAD. Shipped call sites build the command
    into a name and pass the name; reading only literal arguments found ONE of
    the three defects this was written for and called the rest PASS."""
    _mod(tmp_path, "a", '''
        def go(container, tcl):
            cmd = (f"export PATH=/x:$PATH && "
                   f"netgen -source {tcl}")
            return _docker_exec(container, cmd)
    ''')
    assert C.run(tmp_path)["verdict"] == "FAIL"


def test_an_unresolvable_command_is_silent_rather_than_wrong(tmp_path):
    """A name this program cannot resolve yields no finding. Guessing would
    make the guard wrong in the direction that blocks correct code."""
    _mod(tmp_path, "a", '''
        def go(container, cmd):
            return _docker_exec(container, cmd)
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


def test_only_the_shipped_exec_helpers_count(tmp_path):
    """A string handed to something that does not execute is not a command."""
    _mod(tmp_path, "a", '''
        def go(log):
            log.append(f"netgen -source {log}")
            return log
    ''')
    assert C.run(tmp_path)["verdict"] == "PASS"


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------

def test_cli_exit_codes(tmp_path):
    prog = str(_PROGRAMS / "console_tool_termination_check.py")
    _mod(tmp_path, "bad", '''
        def go(container, tcl):
            return _docker_exec(container, f"netgen -source {tcl}")
    ''')
    r = subprocess.run([sys.executable, prog, str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout

    (tmp_path / "bad.py").write_text(
        'def go(c, t):\n    return _docker_exec(c, f"netgen -batch source {t}")\n',
        encoding="utf-8")
    ok = subprocess.run([sys.executable, prog, str(tmp_path)],
                        capture_output=True, text=True)
    assert ok.returncode == 0 and "PASS" in ok.stdout

    missing = subprocess.run([sys.executable, prog, str(tmp_path / "nope")],
                             capture_output=True, text=True)
    assert missing.returncode == 2 and "CANNOT CHECK" in missing.stdout


def test_the_shipped_tree_is_clean():
    """The product itself must satisfy the rule this program states."""
    r = C.run(_PROGRAMS)
    assert r["verdict"] == "PASS", r["findings"]
