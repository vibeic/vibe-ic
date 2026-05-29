#!/usr/bin/env python3
"""cvdp_jsonl_extract.py — CVDP JSONL → Shape-D project-dir extractor.

Captured from v0.1.53 CVDP run (Bucket A landed v0.1.55, formerly the R4
backlog).  The CVDP public example dataset ships as 10 JSONL files
(agentic + nonagentic × code-gen + code-comp × commercial + no-commercial
× with-solutions).  This program walks the agentic_code_generation JSONL
files and emits Shape-D project dirs per benchmark-harness/
blind_instructions_shape_d.md:

    <rundir>/<problem_id>/work/PROMPT.txt                ← prompt
    <rundir>/<problem_id>/work/docs/specification.md     ← context["docs/specification.md"]
    <rundir>/<problem_id>/work/verif/<files>             ← context["verif/*"]
    <rundir>/<problem_id>/score/src/test_*.py            ← harness["src/test_*.py"]
    <rundir>/<problem_id>/score/src/harness_library.py   ← harness["src/harness_library.py"]
    <rundir>/<problem_id>/score/src/test_runner.py       ← harness["src/test_runner.py"]
    <rundir>/<problem_id>/score/src/.env                 ← harness["src/.env"]
    <rundir>/<problem_id>/score/docker-compose.yml       ← harness["docker-compose.yml"]
    <rundir>/<problem_id>/.cvdp_meta.json                ← id + categories

Plus a top-level <rundir>/problems.list with one problem_id per line, and
<rundir>/.bench_config.json with {bench: "cvdp", dataset: "<host>"}.

Nonagentic code-comprehension rows are a different task (explain-the-code,
not spec→RTL generation); they are Shape-E for vibe-ic and are NOT emitted
here.  Run `--include-nonagentic` to also emit them under a `.nonagentic`
sibling dir for inspection only — they will NOT score via
score_cocotb_mcp.py.

Schema reference: cvdp_benchmark v1.1.0 example_dataset.

Usage:
    python3 cvdp_jsonl_extract.py --dataset <DATASET_DIR> --rundir <RUNDIR>
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


# Files we KNOW belong in score/ (hidden harness — the blind rule forbids
# the AI reading them).  Anything not matching → emit under work/.
SCORE_PREFIXES_HARNESS = ("src/", "docker-compose.yml")
WORK_DOCS_KEYS = ("docs/",)
WORK_VERIF_KEYS = ("verif/",)


def _emit_dict_as_files(root: Path, mapping: dict, allowed_prefixes=None):
    """Write each key→value in `mapping` as a file under `root`.
    Keys are relative paths.  Optionally filter by prefix tuple."""
    n = 0
    for rel_path, content in mapping.items():
        if allowed_prefixes is not None and not any(
                rel_path == p or rel_path.startswith(p) for p in allowed_prefixes):
            continue
        dst = root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dst.write_bytes(content)
        else:
            dst.write_text(str(content))
        n += 1
    return n


def extract_one_agentic(row: dict, rundir: Path) -> tuple[bool, str, Path | None]:
    """Emit a Shape-D project dir for one agentic_code_generation row.

    Returns (ok, problem_id, project_dir_or_None).
    """
    pid = row.get("id")
    if not pid:
        return False, "<missing-id>", None
    proj = rundir / pid
    proj.mkdir(parents=True, exist_ok=True)

    # 1. PROMPT.txt + system_message
    prompt = row.get("prompt") or ""
    sys_msg = row.get("system_message") or ""
    work = proj / "work"
    work.mkdir(exist_ok=True)
    (work / "PROMPT.txt").write_text(prompt)
    if sys_msg:
        (work / "SYSTEM_MESSAGE.txt").write_text(sys_msg)

    # 2. context — split into work/docs/* and work/verif/*
    ctx = row.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    _emit_dict_as_files(work, ctx,
                        allowed_prefixes=WORK_DOCS_KEYS + WORK_VERIF_KEYS)

    # 3. harness — emit under score/ (HIDDEN from AI per Shape-D blind rule)
    harness = row.get("harness") or {}
    if not isinstance(harness, dict):
        harness = {}
    score = proj / "score"
    score.mkdir(exist_ok=True)
    _emit_dict_as_files(score, harness, allowed_prefixes=SCORE_PREFIXES_HARNESS)

    # 4. metadata
    meta = {"id": pid, "categories": row.get("categories") or [],
            "schema": "agentic_code_generation"}
    (proj / ".cvdp_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    return True, pid, proj


def extract_jsonl(jsonl_path: Path, rundir: Path,
                  include_nonagentic: bool = False) -> dict:
    """Walk one JSONL file → emit project dirs.  Returns stats dict."""
    stats = {"file": str(jsonl_path), "agentic_emitted": 0,
             "nonagentic_skipped": 0, "rows_total": 0, "ids": []}
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARN: bad JSON in {jsonl_path}: {e}", file=sys.stderr)
                continue
            stats["rows_total"] += 1
            # agentic schema has top-level "prompt"; nonagentic has "input"
            if "prompt" in row and "harness" in row:
                ok, pid, _ = extract_one_agentic(row, rundir)
                if ok:
                    stats["agentic_emitted"] += 1
                    stats["ids"].append(pid)
            else:
                stats["nonagentic_skipped"] += 1
                if include_nonagentic:
                    # Stub emit to .nonagentic/ for inspection
                    pid = row.get("id") or "unknown"
                    nproj = rundir / ".nonagentic" / pid
                    nproj.mkdir(parents=True, exist_ok=True)
                    (nproj / "row.json").write_text(
                        json.dumps(row, indent=2) + "\n")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", required=True,
                    help="Path to cvdp_benchmark/example_dataset/ (or any dir of JSONL)")
    ap.add_argument("--rundir", required=True, help="Output run dir (will be created)")
    ap.add_argument("--include-nonagentic", action="store_true",
                    help="Also stub-emit nonagentic rows under .nonagentic/ (NOT scorable)")
    ap.add_argument("--pattern", default="cvdp_*_agentic_*.jsonl",
                    help="Glob (under --dataset) of JSONL files to extract (default: agentic only)")
    a = ap.parse_args()

    dataset = Path(a.dataset).resolve()
    rundir = Path(a.rundir).resolve()
    if not dataset.is_dir():
        print(f"ERROR: --dataset not a directory: {dataset}", file=sys.stderr)
        return 2
    rundir.mkdir(parents=True, exist_ok=True)

    jsonl_files = sorted(dataset.glob(a.pattern))
    if not jsonl_files:
        # Fallback: try a few well-known names
        jsonl_files = sorted(dataset.glob("*.jsonl"))
    if not jsonl_files:
        print(f"ERROR: no JSONL files in {dataset}", file=sys.stderr)
        return 2

    total_emitted = 0
    all_ids: list[str] = []
    per_file_stats = []
    for jp in jsonl_files:
        s = extract_jsonl(jp, rundir, a.include_nonagentic)
        per_file_stats.append(s)
        total_emitted += s["agentic_emitted"]
        all_ids.extend(s["ids"])

    # Top-level manifests
    # Dedupe IDs (with-solutions and without-solutions JSONLs share IDs;
    # the later write wins — fine for blind authoring, the harness files
    # are the same in both files)
    seen = set()
    deduped_ids = []
    for pid in all_ids:
        if pid not in seen:
            seen.add(pid)
            deduped_ids.append(pid)
    (rundir / "problems.list").write_text("\n".join(deduped_ids) + "\n")
    (rundir / ".bench_config.json").write_text(json.dumps(
        {"bench": "cvdp", "dataset": str(dataset),
         "extractor": "cvdp_jsonl_extract.py",
         "agentic_emitted": len(deduped_ids),
         "rows_seen": sum(s["rows_total"] for s in per_file_stats)},
        indent=2) + "\n")

    print(f"CVDP extract → {rundir}")
    print(f"  JSONL files scanned: {len(jsonl_files)}")
    print(f"  agentic projects:    {len(deduped_ids)}")
    print(f"  nonagentic skipped:  {sum(s['nonagentic_skipped'] for s in per_file_stats)}")
    print(f"  problems.list:       {rundir / 'problems.list'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
