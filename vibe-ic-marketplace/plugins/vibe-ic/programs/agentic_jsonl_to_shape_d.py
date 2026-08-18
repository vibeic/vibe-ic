#!/usr/bin/env python3
"""agentic_jsonl_to_shape_d.py — generic agentic-JSONL → Shape-D project-dir extractor.

GENERAL, not benchmark-specific. Any open IC-design benchmark that ships rows
matching the canonical agentic schema (see SCHEMA below) maps to the Shape-D
project layout per benchmark/blind_instructions_shape_d.md.

This program does NOT know about any specific benchmark name. It auto-detects
which JSONL rows are agentic by checking for the schema's required keys, and
emits a project dir per row.  Benchmarks whose rows don't match the schema are
skipped (the run summary reports the count).

## Canonical Shape-D agentic JSONL row schema (auto-detected)

A row qualifies when ALL of these hold:
  - row["id"]      is a non-empty string                  (problem identifier)
  - row["prompt"]  is a non-empty string                  (NL prompt)
  - row["harness"] is a dict containing per-relpath files (hidden scorer)
At minimum one of:
  - row["context"] is a dict containing per-relpath files (blind inputs)
  - row contains additional schema-flexible keys (system_message, categories, ...)

This matches the schema used by CVDP v1.1.0 and any future open benchmark that
adopts the same prompt+context+harness packaging.

## Emitted Shape-D layout (per row)

    <rundir>/<row.id>/work/PROMPT.txt              ← row["prompt"]   (blind input)
    <rundir>/<row.id>/work/<context-relpaths>      ← row["context"][rel] (e.g. docs/spec.md)
    <rundir>/<row.id>/input/phase1_prompt.md       ← copy of prompt   (runner phase1 ingester)
    <rundir>/<row.id>/input/docs/design_description.md ← prompt + concatenated context (.md files)
    <rundir>/<row.id>/score/<harness-relpaths>     ← row["harness"][rel] (e.g. src/test_*.py)
    <rundir>/<row.id>/.row_meta.json               ← non-content row fields (id, categories, ...)

The `input/` mirror is what `vibe_ic_one_shot_runner.py`'s phase1 reads.
Without it the user has to manually duplicate `work/PROMPT.txt` →
`input/phase1_prompt.md` before invoking the runner. Captured at v0.1.59.

Plus, at the run dir root:
    <rundir>/problems.list                     ← deduped row IDs
    <rundir>/.bench_config.json                ← extractor stats (bench-agnostic)

## Honesty (per open-benchmark-methodology skill § 4)

This extractor is OUT OF SCOPE for the harness contents — it just copies them
into score/ verbatim. The AI authoring the RTL must NEVER open files under
score/ (the blind rule). The extractor does NOT peek at harness assertions,
golden outputs, or test names to seed any extraction hints.

Usage:
    python3 agentic_jsonl_to_shape_d.py --dataset <DIR-of-JSONL> --rundir <OUT>
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


# Keys that, if present at the row top level, are content-as-files (NOT metadata)
# and get emitted under work/ rather than score/.  Anything that LOOKS like a
# dict-of-relpaths becomes either context (work/) or harness (score/) — see
# CONTEXT_KEY / HARNESS_KEY constants. All other top-level scalars become
# .row_meta.json fields.
ROW_ID_KEY      = "id"
PROMPT_KEY      = "prompt"
CONTEXT_KEY     = "context"   # → work/<relpath>
HARNESS_KEY     = "harness"   # → score/<relpath>
SYSMSG_KEY      = "system_message"


def _is_agentic_row(row: dict) -> bool:
    """The schema gate: row is agentic iff it has id + prompt + harness-as-dict.

    `context` is optional (some rows have only PROMPT.txt + hidden harness).
    Rows that look like nonagentic code-comprehension (input.prompt /
    output.response) won't satisfy this and are skipped.
    """
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get(ROW_ID_KEY), str) or not row[ROW_ID_KEY]:
        return False
    if not isinstance(row.get(PROMPT_KEY), str) or not row[PROMPT_KEY]:
        return False
    if not isinstance(row.get(HARNESS_KEY), dict) or not row[HARNESS_KEY]:
        return False
    return True


def _emit_files(root: Path, mapping: dict) -> int:
    """Write each {relpath: content} pair under `root`. Returns file count."""
    n = 0
    for rel, content in mapping.items():
        if not isinstance(rel, str) or not rel:
            continue
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dst.write_bytes(content)
        else:
            dst.write_text(str(content))
        n += 1
    return n


def extract_row(row: dict, rundir: Path) -> Path:
    """Emit one Shape-D project dir for an agentic row. Returns the project dir."""
    pid = row[ROW_ID_KEY]
    proj = rundir / pid
    work = proj / "work"
    score = proj / "score"
    work.mkdir(parents=True, exist_ok=True)
    score.mkdir(parents=True, exist_ok=True)

    # 1. PROMPT.txt (mandatory)
    prompt_body = row[PROMPT_KEY]
    (work / "PROMPT.txt").write_text(prompt_body)

    # 2. Optional auxiliary AI prompt context (system_message etc.)
    sysmsg = row.get(SYSMSG_KEY)
    if isinstance(sysmsg, str) and sysmsg:
        (work / "SYSTEM_MESSAGE.txt").write_text(sysmsg)

    # 3. context → work/ (each relpath drops in as-is so docs/spec.md, verif/tb.sv etc.
    #    keep their natural Shape-D positions)
    ctx = row.get(CONTEXT_KEY) or {}
    if isinstance(ctx, dict):
        _emit_files(work, ctx)

    # 4. harness → score/ (HIDDEN from the AI per blind rule; we just stage it)
    _emit_files(score, row[HARNESS_KEY])

    # 5. v0.1.59 capture (R9): also stage the runner's input/ layout so
    # vibe_ic_one_shot_runner.py's phase1 ingester can read the prompt
    # without a manual mkdir+cp dance. The blind rule is preserved: input/
    # contains the SAME content as work/PROMPT.txt + work/<docs|verif>;
    # nothing under score/ is exposed.
    input_dir = proj / "input"
    input_docs = input_dir / "docs"
    input_docs.mkdir(parents=True, exist_ok=True)
    (input_dir / "phase1_prompt.md").write_text(prompt_body)
    # Concatenate prompt + any context-side .md docs into design_description.md
    composed = [prompt_body.rstrip() + "\n"]
    if isinstance(ctx, dict):
        for rel in sorted(ctx.keys()):
            if rel.endswith(".md") and rel.startswith("docs/"):
                v = ctx[rel]
                composed.append("\n" + (v if isinstance(v, str) else str(v)).rstrip() + "\n")
    (input_docs / "design_description.md").write_text("".join(composed))

    # 6. row metadata (everything that isn't content)
    content_keys = {PROMPT_KEY, CONTEXT_KEY, HARNESS_KEY, SYSMSG_KEY}
    meta = {k: v for k, v in row.items() if k not in content_keys}
    (proj / ".row_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return proj


def walk_jsonl(jsonl_path: Path) -> Iterable[dict]:
    """Yield one row dict per line, skipping malformed lines with a stderr warn."""
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARN: bad JSON in {jsonl_path}: {e}", file=sys.stderr)


def extract_dataset(dataset: Path, rundir: Path, pattern: str) -> dict:
    """Walk all JSONL files matching `pattern` under `dataset`; emit projects.

    Returns a stats dict. Rows are deduped by id across files (with-solutions
    vs no-solutions of the same dataset ship the same ids).
    """
    files = sorted(dataset.glob(pattern))
    if not files:
        files = sorted(dataset.glob("*.jsonl"))
    if not files:
        return {"jsonl_files": 0, "rows_seen": 0, "agentic_emitted": 0,
                "non_agentic_skipped": 0, "ids": []}

    seen_ids: set[str] = set()
    ids: list[str] = []
    rows_seen = 0
    non_agentic = 0
    for jp in files:
        for row in walk_jsonl(jp):
            rows_seen += 1
            if not _is_agentic_row(row):
                non_agentic += 1
                continue
            pid = row[ROW_ID_KEY]
            extract_row(row, rundir)
            if pid not in seen_ids:
                seen_ids.add(pid)
                ids.append(pid)

    return {"jsonl_files": len(files), "rows_seen": rows_seen,
            "agentic_emitted": len(ids), "non_agentic_skipped": non_agentic,
            "ids": ids}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", required=True,
                    help="Directory containing JSONL files of agentic rows")
    ap.add_argument("--rundir", required=True,
                    help="Output run-dir root (will be created)")
    ap.add_argument("--pattern", default="*.jsonl",
                    help="Glob (under --dataset) of JSONL files to scan "
                         "(default: *.jsonl). Use this to restrict to one "
                         "split, e.g. '*_agentic_code_generation*.jsonl'.")
    a = ap.parse_args()

    dataset = Path(a.dataset).resolve()
    rundir = Path(a.rundir).resolve()
    if not dataset.is_dir():
        print(f"ERROR: --dataset not a directory: {dataset}", file=sys.stderr)
        return 2
    rundir.mkdir(parents=True, exist_ok=True)

    stats = extract_dataset(dataset, rundir, a.pattern)
    (rundir / "problems.list").write_text("\n".join(stats["ids"]) + "\n")
    (rundir / ".bench_config.json").write_text(json.dumps({
        "dataset": str(dataset),
        "extractor": "agentic_jsonl_to_shape_d.py",
        "pattern": a.pattern,
        "jsonl_files": stats["jsonl_files"],
        "rows_seen": stats["rows_seen"],
        "agentic_emitted": stats["agentic_emitted"],
        "non_agentic_skipped": stats["non_agentic_skipped"],
    }, indent=2) + "\n")

    print(f"Agentic JSONL → Shape-D: {rundir}")
    print(f"  JSONL files scanned: {stats['jsonl_files']}")
    print(f"  rows seen:           {stats['rows_seen']}")
    print(f"  agentic projects:    {stats['agentic_emitted']}")
    print(f"  non-agentic skipped: {stats['non_agentic_skipped']}")
    print(f"  problems.list:       {rundir / 'problems.list'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
