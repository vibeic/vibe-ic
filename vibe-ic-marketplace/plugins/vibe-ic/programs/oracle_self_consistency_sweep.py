#!/usr/bin/env python3
"""oracle_self_consistency_sweep.py — HARNESS-SIDE audit of a benchmark dataset.

WHAT IT ANSWERS
---------------
Before any pass@1 number can be read as "N out of TOTAL", somebody has to ask
whether TOTAL problems are actually winnable and actually verified. This program
asks that, mechanically, for every problem in a dataset, by running TWO arms of
the SAME official scorer the published numbers used:

  ARM G — the problem's OWN golden, submitted as the candidate.
          A golden that fails its own testbench makes the problem UNWINNABLE.
  ARM S — a constant stub (every output tied 0, and a second tied 1),
          submitted as the candidate. A testbench that passes BOTH constant
          stubs verifies nothing about the outputs: no single function is both
          all-zero and all-one, so the problem is UNVERIFIED.

Per-problem verdict, never a default:

  OK             ARM G passes and the stubs do not both pass.
  BROKEN_GOLDEN  ARM G fails — the scorer's own failure line is the evidence.
  VACUOUS_TB     both stubs pass — the scorer's stub verdicts are the evidence.
  NOT_MEASURED   the scorer did not produce a verdict for this problem
                 (tool missing, timeout, unreadable record). Named, with the
                 reason. NEVER silently defaulted to OK or to broken.

The output is `theoretical_max.json` = {total, broken:[{id,reason,evidence}], max}
plus a human `ORACLE_SWEEP.md`.

THE BOUNDARY (why this program is radioactive to a solver)
----------------------------------------------------------
This program READS GOLDEN. That is allowed here and ONLY here: it is a
harness-side audit OF THE DATASET, not a solve. §4.05 is preserved by
construction:

  * it authors no solution, runs no solve, and emits no lesson, digest or hint;
  * its output carries NO golden content — only problem ids, the verdict, and
    the scorer's own failure lines;
  * it REFUSES to run inside a solve run directory (see `refuse_reason`), and
    `programs/tests/test_oracle_sweep_solver_isolation.py` proves that neither
    the solve dispatcher nor the runner can reach this module.

WHAT IT IS NOT
--------------
It is not a re-implementation of scoring. It shells out to the registry's own
scorer with the registry's own arguments — the exact argv
`benchmark_dispatch.py --score` ends in:

    python3 benchmark/score_iverilog_tb.py --bench B --dataset D --run R

The dispatcher's `--score` wrapper additionally demands solve-run provenance
(`.bench_config.json`, the clean-room guard, the Vibe-IC entry guard). A
harness-side audit is not a solve run and must not forge that metadata, so the
sweep calls the wrapper's own final step directly. Scoring behaviour — the
registry entry, the pass/fail regexes, the compile ladder, every rescue — is
whatever that scorer does, unchanged.

Usage:
    python3 oracle_self_consistency_sweep.py --bench verilogeval-v2 \\
        --dataset /path/to/dataset_spec-to-rtl --out /path/to/outdir
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent
_SCORER = _PLUGIN / "benchmark" / "score_iverilog_tb.py"
_REGISTRY = _PLUGIN / "benchmark" / "BENCHMARK_REGISTRY.json"

# Verdicts. Exported so a reader (and the tests) name them once.
OK = "OK"
BROKEN_GOLDEN = "BROKEN_GOLDEN"
VACUOUS_TB = "VACUOUS_TB"
NOT_MEASURED = "NOT_MEASURED"

# Arm names. ARM G is the golden; S0/S1 are the constant stubs.
ARM_G = "G"
ARM_S0 = "S0"
ARM_S1 = "S1"

# The adapters do ONLY record-format mapping (where the golden lives, what the
# candidate file must be called, what the top module must be named). Every
# judgement above lives in this file and is benchmark-agnostic.
_ADAPTER_MODULES = {
    "verilogeval-v2": "verilogeval_oracle_adapter",
    "verilogeval-human": "verilogeval_oracle_adapter",
    "rtllm": "rtllm_oracle_adapter",
}


class SweepError(RuntimeError):
    """A condition that must stop the sweep rather than produce a number."""


# ─────────────────────────── the solve-run refusal ───────────────────────────
# A solve run directory is identified by the metadata --solve writes. Running a
# golden-reading audit inside one puts golden bytes on a solver's disk, which is
# exactly the leak this program's boundary exists to prevent.
def refuse_reason(out_dir: Path, dataset: Path) -> str | None:
    """Why this sweep must not run here, or None. Pure — takes no action."""
    out_dir = Path(out_dir)
    for anc in [out_dir] + list(out_dir.parents):
        if (anc / ".bench_config.json").is_file():
            return (f"output path {out_dir} is inside a benchmark SOLVE run "
                    f"({anc}/.bench_config.json): a golden-reading audit must "
                    "never write into a solve run directory")
        if anc == anc.parent:
            break
    ds = Path(dataset)
    if (ds / ".bench_config.json").is_file():
        return (f"dataset path {ds} is a solve run directory, not a dataset")
    return None


def _adapter_for(bench: str):
    mod = _ADAPTER_MODULES.get(bench)
    if mod is None:
        raise SweepError(
            f"no oracle adapter for benchmark {bench!r}; known: "
            + ", ".join(sorted(_ADAPTER_MODULES)))
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    return importlib.import_module(mod)


def _registry_entry(bench: str, registry: Path = _REGISTRY) -> dict:
    try:
        data = json.loads(Path(registry).read_text())
    except (OSError, ValueError) as exc:
        raise SweepError(f"cannot read {registry}: {exc}") from exc
    try:
        return data["benchmarks"][bench]
    except KeyError as exc:
        raise SweepError(f"{bench!r} is not in {registry}") from exc


# ───────────────────────────── the constant stubs ─────────────────────────────
# Reuse the scorer's own stub synthesizer — the repo already has exactly one
# implementation of "tie every output to a constant", written for the shape-B
# non-discriminating-TB guard, and a second one here would be a second thing to
# keep true.
def _load_scorer_stub_builder():
    """The SHIPPED scorer's builder — never whichever scorer an arm is being
    run with. Importing the arm's scorer would EXECUTE it (a test fixture
    scorer expects `--run` on argv and died on the import), and the two are
    different things: one is the code we reuse, the other is the process we
    invoke."""
    sys.path.insert(0, str(_SCORER.parent))
    try:
        mod = importlib.import_module(_SCORER.stem)
    except Exception:
        return lambda _text: None       # fall through to the dialect builder
    finally:
        sys.path.pop(0)
    return mod._build_zero_stub


# Header-dialect fallback. The scorer's builder reads outputs out of a PLAIN
# ANSI port list. Two other dialects appear in these datasets: a parameterized
# ANSI header (`module N #(…) (…);`) and a Verilog-1995/2001 non-ANSI header
# whose directions are declared in the BODY (`module f(a,y); input a; output
# reg y; …`). Those are header dialects, not a different idea of what a stub
# is, so the fallback lives here rather than as a second stub-building concept:
# same name, same ports, every output tied to a constant.
def _balanced(text: str, start: int) -> tuple[str, int] | None:
    """The parenthesised group beginning at `start`, and the index after it."""
    if start >= len(text) or text[start] != "(":
        return None
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None


def _split_module_header(text: str):
    """(name, parameter-list-or-None, port-list, body) for the first module.

    Handles the parameterized header `module N #(…) (…);` that the scorer's own
    ANSI-only regex does not reach — the parameter list is a THIRD header
    dialect, not a third idea of what a stub is."""
    m = re.search(r"\bmodule\s+(\w+)", text)
    if not m:
        return None
    i = m.end()
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    params = None
    if i < len(text) and text[i] == "#":
        j = i + 1
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        got = _balanced(text, j)
        if got is None:
            return None
        params, i = got
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
    got = _balanced(text, i)
    if got is None:
        return None
    ports, i = got
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != ";":
        return None
    return m.group(1), params, ports, text[i + 1:]


def _build_general_stub(module_text: str) -> str | None:
    """The two header dialects the scorer's ANSI-only builder cannot read: a
    parameterized ANSI header, and a non-ANSI header whose directions are
    declared in the body. Same idea as the scorer's builder — same name, same
    ports, every output tied to a constant."""
    split = _split_module_header(module_text)
    if split is None:
        return None
    name, params, ports, body = split
    head = f"module {name} " + (f"#({params}) " if params is not None else "")
    if re.search(r"\b(input|output|inout)\b", ports):
        outs = re.findall(r"\boutput\b[^,;]*?(\w+)\s*(?=,|$)", ports, re.S)
        if not outs:
            return None
        drives = "\n".join(f"    assign {o} = '0;" for o in dict.fromkeys(outs))
        return (head + "(" + re.sub(r"\boutput\s+reg\b", "output", ports)
                + ");\n" + drives + "\nendmodule\n")
    body = re.sub(r"//[^\n]*|/\*.*?\*/", " ", body, flags=re.S)
    decls, outs = [], []
    for d in re.finditer(r"\b(input|output|inout)\b((?:\s*(?:reg|wire|logic|signed))*)"
                         r"(\s*\[[^\]]*\])?\s*([\w\s,]+?)\s*;", body, re.S):
        kind, _kw, width, names = d.group(1), d.group(2), d.group(3) or "", d.group(4)
        for n in [x.strip() for x in names.split(",") if x.strip()]:
            decls.append(f"    {kind}{width} {n};")
            if kind == "output":
                outs.append(n)
    if not outs:
        return None
    drives = "\n".join(f"    assign {o} = '0;" for o in dict.fromkeys(outs))
    return (head + f"({ports});\n" + "\n".join(decls) + "\n"
            + drives + "\nendmodule\n")


def constant_stub(module_text: str, level: int) -> str | None:
    """A same-name, same-ports module with every output tied to `level`.

    `level` 0 reuses the scorer's own builder (ANSI header) or the non-ANSI
    fallback above; level 1 rewrites the `'0` drives to `'1`. Returns None when
    neither dialect parses — the caller then reports NOT_MEASURED rather than
    inventing a stub."""
    if level not in (0, 1):
        raise SweepError(f"stub level must be 0 or 1, got {level!r}")
    zero = _load_scorer_stub_builder()(module_text)
    if zero is None:
        zero = _build_general_stub(module_text)
    if zero is None:
        return None
    return zero if level == 0 else zero.replace(" = '0;", " = '1;")


# ────────────────────────────── running one arm ──────────────────────────────
def _run_scorer(bench: str, dataset: Path, run: Path, scorer: Path,
                python: str | None = None) -> subprocess.CompletedProcess:
    argv = [python or sys.executable, str(scorer), "--bench", bench,
            "--dataset", str(dataset), "--run", str(run)]
    return subprocess.run(argv, capture_output=True, text=True)


def _verdicts_from_record(run: Path, ident: str) -> dict:
    """{id: {"verdict":…, "reason":…}} from the scorer's own pass_at_1.json.

    A record we cannot read is not an empty record: the caller turns a missing
    id into NOT_MEASURED naming this file."""
    rec = Path(run) / "pass_at_1.json"
    if not rec.is_file():
        return {}
    try:
        data = json.loads(rec.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for r in data.get("results", []):
        pid = r.get(ident)
        if pid is None:
            continue
        out[pid] = r
    return out


def run_arm(bench: str, dataset: Path, ids: list[str], candidates: dict,
            ident: str, work: Path, scorer: Path = _SCORER,
            python: str | None = None) -> dict:
    """Score one arm. `candidates` maps id -> (sample_relpath, text) or None.

    Returns {"results": {id: result-dict-or-None}, "stdout":…, "stderr":…, "rc":…}.
    A None candidate (the adapter could not build one) stays None here and is
    reported NOT_MEASURED by the caller — never scored as a failure."""
    run = Path(work)
    samples = run / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    present = []
    for pid in ids:
        cand = candidates.get(pid)
        if cand is None:
            continue
        rel, text = cand
        dest = samples / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        present.append(pid)
    (run / "problems.list").write_text("\n".join(present) + ("\n" if present else ""))
    proc = _run_scorer(bench, dataset, run, scorer, python=python)
    recs = _verdicts_from_record(run, ident)
    return {"results": {pid: recs.get(pid) for pid in ids},
            "rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr,
            "run": str(run), "scored": present}


# ───────────────────────────────── the verdict ─────────────────────────────────
def _evidence_line(res: dict | None) -> str:
    """The scorer's OWN line for this problem — never golden content."""
    if not res:
        return ""
    reason = str(res.get("reason") or "")
    log = str(res.get("log") or "")
    if log:
        log = log.strip().splitlines()[-1][:300] if log.strip() else ""
    return (reason + (f" | {log}" if log else "")).strip()


