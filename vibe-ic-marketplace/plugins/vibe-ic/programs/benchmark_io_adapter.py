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
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import rtl_final_bundle_integrity as bundle_integrity  # noqa: E402
from rtl_repair_contract import (  # noqa: E402
    load_json as _load_repair_json,
    validate_normal_repair_contract,
)
# R-0915-85 — THE VOCABULARY, IMPORTED RATHER THAN SPELLED.
# This module READS the runner's step table and decides on its words. Spelling
# them as bare literals is how `SKIPPED-BY-ENTRY` survived here after the word
# was deleted: nothing in this file or in the ratchet could see that the set
# below had stopped matching anything, and every supplied-RTL candidate was
# refused as scaffolding. Through the enum a deleted word is an AttributeError
# at import, and the import itself puts this file inside the ratchet's
# comparison pass.
import verdict as _V                                     # noqa: E402


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
    "agentic": {
        "kind": "agentic_project",
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


def _public_relative(name: str) -> Path:
    """Public-input roles do not grant permission to escape the input root."""
    path = Path(name)
    if (not name or path.is_absolute() or ".." in path.parts
            or "\\" in name or path.as_posix() != name or name == "."):
        raise ValueError("PUBLIC_INPUT_PATH_INVALID: expected a safe relative path")
    return path


def _public_source_hash(record: dict) -> str:
    identity = {key: record[key] for key in ("id", "prompt_sha256", "files")}
    return hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _public_write_once(path: Path, data: bytes) -> None:
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("PUBLIC_INPUT_CHANGED: symbolic link in source snapshot")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("PUBLIC_INPUT_CHANGED: immutable source bytes differ")


def _stage_public_original(problem_id: str, prompt: str, context: dict,
                           project: Path) -> dict:
    """Freeze only declared public input bytes BEFORE any runner transform.

    Hashes provide integrity and task binding, not OS-level author identity.
    No file is promoted from a candidate, repair parent, or unclassified root.
    """
    root = project.resolve() / "input" / "public_original"
    files = []
    for name, text in sorted(context.items()):
        relative = _public_relative(name)
        if not isinstance(text, str):
            raise ValueError("PUBLIC_INPUT_INVALID: context contents must be text")
        data = text.encode("utf-8")
        files.append({"relative_path": relative.as_posix(),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "bytes": len(data)})
    record = {"schema": "vibeic.public_original_input.v1",
              "role": "public_original_input", "id": str(problem_id),
              "status": "PRESENT" if files else "NOT_PROVIDED",
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "files": files}
    record["source_sha256"] = _public_source_hash(record)
    for item in files:
        _public_write_once(root / "files" / item["relative_path"],
                           context[item["relative_path"]].encode("utf-8"))
    _public_write_once(root / "manifest.json",
                       (json.dumps(record, sort_keys=True, indent=2) + "\n").encode())
    return record


def public_original_input(project: Path, problem_id: str, prompt_sha256: str,
                          expected: dict | None = None) -> dict:
    """BLOCKING on dropped/stale inputs; legacy missing is NOT_MEASURED.

    Consumers may allow only paths derived from this verified public manifest.
    A text-generation task explicitly staged without context is NOT_PROVIDED,
    never a fabricated baseline copied from its current RTL.
    """
    root = Path(project).resolve() / "input" / "public_original"
    missing = {"schema": "vibeic.public_original_input.v1",
               "role": "public_original_input", "id": str(problem_id),
               "prompt_sha256": prompt_sha256, "status": "NOT_MEASURED",
               "reason": "PUBLIC_INPUT_MANIFEST_NOT_RECORDED", "files": []}
    if not root.exists() and (expected is None or expected == missing):
        return missing
    try:
        if (root.is_symlink() or (root / "manifest.json").is_symlink()
                or any(p.is_symlink() for p in root.parents)):
            raise ValueError("snapshot root is a symbolic link")
        record = json.loads((root / "manifest.json").read_text())
        if (not isinstance(record, dict)
                or record.get("schema") != "vibeic.public_original_input.v1"
                or record.get("role") != "public_original_input"
                or record.get("id") != str(problem_id)
                or record.get("prompt_sha256") != prompt_sha256
                or record.get("source_sha256") != _public_source_hash(record)
                or (expected is not None and record != expected)):
            raise ValueError("source identity differs from the handoff")
        files = record["files"]
        if record.get("status") != ("PRESENT" if files else "NOT_PROVIDED"):
            raise ValueError("source presence declaration differs")
        names = [item["relative_path"] for item in files]
        if names != sorted(set(names)):
            raise ValueError("source file set is duplicated or unsorted")
        for item in files:
            path = root / "files" / _public_relative(item["relative_path"])
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise ValueError("source path is a symbolic link")
            data = path.read_bytes()
            if (hashlib.sha256(data).hexdigest() != item["sha256"]
                    or len(data) != item["bytes"]):
                raise ValueError("source bytes differ from the staged manifest")
        return record
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"PUBLIC_INPUT_HANDOFF_INVALID: {exc}") from exc


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
    ctx = {}

    if fmt["kind"] == "agentic_project":
        # The general extractor alone parses the JSONL. This adapter reads
        # only its visible work/input output; score and row metadata stay in
        # the coordinator's separate extraction root, never the solver tree.
        root = Path(problem["root"])
        prompt = (root / "input" / "phase1_prompt.md").read_text()
        ctx = {}
        for path in sorted((root / "work").rglob("*")):
            if path.is_symlink():
                raise ValueError("SHAPED_INPUT_PATH_INVALID: linked visible input")
            if path.is_file() and path != root / "work" / "PROMPT.txt":
                ctx[path.relative_to(root / "work").as_posix()] = path.read_text()
    elif fmt["kind"] == "jsonl":
        rec = problem["record"]
        prompt = ((rec.get("input") or {}).get("prompt")) or ""
        ctx = (rec.get("input") or {}).get("context") or {}
        for key in fmt.get("oracle_fields") or []:
            if key in rec and key not in ("input",):
                pass          # present in the record; simply never read
    else:
        prompt = open_input(fmt_name, problem["prompt_path"], problem["root"])

    original = _stage_public_original(problem["id"], prompt, ctx, project)
    destinations = set()
    for name, text in ctx.items():
        relative = _public_relative(name)
        # Preserve the dependency tree while retaining the canonical RTL root.
        if relative.parts[0] == "rtl":
            relative = Path(*relative.parts[1:])
        f = project / "input" / "rtl" / relative
        if f in destinations:
            raise ValueError("PUBLIC_INPUT_PATH_COLLISION: ambiguous staged path")
        destinations.add(f)
        _public_write_once(f, text.encode("utf-8"))
        staged.append(str(f.relative_to(project)))
    (project / "input" / "phase1_prompt.md").write_text(prompt)
    (project / "input" / "docs" / "design_description.md").write_text(prompt)
    if fmt["kind"] == "agentic_project":
        (project / "input" / "docs" / "design_description.md").write_text(
            (root / "input" / "docs" / "design_description.md").read_text())
        _public_write_once(project / "work" / "PROMPT.txt", prompt.encode())
        for name, text in ctx.items():
            _public_write_once(project / "work" / _public_relative(name), text.encode())
    staged += ["input/phase1_prompt.md", "input/docs/design_description.md"]
    return {"id": problem["id"], "project": str(project), "staged": staged,
            "prompt_chars": len(prompt), "public_original_input": original}


