#!/usr/bin/env python3
"""ORGANIC #419 — five mechanisms disagreed about which layout artefacts ship.

Each was locally reasonable and no two agreed:

  1. `.gitignore` ignored `*.gds`/`*.def` at the root and NEGATED them back
     for `benchmark-data/ic/**`; `*.spef`/`*.oas` were never ignored at all.
  2. The comment beside that negation said a size guard in
     `benchmark_evidence_structure_check` would stop files over 50 MB. No such
     guard existed — the sentence was the entire implementation.
  3. `benchmark_evidence_publish` dropped all four by EXTENSION, so a cell
     published by the program carried LESS evidence than the hand-staged
     cells it replaced.
  4. Its docstring justified that as gitignored-or-too-large, false by then
     on both counts.
  5. `NO_RAW_GEOMETRY` failed any cell carrying one — and so failed ALL THREE
     reference cells, the most complete evidence this repository publishes.

MEASURED before choosing a ceiling: the largest tracked blob is 26.75 MB and
exactly one exceeds 20 MB, so 50 MB starts with zero debt and needs no
baseline. Ten UNTRACKED `.gds` under `benchmark-data/ic` are 74–105 MB and are
accepted by the negation; two exceed GitHub's 100 MB hard limit.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _published_corpus import cell_dirs, needs_corpus

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))









# ── the size guard that was promised and never written ──────────────────────













# ── the drift check ─────────────────────────────────────────────────────────









# ── the reference cells, which the old rule rejected ────────────────────────

@needs_corpus
def test_the_reference_cells_pass_their_own_structure_check():
    """Every one of them FAILED on NO_RAW_GEOMETRY before #419, naming the
    .gds/.def/.spef the repository had already decided to accept.

    DRIVEN BY THE CORPUS RATHER THAN BY THREE HARD-CODED NAMES. This was
    `@parametrize("cell", ["v1.5.58_ihp-sg13g2", "v1.5.65_sky130A",
    "v1.9.96_gf180mcuD"])` with an inline `skip("published cell not present")`,
    which after the 2026-08 split skipped all three every run and said nothing
    about why or where the cells went. Worse, it would have gone on skipping
    per-name even with a corpus supplied: a published snapshot legitimately
    carries a different set (today's holds `v1.10.18_sky130A` where the issue
    measured `v1.5.65_sky130A`), and a name-keyed skip turns that into silence.

    So the population is whatever spm cells the corpus publishes, and it is
    asserted non-empty — the check runs on all of them or the test fails. The
    one skip left is `needs_corpus`: no corpus, no cells to check, said in the
    suite's single wording.
    """
    cells = [c for c in cell_dirs() if c.parent.name == "spm"]
    assert len(cells) >= 3, (
        f"the corpus publishes {len(cells)} spm cell(s); #419 was measured on "
        f"three reference cells and this is the population that carries the "
        f"raw geometry the old NO_RAW_GEOMETRY rule rejected: "
        f"{[str(c) for c in cells]}")
    for d in cells:
        r = subprocess.run(
            [sys.executable,
             str(_PROGRAMS / "benchmark_evidence_structure_check.py"), str(d)],
            capture_output=True, text=True)
        assert r.returncode == 0, (d, r.stdout)
