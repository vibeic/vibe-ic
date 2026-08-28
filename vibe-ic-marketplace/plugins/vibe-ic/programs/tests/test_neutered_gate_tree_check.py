"""A checkout carrying a gate that cannot fail must not pass its own gates.

The state is real and was found by hand twice in one session: a killed
`gate_cli_mutation_probe` left two shipped gates with an injected early return.
An injected early return exits 0, the flow reads 0 as PASS, and nothing else in
the repo looked.  Everything here drives the checker on a real tree.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
REPO = PLUGIN.parents[2]
HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import gate_cli_mutation_probe as PROBE  # noqa: E402
import neutered_gate_tree_check as N     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

def _cli(*args):
    return _pr.run(
        [sys.executable, str(PROGRAMS / "neutered_gate_tree_check.py"), *args],
        capture_output=True, text=True)


def _tree(root: Path, body: str = "def main():\n    return 1\n") -> Path:
    pg = root / "programs"
    pg.mkdir(parents=True, exist_ok=True)
    (pg / "some_gate.py").write_text(body)
    return root


def test_a_clean_tree_passes_and_states_its_denominator(tmp_path):
    r = _cli(str(_tree(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"\b1 module\(s\) examined", r.stdout), (
        "a PASS that does not say how much it looked at is the vacuous pass "
        "this repo removes one gate at a time:\n" + r.stdout)


def test_an_injected_early_return_is_caught(tmp_path):
    """The measured state, reproduced: the exact line the probe injects."""
    injected = sorted(N.injected_statements())[0]
    _tree(tmp_path, "def main():\n    %s\n    return 1\n" % injected)
    r = _cli(str(tmp_path))
    assert r.returncode == 1, (
        "a gate carrying an injected always-succeed entry point was reported "
        "clean:\n" + r.stdout + r.stderr)
    assert "NEUTERED_GATE" in r.stderr
    assert "some_gate.py:2" in r.stderr, r.stderr


def test_every_injection_the_probe_declares_is_caught(tmp_path):
    """Not just the first one. `_ENTRIES` carries two distinct injections and a
    checker that recognised one of them would clear a tree damaged by the
    other."""
    for i, injected in enumerate(sorted(N.injected_statements())):
        root = tmp_path / ("t%d" % i)
        _tree(root, "def main():\n    %s\n" % injected)
        r = _cli(str(root))
        assert r.returncode == 1, (
            "injection %r was not recognised:\n%s" % (injected,
                                                      r.stdout + r.stderr))


def test_a_stale_probe_sidecar_is_caught(tmp_path):
    """The other half of what a killed probe leaves. The sidecar may sit beside
    a file that was restored — but it may also sit beside one that was not, and
    a checkout cannot be trusted while it is there."""
    root = _tree(tmp_path)
    (root / "programs" / ("some_gate.py" + PROBE._BACKUP_SUFFIX)).write_text("x")
    r = _cli(str(root))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STALE_PROBE_BACKUP" in r.stderr, r.stderr


def test_the_probes_own_source_is_not_a_finding():
    """The probe HOLDS the injection strings — that is where they come from.

    A substring rule reports it on every run, and a gate that cries wolf about
    itself is a gate that gets switched off. The rule is whole-line, so no
    exemption list is needed and none exists to rot.
    """
    findings, examined = N.scan(PROGRAMS)
    assert examined > 500, "the real programs tree was not scanned: %d" % examined
    offenders = [f for f in findings
                 if Path(f["path"]).name == "gate_cli_mutation_probe.py"]
    assert not offenders, (
        "the probe's own declaration of what it injects was read as damage: %s"
        % offenders)


def test_the_shipped_tree_is_clean_right_now():
    """The assertion a maintainer actually needs, over the real checkout."""
    r = _cli(str(PLUGIN))
    assert r.returncode == 0, (
        "this checkout carries a gate that cannot fail:\n" + r.stderr)


def test_the_sentinel_is_taken_from_the_probe_not_retyped():
    """A re-typed copy keeps passing after the probe's injection changes — a
    second list that looks authoritative and has stopped describing anything.

    Driven, not read: the probe's table is swapped for a different injection
    and the checker must follow it to a tree that the OLD strings would clear.
    """
    import tempfile
    original = PROBE._ENTRIES
    try:
        PROBE._ENTRIES = ((r"^(def main\(\):\n)", "    return 0  # LOBOTOMY\n",
                           "main()"),)
        with tempfile.TemporaryDirectory() as td:
            root = _tree(Path(td), "def main():\n    return 0  # LOBOTOMY\n")
            findings, _ = N.scan(root / "programs")
        assert any(f["kind"] == "NEUTERED_GATE" for f in findings), (
            "the checker did not follow the probe's redeclared injection, so "
            "it is re-typing rather than deriving: %s" % findings)
    finally:
        PROBE._ENTRIES = original


def test_a_probe_that_declares_no_injection_is_not_a_pass(tmp_path):
    """The measurement failing must not read as the tree being clean."""
    original = PROBE._ENTRIES
    try:
        PROBE._ENTRIES = ()
        findings, examined = N.scan(_tree(tmp_path) / "programs")
        assert examined == 0 and findings, (
            "an empty injection table produced a clean scan: %s" % findings)
        assert findings[0]["kind"] == "NO_SENTINEL_DERIVED"
    finally:
        PROBE._ENTRIES = original


def test_a_zero_denominator_refuses(tmp_path):
    """Pointed somewhere with no modules, it must say NOT CHECKED and exit 2 —
    never print the same green sentence as a real scan."""
    (tmp_path / "programs").mkdir()
    r = _cli(str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stderr and "not a pass" in r.stderr, r.stderr


def test_the_checker_is_wired_into_the_hygiene_lane():
    """A detector nothing runs is the defect it was written for, one level up.

    Asserted by DRIVING the script's own declaration (`--list`), not by
    grepping it: the label has to reach the dispatch record, which is what the
    merge gate reads.
    """
    out = _pr.run(["bash", str(HYGIENE), "--list"], cwd=str(REPO),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "no gate is left neutered" in out.stdout, (
        "the checker is not declared by the hygiene lane, so nothing runs "
        "it:\n" + out.stdout)