# A verdict that is a statement about the MACHINE, not about the dataset. The
# scorer reports both through the same FAIL/SKIP channel, and charging a
# loaded host's simulation timeout to a benchmark's golden would manufacture a
# dataset defect out of a busy afternoon. Measured on this host at load 44.
_MACHINE_REASONS = ("sim_timeout", "iverilog_absent", "COMMAND_NOT_FOUND")


def _is_machine_statement(res: dict | None) -> str:
    """The reason this arm says nothing about the dataset, or ""."""
    if not res:
        return ""
    if res.get("verdict") == "SKIP":
        return f"scorer SKIPped this arm: {res.get('reason', '')}"
    blob = f"{res.get('reason', '')} {res.get('log', '')}"
    for marker in _MACHINE_REASONS:
        if marker in blob:
            return (f"the scorer reported {marker!r}, which is a statement "
                    "about the machine, not about the dataset")
    return ""


def classify(golden: dict | None, stub0: dict | None, stub1: dict | None,
             *, golden_missing: str = "", stub_missing: str = "") -> dict:
    """The whole judgement of this program, in one pure function.

    Order matters and is deliberate: a problem whose golden cannot be scored is
    NOT_MEASURED (we do not know), a golden that was scored and FAILED is
    BROKEN_GOLDEN, and vacuity is only asserted when BOTH constant stubs pass —
    which no single function can satisfy, so it carries no false positive on a
    problem whose correct answer happens to be a constant."""
    if golden_missing:
        return {"verdict": NOT_MEASURED, "reason": golden_missing, "evidence": ""}
    if golden is None:
        return {"verdict": NOT_MEASURED,
                "reason": "the scorer produced no record for this problem "
                          "(ARM G); see the arm's pass_at_1.json",
                "evidence": ""}
    machine = _is_machine_statement(golden)
    if machine:
        return {"verdict": NOT_MEASURED, "reason": "ARM G: " + machine,
                "evidence": _evidence_line(golden)}
    if golden.get("verdict") != "PASS":
        return {"verdict": BROKEN_GOLDEN,
                "reason": "the problem's own golden does not pass its own "
                          "official scoring",
                "evidence": _evidence_line(golden)}
    # Golden passes. Now: does the testbench distinguish anything?
    if stub_missing or stub0 is None or stub1 is None:
        return {"verdict": NOT_MEASURED,
                "reason": (stub_missing or
                           "the scorer produced no record for one of the stub "
                           "arms, so vacuity could not be decided"),
                "evidence": ""}
    s0, s1 = stub0.get("verdict"), stub1.get("verdict")
    for arm, res in ((ARM_S0, stub0), (ARM_S1, stub1)):
        machine = _is_machine_statement(res)
        if machine:
            return {"verdict": NOT_MEASURED,
                    "reason": f"ARM {arm}: {machine}, so vacuity could not be "
                              "decided",
                    "evidence": f"S0={s0} S1={s1}"}
    if s0 == "PASS" and s1 == "PASS":
        return {"verdict": VACUOUS_TB,
                "reason": "both the all-zero and the all-one constant stub pass "
                          "this problem's own testbench, so it verifies nothing "
                          "about the outputs",
                "evidence": "ARM S0=PASS ARM S1=PASS"}
    single = ARM_S0 if s0 == "PASS" else (ARM_S1 if s1 == "PASS" else "")
    out = {"verdict": OK, "reason": "", "evidence": ""}
    if single:
        # Honest, and deliberately NOT a broken verdict: a problem whose correct
        # answer IS that constant is passed by that stub legitimately.
        out["single_stub_pass"] = single
    return out


