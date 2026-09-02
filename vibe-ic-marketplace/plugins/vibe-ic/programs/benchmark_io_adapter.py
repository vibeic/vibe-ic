#!/usr/bin/env python3
r"""benchmark_io_adapter.py — the ONLY place a benchmark's file format may appear.

WHY THIS FILE IS ALLOWED TO KNOW BENCHMARK NAMES, AND NOTHING ELSE IS
=====================================================================
§ 0 GENERAL-CORE / THIN-ADAPTER: a benchmark-named file is legitimate ONLY as
the IO shell that maps a dataset's record format to a project layout and back.
Everything between IN and OUT is the general flow. So this module does exactly
two things, per format:

    stage(problem)   dataset record/files  ->  <project>/input/...
    collect(project) <project> artefacts   ->  the response the scorer reads

and holds no solving logic whatsoever. If you find yourself adding a rule here
about HOW to build RTL, it belongs in the general layer instead.

THE INPUT / ORACLE SPLIT IS DATA, AND IT IS ENFORCED
====================================================
Every dataset ships the answer next to the question:

    VerilogEval   Prob042_prompt.txt   INPUT
                  Prob042_ref.sv       ORACLE (the golden)
                  Prob042_test.sv      ORACLE (the grading testbench)
    RTLLM         design_description.txt  INPUT
                  verified_*.v            ORACLE
                  testbench.v             ORACLE
    CVDP          input.prompt/.context   INPUT
                  output.*, harness       ORACLE

§ 4.05 says read only the INPUT. Stated as prose, that is a rule an agent has to
remember — and this repo has measured what happens to rules agents have to
remember (v0.1.25: the in-gate fix held across 17 fresh agents, the same content
as free-text guidance regressed). So the split is a TABLE, and `open_input()`
RAISES on an oracle path. A staging bug becomes an exception instead of a
quietly contaminated number.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import rtl_final_bundle_integrity as bundle_integrity  # noqa: E402


class OracleAccess(RuntimeError):
    """Raised when something tries to read a file the grader owns."""


# ── the formats, declaratively ───────────────────────────────────────────────
# `input_globs` / `oracle_globs` are matched against the problem-relative name.
# A file matching NEITHER is unclassified and is treated as ORACLE: an unknown
# file next to a golden is far more likely to be part of the answer than part of
# the question, so the safe default is to refuse it.
FORMATS: Dict[str, Dict[str, Any]] = {
    "verilogeval": {
        "kind": "dir_of_files",
        "problem_glob": "*_prompt.txt",
        "problem_id": r"^(.*)_prompt\.txt$",
        "input_globs": ["*_prompt.txt"],
        "oracle_globs": ["*_ref.sv", "*_test.sv"],
        "prompt_from": "*_prompt.txt",
        "response": {"kind": "file", "path": "samples/{id}_sample01.sv"},
    },
    "rtllm": {
        "kind": "dir_of_dirs",
        "problem_marker": "design_description.txt",
        "input_globs": ["design_description.txt"],
        "oracle_globs": ["verified_*.v", "testbench.v", "makefile", "*_tb.v"],
        "prompt_from": "design_description.txt",
        "response": {"kind": "dir", "path": "{id}/"},
    },
    "cvdp": {
        "kind": "jsonl",
        "record_id": "id",
        "input_fields": ["input.prompt", "input.context"],
        "oracle_fields": ["output", "harness"],
        "prompt_from": "input.prompt",
        "context_from": "input.context",
        "response": {"kind": "jsonl_record", "fields": ["id", "completion"]},
    },
}

# What a user is likely to type -> the registry key. A front door that answers
# "unknown benchmark: verilogeval-v1" to someone who typed a name from our own
# README is a front door with a lock on it.
NAME_ALIASES: Dict[str, str] = {
    "ve": "verilogeval-v2", "ve-v1": "verilogeval-human",
    "ve-v2": "verilogeval-v2", "ve-human": "verilogeval-human",
    "verilogeval": "verilogeval-v2", "verilogeval-v1": "verilogeval-human",
    "verilog-eval": "verilogeval-v2",
    "rtllm": "rtllm", "rtllm-v2": "rtllm", "rtllm2": "rtllm",
    "cvdp": "cvdp-open", "cvdp-open": "cvdp-open", "cvdp_open": "cvdp-open",
}


def resolve_name(user_text: str) -> Optional[str]:
    """The registry key a user's spelling means, or None."""
    k = str(user_text or "").strip().lower().replace("_", "-")
    return NAME_ALIASES.get(k)


