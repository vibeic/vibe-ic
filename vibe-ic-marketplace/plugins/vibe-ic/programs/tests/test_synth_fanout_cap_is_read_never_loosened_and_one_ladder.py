#!/usr/bin/env python3
"""The synthesis fanout cap: a design-declared value is READ and never
loosened, and synthesis and BOTH sign-off SDC paths get the same cap from ONE
ladder (review of next/icsub5-synthfo, findings 3 and 4).

FINDING 3, MEASURED on spm (gf180mcuD). Its L9 §9.1B declares the cap as a
per-library table:

    | library | `MAX_FANOUT_CONSTRAINT` |
    | `sky130_fd_sc_ls` | 5 |
    | `gf180mcu_*` | 4 |
    | 其他 | 工具預設 |

`_L9_SYNTH_MAX_FANOUT_RE` only reads a single `SYNTH_MAX_FANOUT | N |` row, so
the design's 4 read as "no cap" and the PDK-family default (10) LOOSENED it.

FINDING 4. The staged-SDC (augment) path stopped at the design-declared tiers
and the liberty, skipping the PDK-family default synthesis consults, so a
design staging its own SDC could be bounded at 10 in synthesis and carry no
`set_max_fanout` at sign-off. And a design SDC's own `set_max_fanout` (kept
byte-identical at sign-off) was invisible to synthesis.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


SPM_L9 = """## 9.1B Synthesis Fanout Limit(非 SDC,合成階段約束)

| library | `MAX_FANOUT_CONSTRAINT` |
|---|---|
| `sky130_fd_sc_ls` | 5 |
| `gf180mcu_*` | 4 |
| 其他 | 工具預設 |
"""














# --- finding 3: a per-library L9 table is a declaration ---------------------












# --- finding 4: one ladder for synthesis and BOTH SDC paths ----------------










def test_every_sdc_path_resolves_through_the_one_ladder():
    """Source pin: no SDC path resolves the cap on its own again."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    for fn in ("def _ensure_staged_sdc_drv", "def _build_auto_silicon_sdc"):
        i = src.index(fn)
        j = src.index("\ndef ", i + 10)
        body = src[i:j]
        assert "_synth_max_fanout(" in body, fn
        assert "_l9_declared_max_fanout(project" not in body, (
            f"{fn} resolves the cap on its own again")