# ─────────────────────────────────── the sweep ───────────────────────────────────
def sweep(bench: str, dataset: Path, out_dir: Path, *, work_root: Path | None = None,
          scorer: Path = _SCORER, registry: Path = _REGISTRY,
          ids: list[str] | None = None, python: str | None = None,
          keep_work: bool = False, from_work: bool = False,
          provenance: dict | None = None,
          semantic_elsewhere: list[str] | None = None) -> dict:
    """Run the arms and classify. `from_work` re-reads the arm records a previous
    run left under `work_root` and re-derives the outputs WITHOUT re-simulating:
    a report regeneration must never need a fresh sweep, and a re-run would be a
    different measurement wearing the same name."""
    dataset, out_dir = Path(dataset).resolve(), Path(out_dir).resolve()
    why = refuse_reason(out_dir, dataset)
    if why:
        raise SweepError("REFUSING TO RUN: " + why)
    entry = _registry_entry(bench, registry)
    ident = "design" if entry["shape"] == "B" else "problem"
    ad = _adapter_for(bench)
    all_ids = ad.problems(dataset, entry)
    if ids is not None:
        missing = [i for i in ids if i not in all_ids]
        if missing:
            raise SweepError(f"--ids not in the dataset: {missing}")
        all_ids = [i for i in all_ids if i in set(ids)]
    if not all_ids:
        raise SweepError(f"no problems found under {dataset}")

    # Build every candidate ONCE, so an adapter failure is a named
    # NOT_MEASURED and never an unscored silence.
    golden, stub0, stub1 = {}, {}, {}
    gmiss, smiss = {}, {}
    for pid in all_ids:
        try:
            rel, text, seed = ad.golden_candidate(dataset, pid, entry)
        except Exception as exc:                      # adapter-side, per problem
            gmiss[pid] = f"could not build the golden candidate: {exc}"
            continue
        golden[pid] = (rel, text)
        for level, bucket in ((0, stub0), (1, stub1)):
            st = constant_stub(seed, level)
            if st is None:
                smiss[pid] = ("the golden's module header is not a parseable "
                              "ANSI header, so no constant stub could be built")
                continue
            bucket[pid] = (rel, st)

    if from_work:
        if work_root is None:
            raise SweepError("--from-work needs the --work directory of the run "
                             "whose arms are being re-read")
        work_root = Path(work_root)
        arms = {}
        for name in (ARM_G, ARM_S0, ARM_S1):
            arm_dir = work_root / f"arm_{name}"
            if not (arm_dir / "pass_at_1.json").is_file():
                raise SweepError(
                    f"{arm_dir}/pass_at_1.json is absent: this work directory "
                    "does not hold a completed arm, and a missing arm is not an "
                    "empty one")
            recs = _verdicts_from_record(arm_dir, ident)
            arms[name] = {"results": {pid: recs.get(pid) for pid in all_ids},
                          "rc": 0, "run": str(arm_dir),
                          "scored": sorted(recs), "reread": True}
    else:
        work_root = Path(work_root) if work_root else Path(
            tempfile.mkdtemp(prefix="oracle_sweep_"))
        work_root.mkdir(parents=True, exist_ok=True)
        arms = {}
        for name, cands in ((ARM_G, golden), (ARM_S0, stub0), (ARM_S1, stub1)):
            arms[name] = run_arm(bench, dataset, all_ids, cands, ident,
                                 work_root / f"arm_{name}", scorer, python=python)

    per = {}
    for pid in all_ids:
        per[pid] = classify(arms[ARM_G]["results"].get(pid),
                            arms[ARM_S0]["results"].get(pid),
                            arms[ARM_S1]["results"].get(pid),
                            golden_missing=gmiss.get(pid, ""),
                            stub_missing=smiss.get(pid, ""))
    # Every broken entry MUST carry evidence: `bench_eval_max_check.py` honours
    # this file only when each one does, so an entry whose scorer printed no
    # reason would silently void the WHOLE record. When the scorer said nothing,
    # the evidence is the arm verdicts themselves — still measured, never blank.
    broken = []
    for p, v in per.items():
        if v["verdict"] not in (BROKEN_GOLDEN, VACUOUS_TB):
            continue
        ev = v["evidence"] or (
            "ARM G=" + str((arms[ARM_G]["results"].get(p) or {}).get("verdict"))
            + " S0=" + str((arms[ARM_S0]["results"].get(p) or {}).get("verdict"))
            + " S1=" + str((arms[ARM_S1]["results"].get(p) or {}).get("verdict")))
        broken.append({"id": p, "reason": v["reason"], "evidence": ev})
    not_measured = [{"id": p, "reason": v["reason"]}
                    for p, v in per.items() if v["verdict"] == NOT_MEASURED]
    theoretical_max = {
        "schema": "vibeic.benchmark.theoretical_max.v1",
        "benchmark": bench,
        "total": len(all_ids),
        "broken": sorted(broken, key=lambda b: b["id"]),
        "max": len(all_ids) - len(broken),
        "not_measured": sorted(not_measured, key=lambda b: b["id"]),
        "max_scope": (
            "SELF-CONSISTENCY ONLY. `max` subtracts the problems this sweep "
            "can PROVE broken by running them: a golden that fails its own "
            "testbench, and a testbench both constant stubs pass. It cannot "
            "see a SEMANTIC (Category A2) defect — a golden that passes its "
            "own testbench and contradicts the prompt — so this `max` is an "
            "UPPER BOUND on the true theoretical maximum, never a refutation "
            "of a lower one published elsewhere."),
        "presentation_rule": (
            "Every published number keeps the ORIGINAL denominator. This file "
            "is bookkeeping: its only consequence is that NO enhancement is "
            "owed on a problem listed in `broken`."),
        "oracle_use": (
            "HARNESS-SIDE DATASET AUDIT, DECLARED. Each verdict comes from "
            "running the problem's own golden, and two constant stubs, through "
            "the benchmark's own official scorer. No authoring path reads this "
            "file's inputs, and the file itself carries no golden content."),
        "method": {
            "arm_G": "the problem's own golden as the candidate",
            "arm_S0": "a constant stub, every output tied 0",
            "arm_S1": "a constant stub, every output tied 1",
            "broken_rule": ("BROKEN_GOLDEN when ARM G fails; VACUOUS_TB when "
                            "BOTH stubs pass. One stub passing is reported as "
                            "advisory and never charged — a problem whose "
                            "correct answer IS that constant passes it "
                            "legitimately."),
            "not_measured_rule": ("named, with a reason, and NOT subtracted "
                                  "from `max`: an unmeasured problem is not a "
                                  "proven-broken one"),
        },
    }
    if semantic_elsewhere:
        theoretical_max["semantic_defects_documented_elsewhere"] = list(
            semantic_elsewhere)
    if provenance:
        theoretical_max.update(provenance)
    if not keep_work:
        for a in arms.values():
            a.pop("stdout", None), a.pop("stderr", None)
    return {"theoretical_max": theoretical_max, "per_problem": per,
            "arms": arms, "work_root": str(work_root), "ident": ident,
            "shape": entry["shape"]}


