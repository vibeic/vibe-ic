#!/usr/bin/env python3
"""rtl_timescale_stamp.py — state an emitted candidate's TIME UNIT, or refuse by
name.

WHY (#2053, emitter half)
-------------------------
A Verilog source file that contains no `timescale directive has no time unit of
its own: it inherits the unit of whatever file the simulator compiled before it.
So a candidate whose behaviour is defined by DELAY CONTROLS (`#5 clk = ~clk`)
means different things depending on the ORDER its files are handed to iverilog.

MEASURED (lane brtllm, 2026-09-06, finding BR-08) on a frozen clkgenerator
candidate against its own frozen challenge:

    candidate first, challenge second -> FAIL, "first rising edge at time
                                         705032704, expected 5", $finish at
                                         35000000000000
    challenge first, candidate second -> PASS,                  $finish at 35000
    candidate first + a `timescale prepended to a byte-identical COPY -> PASS

The harness reported that as a design defect ("the frozen candidate must pass its
required prompt-derived verification test"). It is not one: it is a missing unit
declaration, and argv order decided the verdict.

WHAT THIS DOES, AND WHAT IT REFUSES TO DO
-----------------------------------------
`stamp_rtl` prepends a `timescale to emitted RTL **only when the design's own
input DECLARES one**. A time unit cannot be inferred: a prompt that says "period
10" or "10ns" states a PERIOD, not a unit/precision pair, and turning one into
the other is a guess about what the design means. So:

  * the RTL already carries a `timescale  -> unchanged, reason
    ALREADY_DECLARED (the file already states its own unit);
  * the design input carries a `timescale directive -> that exact unit is
    prepended, reason DECLARED_IN_INPUT with the source named;
  * nothing declares one -> the RTL is returned BYTE-IDENTICAL and the refusal
    is returned BY NAME as NO_DECLARED_TIME_UNIT, naming the files searched.

The refusal is the point. An emitter that guessed `1ns/1ps` would be picking a
unit the design never stated, and every delay in the file would then mean
something the author did not write; an emitter that says NO_DECLARED_TIME_UNIT
hands the reader the one fact that explains an order-dependent verdict.

§4.05: the input searched is the DESIGN INPUT ONLY — the prompt and the L
documents generated from it. No dataset testbench, reference or golden is opened.
chip-AGNOSTIC: a `timescale grammar; no design, vendor or SKU literal.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: `timescale <unit>/<precision>` — the only form that DECLARES a time unit.
TIMESCALE_RE = re.compile(
    r'`timescale\s+(\d+\s*[munpf]?s)\s*/\s*(\d+\s*[munpf]?s)', re.I)

ALREADY_DECLARED = "ALREADY_DECLARED"
DECLARED_IN_INPUT = "DECLARED_IN_INPUT"
NO_DECLARED_TIME_UNIT = "NO_DECLARED_TIME_UNIT"


def _norm(unit: str) -> str:
    return re.sub(r'\s+', '', unit).lower()


def declared_in_text(text: str) -> Optional[Tuple[str, str]]:
    """The (unit, precision) a text DECLARES, or None."""
    m = TIMESCALE_RE.search(text or "")
    return (_norm(m.group(1)), _norm(m.group(2))) if m else None


def design_input_files(project: Path) -> List[Path]:
    """The design INPUT this may read: the prompt and the L documents.

    Deliberately NOT the project's sim/ or testbench trees — §4.05. The list is
    returned even when the files are absent so a refusal can name what it looked
    for rather than only what it found.
    """
    project = Path(project)
    out: List[Path] = [
        project / "input" / "phase1_prompt.md",
        project / "input" / "phase1_structured.yaml",
    ]
    docs = project / "phase1" / "generated_docs"
    out.extend(sorted(docs.glob("L*.json")) if docs.is_dir() else [])
    for d in (project / "input" / "docs", project / "phase1" / "input_doc"):
        if d.is_dir():
            out.extend(sorted(p for p in d.rglob("*") if p.is_file()))
    return out


def declared_time_unit(project: Path) -> Tuple[Optional[Tuple[str, str]],
                                               Optional[Path], List[Path]]:
    """(unit_pair, source_file, files_searched) from the DESIGN INPUT only."""
    searched = design_input_files(project)
    for f in searched:
        try:
            if not f.is_file():
                continue
            found = declared_in_text(f.read_text(errors="replace"))
        except OSError:
            continue
        if found:
            return found, f, searched
    return None, None, searched


def stamp_rtl(rtl: str, project: Path) -> Dict[str, object]:
    """Return {'rtl', 'reason', 'timescale', 'source', 'searched'}.

    `rtl` comes back byte-identical unless a unit was DECLARED and the file did
    not already carry one.
    """
    already = declared_in_text(rtl)
    if already:
        return {"rtl": rtl, "reason": ALREADY_DECLARED,
                "timescale": "/".join(already), "source": None,
                "searched": []}
    unit, src, searched = declared_time_unit(project)
    if unit is None:
        return {"rtl": rtl, "reason": NO_DECLARED_TIME_UNIT,
                "timescale": None, "source": None,
                "searched": [str(p) for p in searched]}
    directive = f"`timescale {unit[0]}/{unit[1]}"
    return {"rtl": f"{directive}\n{rtl}", "reason": DECLARED_IN_INPUT,
            "timescale": "/".join(unit), "source": str(src),
            "searched": [str(p) for p in searched]}


def refusal_sentence(result: Dict[str, object]) -> Optional[str]:
    """The named refusal, in one sentence, or None when a unit was stated."""
    if result.get("reason") != NO_DECLARED_TIME_UNIT:
        return None
    n = len(result.get("searched") or [])
    return (f"{NO_DECLARED_TIME_UNIT}: no `timescale is declared by the design "
            f"input ({n} file(s) searched) and none may be invented — a file "
            f"with no time unit inherits the unit of whichever source the "
            f"simulator compiled first, so a delay-defined candidate can be "
            f"read in a different unit from the testbench that measures it.")
