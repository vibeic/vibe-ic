"""The two-writers rule, driven in both directions.

The record demanded a negative control "asserting the historical paths are
still recognised as flow-owned, so the check cannot pass over an empty set".
That control is `--self-test` and it is driven here.
"""
from __future__ import annotations

import re
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _count(out: str, label: str) -> int:
    """The integer on the population line `label`, or -1 if absent.

    A SUBSTRING assertion on a count is not a pin. `"declared concrete output
    paths:  1"` is a PREFIX of the same line ending `121`, so it passed for 1,
    121 and 199 alike -- and would refuse 2 -- which pins nothing. This reads
    the number so the caller can state the relation it actually means.
    """
    m = re.search(rf"^\s*{re.escape(label)}:\s+(\d+)\s*$", out, re.M)
    return int(m.group(1)) if m else -1

_RULE = "only_the_declaring_step_writes_its_output"
PROG = (Path(__file__).resolve().parents[1]
        / "only_the_declaring_step_writes_its_output_census.py")

_FLOW = """\
steps:
  - id: "18"
    required_outputs:
      - reports/coverage.json
  - id: "19"
    required_outputs:
      - reports/*.log
      - reports/a.json OR reports/b.json
"""

_DECLARING = '''\
from pathlib import Path


def emit(project):
    out = project / "reports" / "coverage.json"
    out.write_text("{}")
'''

#: A second module writing the same declared path.
_SECOND_WRITER = '''\
from pathlib import Path


def precheck(project):
    (project / "reports" / "coverage.json").write_text("{}")
'''

#: The remedy: private directory AND a different basename.
_PRIVATE = '''\
from pathlib import Path


def precheck(project):
    (project / "reports" / "_precheck" / "coverage_precheck.json").write_text("{}")
'''

#: A checker that READS the declared path is not a writer. Matching modules
#: that merely NAME the path returns 88 of 121 paths; matching writes returns 2.
_READER = '''\
import json
from pathlib import Path


def check(project):
    doc = json.loads((project / "reports" / "coverage.json").read_text())
    return 0 if doc else 1
'''


def _tree(files: dict, flow: str = _FLOW, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="odw_"))
    (root / ".git").mkdir()
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    (plugin / "flow").mkdir(parents=True)
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(flow)
    for name, body in files.items():
        (plugin / "programs" / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, *extra, inventory: Path = None):
    return subprocess.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json")), *extra],
        capture_output=True, text=True, timeout=300)


def test_two_writers_for_one_declared_path_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree({"emit_coverage.py": _DECLARING,
                    "precheck_coverage.py": _SECOND_WRITER}), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "reports/coverage.json" in r.stdout
    assert "emit_coverage.py" in r.stdout and "precheck_coverage.py" in r.stdout


def test_one_writer_is_not_refused():
    r = _run(_tree({"emit_coverage.py": _DECLARING}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_private_directory_and_basename_is_the_remedy():
    r = _run(_tree({"emit_coverage.py": _DECLARING,
                    "precheck_coverage.py": _PRIVATE}))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_reader_is_not_a_writer():
    """Naming is not writing: 88 paths by name, 2 by write."""
    r = _run(_tree({"emit_coverage.py": _DECLARING,
                    "coverage_check.py": _READER}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_glob_or_alternation_is_not_a_single_owned_path():
    """A set cannot have one owner, so those declarations are out of scope."""
    r = _run(_tree({"emit_coverage.py": _DECLARING}))
    assert r.returncode == 0
    # EXACTLY ONE on this SYNTHETIC fixture: the glob and the OR alternation
    # must not each become an owned path. The old form asserted the SUBSTRING
    # "declared concrete output paths:  1", which also passes for 121 and 199
    # -- right answer, vacuous predicate.
    assert _count(r.stdout, "declared concrete output paths") == 1, (
        f"the glob and the OR alternation were counted as owned paths\n"
        f"{r.stdout}")


# ------------------------------------------- the control the record demanded
def test_self_test_refuses_when_a_control_path_stops_being_flow_owned():
    """A scan whose declared set came back empty would pass over nothing."""
    r = _run(_tree({"emit_coverage.py": _DECLARING}), "--self-test")
    assert r.returncode == 2, (
        f"the fixture flow does not declare the control paths, so --self-test "
        f"must refuse rather than pass (rc={r.returncode})\n{r.stdout}\n"
        f"{r.stderr}")
    assert "no longer flow-owned" in r.stderr


def test_self_test_passes_on_the_shipped_flow():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root),
                        "--self-test"], capture_output=True, text=True,
                       timeout=1800)
    assert "self-test" in r.stdout, f"{r.stdout}\n{r.stderr}"


def test_a_flow_declaring_nothing_is_undetermined_not_a_pass():
    r = _run(_tree({"emit_coverage.py": _DECLARING}, flow="steps: []\n"))
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree({"emit_coverage.py": _DECLARING}, inventory=[
        {"key": "reports/gone.json::a.py,b.py", "reason": "stale"}]), "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "with a write this scan resolves:" in r.stdout, (
        "the run must disclose how much of its population it can see")


def test_the_census_never_blocks_by_default():
    """The ruling: this is a census and must not be wired as a blocking check.

    A census that exits non-zero gets wired as a gate by the next person who
    reads the exit code, so the default is 0 whatever is found — and the
    output says so and names the gate that does refuse.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, (
        f"the census refused by default (rc={r.returncode}); it must report\n"
        f"{r.stdout}\n{r.stderr}")
    assert "[CENSUS]" in r.stdout
    assert "the gate is programs/%s.py" % _RULE in r.stdout, (
        "the census must name the gate that does the refusing")

_SECOND_WRITER_SHUTIL = """\
import shutil
from pathlib import Path


def publish(project, src):
    shutil.copy2(src, project / "reports" / "coverage.json")
"""

_SECOND_WRITER_PATH_OPEN = """\
import json
from pathlib import Path


def publish(project, data):
    with (project / "reports" / "coverage.json").open("w") as fh:
        json.dump(data, fh)
"""


def test_a_second_writer_via_shutil_copy2_is_seen():
    """`shutil.copy2` is 67 uses in this tree and was NOT in the enumeration.

    A second writer arriving through it would have been invisible. There is no
    such site today, so without this test the widening is unfalsifiable.
    """
    r = _run(_tree({"emit_coverage.py": _DECLARING,
                    "publish_coverage.py": _SECOND_WRITER_SHUTIL}), "--strict")
    assert r.returncode == 1, (
        f"shutil.copy2 to a declared path was not seen as a write "
        f"(rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    assert "publish_coverage.py" in r.stdout


def test_a_second_writer_via_path_open_w_is_seen():
    """`p.open("w")` is an ATTRIBUTE call; the bare `open()` branch misses it."""
    r = _run(_tree({"emit_coverage.py": _DECLARING,
                    "publish_coverage.py": _SECOND_WRITER_PATH_OPEN}), "--strict")
    assert r.returncode == 1, (
        f"path.open('w') to a declared path was not seen as a write "
        f"(rc={r.returncode})\n{r.stdout}\n{r.stderr}")
