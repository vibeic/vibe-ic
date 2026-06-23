#!/usr/bin/env python3
"""emit_attestation.py — GATE-AS-SOLE-EMIT-PATH enforcement (shared helper).

WHY: the canonical run-shapes route every authored sample through the deterministic
emit path — `gates_atomic.py` (Shape C) / `shape_b_sample_export.py` (Shape B) — which
applies the structural / functional emit gates (spec-conformance, K-map / worked-example
oracle, divider phase-form, power-up hygiene) and the port-reorder, and emits the sample to
`samples/` ONLY on a clean pass. But nothing PROVED a sample reached `samples/` that way: an
agent could author a sample directly into `samples/`, bypass every gate, and the host scorer
would happily score it — publishing a number that measures "the raw LLM", not "the runner"
(and silently undercounting on emit-gate-recoverable designs, or worse, gaming the headline).

WHAT: when an emit-path program emits a sample it calls `record()`, which appends a line to
`<samples_dir>/.emit_attestation.jsonl` binding the sample's basename to the sha256 of its
exact bytes + the gate set that passed + the shape. `verify()` (used by
`emit_attestation_check.py`, wired into `benchmark_dispatch --score`) then asserts EVERY
scoreable sample carries a matching attestation whose sha256 equals the on-disk file — so a
directly-authored / gate-bypassing / post-emit-mutated sample is detectable and the run is
flagged NON-CANONICAL rather than published as a clean number.

chip-AGNOSTIC, deterministic, no network. The attestation file is hidden (dot-prefixed) so the
host scorer's `*.sv`/`*.v` glob ignores it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

ATTEST_NAME = ".emit_attestation.jsonl"
SAMPLE_EXTS = (".sv", ".v")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def record(samples_dir: Path, sample_path: Path, gates: Iterable[str],
           shape: str = "") -> None:
    """Append an emit attestation for `sample_path` (already written under samples_dir)."""
    samples_dir = Path(samples_dir)
    sample_path = Path(sample_path)
    if not sample_path.is_file():
        return
    line = {
        "sample": sample_path.name,
        "sha256": sha256_file(sample_path),
        "gates": sorted(set(g for g in gates if g)),
        "shape": shape,
    }
    samples_dir.mkdir(parents=True, exist_ok=True)
    with (samples_dir / ATTEST_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def _load(samples_dir: Path) -> dict:
    """basename -> {sha256, gates, shape} (last attestation wins for a basename)."""
    f = Path(samples_dir) / ATTEST_NAME
    out: dict = {}
    if not f.is_file():
        return out
    for ln in f.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
            if d.get("sample"):
                out[d["sample"]] = d
        except (ValueError, TypeError):
            continue
    return out


def verify(samples_dir: Path, exts: Iterable[str] = SAMPLE_EXTS):
    """Return (ok, ungated, total). `ungated` = scoreable samples with NO attestation or a
    sha256 that no longer matches the on-disk bytes (authored-direct / mutated after emit)."""
    samples_dir = Path(samples_dir)
    att = _load(samples_dir)
    samples = sorted(p for p in samples_dir.iterdir()
                     if p.is_file() and p.suffix in tuple(exts) and not p.name.startswith("."))
    ungated = []
    for s in samples:
        rec = att.get(s.name)
        if not rec or rec.get("sha256") != sha256_file(s):
            ungated.append(s.name)
    return (len(ungated) == 0, ungated, len(samples))


if __name__ == "__main__":  # tiny CLI for manual inspection
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("samples_dir", type=Path)
    a = ap.parse_args()
    ok, ungated, total = verify(a.samples_dir)
    print(f"{'OK' if ok else 'UNGATED'}: {total - len(ungated)}/{total} attested; "
          f"ungated={ungated[:10]}")
    raise SystemExit(0 if ok else 1)
