"""Review F10 — a formal proof transcript must be SHIPPABLE, not silently
dropped by `.gitignore`.

THE DEFECT, MEASURED on 135ce027a. The Step-5 gate report `formal_evidence.json`
lives under `reports/` and therefore ships. The proof it cites does not: the
runner writes its SymbiYosys transcript beside the task, at
`phase2/stage1/formal/<stem>.sby.log`, and the repo-wide `*.log` rule ignores
it. The #361 rescue `!benchmark-data/**/reports/**/*.log` covers `reports/**`
only, so the citation and its proof sat on opposite sides of one ignore rule.

Result: all three published spm PDK cells cite
`phase2/stage1/formal/formal_<top>_formal.sby.log`, all three genuinely ran the
proof (each cell's own `phase2_one_shot.json` lists `formal/results.json` in
`phase2_manifests.output_files` — a path the runner appends ONLY on the
proved-and-all_proved branch), and ZERO transcripts are tracked. That is not an
authoring slip in one campaign; it is the structurally guaranteed outcome for
every design, because shipping the proof required a `git add -f` nobody knew
was needed.

Each assertion below was run by hand against the repo before being written
down. The end-state test FAILS on a tree without the F10 rule (measured: `git
check-ignore` returns 0 = ignored), so it discriminates rather than restating
the file.
"""
import subprocess
from pathlib import Path

import pytest

# The runner's own transcript filename shape, from formal_property_run:
#   sby_path = formal_dir / f"{top}_formal.sby";  log = f"{sby_path.stem}.sby.log"
# chip-AGNOSTIC: `<ic>` / `<top>` below are placeholders, not design names.
_CITED_TRANSCRIPT = (
    "benchmark-data/ic/<ic>/phase2/stage1/formal/formal_<top>_formal.sby.log")
_SUBDIR_TRANSCRIPT = (
    "benchmark-data/ic/<ic>/phase2/stage1/formal/reset_safety/proof.sby.log")
# SymbiYosys task-workdir noise — must STAY ignored, or a wide add sweeps in
# hundreds of intermediate yosys logs per run.
_TASK_WORKDIR_NOISE = (
    "benchmark-data/ic/<ic>/phase2/stage1/formal/task/model/design.log")
_REPORTS_LOG = "benchmark-data/ic/<ic>/reports/phase2/gates/proof.log"


def _repo_root() -> Path:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent))
    if cp.returncode != 0:
        pytest.skip("not in a git repo")
    return Path(cp.stdout.strip())


def _ignored(root: Path, rel: str) -> bool:
    """True iff `rel` is git-ignored. `--no-index` so the answer is a pure
    function of the ignore rules and never of what happens to be tracked."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", rel],
        cwd=str(root), capture_output=True, text=True).returncode == 0


def test_end_state_cited_formal_transcript_is_shippable():
    """END-STATE: the exact path shape the Step-5 report cites is NOT ignored.

    This is the discriminator. Without the F10 negation the repo-wide `*.log`
    rule wins and this returns ignored=True.
    """
    root = _repo_root()
    assert not _ignored(root, _CITED_TRANSCRIPT), (
        f"{_CITED_TRANSCRIPT} is git-ignored — the Step-5 gate report cites "
        f"this path and could never ship it")


def test_end_state_per_property_subdir_transcript_is_shippable():
    """Evidence organised one level down (`formal/<property>/`) is covered too
    — the `**` in the rule is load-bearing, not decoration."""
    root = _repo_root()
    assert not _ignored(root, _SUBDIR_TRANSCRIPT)


def test_noleak_sby_task_workdir_logs_stay_ignored():
    """§ no-leak: the rescue is narrow ON PURPOSE. SymbiYosys writes many
    intermediate `*.log` files into its task workdir; un-ignoring those would
    trade a missing proof for hundreds of untracked-noise paths per run, and a
    rule that makes `git status` unreadable is a rule that gets reverted."""
    root = _repo_root()
    assert _ignored(root, _TASK_WORKDIR_NOISE)


def test_noleak_existing_reports_rescue_still_works():
    """§ no-regression: the #361 rescue this sits beside is untouched."""
    root = _repo_root()
    assert not _ignored(root, _REPORTS_LOG)


def test_noleak_ordinary_build_log_stays_ignored():
    """§ no-regression: `*.log` still ignores build noise outside
    benchmark-data. The fix widens what can SHIP as evidence, not what git
    tracks in general."""
    root = _repo_root()
    assert _ignored(root, "build/compile.log")
    assert _ignored(root, "vibe-ic-marketplace/plugins/vibe-ic/run.sby.log")
