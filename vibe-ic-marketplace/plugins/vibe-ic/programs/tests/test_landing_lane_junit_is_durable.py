"""The two wide landing lanes must not destroy the report they just computed.

`run_repo_tools_pytest` and `run_unselectable_pytest` each merge a complete
per-file JUnit — every case name, every failure message — and used to `rm -f`
it unconditionally a few lines later. In a `--rm` container that is the only
copy, so a ~46-minute lane produced a COUNT and nothing else: "28 red cases",
"8 red cases", names already deleted. Recovering what the lane had ALREADY
COMPUTED then costs a re-measurement of the whole corpus.

`run_pytest` never had this defect; it honours `GATEKEEPER_PYTEST_JUNIT`. These
tests assert the other two lanes now mirror it, and they assert it by RUNNING
THE REAL FUNCTION BODIES sliced out of `tools/gatekeeper-land.sh` — not by
reading the source and hoping. The driver and the write guard are stubbed so
the lanes finish in milliseconds; everything the fix touches (the target
selection, the up-front removal, the final `rm`) is the shipped code.

NEGATIVE CONTROL, in the same file rather than promised in a commit message:
each test also runs the PRE-FIX body — reconstructed by textual surgery on the
sliced function — and asserts the report is DESTROYED. A test that cannot fail
against the old code proves nothing about the new code.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PROGRAMS.parents[3]
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"

#: The stub driver writes this case name into the report it is asked for. It is
#: the thing an operator needs and the count can never carry: a NAME.
_CASE = "test_a_name_the_count_cannot_carry"

_LANES = {
    "run_repo_tools_pytest": "GATEKEEPER_REPO_TOOLS_JUNIT",
    "run_unselectable_pytest": "GATEKEEPER_UNSELECTABLE_JUNIT",
}


def _slice_function(name: str) -> str:
    """The shipped body, from `name() {` to the closing brace in column 0."""
    src = _LAND.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}\(\) \{{$", src, re.M)
    assert m, f"{name} is not defined in {_LAND}"
    end = re.compile(r"^\}$", re.M).search(src, m.start())
    assert end, f"{name} has no closing brace"
    return src[m.start():end.end()] + "\n"


def _to_pre_fix(body: str, var: str, tmp_prefix: str) -> str:
    """Reconstruct the body as it was before the durable-JUnit fix.

    This is the negative arm and it is deliberately EXACT: the env-aware target
    block collapses back to the bare `mktemp`, and the final `rm` goes back to
    removing `$merged` whatever it is. If either substitution stops matching,
    the test ERRORS rather than silently passing against the new code.
    """
    block = re.compile(
        r'  local merged_tmp=""\n'
        rf'  merged="\$\{{{re.escape(var)}:-\}}"\n'
        r"  if \[ -z \"\$merged\" \]; then\n"
        rf'    merged_tmp="\$\(mktemp -t {re.escape(tmp_prefix)}\.XXXXXX\)"\n'
        r'    merged="\$merged_tmp"\n'
        r"  else\n"
        r"(?:^.*\n)*?"          # the up-front-removal comment, whatever it says
        r'    rm -f "\$merged" 2>/dev/null \|\| true\n'
        r"  fi\n",
        re.M)
    body, n = block.subn(f'  merged="$(mktemp -t {tmp_prefix}.XXXXXX)"\n', body)
    assert n == 1, f"the durable-JUnit target block no longer matches in {var}"
    body, n = re.subn(
        r'rm -f "\$snap" "\$list" \$\{merged_tmp:\+"\$merged_tmp"\}',
        'rm -f "$snap" "$list" "$merged"', body)
    assert n == 1, f"the guarded final rm no longer matches in {var}"
    return body


def _stub_programs(tmp_path: Path) -> Path:
    """A driver and a write guard that answer instantly and honestly."""
    d = tmp_path / "programs"
    d.mkdir()
    (d / "suite_write_guard.py").write_text(
        "import sys; sys.exit(0)\n", encoding="utf-8")
    # Writes the report it was asked for, exactly as the real driver does, then
    # exits 0. `--stop-after-failures 0` and friends are accepted and ignored.
    (d / "pytest_per_file_junit.py").write_text(
        "import sys\n"
        "a = sys.argv[1:]\n"
        "j = a[a.index('--junit') + 1]\n"
        "open(j, 'w').write(\n"
        "    '<?xml version=\"1.0\"?><testsuites><testsuite name=\"s\" "
        "tests=\"1\" failures=\"1\">"
        "<testcase file=\"tools/test_x.py\" name=\"%s\">"
        "<failure message=\"red\"/></testcase>"
        "</testsuite></testsuites>' )\n"
        "sys.exit(int(__import__('os').environ.get('STUB_RC', '0')))\n" % _CASE,
        encoding="utf-8")
    (d / "trusted_pytest_entry.py").write_text(
        "import sys; sys.exit(0)\n", encoding="utf-8")
    # Only `run_unselectable_pytest` consults this one; it prints the corpus.
    (d / "landing_unselectable_pytest_corpus.py").write_text(
        "print('tools/test_x.py')\n", encoding="utf-8")
    return d


def _fake_root(tmp_path: Path) -> Path:
    """A tree whose `find tools` discovery is non-empty — an empty corpus is a
    refusal in both lanes, and would pass this test for the wrong reason."""
    root = tmp_path / "root"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "test_x.py").write_text("def test_x():\n    pass\n",
                                              encoding="utf-8")
    return root


def _run_lane(body: str, lane: str, tmp_path: Path, env_extra: dict) -> tuple:
    root = _fake_root(tmp_path)
    progs = _stub_programs(tmp_path)
    script = tmp_path / "lane.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        'ROOT="$1"; PROGRAMS="$2"; FAILED=0\n'
        f"{body}\n"
        f"{lane}\n"
        'exit $?\n', encoding="utf-8")
    env = dict(os.environ)
    env.pop("GATEKEEPER_REPO_TOOLS_JUNIT", None)
    env.pop("GATEKEEPER_UNSELECTABLE_JUNIT", None)
    env.update(env_extra)
    p = subprocess.run(["bash", str(script), str(root), str(progs)],
                       capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.parametrize("lane,var", sorted(_LANES.items()))
def test_a_named_report_survives_the_lane(lane, var, tmp_path):
    """THE FIX. With the variable set, the merged report is still there after
    the lane returns — and it carries the case NAME, which is the whole point."""
    out = tmp_path / "kept.xml"
    rc, log = _run_lane(_slice_function(lane), lane, tmp_path,
                        {var: str(out)})
    assert rc == 0, f"lane did not complete cleanly (rc={rc}):\n{log}"
    assert out.is_file(), (
        f"{lane} destroyed the report it was told to keep at {out} — this is "
        f"the ~46-minute run that can only report a count:\n{log}")
    assert _CASE in out.read_text(encoding="utf-8"), (
        "the report survived but carries no case name, which is a count with "
        "extra steps")


@pytest.mark.parametrize("lane,var", sorted(_LANES.items()))
def test_the_pre_fix_body_still_destroys_it(lane, var, tmp_path):
    """THE NEGATIVE CONTROL. Remove the fix from the real body and the same
    failure returns with the same shape: the named report is gone."""
    prefix = {"run_repo_tools_pytest": "gk_tools_junit",
              "run_unselectable_pytest": "gk_unsel_junit"}[lane]
    body = _to_pre_fix(_slice_function(lane), var, prefix)
    out = tmp_path / "kept.xml"
    rc, log = _run_lane(body, lane, tmp_path, {var: str(out)})
    assert rc == 0, f"the pre-fix arm must fail only by DELETION (rc={rc}):\n{log}"
    assert not out.exists(), (
        "the pre-fix body kept the report, so this test cannot distinguish the "
        "fix from its absence and proves nothing")


@pytest.mark.parametrize("lane,var", sorted(_LANES.items()))
def test_a_stale_report_is_removed_before_the_run(lane, var, tmp_path):
    """A leftover must never be readable as THIS run's record. A lane that dies
    without writing has to leave NOTHING: absence is honest, and a stale report
    that parses and describes a different session is worse than none."""
    out = tmp_path / "kept.xml"
    out.write_text("<testsuites><!-- a previous run --></testsuites>",
                   encoding="utf-8")
    # STUB_RC=199 is the driver's stall kill: it writes nothing and is not a
    # result. The lane must surface it as a FAIL and leave no stale report.
    rc, log = _run_lane(_slice_function(lane), lane, tmp_path,
                        {var: str(out), "STUB_RC": "199"})
    assert rc == 1, f"a stalled driver must fail the lane, got rc={rc}:\n{log}"
    assert "a previous run" not in (
        out.read_text(encoding="utf-8") if out.exists() else ""), (
        "the previous run's report survived and would be read as this one's")


@pytest.mark.parametrize("lane,var", sorted(_LANES.items()))
def test_control_the_default_path_is_unchanged_and_leaves_nothing(
        lane, var, tmp_path):
    """THE CONTROL GREEN. With the variable unset the lane behaves exactly as
    it always has: it passes, and it leaves no temporary report behind. The fix
    may only ADD a record, never change what the lane does by default."""
    before = set(Path("/tmp").glob("gk_*junit*"))
    rc, log = _run_lane(_slice_function(lane), lane, tmp_path, {})
    assert rc == 0, f"the default path regressed (rc={rc}):\n{log}"
    assert "PASS" in log, f"the default path stopped reporting PASS:\n{log}"
    leaked = set(Path("/tmp").glob("gk_*junit*")) - before
    assert not leaked, f"{lane} leaked a temporary report: {leaked}"


def test_neither_variable_can_gate_anything():
    """Mirror of `test_the_junit_hook_in_the_landing_script_changes_no_verdict`
    for the two new variables. If either ever gated, the merge path and the
    push path would stop agreeing."""
    src = _LAND.read_text(encoding="utf-8")
    for var in _LANES.values():
        assert var in src, f"{var} is not wired into {_LAND}"
        for line in src.splitlines():
            if var in line and not line.lstrip().startswith("#"):
                assert "FAILED=1" not in line, line
