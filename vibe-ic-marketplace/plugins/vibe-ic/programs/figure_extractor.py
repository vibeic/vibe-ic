#!/usr/bin/env python3
"""figure_extractor.py — the VISION tier's deterministic program side.

A diagram in a design doc (state diagram, timing/waveform, block diagram, circuit
schematic, floorplan) is an IMAGE — the program cannot parse the picture, but it CAN
deterministically (a) find every figure reference + caption, (b) classify it by its
caption to the right vision element_type, and (c) route it `lead="vision"` with the
figure number / image reference so the runtime VISION pass (an image model, supplied
by the caller exactly like the AI text pass) interprets the picture into structured
data ({states,edges} / {signals,edges} / {modules,dataflow} / ...).

This makes the vision tier first-class in the dual-pass baseline: the program emits
the figure inventory + routing; the vision pass fills each figure's `data`. Sources:
markdown images `![alt](path)`, numbered captions `Figure N: ...` / `Fig. N - ...`.
chip-AGNOSTIC, pure regex.
"""
from __future__ import annotations
import re
from typing import Dict, List

_FIG_CLASS = (
    ("state_diagram", r"state\s+(?:diagram|machine|transition|bubble)|bubble\s+diagram"),
    ("timing_diagram", r"timing\s+diagram|waveform"),
    ("block_diagram", r"block\s+diagram|architecture(?:\s+diagram)?|top[- ]level\s+diagram|datapath\s+diagram"),
    ("circuit_schematic", r"schematic|circuit\s+diagram|gate[- ]level|transistor[- ]level"),
    ("floorplan_spec", r"floorplan|layout\s+(?:diagram|plot)?|placement\s+diagram|die\s+plot"),
)


def _classify(caption: str) -> str:
    for etype, pat in _FIG_CLASS:
        if re.search(pat, caption, re.I):
            return etype
    return "figure"        # a figure we cannot type from the caption (still vision-routed)


def extract_figures(text: str) -> List[Dict]:
    """[{element_type, data{lead:'vision', caption, figure, ref}}] for every figure
    reference in the doc. [] when none. Deduped by (type, caption)."""
    figs: List[Dict] = []
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", text):
        figs.append({"caption": m.group(1).strip(), "ref": m.group(2).strip()})
    for m in re.finditer(r"\b(?:figure|fig\.?)\s+([0-9]+|[A-Za-z])\s*[:.\-)]\s+([^\n]{3,120})",
                         text, re.I):
        figs.append({"figure": m.group(1), "caption": m.group(2).strip()})
    out, seen = [], set()
    for f in figs:
        cap = f.get("caption", "")
        if not cap and "ref" not in f:
            continue
        etype = _classify(cap)
        key = (etype, cap[:48].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"element_type": etype, "data": {"lead": "vision", **f}})
    return out


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True)
    a = ap.parse_args()
    print(json.dumps(extract_figures(Path(a.doc).read_text(errors="replace")), indent=2))
