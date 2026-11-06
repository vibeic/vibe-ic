"""A checkout carrying a gate that cannot fail must not pass its own gates.

The state is real and was found by hand twice in one session: a killed
`gate_cli_mutation_probe` left two shipped gates with an injected early return.
An injected early return exits 0, the flow reads 0 as PASS, and nothing else in
the repo looked.  Everything here drives the checker on a real tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
REPO = PLUGIN.parents[2]
HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402























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
