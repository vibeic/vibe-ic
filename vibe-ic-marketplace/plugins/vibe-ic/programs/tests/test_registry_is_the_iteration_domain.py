"""The registry-as-population rule, driven in both directions.

The negative control is the whole point: a checker that cannot go RED when the
defect is reintroduced is a regression test wearing a rule's name. Every red
case here builds a synthetic tree carrying the defect and asserts rc 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1] / "registry_is_the_iteration_domain.py"

#: A check whose ONLY finding-emitting loop iterates the registry, and which
#: reaches an independent population it never turns into a finding. This is the
#: defect, spelled out.
_DEFECT = '''\
import json
from pathlib import Path

LEDGER_REL = "acknowledged.json"


def load_ledger(path):
    return json.loads(path.read_text())


def main(repo):
    record = json.loads((repo / "hygiene_record.json").read_text())
    reds = [g for g, v in record.items() if v == "FAIL"]
    ledger_path = repo / LEDGER_REL
    ledger = load_ledger(ledger_path)
    findings = []
    for row in ledger:
        if not row.get("since"):
            findings.append("acknowledgement without a bound")
    return 1 if findings else 0
'''

#: The same module with the registry demoted to a FILTER over the derived
#: population. One token of structure apart, opposite verdicts.
_REPAIRED = '''\
import json
from pathlib import Path

LEDGER_REL = "acknowledged.json"


def load_ledger(path):
    return json.loads(path.read_text())


def main(repo):
    record = json.loads((repo / "hygiene_record.json").read_text())
    reds = [g for g, v in record.items() if v == "FAIL"]
    ledger_path = repo / LEDGER_REL
    ledger = load_ledger(ledger_path)
    acknowledged = {r.get("gate") for r in ledger}
    findings = []
    for gate in reds:
        if gate not in acknowledged:
            findings.append(f"{gate} is red and unacknowledged")
    return 1 if findings else 0
'''


def _tree(body: str, inventory=None) -> Path:
    """A repository-shaped scratch tree holding one enforcement module.

    `tempfile.mkdtemp` and not `tmp_path`: the pytest fixture root carries a
    newline in the container this suite runs in.
    """
    root = Path(tempfile.mkdtemp(prefix="rgd_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "acknowledged.json").write_text("[]\n")
    (progs / "sample_gate_check.py").write_text(body)
    inv = root / "inventory.json"
    inv.write_text(json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    argv = [sys.executable, str(PROG), "--root", str(root)]
    argv += ["--inventory", str(inventory or (root / "inventory.json"))]
    return subprocess.run(argv, capture_output=True, text=True, timeout=300)


# --------------------------------------------------------------- the RED case
def test_registry_as_the_iteration_domain_is_refused():
    """NEGATIVE CONTROL. Reintroduce the defect; the rule must go red."""
    root = _tree(_DEFECT)
    r = _run(root)
    assert r.returncode == 1, (
        f"the defect was NOT refused (rc={r.returncode}).\n"
        f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
    assert "sample_gate_check.py" in r.stdout
    assert "for row in ledger" in r.stdout
    assert "acknowledged.json" in r.stdout


# ------------------------------------------------------------- the GREEN case
def test_registry_used_as_a_filter_is_not_refused():
    """The remedy the rule asks for must PASS, or the rule refuses its own fix."""
    root = _tree(_REPAIRED)
    r = _run(root)
    assert r.returncode == 0, (
        f"the FILTER shape was refused (rc={r.returncode}) — the rule would be "
        f"refusing its own remedy.\n--- stdout ---\n{r.stdout}\n"
        f"--- stderr ---\n{r.stderr}")
    assert "[PASS]" in r.stdout


def test_a_check_whose_only_artefact_is_the_registry_is_not_refused():
    """No independent population means there is nothing it could have filtered.

    `phase1_no_waivers_used_check` is this shape on the real tree: the waiver
    file IS its subject. Flagging it would flag a correct check.
    """
    body = _DEFECT.replace(
        '    record = json.loads((repo / "hygiene_record.json").read_text())\n'
        "    reds = [g for g, v in record.items() if v == \"FAIL\"]\n", "")
    root = _tree(body)
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_inventory_suppresses_that_exact_site_and_nothing_else():
    root = _tree(_DEFECT, inventory=[{
        "key": ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "sample_gate_check.py::acknowledged.json::ledger::row"),
        "reason": "the fixture's own known site"}])
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_inventory_row_that_matches_nothing_is_a_failure():
    """A register that keeps suppressing after its name stops describing
    anything is the shape this gate exists to refuse — including its own."""
    root = _tree(_REPAIRED, inventory=[{
        "key": "programs/gone.py::gone.json::ledger::row",
        "reason": "deliberately stale"}])
    r = _run(root)
    assert r.returncode == 1, f"a stale row passed (rc={r.returncode})\n{r.stdout}"
    assert "match nothing" in r.stdout


# ------------------------------------------------------------- the rc contract
def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run(
        [sys.executable, str(PROG), "--root", "/nonexistent/jdistmat"],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_unreadable_inventory_is_undetermined_not_a_pass():
    root = _tree(_REPAIRED)
    bad = root / "bad.json"
    bad.write_text("{not json")
    r = _run(root, inventory=bad)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "CANNOT DETERMINE" in r.stderr


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


# --------------------------------------------------------- the shipped corpus
def test_the_shipped_tree_passes_its_own_rule():
    """A guard that flags the very tree it ships with is a bug, not a guard."""
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, (
        f"the shipped tree does not pass (rc={r.returncode}).\n{r.stdout}\n"
        f"{r.stderr}")
