"""v1.3.53 R10 — close the loop_watchdog gate's opaque-shell-runner boundary.

`loop_watchdog_compliance_check.py` (v1.3.48) could not AST-inspect an opaque
`bash <run.sh>` / `sh <script>` runner, so a long EDA tool launched from inside
a shell script escaped the gate silently (a documented-but-unbounded limit).
v1.3.53 SURFACES that boundary as OFFENSE CLASS (c): a `bash`/`sh` launcher of a
`.sh`/`.bash` SCRIPT (or a `bash -c` inline that names a long tool) is FLAGGED
unless watchdog-wrapped / marker-supervised OR carrying a
`# watchdog-exempt: <reason>` annotation.

Precision requirements pinned here:
  * FALSE-POSITIVE guard: a plain `bash -c "echo …"` one-liner (no long-tool
    token, no script file) is NOT flagged; a `docker exec … bash -lc cmd`
    (argv[0] == docker) is NOT flagged.
  * FALSE-NEGATIVE guard: a `bash <script>.sh` runner — literal OR a dynamic
    script path like `bash str(runner)` — IS flagged; a `bash -c "openroad …"`
    inline long tool IS flagged.
  * Corpus-sweep CLEAN: the real programs/ tree passes (the one legitimate
    existing shell-runner carries a real annotation).

chip-AGNOSTIC / tool-AGNOSTIC.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import loop_watchdog_compliance_check as G  # noqa: E402


def _offenses(src: str):
    """Scan a synthetic source string and return its Offense list."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "cand.py"
        f.write_text(src)
        return G.scan_file(f)


def _kinds(offs):
    return [o.kind for o in offs]


# ── FALSE-NEGATIVE guards: real shell-runners MUST be flagged ────────────────

def test_literal_bash_script_runner_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', 'run.sh'], timeout=900)\n")
    assert "shell_runner" in _kinds(offs), offs


def test_dynamic_script_path_runner_flagged():
    """The real bit_level shape: `bash str(runner)` where runner is a Path to a
    .sh — the script arg is dynamic, but the `bash <non-flag positional>` shape
    is still a script-runner and must NOT be a false-negative."""
    offs = _offenses(
        "import subprocess\n"
        "def go(sim_dir):\n"
        "    runner = sim_dir / 'run.sh'\n"
        "    subprocess.run(['bash', str(runner)], cwd=str(sim_dir))\n")
    assert "shell_runner" in _kinds(offs), offs


def test_sh_with_mode_flag_then_bash_script_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.Popen(['sh', '-x', 'deploy.bash'])\n")
    assert "shell_runner" in _kinds(offs), offs


def test_bash_dash_c_inline_longtool_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '-c', 'openroad -exit'])\n")
    assert "shell_runner" in _kinds(offs), offs


def test_docker_exec_bash_script_runner_flagged():
    offs = _offenses(
        "def go(c):\n"
        "    _docker_exec(c, 'cd /w && bash run.sh')\n")
    assert "shell_runner" in _kinds(offs), offs


# ── FN-1 (Step-2.7): a start-up flag containing the letter 'c' must NOT
#    disable script detection — `--norc`/`--noprofile`/`--rcfile` are common
#    clean-env CI wrappers, NOT the `-c` command flag. ───────────────────────

def test_norc_longflag_then_script_flagged():
    """`bash --norc run.sh` — `--norc` contains 'c' but is a START-UP flag, not
    the `-c` command flag; the trailing script MUST still be flagged."""
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '--norc', 'run.sh'])\n")
    assert "shell_runner" in _kinds(offs), offs


def test_multiple_longflags_then_script_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '--noprofile', '--norc', 'build.sh'])\n")
    assert "shell_runner" in _kinds(offs), offs


def test_rcfile_option_with_arg_then_script_flagged():
    """`--rcfile r` takes a separate argument; the argv-LIST form still finds
    the `.sh` token past it."""
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '--rcfile', 'r', 'run.sh'])\n")
    assert "shell_runner" in _kinds(offs), offs


def test_norc_longflag_bare_string_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run('bash --norc run.sh', shell=True)\n")
    assert "shell_runner" in _kinds(offs), offs


# ── FALSE-POSITIVE guards: benign shapes MUST NOT be flagged ─────────────────

def test_bash_dash_c_echo_oneliner_not_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '-c', 'echo hello'])\n")
    assert offs == [], offs


def test_bash_lc_short_command_not_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['bash', '-lc', 'mkdir -p /w/out'])\n")
    assert offs == [], offs


def test_docker_exec_bash_lc_is_argv0_docker_not_flagged():
    """`subprocess.run(['docker','exec',c,'bash','-lc',cmd])` has argv[0]==docker
    (a benign launcher); the class-(c) rule keys on a bash/sh argv[0], so this
    docker-exec shape is NOT a false positive."""
    offs = _offenses(
        "import subprocess\n"
        "def go(c, cmd):\n"
        "    subprocess.run(['docker', 'exec', c, 'bash', '-lc', cmd])\n")
    assert offs == [], offs


def test_docker_exec_bash_script_with_marker_not_flagged():
    offs = _offenses(
        "def go(c):\n"
        "    _docker_exec(c, 'cd /w && bash run.sh', marker='sim')\n")
    assert offs == [], offs


def test_annotated_shell_runner_not_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    # watchdog-exempt: bounded TB sim capped by timeout below\n"
        "    subprocess.run(['bash', 'run.sh'], timeout=900)\n")
    assert offs == [], offs


def test_bare_tag_without_reason_does_not_exempt():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    # watchdog-exempt:\n"
        "    subprocess.run(['bash', 'run.sh'])\n")
    assert "shell_runner" in _kinds(offs), offs


# ── class (a) regression: a direct long-tool launch is still caught ──────────

def test_direct_openroad_subprocess_still_flagged():
    offs = _offenses(
        "import subprocess\n"
        "def go():\n"
        "    subprocess.run(['openroad', '-exit'])\n")
    assert "subprocess" in _kinds(offs), offs


# ── corpus-sweep clean on the REAL programs tree ─────────────────────────────

def test_real_programs_tree_is_clean():
    """The whole programs/ dir must PASS with the extended gate — the one
    legitimate existing shell-runner (bit_level_full_stack_tb_check.py) carries
    a real `# watchdog-exempt:` annotation."""
    offs = G.scan_programs(PROG)
    assert offs == [], "\n".join(f"{o.file}:{o.line} [{o.kind}] {o.detail}"
                                 for o in offs)


def test_bit_level_runner_has_real_annotation():
    """Regression guard: the annotation that keeps the corpus green must stay
    (a real, non-empty reason)."""
    f = PROG / "bit_level_full_stack_tb_check.py"
    txt = f.read_text()
    assert "watchdog-exempt:" in txt
    # the reason after the tag is non-empty on the annotated line
    for ln in txt.splitlines():
        if "watchdog-exempt:" in ln:
            assert ln.split("watchdog-exempt:", 1)[1].strip(), ln