def collect(fmt_name: str, problem_id: str, project: Path, *,
            supplied_rtl: bool = False,
            required_top: Optional[str] = None,
            repair_contract=None,
            require_repair_contract: bool = False) -> Dict[str, Any]:
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

    NOR IS THE WRONG MODULE NAME AN ANSWER. When the benchmark's scorer
    instantiates one fixed top module (``module_name_strategy``), an artefact
    that never declares that module cannot be scored at all: the grading
    testbench fails to elaborate. Callers that know the required name pass it as
    ``required_top`` and this refuses the artefact, with `ok=False`, exactly as
    it refuses a scaffold.

    Refusing HERE is the whole point. The identical check already existed at the
    sample-export step, which is the last step of the run -- far past the point
    where anything could act on it. Measured on a 156-problem VerilogEval-v2
    run: one candidate was emitted as `module chip_top` with correct logic, and
    because the check lived only at export, (a) it was sent for AI review, where
    it CANNOT be failed, since the review contract requires a challenge
    testbench instantiating the missing module and such a testbench cannot
    elaborate, and (b) the all-or-nothing export then blocked the ENTIRE run's
    score. A defect the program can detect deterministically must be detected
    where the flow can still act on it -- here, which routes it to AI backup for
    re-authoring, the correct remedy.

    NOR IS ONE FILE THE DELIVERABLE (vibe-ic#2211). Everything above judges the
    generating STEP or a property of the concatenated text; nothing asked whether
    the complete set COMPILES. Measured on this tree at plugin 1.20.18: emit a
    normalized copy of the RTL back into the deliverable directory and
    `harness_exact_selfverify` returns rc 0 with all three of its gates PASS on
    the file it was handed, while `iverilog` on the resulting set exits 2 --
    "'test_unit' has already been declared in this scope". The per-file harness
    is not at fault; it verified exactly what it was given. The gap was that
    `ok=True` from HERE is what freezes the whole set (`_archive_candidate`) and
    sends it onward. So the exact ordered deliverable manifest is compiled here,
    bound to its own hashes, and a set that cannot compile is refused with the
    compiler's own words.
    """
    project = Path(project)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl = sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))
    if any(p.is_symlink() or any(parent.is_symlink() for parent in p.parents) for p in rtl):
        return {"id": problem_id, "ok": False, "reason": "candidate RTL contains a symlink"}
    if not rtl:
        return {"id": problem_id, "ok": False,
                "reason": "no RTL at phase2/stage1/rtl/ — nothing to hand back"}

    verdict = _rtl_gen_verdict(project)
    if verdict is None:
        return {"id": problem_id, "ok": False, "rtl_gen": None,
                "reason": "the run wrote no phase2 report — cannot tell whether "
                          "this RTL was produced or merely scaffolded"}
    accepted_statuses = {_V.Verdict.PASS.value}
    if supplied_rtl:
        # R-0915-85 — `SKIPPED-BY-ENTRY` is `NOT_APPLICABLE`, declared_by the
        # run's own `--entry-step`. MEASURED: both sites in
        # `design_one_shot_runner` that leave `rtl_gen` on this word say the
        # same thing — the RTL was SUPPLIED, not produced here (the entry-step
        # sentinel, and the DECLINE when the design ships its own build RTL).
        # That is exactly the claim `supplied_rtl=True` makes, and it is the
        # caller who makes it, so the word admits nothing the flag does not.
        # Left as the deleted word this set accepted NOTHING any producer
        # writes and every supplied-RTL candidate was refused as scaffolding.
        accepted_statuses.add(_V.Verdict.NOT_APPLICABLE.value)
    if verdict["status"] not in accepted_statuses:
        return {"id": problem_id, "ok": False, "rtl_gen": verdict["status"],
                "reason": f"rtl_gen reported {verdict['status']}, so what is on "
                          f"disk is scaffolding, not an answer: "
                          f"{verdict['detail'][:180]}"}

    # Read ONCE. Every fact below — the concatenation handed back as
    # `completion`, the per-file hashes, and the bytes that are compiled — comes
    # from this one read, so the bundle that was validated is provably the
    # bundle that is frozen (vibe-ic#2211).
    sources = [(f.name, f.read_text(errors="replace")) for f in rtl]
    text = "\n".join(body for _name, body in sources)
    if required_top and required_top not in _declared_module_names(text):
        return {"id": problem_id, "ok": False, "rtl_gen": verdict["status"],
                "declared_modules": _declared_module_names(text),
                "reason": (f"the scorer instantiates {required_top!r}, and this "
                           f"artefact declares no such module "
                           f"(declares: {', '.join(_declared_module_names(text)) or 'none'})"
                           " — the grading testbench could not elaborate against it")}
    # THE COMPLETE DELIVERABLE, NOT A FILE OF IT (vibe-ic#2211).
    #
    # Everything above this line is satisfiable by a bundle that cannot exist.
    # `rtl_gen` reports on the STEP; `required_top` is satisfied by a name
    # declared twice exactly as well as by one declared once; and the per-file
    # harness (`harness_exact_selfverify`) verifies the one file it is handed and
    # is entitled to say so. Measured on this tree, plugin 1.20.18: emit a
    # normalized copy of the RTL back into the deliverable directory and the
    # per-file harness returns rc 0 with all three of its gates PASS, while
    # `iverilog` on the resulting set exits 2 with "'test_unit' has already been
    # declared in this scope". `ok=True` here is what freezes that set
    # (`_archive_candidate`) and sends it to review, so the defect survived to
    # export — which is exactly the argument this function's own docstring
    # already makes about the required-top check.
    #
    # The compiler is the authority and the textual module count is NOT. The
    # sibling rule in `rtl_final_bundle_integrity._module_map` reports duplicate
    # ownership for `ifdef`-guarded alternatives, which are legal and compile
    # clean; only the compile separates those from a real redeclaration. So this
    # calls the SHARED `compile_source_manifest` — one implementation, also used
    # by the export-time `check_final_bundle` — and never a second textual
    # duplicate-module policy.
    #
    # A BLOCKED bundle is refused HERE, where the flow can still act on it: the
    # caller routes an `ok=False` candidate to AI backup for re-authoring, which
    # is the remedy. NOT_MEASURED (no `iverilog`, or a compile that outran its
    # timeout) is NEITHER — the candidate is admitted and the record says the
    # bundle compile was never measured, because a missing tool is not evidence
    # of a clean bundle and must not be reported as one.
    manifest = [{"path": name,
                 "sha256": hashlib.sha256(body.encode()).hexdigest()}
                for name, body in sources]
    # ORDER IS LOAD-BEARING. The cross-file view is pure; the compile is a
    # subprocess. Asking the cheap question first means the compiler is invoked
    # ONLY for a manifest that already looks wrong, so a well-formed candidate
    # costs nothing and this function stays inspect-only on the path every
    # candidate takes. Measured why that matters: running it unconditionally put
    # an `iverilog` call inside the solve path, and
    # `test_public_input_backup_provenance` -- which patches `bd.subprocess.run`,
    # i.e. the subprocess MODULE, and counts worker invocations -- saw 2 where it
    # requires 1. The gate had started answering for the runner.
    cross_file = _cross_file_duplicate_modules(sources)
    if cross_file:
        bundle_compile, manifest_reasons = (
            bundle_integrity.compile_source_manifest(dict(sources)))
    else:
        bundle_compile, manifest_reasons = {
            "status": "NOT_ATTEMPTED",
            "reason": ("no module in this manifest is declared by more than one "
                       "file, so there is no cross-file redeclaration for a "
                       "compile to confirm or refute here"),
        }, []
    bundle = {
        "source_manifest": manifest,
        "bundle_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "bundle_compile": bundle_compile,
        "bundle_manifest_findings": manifest_reasons,
        "cross_file_duplicate_modules": cross_file,
    }
    if cross_file and bundle_compile.get("status") == "BLOCKED":
        return {"id": problem_id, "ok": False, "rtl_gen": verdict["status"],
                "files": [name for name, _body in sources], **bundle,
                "reason": (
                    "the complete deliverable source manifest "
                    f"({', '.join(name for name, _b in sources)}) declares "
                    f"{', '.join(cross_file)} in more than one file and does "
                    f"not compile as a set, so this candidate cannot be "
                    f"scored: {str(bundle_compile.get('reason') or '')[:400]}")}

    # NORMAL REPAIR CONSUMER (issues #2852/#2853/#3655). benchmark_dispatch.py
    # already routes every ordinary completion through this adapter; keeping
    # the binding here gives the declaration one consumer for both contracts
    # without changing the dispatcher stack.  A declaration is opt-in for
    # legacy projects, but once present it is checked against the fresh source
    # bytes immediately before the accepted completion is returned.
    contract = repair_contract
    if contract is None and not require_repair_contract:
        for candidate in (
                project / "reports" / "rtl_repair_contract.json",
                project / "reports" / "repair_contract.json",
                project / "input" / "rtl_repair_contract.json"):
            if candidate.is_file():
                try:
                    contract = _load_repair_json(candidate)
                except (OSError, ValueError, TypeError) as exc:
                    contract = {"_load_error": str(exc)}
                break
    required_marker = (not require_repair_contract and
                       (project / "reports" / "rtl_repair_contract.required").is_file())
    if contract is not None or require_repair_contract or required_marker:
        if isinstance(contract, dict) and contract.get("_load_error"):
            repair_report = {"verdict": "REFUSED", "findings": [{
                "code": "DECLARATION_READ_ERROR", "message": contract["_load_error"]}]}
        else:
            if isinstance(contract, dict) and contract.get("schema") == "vibeic.rtl_preservation_declaration.v1":
                contract = {"preservation": contract}
            elif isinstance(contract, dict) and contract.get("schema") == "vibeic.public_elaboration_matrix.v1":
                contract = {"elaboration_matrix": contract}
            elif isinstance(contract, dict) and contract.get("schema") == "vibeic.native_structural_contract.v1":
                contract = {"structural": contract}
            original_root = project / "input" / "public_original" / "files"
            original_sources: Dict[str, str] = {}
            symlink_refused = False
            if original_root.is_dir():
                for source_path in sorted(original_root.rglob("*")):
                    if source_path.is_symlink() or any(parent.is_symlink() for parent in source_path.parents):
                        symlink_refused = True
                        break
                    if source_path.is_file():
                        original_sources[str(source_path.relative_to(original_root))] = \
                            source_path.read_text(errors="replace")
            candidate_sources = {}
            for name, body in sources:
                key = name[4:] if name.startswith("rtl/") else name
                if key in candidate_sources:
                    repair_report = {"verdict": "REFUSED", "findings": [{
                        "code": "SOURCE_PATH_COLLISION",
                        "message": "candidate paths collide after canonical rtl/ normalization"}]}
                candidate_sources[key] = body
            matrix = contract.get("elaboration_matrix", contract.get("public_elaboration_matrix")) \
                if isinstance(contract, dict) else None
            structural = contract.get("structural", contract.get("native_structural_contract")) \
                if isinstance(contract, dict) else None
            top = None
            if isinstance(matrix, dict):
                top = matrix.get("top", matrix.get("top_module"))
            if isinstance(structural, dict):
                top = structural.get("top") or top
            top = top or required_top
            source_for_matrix = None
            matrix_candidate_path = None
            source_for_structural = None
            structural_candidate_path = None
            repair_report = None
            if isinstance(matrix, dict):
                wanted = matrix.get("source_path", matrix.get("source"))
                if isinstance(wanted, dict):
                    wanted = wanted.get("path")
                if isinstance(wanted, str):
                    wanted = wanted[4:] if wanted.startswith("rtl/") else wanted
                    # A source-bound matrix is only meaningful when the exact
                    # declared path is present in both frozen maps.  Never
                    # fall back to a basename, concatenated candidate, or a
                    # different preservation source.
                    if wanted in original_sources and wanted in candidate_sources:
                        source_for_matrix = original_sources[wanted]
                        for source_path in rtl:
                            if str(source_path.relative_to(rtl_dir)) == wanted:
                                matrix_candidate_path = source_path
                                break
                    else:
                        repair_report = {"verdict": "REFUSED", "findings": [{
                            "code": "SOURCE_PATH_INVALID",
                            "message": "declared source_path is absent from the exact original and candidate maps"}]}
                    preservation = contract.get("preservation") if isinstance(contract, dict) else None
                    preservation_paths = set()
                    if isinstance(preservation, dict):
                        for row in preservation.get("sources") or []:
                            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                                continue
                            path_key = row["path"]
                            preservation_paths.add(
                                path_key[4:] if path_key.startswith("rtl/") else path_key)
                    if require_repair_contract and wanted not in preservation_paths:
                        repair_report = {"verdict": "REFUSED", "findings": [{
                            "code": "SOURCE_PATH_UNBOUND",
                            "message": "matrix source_path is absent from preservation sources"}]}
                if source_for_matrix is None and len(original_sources) == 1:
                    source_for_matrix = next(iter(original_sources.values()))
                if (matrix_candidate_path is None and not require_repair_contract
                        and len(rtl) == 1):
                    matrix_candidate_path = rtl[0]
            if isinstance(structural, dict):
                wanted = structural.get("source_path")
                if isinstance(wanted, str):
                    wanted = wanted[4:] if wanted.startswith("rtl/") else wanted
                    if wanted in original_sources and wanted in candidate_sources:
                        source_for_structural = original_sources[wanted]
                        for source_path in rtl:
                            if str(source_path.relative_to(rtl_dir)) == wanted:
                                structural_candidate_path = source_path
                                break
                    else:
                        repair_report = {"verdict": "REFUSED", "findings": [{
                            "code": "STRUCTURAL_SOURCE_PATH_INVALID",
                            "message": "structural source_path is absent from exact original and candidate maps"}]}
            if (matrix_candidate_path is not None and structural_candidate_path is not None
                    and matrix_candidate_path != structural_candidate_path):
                repair_report = {"verdict": "REFUSED", "findings": [{
                    "code": "REPAIR_CONTRACT_SOURCE_AMBIGUOUS",
                    "message": "elaboration and structural proof select different candidate sources"}]}
            with tempfile.TemporaryDirectory(prefix="rtl_repair_consumer_") as temp_dir:
                candidate_path = Path(temp_dir) / "candidate.sv"
                selected_candidate_path = matrix_candidate_path or structural_candidate_path
                if selected_candidate_path is not None:
                    # Freeze exactly the selected file once; matrix execution
                    # must never compile the concatenated multi-file answer.
                    candidate_path.write_bytes(selected_candidate_path.read_bytes())
                else:
                    candidate_path.write_text("")
                requirement_sources = {}
                prompt_path = project / "input" / "phase1_prompt.md"
                if (prompt_path.is_file() and not prompt_path.is_symlink()
                        and not any(parent.is_symlink() for parent in prompt_path.parents)):
                    requirement_sources["input/phase1_prompt.md"] = \
                        prompt_path.read_text(errors="replace")
                repair_report = (repair_report if isinstance(repair_report, dict) and repair_report.get("verdict") == "REFUSED" else ({"verdict": "REFUSED", "findings": [{
                    "code": "SOURCE_SYMLINK", "message": "public source manifest contains a symlink"}]}
                    if symlink_refused else validate_normal_repair_contract(
                        original_sources, candidate_sources, contract,
                        candidate_path=candidate_path,
                        original_source=source_for_matrix or source_for_structural,
                        top=top,
                        requirement_sources=requirement_sources,
                        require=True)))
        # Ordinary benchmark dispatch must consume both independently-bound
        # contracts immediately before completion; a single opt-in half is not
        # sufficient evidence for a repair candidate.
        if require_repair_contract and isinstance(contract, dict):
            if not contract.get("preservation") or not contract.get("elaboration_matrix"):
                repair_report = {"verdict": "REFUSED", "findings": [{
                    "code": "DECLARATION_INCOMPLETE",
                    "message": "normal benchmark completion requires preservation and elaboration_matrix contracts"}]}
        bundle["repair_contract"] = repair_report
        if repair_report.get("verdict") != "PASS":
            return {"id": problem_id, "ok": False,
                    "rtl_gen": verdict["status"],
                    "files": [name for name, _body in sources], **bundle,
                    "reason": ("source-bound RTL repair contract "
                               f"{repair_report.get('verdict')}: "
                               f"{str(repair_report.get('findings') or '')[:600]}")}
    return {"id": problem_id, "ok": True, "completion": text,
            "rtl_gen": verdict["status"], "supplied_rtl": supplied_rtl,
            "files": [name for name, _body in sources], **bundle}


def _cross_file_duplicate_modules(
        sources: List[tuple]) -> List[str]:
    """Module names declared by MORE THAN ONE file of the manifest.

    vibe-ic#2211, and the boundary is the whole point. A name declared twice
    across two files is a property of the SET: no single file is wrong, which is
    why a per-file harness can pass every one of them and the bundle still fails
    to compile. A name declared twice INSIDE one file is a property of that file,
    and this deliberately does not report it -- `ifdef`-guarded alternatives are
    exactly that shape and are legal.

    This never decides anything on its own. The caller refuses only when the
    compiler ALSO says the set does not compile, so a legal cross-file
    arrangement that happens to reuse a name in a way iverilog accepts is not
    rejected by counting.
    """
    owners: Dict[str, set] = {}
    for name, body in sources:
        for module, _block in bundle_integrity.module_blocks(body):
            owners.setdefault(module, set()).add(name)
    return sorted(module for module, files in owners.items() if len(files) > 1)


def _declared_module_names(text: str) -> List[str]:
    """Every module this source declares, in order, ignoring comments.

    Deliberately does NOT treat an instantiation as a declaration: `TopModule
    u0(...)` inside another module must not satisfy a requirement to DECLARE
    TopModule.
    """
    stripped = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    stripped = re.sub(r"//[^\n]*", " ", stripped)
    return re.findall(r"\bmodule\s+([A-Za-z_]\w*)", stripped)


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
