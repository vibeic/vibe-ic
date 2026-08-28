"""The declared-invocation rule, driven in both directions.

The subcommand case is a test in its own right: it is the exact input on which
the STATIC form of this rule reports a false positive, and the reason the real
parser is driven instead.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "declared_invocation_accepted_by_its_own_parser.py")

#: A program whose parser marks two arguments required.
_STRICT = '''\
#!/usr/bin/env python3
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", required=True)
    ap.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

#: A program whose MODES are subcommands. A static comparison against every
#: required argument in the file reports this as missing `--to`; the parser
#: does not, because `--to` belongs to a different subcommand.
_SUBCOMMANDS = '''\
#!/usr/bin/env python3
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    check = sub.add_parser("check")
    check.add_argument("project")
    render = sub.add_parser("render")
    render.add_argument("--to", required=True)
    ap.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

#: A program that exits 2 because its INPUT is not applicable. rc 2 has two
#: meanings and this is the other one.
_INPUT_MISSING = '''\
#!/usr/bin/env python3
import sys
from pathlib import Path


def main():
    if not Path("reports/sta.json").is_file():
        print("[SKIP] no STA report in this project; nothing to check")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _tree(programs: dict, clauses: list, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="dip_"))
    (root / ".git").mkdir()
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    (plugin / "flow").mkdir(parents=True)
    for name, body in programs.items():
        (plugin / "programs" / name).write_text(body)
    lines = ["steps:", "  - id: s1", "    acceptance:"]
    lines += [f"        - {k}: {v!r}" for k, v in clauses]
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(
        "\n".join(lines) + "\n")
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--jobs", "2",
         "--inventory", str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_a_declared_vector_the_parser_refuses_is_refused():
    """NEGATIVE CONTROL — the class the capture recorded, reintroduced."""
    root = _tree({"release_docs_gen.py": _STRICT},
                 [("program_exit_zero", "release_docs_gen .")])
    r = _run(root)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "release_docs_gen" in r.stdout
    assert "argparse rejected" in r.stdout


def test_a_complete_declared_vector_is_not_refused():
    root = _tree({"release_docs_gen.py": _STRICT},
                 [("program_exit_zero",
                   "release_docs_gen --out reports/x.md --version 1.0.0")])
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_valid_subcommand_is_not_a_false_positive():
    """The reason the parser is DRIVEN and not compared.

    A static comparison against every required argument in the file reports
    `--to` as missing. The parser does not: `--to` belongs to the `render`
    subcommand and the clause selects `check`.
    """
    root = _tree({"modal_check.py": _SUBCOMMANDS},
                 [("program_exit_zero", "modal_check check .")])
    r = _run(root)
    assert r.returncode == 0, (
        f"the subcommand false positive was NOT avoided (rc={r.returncode})\n"
        f"{r.stdout}\n{r.stderr}")


def test_an_invalid_subcommand_is_still_refused():
    root = _tree({"modal_check.py": _SUBCOMMANDS},
                 [("program_exit_zero", "modal_check render .")])
    r = _run(root)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_input_not_applicable_skip_is_not_a_declaration_defect():
    """rc 2 has two meanings and this rule separates them, not conflates them."""
    root = _tree({"sta_present_check.py": _INPUT_MISSING},
                 [("program_exit_zero", "sta_present_check .")])
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_advisory_clause_is_in_the_population():
    """An advisory clause that cannot be invoked is advisory about nothing."""
    root = _tree({"release_docs_gen.py": _STRICT},
                 [("advisory_program_exit_zero", "release_docs_gen .")])
    r = _run(root)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_flow_that_declares_nothing_is_undetermined_not_a_pass():
    """A verdict over an empty population is not a pass."""
    root = _tree({}, [])
    r = _run(root)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "CANNOT DETERMINE" in r.stderr


def test_a_stale_inventory_row_is_a_failure():
    root = _tree({"release_docs_gen.py": _STRICT},
                 [("program_exit_zero",
                   "release_docs_gen --out reports/x.md --version 1.0.0")],
                 inventory=[{"key": "gone::.", "reason": "stale"}])
    r = _run(root)
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_it_shares_one_definition_of_accepted_with_the_umbrella_probe():
    """A POPULATION extension must not carry a second copy of the predicate."""
    src = PROG.read_text(encoding="utf-8")
    assert "import _gate_invocation" in src
    assert "_gate_invocation.classify_not_invocable" in src


def test_the_shipped_tree_passes_its_own_rule():
    """THE CORPUS SWEEP, AS A GUARD RATHER THAN A ONE-TIME MEASUREMENT.

    "A guard that flags the very tree you are shipping is a bug, not a guard."
    Every other instrument in this batch pins that with a test; this suite drove
    the rule entirely on SYNTHETIC trees, so nothing here would notice if a
    widening made it fire on the repository itself. The sweep was run by hand
    and was rc 0 -- and a hand-run sweep is a claim taken at a sha.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"the rule now fires on the tree that ships it (rc={r.returncode}). "
        f"Narrow it or record the finding -- do not relax the assertion.\n"
        f"{r.stdout}")
