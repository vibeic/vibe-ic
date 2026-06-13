"""v1.6.180 (#72 P2-8) — confirm-inline-mode helper for the two
Step 14 Yosys gates (`yosys_hilomap_required_check`,
`yosys_script_template_check`).

Both gates emit `verdict: VACUOUS_PASS` when no `.ys` script is
found under the project's canonical search globs, on the
assumption that the project is using the
`phase3_one_shot_runner` inline `yosys -p '<commands>'` mode.

Field-agent's P2-8 question: how does a reviewer know whether the
VACUOUS_PASS is legitimate ("project genuinely uses inline mode")
or a bug ("the gate didn't find a `.ys` script it expected to find,
masking a real synthesis failure")? Pre-v1.6.180 the verdict alone
gave no answer.

v1.6.180 positively confirms the inline-mode case by inspecting
project state for any of:

  (a) `phase3_one_shot_runner.py` artefacts:
      - `reports/phase3_one_shot.json` (the runner's own report)
      - `phase3/stage2/synth/yosys.log`
      - `phase3/stage2/synth/synth.log`
  (b) `yosys -p` invocation in any shell / tcl / makefile under
      `phase3/`, `phase2/stage2/synth/`, `scripts/`, or
      `Makefile`-style top-level files.

If at least one positive marker is found, the verdict becomes
`VACUOUS_PASS` with `reason_class: inline_yosys_p_mode_confirmed`.

If none, the gate stays rc=0 but reports
`verdict: VACUOUS_PASS_UNCONFIRMED` so audit reviewers can see the
gate's vacuousness was not positively justified.

chip-AGNOSTIC: looks for structural markers, never chip-class
literals.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple


_RUNNER_ARTEFACTS = (
    "reports/phase3_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "phase3/reports/phase3_one_shot.json",
    "phase3/stage2/synth/yosys.log",
    "phase3/stage2/synth/synth.log",
    "phase2/stage2/synth/yosys.log",
    "phase2/stage2/synth/synth.log",
)

_INLINE_SEARCH_DIRS = (
    "phase3",
    "phase2/stage2/synth",
    "scripts",
)

# Match `yosys -p ...`, `yosys --commands ...`, `yosys --command ...`
# in any shell / tcl / makefile / py blob. Word boundary on the left
# keeps it from matching `xyosys`.
_INLINE_CMD_RE = re.compile(
    r"\byosys\s+(?:-p|--commands?|--command)\b",
    re.IGNORECASE,
)


def _file_has_inline_marker(path: Path) -> bool:
    try:
        head = path.open("r", errors="replace").read(64 * 1024)
    except OSError:
        return False
    return bool(_INLINE_CMD_RE.search(head))


def detect_inline_mode(project: Path) -> Tuple[str, List[str]]:
    """Return (status, evidence_paths_rel).

    status ∈ {"confirmed", "unconfirmed"}.

    evidence_paths_rel is a list of project-relative paths whose
    presence (or content) confirms inline mode. When status is
    "unconfirmed" the list is empty.
    """
    evidence: List[str] = []

    # (a) Runner artefacts.
    for rel in _RUNNER_ARTEFACTS:
        p = project / rel
        if p.is_file() and p.stat().st_size > 0:
            evidence.append(rel)

    # (b) Inline-command grep.
    for sub in _INLINE_SEARCH_DIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for ext in ("*.sh", "*.tcl", "*.py", "Makefile", "makefile",
                     "*.mk"):
            for f in d.rglob(ext):
                if _file_has_inline_marker(f):
                    try:
                        evidence.append(str(f.relative_to(project)))
                    except ValueError:
                        evidence.append(str(f))
                    if len(evidence) >= 8:
                        break
            if len(evidence) >= 8:
                break
        if len(evidence) >= 8:
            break

    if evidence:
        return "confirmed", evidence
    return "unconfirmed", []


__all__ = ["detect_inline_mode"]