def _classify(fmt: Dict[str, Any], rel_name: str) -> str:
    for g in fmt.get("oracle_globs") or []:
        if fnmatch.fnmatch(rel_name, g):
            return "oracle"
    for g in fmt.get("input_globs") or []:
        if fnmatch.fnmatch(rel_name, g):
            return "input"
    return "oracle"          # unclassified defaults to oracle, deliberately


def open_input(fmt_name: str, path: Path, problem_root: Path) -> str:
    """Read a file the run is ALLOWED to read. Raises on anything else."""
    fmt = FORMATS[fmt_name]
    try:
        rel = str(Path(path).relative_to(problem_root))
    except ValueError:
        rel = Path(path).name
    kind = _classify(fmt, Path(rel).name)
    if kind != "input":
        raise OracleAccess(
            f"{path} is {kind} for format {fmt_name!r} — the grader owns it. "
            f"Reading it would contaminate the number this run produces, so "
            f"this is a refusal, not a warning.")
    return Path(path).read_text(errors="replace")


def problems(fmt_name: str, dataset: Path) -> Iterator[Dict[str, Any]]:
    """Enumerate a dataset's problems. INPUT files only; oracles never listed."""
    fmt = FORMATS[fmt_name]
    ds = Path(dataset)
    kind = fmt["kind"]
    if kind == "dir_of_files":
        rx = re.compile(fmt["problem_id"])
        for f in sorted(ds.glob(fmt["problem_glob"])):
            m = rx.match(f.name)
            if m:
                yield {"id": m.group(1), "root": ds, "prompt_path": f}
    elif kind == "dir_of_dirs":
        marker = fmt["problem_marker"]
        for f in sorted(ds.rglob(marker)):
            yield {"id": f.parent.name, "root": f.parent, "prompt_path": f}
    elif kind == "jsonl":
        for line in ds.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get(fmt["record_id"]):
                yield {"id": rec[fmt["record_id"]], "root": ds, "record": rec}
    else:
        raise ValueError(f"unknown format kind {kind!r}")


def stage(fmt_name: str, problem: Dict[str, Any], project: Path) -> Dict[str, Any]:
    """Write the problem's INPUT into a project the general flow can enter.

    The prompt lands at BOTH `input/phase1_prompt.md` and
    `input/docs/design_description.md` because the Phase-1 ingester consumes the
    latter while the runner detects the former; supplied RTL lands at
    `input/rtl/`, which is a recognised build-RTL source root.
    """
    fmt = FORMATS[fmt_name]
    project = Path(project)
    (project / "input" / "docs").mkdir(parents=True, exist_ok=True)
    staged: List[str] = []

    if fmt["kind"] == "jsonl":
        rec = problem["record"]
        prompt = ((rec.get("input") or {}).get("prompt")) or ""
        ctx = (rec.get("input") or {}).get("context") or {}
        for key in fmt.get("oracle_fields") or []:
            if key in rec and key not in ("input",):
                pass          # present in the record; simply never read
        for path, text in ctx.items():
            if Path(path).suffix in (".v", ".sv", ".vh", ".svh"):
                f = project / "input" / "rtl" / Path(path).name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
                staged.append(str(f.relative_to(project)))
    else:
        prompt = open_input(fmt_name, problem["prompt_path"], problem["root"])

    (project / "input" / "phase1_prompt.md").write_text(prompt)
    (project / "input" / "docs" / "design_description.md").write_text(prompt)
    staged += ["input/phase1_prompt.md", "input/docs/design_description.md"]
    return {"id": problem["id"], "project": str(project), "staged": staged,
            "prompt_chars": len(prompt)}


