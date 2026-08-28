"""ORGANIC #583 round-2 — the dispatcher's own argparse consumed
`--ic-name` into args.ic_name (never into `extras`), so on the
orchestrator-forwarded docs-mode MAIN path the docs runner's #541
authoritative override never fired: the name heuristic ran and the
L9.top_module fallback picked the project DIRECTORY name ('proj').

Fix: `_run_docs_mode` re-emits `--ic-name <name>` onto the delegated
argv whenever the caller stated a real name (the "UNNAMED_CHIP"
dispatcher default is not a statement); the subprocess fallback reuses
the same argv shape.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent

_DOC = """\
# Advanced Encryption Peripheral

A hardware block implementing a 128-bit block cipher with key expansion.
The register interface exposes CTRL (0x00, RW), STATUS (0x04, R) and
DATA_IN (0x08, W) registers on a 32-bit bus. Clock 100 MHz.
"""


def _run_dispatcher(tmp_path: Path, *cli) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "datasheet.md").write_text(_DOC)
    result = _pr.run(
        [sys.executable, str(PROG / "phase1_one_shot_runner.py"),
         str(proj), "--mode", "docs", *cli],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-800:]
    return proj


def test_icname_reaches_docs_mode_main_path(tmp_path):
    """The reopen's exact 現象 end-state: orchestrator-shape invocation
    (--mode docs --ic-name X) must land X in L1.ic_name AND L9.top_module
    must NOT be the project directory name."""
    proj = _run_dispatcher(tmp_path, "--ic-name", "aes_unit")
    gd = proj / "phase1" / "generated_docs"
    l1 = json.loads((gd / "L1_DATASHEET.json").read_text())
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())
    assert l1.get("ic_name") == "aes_unit", l1.get("ic_name")
    assert l9.get("top_module") != "proj", l9.get("top_module")


def test_unnamed_chip_default_not_forwarded(tmp_path):
    """The dispatcher default 'UNNAMED_CHIP' is not a statement — the
    docs runner's own heuristic must stay in charge (no bogus override
    poisoning every default-invocation run)."""
    proj = _run_dispatcher(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    l1 = json.loads((gd / "L1_DATASHEET.json").read_text())
    assert l1.get("ic_name") != "UNNAMED_CHIP", l1.get("ic_name")
