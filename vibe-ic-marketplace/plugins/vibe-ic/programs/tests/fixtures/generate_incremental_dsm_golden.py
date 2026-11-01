#!/usr/bin/env python3
"""Regenerate synthetic decoder records using the study's unmodified idsm.py.

Usage: python3 generate_incremental_dsm_golden.py /path/to/idsm.py output.json
This offline model is our synthetic generator, never a design/native oracle.
No product decoder is imported when generating the reference.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def generate(model_path):
    spec = importlib.util.spec_from_file_location("idsm", model_path)
    model = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = model
    spec.loader.exec_module(model)
    # Study's H_inf=1.4 path gains. Construct its denominator directly so
    # regeneration needs only numpy, not scipy's filter-design routines.
    k1, k2, k3 = .6668447509766403, .20462778018567096, .02759084217906796
    den = np.array([1., -3 + k1, 3 - 2*k1 + k2, -1 + k1 - k2 + k3])
    inputs = np.concatenate(([.03], model.series_inputs(.72, .03, length=64, tone_bin=9)))
    records = []
    for kind in ("ciff", "cifb"):
        for delay in (0, 1):
            gains = model.ciff_gains(den, delay)
            a = [.2, .35, .25] if kind == "ciff" else [.25, .25]
            ff = [gains[f"k{i+1}"] / np.prod(a[:i+1]) for i in range(3)]
            loop = model.Loop(kind=kind, a=a, b=a, c=ff if kind == "ciff" else (),
                              c0=1.0 if kind == "ciff" else 0.0,
                              k0=gains.get("k0", 0.0) if kind == "ciff" else 0.0, D=delay)
            for n in (511, 512):
                result = model.run(loop, inputs, n)
                records.append({"kind": kind, "delay": delay, "updates": n,
                    "a": a, "c": list(loop.c), "c0": loop.c0, "k0": loop.k0,
                    "inputs": inputs.tolist(),
                    "bits": ["".join("1" if v > 0 else "0" for v in stream)
                             for stream in result["v"].T],
                    "decoded": model.decode(loop, result["v"], n).tolist(),
                    "final_state": result["xN"][-1].tolist(),
                    "peaks": result["peak"].tolist()})
    loop = model.Loop(kind="ciff", a=[1., 1., 1.],
        c=[model.ciff_gains(den, 0)[f"k{i}"] for i in (1, 2, 3)], c0=1.)
    grid = np.arange(-110, 111) / 100
    stability = {"a": list(loop.a), "c": list(loop.c), "window": 512,
        "grid": grid.tolist(),
        "peaks_by_window": {str(n): model.run(loop, grid, n)["peak"].T.tolist()
                            for n in (64, 512, 2048)},
        "short_limit": model.stable_input_limit(loop, 512),
        "long_limit": model.stable_input_limit(loop, 512, long_window=True),
        "overload_peaks": [model.run(loop, np.array([1.1]), n)["peak"][:, 0].tolist()
                           for n in (512, 2048)]}
    return {"generator": "unmodified study idsm.py; synthetic offline model, not design oracle",
            "model_sha256": hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
            "records": records, "stability": stability}


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(generate(Path(sys.argv[1])), indent=2) + "\n")