def collect(fmt_name: str, problem_id: str, project: Path, *,
            supplied_rtl: bool = False) -> Dict[str, Any]:
    """The answer artefact, in the shape the scorer reads — or a refusal.

    Always step 1's RTL (`phase2/stage1/rtl/*`) — measured: every open RTL
    benchmark's scorer reads RTL and none reads a netlist or a GDS.

    A FILE EXISTING IS NOT AN ANSWER. The first version of this function globbed
    the directory and reported ok=True on anything it found. Measured on a
    6-problem VerilogEval run: 4 of them had `rtl_gen` BLOCKED ("REFUSED TO RUN:
    1 declared input(s) ABSENT") and still carried a 67-byte
    `module chip_top(output out);` skeleton written by a scaffolding step — and
    `--solve` reported **6/6 produced an artefact**. It would have handed four
    empty modules to a scorer and called it success.

    So the run's OWN VERDICT decides. Normally the step that owns this
    artefact must report PASS.  The sole exception is an explicitly supplied
    AI-backup/repair candidate: its re-entry run begins at step 2 so rtl_gen
    must report SKIPPED-BY-ENTRY, while all downstream PROGRAM gates run over
    the hash-bound supplied bytes.  Callers must opt into that exception with
    ``supplied_rtl=True``; an ordinary solve can therefore never promote a
    scaffold merely because its generation step was skipped.
    """
    project = Path(project)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl = sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))
    if not rtl:
        return {"id": problem_id, "ok": False,
                "reason": "no RTL at phase2/stage1/rtl/ — nothing to hand back"}

    verdict = _rtl_gen_verdict(project)
    if verdict is None:
        return {"id": problem_id, "ok": False, "rtl_gen": None,
                "reason": "the run wrote no phase2 report — cannot tell whether "
                          "this RTL was produced or merely scaffolded"}
    accepted_statuses = {"PASS"}
    if supplied_rtl:
        accepted_statuses.add("SKIPPED-BY-ENTRY")
    if verdict["status"] not in accepted_statuses:
        return {"id": problem_id, "ok": False, "rtl_gen": verdict["status"],
                "reason": f"rtl_gen reported {verdict['status']}, so what is on "
                          f"disk is scaffolding, not an answer: "
                          f"{verdict['detail'][:180]}"}

    text = "\n".join(f.read_text(errors="replace") for f in rtl)
    return {"id": problem_id, "ok": True, "completion": text,
            "rtl_gen": verdict["status"], "supplied_rtl": supplied_rtl,
            "files": [f.name for f in rtl]}


