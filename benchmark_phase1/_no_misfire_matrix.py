#!/usr/bin/env python3
"""No-misfire matrix for every AUTO_DISPATCH drop-in protocol synth.

For each *_protocol_synth.py exposing AUTO_DISPATCH=True + is_<base>, call its
detector on EVERY benchmark's content blob (generated L1-L3 + input_doc text).
A detector must fire ONLY on its own benchmark (named after the base). Any
other True is a cross-fire and is reported as FAIL.
"""
import glob, importlib, os, sys
from pathlib import Path

PROG = Path("/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs")
BENCH = Path("/home/reyerchu/vibe-ic/benchmark_phase1")
sys.path.insert(0, str(PROG))

def _safe(fn, blob):
    try:
        return bool(fn(blob))
    except Exception:
        return False

def blob_for(name):
    # Mirror the runner's [14e2b/15] auto-dispatch blob: input_doc FIRST,
    # then generated L1-L3 (so a head-based subject-dominance check sees the
    # source spec title, exactly as it does at dispatch time).
    b = ""
    idir = BENCH / name / "phase1" / "input_doc"
    if idir.is_dir():
        for f in sorted(idir.glob("*.txt")) + sorted(idir.glob("*.md")):
            try:
                b += f.read_text(errors="ignore")
            except Exception:
                pass
    gd = BENCH / name / "phase1" / "generated_docs"
    for n in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json"):
        p = gd / n
        if p.is_file():
            b += p.read_text()
    return b

benches = sorted(d.name for d in BENCH.iterdir()
                 if d.is_dir() and (d / "phase1" / "input_doc").is_dir())
blobs = {n: blob_for(n) for n in benches}

autodispatch = []
for path in sorted(PROG.glob("*_protocol_synth.py")):
    stem = path.stem
    base = stem[:-len("_protocol_synth")]
    try:
        mod = importlib.import_module(stem)
    except Exception as e:
        continue
    if not getattr(mod, "AUTO_DISPATCH", False):
        continue
    is_fn = getattr(mod, f"is_{base}", None)
    if callable(is_fn):
        autodispatch.append((base, is_fn))

print(f"AUTO_DISPATCH drop-ins: {[b for b,_ in autodispatch]}")
fails = 0
for base, is_fn in autodispatch:
    fired = [n for n in benches if _safe(is_fn, blobs[n])]
    own = base in fired
    foreign = [n for n in fired if n != base]
    status = "OK" if (own and not foreign) else "FAIL"
    if status == "FAIL":
        fails += 1
    print(f"  [{status}] is_{base}: own={own} foreign_fires={foreign}")
print(f"\n{'ALL_PASS' if fails == 0 else str(fails)+' CROSS-FIRE FAILURE(S)'}")
sys.exit(1 if fails else 0)
