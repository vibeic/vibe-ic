#!/usr/bin/env python3
"""cvdp_prompt_export.py — context-COMPLETE author-input export for CVDP copilot.

The blind-authoring INPUT analogue of `cvdp_gate.py` being the sole EMIT path.

A CVDP copilot record's `input.context` is a dict `{"rtl/<name>.sv": "<content>"}`
of the ORIGINAL RTL the task asks the author to modify / lint / optimize / complete.
The official scorer drops exactly those files into `/code/rtl/` and compiles the
author's top against them, so an author that never sees `input.context` must
RE-INVENT the original module's name / ports / parameters / behaviour — which the
hidden harness then rejects (ELAB_ERROR or a functional mismatch).

This is GIVEN INPUT, not oracle data: the prompt literally says "modify this RTL".
The clean-room rule forbids the GOLDEN (`output.response`), the HARNESS, and OTHER
problems' materials — NOT a problem's own `input.context`. Hand-rolled exports that
emit only `{id, prompt}` silently strip it (prose-only "remember the context"
regresses — the GATE-AS-SOLE-EMIT-PATH lesson on the input side), so this program
makes the context-complete record the SOLE export path.

Emit (one of):
  - a single prompts JSONL of `{id, prompt, context}` (context = the rtl-file map,
    omitted when the record has none) — what the author / `cvdp_gate --prompts`
    and `--dataset` plumbing consume; or
  - `--batch-dir` + `--batch-size N`: the same records split into `batchNN.jsonl`
    for batch-agent fan-out.

chip-AGNOSTIC: pure dataset-field extraction; no IC / design specifics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _rtl_context(rec: dict) -> Dict[str, str]:
    """Return {path: content} of the record's `input.context` RTL files (an
    `rtl/<name>.sv|.v` -> source map). Tolerates `input.context` as a dict, a
    list of {name?/path?, content?/text?} entries, or a top-level `context`.
    Only files that carry source content are kept; empty when the record has
    none (a from-scratch / spec-only problem)."""
    ctx = None
    inp = rec.get("input")
    if isinstance(inp, dict):
        ctx = inp.get("context")
    if ctx is None:
        ctx = rec.get("context")
    out: Dict[str, str] = {}
    if isinstance(ctx, dict):
        for k, v in ctx.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):
                if v.strip():
                    out[k] = v
            elif isinstance(v, dict):
                # symmetry with the list branch below: a non-canonical HF dump
                # may wrap the source as {content|text: <src>} instead of a bare
                # string. Unwrap it so a GIVEN input.context file is never
                # silently re-blinded (this program's whole purpose is to stop
                # dropping input.context). Still input-side only — never output.
                inner = v.get("content")
                if inner is None:
                    inner = v.get("text")
                if isinstance(inner, str) and inner.strip():
                    out[k] = inner
    elif isinstance(ctx, list):
        for e in ctx:
            if not isinstance(e, dict):
                continue
            name = e.get("name") or e.get("path") or e.get("file")
            content = e.get("content")
            if content is None:
                content = e.get("text")
            if isinstance(name, str) and isinstance(content, str) and content.strip():
                out[name] = content
    return out


def _prompt_text(rec: dict) -> str:
    inp = rec.get("input")
    if isinstance(inp, dict):
        t = inp.get("prompt") or inp.get("question") or inp.get("text")
        if isinstance(t, str):
            return t
    # flat shapes (already-exported records)
    t = rec.get("prompt") or rec.get("input") or rec.get("question") or rec.get("text")
    return t if isinstance(t, str) else ""


def export_records(dataset: Path) -> Tuple[List[dict], int, int]:
    """Read the dataset JSONL and return (author_records, n_total, n_with_ctx).

    Each author record is `{id, prompt}` plus `context` (the rtl map) when the
    source record provides one — the SOLE context-complete author input."""
    records: List[dict] = []
    n_ctx = 0
    for ln in dataset.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = rec.get("id")
        if rid is None:
            continue
        out: dict = {"id": str(rid), "prompt": _prompt_text(rec)}
        ctx = _rtl_context(rec)
        if ctx:
            out["context"] = ctx
            n_ctx += 1
        records.append(out)
    return records, len(records), n_ctx


def _write_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Context-COMPLETE author-input export for CVDP copilot "
                    "(the input-side sole-source: never drops `input.context`).")
    ap.add_argument("--dataset", required=True,
                    help="source CVDP dataset JSONL (records carry input.context)")
    ap.add_argument("--out", default=None,
                    help="single prompts JSONL of {id, prompt, context}")
    ap.add_argument("--batch-dir", default=None,
                    help="instead of --out, split into batchNN.jsonl here")
    ap.add_argument("--batch-size", type=int, default=5,
                    help="records per batch file (with --batch-dir; default 5)")
    args = ap.parse_args(argv)

    ds = Path(args.dataset)
    if not ds.is_file():
        sys.stderr.write(f"cvdp_prompt_export: dataset not found: {ds}\n")
        return 2
    if not args.out and not args.batch_dir:
        sys.stderr.write("cvdp_prompt_export: need --out or --batch-dir\n")
        return 2

    records, n_total, n_ctx = export_records(ds)
    if not records:
        sys.stderr.write("cvdp_prompt_export: no records exported\n")
        return 1

    if args.out:
        _write_jsonl(Path(args.out), records)
    nb = 0
    if args.batch_dir:
        bd = Path(args.batch_dir)
        bd.mkdir(parents=True, exist_ok=True)
        size = max(1, args.batch_size)
        for k in range(0, len(records), size):
            nb += 1
            _write_jsonl(bd / f"batch{nb:02d}.jsonl", records[k:k + size])

    sys.stderr.write(
        f"cvdp_prompt_export: {n_total} records "
        f"({n_ctx} with input.context RTL preserved"
        f"{', ' + str(nb) + ' batches' if nb else ''})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