def _rtl_gen_verdict(project: Path) -> Optional[Dict[str, str]]:
    """What the run itself said about the step that owns the RTL."""
    rep = Path(project) / "reports" / "orchestrator" / "phase2_one_shot.json"
    if not rep.is_file():
        return None
    try:
        d = json.loads(rep.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    last = None
    for st in d.get("steps") or []:
        if st.get("name") == "rtl_gen":
            last = {"status": str(st.get("status")),
                    "detail": str(st.get("detail") or "")}
    return last


def cvdp_scorer_contracts(dataset: Path) -> Dict[str, List[str]]:
    """Return CVDP's scorer-visible response paths, never reference bytes.

    This is a POST-GENERATION scorer adapter. CVDP stores the file-envelope
    contract as the keys of output.context beside the hidden reference values.
    The authoring path must not read that object; the host scorer may read the
    keys only after Program First + AI Review acceptance is complete. Keeping
    this function here preserves the general-core/thin-adapter boundary: the
    contract can package already-accepted bytes, but cannot route or solve.
    """
    contracts: Dict[str, List[str]] = {}
    for raw in Path(dataset).read_text(errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        pid = record.get("id")
        output = record.get("output")
        context = output.get("context") if isinstance(output, dict) else None
        if not pid or not isinstance(context, dict):
            continue
        paths = [str(path) for path in context
                 if isinstance(path, str) and path]
        if paths:
            contracts[str(pid)] = paths
    return contracts


def cvdp_response_file_map(completion: str,
                           response_paths: List[str]) -> Dict[str, str]:
    """Decode exactly the file bytes the CVDP scorer will receive."""
    if len(response_paths) == 1:
        return {response_paths[0]: completion}
    try:
        payload = json.loads(completion)
    except json.JSONDecodeError as exc:
        raise ValueError(f"CVDP multi-file response is not JSON: {exc}") from exc
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, list):
        raise ValueError("CVDP multi-file response lacks a code list")
    files: Dict[str, str] = {}
    for item in code:
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError("CVDP code entries must be one-path objects")
        path, text = next(iter(item.items()))
        if not isinstance(path, str) or not isinstance(text, str):
            raise ValueError("CVDP code entry path and content must be strings")
        if path in files:
            raise ValueError(f"duplicate CVDP response path {path!r}")
        files[path] = text
    if list(files) != response_paths:
        raise ValueError("CVDP packaged path order differs from scorer contract")
    return files


def cvdp_package_response(snapshot_paths: List[Path],
                          source_paths: List[Path],
                          response_paths: List[str]) -> str:
    """Package exact accepted RTL bytes for CVDP's local-import scorer.

    One-file contracts receive bare RTL. Multi-file contracts receive the
    official code-map envelope. Mapping is by an exact source basename first,
    then by exact module-name == response basename, then by a single unique
    residual bijection. This is BLOCKING: anything ambiguous or missing is
    refused; a format adapter must never guess a transformation.
    """
    snapshots = [Path(p) for p in snapshot_paths]
    sources = [Path(p) for p in source_paths]
    if not snapshots or len(snapshots) != len(sources):
        raise ValueError("candidate snapshot/source path cardinality mismatch")
    if not all(path.is_file() for path in snapshots):
        raise ValueError("candidate snapshot RTL is absent")
    if not response_paths:
        raise ValueError("CVDP scorer response contract is absent")

    texts = [path.read_text(errors="replace") for path in snapshots]
    source_modules = [bundle_integrity.module_blocks(text) for text in texts]
    module_rows = [row for rows in source_modules for row in rows]
    module_counts: Dict[str, int] = {}
    for name, _body in module_rows:
        module_counts[name] = module_counts.get(name, 0) + 1
    duplicate_modules = sorted(
        name for name, count in module_counts.items() if count != 1)
    if duplicate_modules:
        raise ValueError("accepted RTL declares duplicate module(s): "
                         + ", ".join(duplicate_modules))
    combined = "\n".join(texts)
    if len(response_paths) == 1:
        return combined

    by_basename: Dict[str, tuple[str, set[str]]] = {}
    duplicate_basenames = set()
    for source, text, modules in zip(sources, texts, source_modules):
        name = source.name
        if name in by_basename:
            duplicate_basenames.add(name)
        by_basename[name] = (text, {module for module, _body in modules})
    for name in duplicate_basenames:
        by_basename.pop(name, None)

    by_module: Dict[str, str] = {}
    # #731 — SCAN the blanked text, SLICE the original. A commented-out
    # `endmodule` inside a module body ends the non-greedy `[\s\S]*?` early,
    # so `match.group(0)` is the module TRUNCATED at the comment: the packaged
    # RTL loses every line after it, including the real `endmodule`, and the
    # scorer receives a file that does not parse. Blanking is OFFSET-PRESERVING
    # precisely so the span can still index `combined` — this function's
    # contract is "exact accepted RTL bytes", and bytes with their comments
    # blanked out are not the accepted bytes.
    for name, body in module_rows:
        by_module[name] = body

    selected: List[Optional[Dict[str, Any]]] = [None] * len(response_paths)
    used_modules: set[str] = set()
    requested_stems = {Path(path).stem for path in response_paths}
    for index, response_path in enumerate(response_paths):
        basename = Path(response_path).name
        stem = Path(response_path).stem
        if basename in by_basename:
            source_body, names = by_basename[basename]
            claimed_by_another_path = names & (requested_stems - {stem})
        else:
            source_body, names, claimed_by_another_path = "", set(), set()
        if basename in by_basename and not claimed_by_another_path:
            body = source_body
            chosen_modules = names
            whole_source = True
        elif stem in by_module:
            body = by_module[stem]
            chosen_modules = {stem}
            whole_source = False
        else:
            continue
        if used_modules & chosen_modules:
            raise ValueError(
                f"accepted RTL mapping for {response_path!r} is ambiguous")
        used_modules.update(chosen_modules)
        selected[index] = {"body": body, "modules": set(chosen_modules),
                           "whole_source": whole_source}

    # An accepted source may contain several modules while the scorer asks for
    # one file per module. After every exact basename/module match, a SINGLE
    # unmatched response and a SINGLE unused module form a unique residual
    # bijection. This changes only the scorer envelope's path; it never edits
    # the reviewed RTL or guesses among two possible modules.
    missing = [index for index, value in enumerate(selected) if value is None]
    unused_modules = [
        (name, body) for name, body in by_module.items()
        if name not in used_modules
    ]
    if len(missing) == 1 and len(unused_modules) == 1:
        name, body = unused_modules[0]
        selected[missing[0]] = {"body": body, "modules": {name},
                                "whole_source": False}
        used_modules.add(name)
    for response_path, value in zip(response_paths, selected):
        if value is None:
            raise ValueError(
                f"accepted RTL cannot be mapped exactly to {response_path!r}")

    # Preserve every reviewed module.  A helper may move only when the module
    # already selected for exactly one response transitively instantiates it.
    # This repairs a deterministic file-envelope split without inventing RTL.
    all_names = set(by_module)
    dependencies = {
        name: bundle_integrity.module_dependencies(body, all_names)
        for name, body in by_module.items()
    }
    for orphan in [name for name in by_module if name not in used_modules]:
        owners = []
        for index, value in enumerate(selected):
            if value is None:
                continue
            reachable = set(value["modules"])
            pending = list(reachable)
            while pending:
                current = pending.pop()
                for dependency in dependencies.get(current, set()):
                    if dependency not in reachable:
                        reachable.add(dependency)
                        pending.append(dependency)
            if orphan in reachable:
                owners.append(index)
        if len(owners) != 1:
            continue
        selected[owners[0]]["modules"].add(orphan)
        selected[owners[0]]["whole_source"] = False
        used_modules.add(orphan)

    unrepresented = sorted(all_names - used_modules)
    if unrepresented:
        raise ValueError("accepted RTL module(s) would be dropped by the scorer "
                         "envelope: " + ", ".join(unrepresented))

    module_order = {name: index for index, (name, _body) in enumerate(module_rows)}
    for value in selected:
        if value is not None and not value["whole_source"]:
            value["body"] = "\n".join(
                by_module[name] for name in sorted(
                    value["modules"], key=module_order.__getitem__))

    packaged = []
    for response_path, value in zip(response_paths, selected):
        if value is None:
            raise ValueError(
                f"accepted RTL cannot be mapped exactly to {response_path!r}")
        packaged.append({response_path: value["body"]})
    packaged_counts: Dict[str, int] = {}
    for item in packaged:
        for body in item.values():
            for name, _module_body in bundle_integrity.module_blocks(body):
                packaged_counts[name] = packaged_counts.get(name, 0) + 1
    if packaged_counts != {name: 1 for name in all_names}:
        raise ValueError("packaged module inventory differs from reviewed RTL")
    return json.dumps({"code": packaged}, ensure_ascii=False)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect a benchmark's IO mapping.")
    ap.add_argument("--format", required=True, choices=sorted(FORMATS))
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args(argv)
    n = 0
    for p in problems(a.format, Path(a.dataset)):
        print(f"  {p['id']}")
        n += 1
        if n >= a.limit:
            break
    print(f"({n} shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
