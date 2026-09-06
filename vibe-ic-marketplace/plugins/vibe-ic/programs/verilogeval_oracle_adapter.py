#!/usr/bin/env python3
"""verilogeval_oracle_adapter.py — record-format mapping for the oracle sweep.

Thin by design. Everything this module knows is WHERE the VerilogEval pieces
live and WHAT the candidate file must be called; every verdict, every arm and
every judgement lives in `programs/oracle_self_consistency_sweep.py`, which is
benchmark-agnostic.

VerilogEval (both `dataset_spec-to-rtl` and `dataset_code-complete-iccad2023`)
is a flat Shape-C dataset:

    <dataset>/<Prob>_prompt.txt     the problem statement (the solver's input)
    <dataset>/<Prob>_test.sv        the hidden testbench
    <dataset>/<Prob>_ref.sv         the golden, as `module RefModule`
    <run>/samples/<Prob>_sample01.sv  the candidate, as `module TopModule`

The testbench compiles the candidate together with `_ref.sv` and compares the
two instances, so the only mapping needed to submit the golden AS the candidate
is the module rename RefModule -> TopModule. Measured on both datasets at
verilog-eval c498220d: all 312 `_ref.sv` files declare exactly one module and it
is `RefModule`, so the rename cannot collide with a helper module — and the
adapter refuses (rather than guesses) if that ever stops being true.
"""
from __future__ import annotations

import re
from pathlib import Path

GOLDEN_MODULE = "RefModule"
CANDIDATE_MODULE = "TopModule"

_MODULE_DECL_RE = re.compile(r"^[ \t]*module\s+(\w+)", re.M)


def problems(dataset: Path, entry: dict) -> list[str]:
    suffix = entry["layout"]["prompt_suffix"]
    return sorted(p.name[: -len(suffix)] for p in Path(dataset).glob(f"*{suffix}"))


def golden_candidate(dataset: Path, pid: str, entry: dict):
    """(sample relpath, candidate text, stub seed text) for ARM G."""
    ref = Path(dataset) / f"{pid}{entry['layout']['ref_suffix']}"
    text = ref.read_text(errors="replace")
    decls = _MODULE_DECL_RE.findall(text)
    if decls != [GOLDEN_MODULE]:
        raise ValueError(
            f"{ref.name} declares {decls!r}; this adapter maps a single "
            f"`{GOLDEN_MODULE}` to `{CANDIDATE_MODULE}` and will not guess "
            "which of several modules is the top")
    cand = re.sub(rf"\b{GOLDEN_MODULE}\b", CANDIDATE_MODULE, text)
    return (f"{pid}_sample01.sv", cand, cand)
