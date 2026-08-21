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
from typing import Iterable, Optional, Union

ATTEST_NAME = ".emit_attestation.jsonl"
SAMPLE_EXTS = (".sv", ".v")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _resolve_generated_docs(src: Path) -> Optional[Path]:
    """Resolve the Phase-1 `generated_docs/` dir from a project root OR a
    docs dir. Tries `<src>/phase1/generated_docs`, `<src>/generated_docs`,
    then `<src>` itself (if it already holds L*.json). Returns None if none
    carries an L-doc."""
    src = Path(src)
    for cand in (src / "phase1" / "generated_docs", src / "generated_docs", src):
        if cand.is_dir() and any(cand.glob("L*.json")):
            return cand
    return None


def phase1_provenance(src: Union[Path, str, None]) -> dict:
    """Phase-1 PROVENANCE fingerprint for the design behind a sample: proof the
    RTL was derived from Phase-1 L*.json, not authored from the bare prompt with
    Phase 1 skipped. `src` is the project root or its `generated_docs/` dir.

    Returns `{"ran": True, "ldoc_count": N, "ldocs": [...], "digest": <sha256>}`
    when L-docs are present (digest binds the exact L-doc set + bytes, so a
    later L-doc edit / a different design's docs are distinguishable), else
    `{"ran": False}` — a Phase-1-skipping run is thereby recorded as NON-canonical."""
    if src is None:
        return {"ran": False}
    gd = _resolve_generated_docs(Path(src))
    if gd is None:
        return {"ran": False}
    ldocs = sorted(p for p in gd.glob("L*.json") if p.is_file())
    if not ldocs:
        return {"ran": False}
    h = hashlib.sha256()
    for p in ldocs:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_file(p).encode("utf-8"))
        h.update(b"\n")
    return {
        "ran": True,
        "ldoc_count": len(ldocs),
        "ldocs": [p.stem for p in ldocs],
        "digest": h.hexdigest(),
    }


def record(samples_dir: Path, sample_path: Path, gates: Iterable[str],
           shape: str = "",
           phase1: Union[Path, str, dict, None] = None) -> None:
    """Append an emit attestation for `sample_path` (already written under samples_dir).

    `phase1` records Phase-1 provenance — REQUIRED for a canonical attestation: a
    sample whose RTL did NOT flow through `(doc|prompt) → Phase1(L*.json) → Phase2`
    is non-canonical. Pass the project root / `generated_docs/` dir (fingerprinted
    via `phase1_provenance`) or a pre-computed provenance dict. Omitting it leaves
    the "phase1" key absent, which `verify()` flags as ungated by default."""
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
    if phase1 is not None:
        line["phase1"] = phase1 if isinstance(phase1, dict) else phase1_provenance(phase1)
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


def verify(samples_dir: Path, exts: Iterable[str] = SAMPLE_EXTS,
           require_phase1: bool = True):
    """Return (ok, ungated, total). `ungated` = scoreable samples that are NOT canonical:
      • NO attestation, or a sha256 that no longer matches the on-disk bytes
        (authored-direct into samples/ / mutated after emit), OR
      • (default) an attestation lacking Phase-1 provenance / `phase1.ran != True` —
        the RTL did not flow through `(doc|prompt) → Phase1(L*.json) → Phase2`.

    Phase-1 provenance is REQUIRED for canonical by default; pass
    `require_phase1=False` only for offline inspection of a pre-provenance run."""
    samples_dir = Path(samples_dir)
    att = _load(samples_dir)
    samples = sorted(p for p in samples_dir.iterdir()
                     if p.is_file() and p.suffix in tuple(exts) and not p.name.startswith("."))
    ungated = []
    for s in samples:
        rec = att.get(s.name)
        if not rec or rec.get("sha256") != sha256_file(s):
            ungated.append(s.name)
            continue
        if require_phase1 and not (rec.get("phase1") or {}).get("ran"):
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