# ───────────────────────────────── the report ─────────────────────────────────
def _tool_versions(python: str | None = None) -> dict:
    out = {}
    for name, argv in (("iverilog", ["iverilog", "-V"]),
                       ("verilator", ["verilator", "--version"]),
                       ("python", [python or sys.executable, "-V"])):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            line = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
            out[name] = line[0] if line else "unknown"
        except (OSError, subprocess.SubprocessError):
            out[name] = "NOT_MEASURED (probe failed)"
    return out


def _git_sha(path: Path) -> str:
    try:
        p = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 else "NOT_MEASURED (not a git checkout)"
    except (OSError, subprocess.SubprocessError):
        return "NOT_MEASURED (git probe failed)"


def render_markdown(bench: str, res: dict, dataset: Path, *, image: str = "",
                    host: str = "", semantic_elsewhere: list[str] | None = None,
                    python: str | None = None) -> str:
    tm = res["theoretical_max"]
    per = res["per_problem"]
    lines = [f"# Oracle self-consistency sweep — {bench}", "",
             "Every problem's OWN golden through its OWN official scorer, plus a",
             "constant-stub control. Harness-side dataset audit; no solve, no",
             "authoring. The table carries problem ids, verdicts and the scorer's",
             "own failure lines only — never golden content.", "",
             "## Provenance", "",
             f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
             f"- dataset: `{dataset}`",
             f"- dataset commit: `{_git_sha(Path(dataset))}`",
             f"- scorer: `benchmark/score_iverilog_tb.py --bench {bench}` "
             "(the exact argv `benchmark_dispatch.py --score` ends in)",
             f"- image: `{image or 'NOT_MEASURED (not stated by the caller)'}`",
             f"- host: `{host or 'NOT_MEASURED (not stated by the caller)'}`"]
    for k, v in _tool_versions(python).items():
        lines.append(f"- {k}: `{v}`")
    lines += ["", "## Result", "",
              f"- total: **{tm['total']}**",
              f"- BROKEN_GOLDEN + VACUOUS_TB (`broken`): **{len(tm['broken'])}**",
              f"- NOT_MEASURED: **{len(tm['not_measured'])}**",
              f"- theoretical max: **{tm['max']}**", ""]
    for label, verdict in (("BROKEN_GOLDEN", BROKEN_GOLDEN),
                           ("VACUOUS_TB", VACUOUS_TB)):
        ids = sorted(p for p, v in per.items() if v["verdict"] == verdict)
        lines += [f"### {label} ({len(ids)})", ""]
        if not ids:
            lines += ["_none_", ""]
        for p in ids:
            lines.append(f"- `{p}` — {per[p]['reason']}"
                         + (f" — scorer: `{per[p]['evidence']}`"
                            if per[p]["evidence"] else ""))
        lines.append("")
    nm = sorted(tm["not_measured"], key=lambda b: b["id"])
    lines += [f"### NOT_MEASURED ({len(nm)})", ""]
    lines += ([f"- `{b['id']}` — {b['reason']}" for b in nm] or ["_none_"])
    single = sorted(p for p, v in per.items() if v.get("single_stub_pass"))
    lines += ["", f"### Advisory: exactly one constant stub passes ({len(single)})", "",
              "Not a defect verdict. A problem whose correct answer IS that",
              "constant is passed by that stub legitimately; only BOTH stubs",
              "passing proves the testbench verifies nothing.", ""]
    lines += ([f"- `{p}` — ARM {per[p]['single_stub_pass']}" for p in single]
              or ["_none_"])
    if semantic_elsewhere:
        lines += ["", "### Semantic (Category A2) — documented elsewhere, NOT re-derived here", "",
                  "These goldens PASS their own testbench and contradict the",
                  "prompt instead. A self-consistency sweep cannot see that, by",
                  "construction; the published RESULT.md headings carry them.", ""]
        lines += [f"- `{p}`" for p in semantic_elsewhere]
    lines += ["", "### Per-problem", "", "| id | verdict |", "| --- | --- |"]
    lines += [f"| `{p}` | {per[p]['verdict']} |" for p in sorted(per)]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--work", default="", help="scratch root for the arms")
    ap.add_argument("--ids", default="", help="comma-separated subset (control runs)")
    ap.add_argument("--image", default=os.environ.get("VIBEIC_EDA_IMAGE", ""))
    ap.add_argument("--host", default=os.environ.get("HOSTNAME", ""))
    ap.add_argument("--semantic-elsewhere", default="",
                    help="comma-separated ids documented as Category A2 semantic "
                         "defects; listed in the report, never re-derived here")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--from-work", action="store_true",
                    help="re-read the arm records under --work and re-derive the "
                         "outputs without re-simulating")
    ap.add_argument("--dataset-repo", default="")
    ap.add_argument("--dataset-subdir", default="")
    a = ap.parse_args(argv)
    semantic = [i for i in a.semantic_elsewhere.split(",") if i]
    try:
        prov = {"dataset_commit": _git_sha(Path(a.dataset)),
                "measured_on": {"host": a.host or "NOT_MEASURED (not stated)",
                                "image": a.image or "NOT_MEASURED (not stated)",
                                "date": datetime.now(timezone.utc).date().isoformat(),
                                "tools": _tool_versions()}}
        if a.dataset_repo:
            prov["dataset_repository"] = a.dataset_repo
        if a.dataset_subdir:
            prov["dataset_subdir"] = a.dataset_subdir
        res = sweep(a.bench, Path(a.dataset), Path(a.out),
                    work_root=Path(a.work) if a.work else None,
                    ids=[i for i in a.ids.split(",") if i] or None,
                    keep_work=a.keep_work, from_work=a.from_work,
                    provenance=prov, semantic_elsewhere=semantic)
    except SweepError as exc:
        print(f"[oracle-sweep] {exc}", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "theoretical_max.json").write_text(
        json.dumps(res["theoretical_max"], indent=2) + "\n")
    (out / "ORACLE_SWEEP.md").write_text(render_markdown(
        a.bench, res, Path(a.dataset), image=a.image, host=a.host,
        semantic_elsewhere=semantic))
    tm = res["theoretical_max"]
    print(f"{a.bench}: total={tm['total']} broken={len(tm['broken'])} "
          f"not_measured={len(tm['not_measured'])} max={tm['max']}")
    for b in tm["broken"]:
        print(f"  BROKEN {b['id']}: {b['evidence'] or b['reason']}")
    for b in tm["not_measured"]:
        print(f"  NOT_MEASURED {b['id']}: {b['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
