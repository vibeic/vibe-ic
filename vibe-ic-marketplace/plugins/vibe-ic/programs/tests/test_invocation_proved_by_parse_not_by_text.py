"""The parse-not-text rule, driven in both directions."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "invocation_proved_by_parse_not_by_text.py")

#: The shape the known instance ships: a corpus built from a closed list of
#: runner modules, passed as a PARAMETER, and searched by `in`. No syntax tree
#: anywhere in the module.
_DEFECT = '''\
import re
from pathlib import Path

_RUNNER_FILES = ["phase1_one_shot_runner.py", "phase3_one_shot_runner.py"]
_HERE = Path(__file__).resolve().parent


def _load_runner_text():
    parts = []
    for f in _RUNNER_FILES:
        p = _HERE / f
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\\n".join(parts)


def classify(steps, runner_text):
    orphans = []
    for step in steps:
        if step["producer"] not in runner_text:
            orphans.append(step["id"])
    return orphans


def main(steps):
    return classify(steps, _load_runner_text())
'''

#: The remedy: decide from the syntax tree.
_REPAIRED = '''\
import ast
from pathlib import Path

_RUNNER_FILES = ["phase1_one_shot_runner.py", "phase3_one_shot_runner.py"]
_HERE = Path(__file__).resolve().parent


def _dispatched_names():
    out = set()
    for f in _RUNNER_FILES:
        p = _HERE / f
        if not p.is_file():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.add(n.value)
    return out


def classify(steps):
    dispatched = _dispatched_names()
    return [s["id"] for s in steps if s["producer"] not in dispatched]
'''

#: Reading a REPORT and grepping it is not this rule's subject: the corpus is
#: not python source, so there is no syntax tree it failed to consult.
_NON_PYTHON_CORPUS = '''\
import re
from pathlib import Path


def check(project):
    text = (project / "reports" / "drc.rpt").read_text(errors="ignore")
    return "VIOLATION" in text
'''


def _tree(body: str, inventory=None, name="sample_coverage_check.py") -> Path:
    root = Path(tempfile.mkdtemp(prefix="ipt_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_a_text_decided_wiring_audit_is_refused():
    """NEGATIVE CONTROL — the instance the capture measured, reintroduced."""
    r = _run(_tree(_DEFECT))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "runner_text" in r.stdout
    assert "never parses it" in r.stdout


def test_a_syntax_tree_audit_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_non_python_corpus_is_out_of_population():
    """The rule is about a corpus of PYTHON MODULES, not about any read.

    Keying on 'the module mentions a .py string somewhere' was measured at 108
    findings across 67 modules, nearly all of them reading a report.
    """
    r = _run(_tree(_NON_PYTHON_CORPUS))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_non_enforcement_module_is_out_of_population():
    r = _run(_tree(_DEFECT, name="sample_helper.py"))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_corpus_must_be_traced_through_the_parameter():
    """The defect never binds its corpus to a name in the searching function.

    This is the same fixture as the red case, asserted for the specific reason
    it is hard: a tracker reading only assignments cannot see it.
    """
    r = _run(_tree(_DEFECT))
    assert "python source read at line" in r.stdout
    assert r.returncode == 1


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::blob::`in` membership", "reason": "stale"}]))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
