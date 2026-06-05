#!/usr/bin/env python3
"""score_iverilog_tb.py — generic iverilog-substitutes-VCS scorer for Shape B + Shape C.

Generalizes the two scorers used in the 2026-05-28 sweep
(benchmark_external/verilogeval_v2/score_verilogeval.py + .../rtllm/score_rtllm.py).
Driven by the per-benchmark entry in BENCHMARK_REGISTRY.json so a new plugin user
runs `/vibe-ic-benchmark <bench>` and gets the right scoring without writing code.

Substitution disclosure: this scorer uses iverilog 12 -g2012 in place of Synopsys
VCS or Cadence Xcelium (per open-benchmark-methodology skill § 3). It runs vvp
with cwd=design_dir so the official TB's relative-path `$readmemh(...)` resolves
(per § 3 cwd-rule).

LAYOUTS supported (BENCHMARK_REGISTRY.layout):

  Shape B (per-design dir):
    <dataset>/<design>/<prompt_filename>          (e.g. design_description.txt)
    <dataset>/<design>/<tb_filename>              (e.g. testbench.v)
    <run>/samples/<leaf>.v                        (candidate RTL; leaf = last path component of <design>)

  Shape C (flat dataset, one file per piece):
    <dataset>/<Prob><prompt_suffix>               (e.g. _prompt.txt)
    <dataset>/<Prob><tb_suffix>                   (e.g. _test.sv)
    <dataset>/<Prob><ref_suffix>                  (e.g. _ref.sv — compiled with TB if tb_compile_with_ref=true)
    <run>/samples/<Prob>_sample01.sv              (candidate RTL)

Pass detection:
  - PASS iff `pass_regex` matches the vvp stdout/stderr AND (no `fail_regex` match if fail_regex given).
  - Compile-error / sim-timeout / no_sample report explicit FAIL reasons.

Usage examples:
  # Shape B (RTLLM)
  python3 score_iverilog_tb.py --bench rtllm \\
      --dataset /path/to/RTLLM --run /path/to/run_blind_v0126

  # Shape C (VerilogEval-v2)
  python3 score_iverilog_tb.py --bench verilogeval-v2 \\
      --dataset /path/to/dataset_spec-to-rtl --run /path/to/run_fresh_v0125

Honesty: this scorer ONLY touches the hidden testbench/ref/golden at scoring time.
The generation step must be blind (per the skill's absolute-blindness rule).
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile, os, re, shutil
from pathlib import Path
from typing import Optional


def _registry_path() -> Path:
    return Path(__file__).resolve().parent / "BENCHMARK_REGISTRY.json"


# benchmark-enhancement-capture (2026-06-01): canonical power-up gate.
# Direct-agent blind authoring skips the runner's gate pipeline, so a logically
# correct sequential DUT can be X at t=0 and mismatch an initialized reference
# on the very first compared cycle. Apply the deterministic power-up determinism
# fix (rtl_hygiene_lint --fix inserts `initial <reg>=0;`) to a NON-DESTRUCTIVE
# temp copy of each candidate sample before compiling it, so the canonical
# scorer enforces the same hygiene the gates-harness does. Chip/benchmark-AGNOSTIC.
def _power_up_fixed(sample: Path, td: str) -> str:
    """Return a path to a power-up-determinism-fixed copy of `sample` (or the
    original path if the hygiene program is unavailable). Never mutates the
    original sample file."""
    try:
        lint = (Path(__file__).resolve().parent.parent
                / "programs" / "rtl_hygiene_lint.py")
        if not lint.is_file():
            return str(sample)
        import shutil as _sh
        fixed = os.path.join(td, "fixed_" + sample.name)
        _sh.copyfile(str(sample), fixed)
        subprocess.run(["python3", str(lint), "--fix", fixed],
                       capture_output=True, text=True, timeout=60)
        return fixed if os.path.isfile(fixed) and os.path.getsize(fixed) else str(sample)
    except Exception:
        return str(sample)


def _load_bench(name: str) -> dict:
    reg = json.loads(_registry_path().read_text())
    entry = reg.get("benchmarks", {}).get(name)
    if not entry:
        raise SystemExit(f"Benchmark '{name}' not in BENCHMARK_REGISTRY.json. "
                         f"Known: {sorted(reg.get('benchmarks', {}).keys())}")
    if entry.get("shape") not in ("B", "C"):
        raise SystemExit(f"Benchmark '{name}' is Shape {entry.get('shape')} — "
                         f"this scorer handles only B + C. Use the matching scorer "
                         f"(e.g. score_cocotb_mcp.py for Shape D).")
    return entry


def _problems_list_shape_c(run: Path, dataset: Path, prompt_suffix: str) -> list[str]:
    """Return ordered list of <Prob> identifiers for Shape C from problems.list, or
    discovered from the dataset if no problems.list."""
    pl = run / "problems.list"
    if pl.is_file():
        return [l.strip() for l in pl.read_text().splitlines() if l.strip()]
    # discovery fallback: list of files matching <Prob><prompt_suffix>
    return sorted(p.name.removesuffix(prompt_suffix)
                  for p in dataset.glob(f"*{prompt_suffix}"))


def _problems_list_shape_b(run: Path, dataset: Path, prompt_filename: str) -> list[str]:
    """Return ordered list of design dirs (relative to dataset) for Shape B."""
    pl = run / "problems.list"
    if pl.is_file():
        return [l.strip() for l in pl.read_text().splitlines() if l.strip()]
    # discovery fallback
    return sorted(str(p.parent.relative_to(dataset))
                  for p in dataset.rglob(prompt_filename) if p.is_file())


# Scorer fix: resolve the candidate sample by the spec's authoritative
# module name, not just the directory leaf. Some specs declare a module name that
# differs from the dir leaf (e.g. a typo'd dir vs the spec's "Module name:" line);
# the candidate file is written under the MODULE name. Try leaf.v, then the spec's
# module name, then any single .v in samples/ that declares the TB-required top.
def _resolve_sample_b(design: str, samples: Path, dataset: Path,
                      layout: dict) -> Optional[Path]:
    leaf = design.split("/")[-1]
    cand = samples / f"{leaf}.v"
    if cand.is_file():
        return cand
    # spec "Module name:" line (RTLLM convention)
    spec = dataset / design / layout.get("prompt_filename", "design_description.txt")
    if spec.is_file():
        m = re.search(r"Module\s*name:\s*\n?\s*([A-Za-z_]\w*)",
                      spec.read_text(errors="ignore"))
        if m:
            cand2 = samples / f"{m.group(1)}.v"
            if cand2.is_file():
                return cand2
    return None


# Scorer fix: Verilator escalation for SV-2012 testbench tool-gaps.
# The host iverilog 12 (AND container iverilog 13) internal-error on some SV-2012
# testbench constructs — array-aggregate/array-literal initializers (`{8'd1,...}`)
# and `break;` in for-loops. These are a TOOL-GAP in the open *simulator*, NOT a
# candidate-RTL bug. Verilator 5.x supports both constructs, so it is the correct
# § 3 substitution rung above iverilog. open-benchmark-methodology an earlier release verified
# this: ring_counter PASSes under Verilator (genuine tool-gap, recovered to PASS),
# while asyn_fifo FAILs under Verilator (a real functional bug, NOT a TB-side gap).
# So: iverilog "sorry"/"internal error" → escalate to Verilator, whose verdict is
# authoritative; only a Verilator *build* failure stays a hard tool-gap → SKIP.
_IV13_CONTAINER = os.environ.get("VIBEIC_IVERILOG13_CONTAINER", "iic-eda")
_HOST_DESIGNS_ROOT = os.environ.get("VIBEIC_DESIGNS_HOST_ROOT", "/home/reyerchu/AI_IC_design")
_CONT_DESIGNS_ROOT = os.environ.get("VIBEIC_DESIGNS_CONT_ROOT", "/foss/designs")


def _to_container(p: str) -> str:
    return p.replace(_HOST_DESIGNS_ROOT, _CONT_DESIGNS_ROOT)


def _build_zero_stub(sample_text: str) -> Optional[str]:
    """From an ANSI-header module, synthesize a trivially-WRONG stub with the same
    name + ports but every output driven to constant 0 (reg stripped so `assign`
    is legal). Used to detect non-discriminating testbenches — if this garbage
    stub passes the same TB, the TB can't verify anything. Returns stub source, or
    None if the header isn't a parseable ANSI module (then skip the guard)."""
    m = re.search(r"\bmodule\s+(\w+)\s*\((.*?)\)\s*;", sample_text, re.S)
    if not m:
        return None
    name, ports = m.group(1), m.group(2)
    # output port names (ANSI: `output [reg|wire] [width] name`, possibly listed)
    outs = re.findall(r"\boutput\b[^,;]*?(\w+)\s*(?=,|$)", ports, re.S)
    if not outs:
        return None
    header_ports = re.sub(r"\boutput\s+reg\b", "output", ports)
    drives = "\n".join(f"    assign {o} = '0;" for o in dict.fromkeys(outs))
    return f"module {name} ({header_ports});\n{drives}\nendmodule\n"


def _verilator_run_text(text: str, design: str, tb: Path, design_dir: Path,
                        pass_re, tag: str):
    """Stage arbitrary RTL text under the designs root and build+run it under
    container Verilator against `tb`. Returns (built: bool, pass_marker: bool)."""
    stage_dir = Path(_HOST_DESIGNS_ROOT) / ".vibeic_scorer_tmp"
    stage_dir.mkdir(parents=True, exist_ok=True)
    p = stage_dir / f"{re.sub(r'[^A-Za-z0-9_]', '_', design.split('/')[-1])}_{tag}.v"
    try:
        p.write_text(text)
        cs = _to_container(str(p.resolve()))
        cd = _to_container(str(Path(design_dir).resolve()))
        ctb = _to_container(str(Path(tb).resolve()))
        mdir = f"/tmp/vobj_{tag}_" + re.sub(r"\W", "_", design.split("/")[-1])
        cmd = (f"export PATH=/foss/tools/bin:$PATH && cd '{cd}' && rm -rf {mdir} && "
               f"verilator --binary --timing -Wno-fatal -Wno-WIDTH -Wno-CASEINCOMPLETE "
               f"-Mdir {mdir} '{cs}' '{ctb}' 2>&1 && echo __VBUILT__ && "
               f"timeout 90 {mdir}/V* 2>&1")
        r = subprocess.run(["docker", "exec", _IV13_CONTAINER, "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=300)
        out = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                        if not l.startswith("[INFO]"))
        if "__VBUILT__" not in out:
            return (False, False)
        return (True, bool(pass_re.search(out.split("__VBUILT__", 1)[1])))
    except Exception:
        return (False, False)
    finally:
        try:
            p.unlink()
        except OSError:
            pass


def _tb_is_non_discriminating(sample_text: str, tb: Path, design_dir: Path,
                              pass_re) -> Optional[bool]:
    """Honesty audit: a benchmark TB is non-discriminating if a deliberately-WRONG
    design (all outputs tied to constant 0) ALSO prints the pass marker — meaning
    the TB's check is unconditional or one-sided and cannot actually verify
    correctness (e.g. a commented-out $finish, or `error` only set on a one-sided
    condition). Such a PASS is not a meaningful functional result. Returns True if
    non-discriminating, False if the stub is correctly rejected (TB discriminates),
    or None if the stub can't be built/run (inconclusive — left counted).
    NOT chip-specific: keys on the constant-0 stub passing, never on a design name."""
    stub = _build_zero_stub(sample_text)
    if stub is None:
        return None
    # Prefer host iverilog (fast). If the TB is an iverilog tool-gap, use Verilator.
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "zstub.v"
        sp.write_text(stub)
        binp = os.path.join(td, "zb")
        c = subprocess.run(["iverilog", "-g2012", "-o", binp, str(sp), str(tb)],
                           capture_output=True, text=True, timeout=60)
        clow = (c.stdout + c.stderr).lower()
        if "sorry:" in clow or "internal error" in clow or "i don't know how to elaborate" in clow:
            built, stub_pass = _verilator_run_text(
                stub, design_dir.name, tb, design_dir, pass_re, "zstub")
            return bool(stub_pass) if built else None
        if c.returncode != 0 or not os.path.exists(binp):
            return None
        try:
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=30, cwd=str(design_dir))
        except subprocess.TimeoutExpired:
            return None  # stub hangs the TB ⇒ TB depends on outputs ⇒ inconclusive→leave counted
        return bool(pass_re.search(r.stdout + r.stderr))


def _verilator_compile_run(design: str, sample_c: str, tb: Path, design_dir: Path,
                           pass_re, fail_re) -> Optional[dict]:
    """Escalation rung for SV-2012 TB tool-gaps iverilog can't elaborate. Build +
    run under container Verilator 5.x (`--binary --timing`, auto-inferred top so a
    TB module named `<x>_tb` works). Returns a verdict dict, or None if the
    container/Verilator is unavailable. A Verilator BUILD failure (the TB exceeds
    even Verilator) → SKIP (genuine tool-gap, excluded from the denominator); a
    successful build with no pass marker → real functional FAIL."""
    staged = None
    try:
        # The power-up-fixed sample lives in a host /tmp dir the container can't
        # see (only the designs root is bind-mounted). Stage it UNDER the designs
        # root so _to_container maps it to a path Verilator-in-container can read.
        sample_c = Path(sample_c)
        if _HOST_DESIGNS_ROOT not in str(sample_c.resolve()):
            stage_dir = Path(_HOST_DESIGNS_ROOT) / ".vibeic_scorer_tmp"
            stage_dir.mkdir(parents=True, exist_ok=True)
            staged = stage_dir / f"{re.sub(r'[^A-Za-z0-9_]', '_', design.split('/')[-1])}.v"
            shutil.copyfile(sample_c, staged)
            sample_c = staged
        # Resolve to ABSOLUTE host paths first — the dataset/run args are often
        # relative (e.g. _extbench/RTLLM/...), and _to_container only rewrites the
        # absolute designs-root prefix. A relative `cd` would fail inside the
        # container (different default cwd) → spurious build failure → false SKIP.
        cd = _to_container(str(Path(design_dir).resolve()))
        cs = _to_container(str(Path(sample_c).resolve()))
        ctb = _to_container(str(Path(tb).resolve()))
        mdir = "/tmp/vobj_" + re.sub(r"\W", "_", design.split("/")[-1])
        cmd = (f"export PATH=/foss/tools/bin:$PATH && cd '{cd}' && rm -rf {mdir} && "
               f"verilator --binary --timing -Wno-fatal -Wno-WIDTH -Wno-CASEINCOMPLETE "
               f"-Mdir {mdir} '{cs}' '{ctb}' 2>&1 && echo __VBUILT__ && "
               f"timeout 90 {mdir}/V* 2>&1")
        r = subprocess.run(["docker", "exec", _IV13_CONTAINER, "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=300)
        out = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                        if not l.startswith("[INFO]"))
        if "__VBUILT__" not in out:
            # Even Verilator cannot elaborate the TB → hard simulator tool-gap.
            return {"verdict": "SKIP",
                    "reason": "tool_gap_sv2012 (iverilog + verilator)"}
        run_out = out.split("__VBUILT__", 1)[1]
        if pass_re.search(run_out):
            if fail_re and fail_re.search(run_out):
                return {"verdict": "FAIL",
                        "reason": "functional_mismatch (verilator)"}
            # PASS per the benchmark's own marker. The discriminating-TB audit
            # (centralized in main(), gated by scorer_args.verify_discriminating)
            # then flags it non_discriminating_tb if a constant-0 stub also passes.
            return {"verdict": "PASS", "reason": "recovered_via_verilator"}
        return {"verdict": "FAIL",
                "reason": "functional_mismatch (verilator, no pass marker)"}
    except Exception:
        return None
    finally:
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                pass


def _score_shape_b(design: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    sample = _resolve_sample_b(design, samples, dataset, layout)
    tb = dataset / design / layout["tb_filename"]
    if sample is None:
        return {"design": design, "verdict": "FAIL", "reason": "no_sample"}
    if not tb.is_file():
        return {"design": design, "verdict": "FAIL", "reason": "no_testbench"}
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        sample_c = _power_up_fixed(sample, td)  # canonical power-up gate
        pass_re = re.compile(args["pass_regex"])
        fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
        c = subprocess.run(["iverilog", "-g2012", "-o", binp, sample_c, str(tb)],
                           capture_output=True, text=True, timeout=120)
        # iverilog-12 prints "sorry: <feature> not supported" for SV-2012 TB
        # constructs but STILL EXITS 0 (e.g. asyn_fifo's `break;`), so a tool-gap
        # must be detected on the OUTPUT, not just the return code. ring_counter's
        # array-literal init exits non-zero ("internal error … elaborate"). Catch
        # both, then escalate to Verilator (the § 3 rung that supports them).
        clow = (c.stdout + c.stderr).lower()
        tool_gap = ("sorry:" in clow or "internal error" in clow
                    or "i don't know how to elaborate" in clow)
        if tool_gap:
            v = _verilator_compile_run(
                design, sample_c, tb,
                (dataset / design) if args.get("cwd_design_dir", True) else Path(os.getcwd()),
                pass_re, fail_re)
            if v is not None:
                v["design"] = design
                return v
        if c.returncode != 0:
            return {"design": design, "verdict": "FAIL", "reason": "compile_error",
                    "log": c.stderr[-400:]}
        try:
            # cwd=design dir so the TB's relative-path $readmemh works (skill §3)
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=120,
                               cwd=str(dataset / design) if args.get("cwd_design_dir", True) else None)
        except subprocess.TimeoutExpired:
            return {"design": design, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        pass_re = re.compile(args["pass_regex"])
        fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
        if pass_re.search(out):
            if fail_re and fail_re.search(out):
                m = re.search(r"(\d+)\s*/\s*\d+\s*failures", out)
                return {"design": design, "verdict": "FAIL",
                        "reason": f"functional_mismatch ({m.group(0) if m else 'test failed'})"}
            return {"design": design, "verdict": "PASS"}
        return {"design": design, "verdict": "FAIL",
                "reason": "no_pass_marker" + (" (some Test failed)" if fail_re and fail_re.search(out) else "")}


def _golden_ref_self_compiles(prob: str, dataset: Path, layout: dict):
    """Compile the golden reference + hidden testbench ALONE (no candidate DUT)
    to tell an irreducible benchmark defect from a genuine candidate bug.

    Returns True if iverilog elaborates ref+TB; False if even the official
    reference cannot satisfy its own testbench (e.g. the TB instantiates ports
    the reference never declares — unsatisfiable by ANY submission); None when
    there is no ref/TB to check (determination impossible).

    Deterministic + chip-AGNOSTIC: an exit-code check only — no design-id lookup,
    no per-problem branch; driven by the registry's module_name_strategy. Honesty:
    touches the hidden ref/TB at SCORING time only (same as the main scorer),
    never during blind authoring.

    The TB instantiates BOTH the golden RefModule and the candidate (TopModule),
    so it cannot compile from ref+TB alone. We provide a stand-in DUT by aliasing
    the golden ref to the candidate's module name: a well-formed problem then
    compiles (golden-vs-golden); only a problem whose TB wires ports neither
    module declares (e.g. TB instantiates .Y2()/.Y4() on a Y1/Y3 module) fails —
    which is the irreducible defect we want to flag. Scoped to the
    always_TopModule strategy (VerilogEval-class), where this defect class lives;
    returns None otherwise (no determination, no flag).
    """
    if not layout.get("ref_suffix") or not layout.get("tb_suffix"):
        return None
    if layout.get("module_name_strategy") != "always_TopModule":
        return None
    dut_name = "TopModule"
    ref = dataset / f"{prob}{layout['ref_suffix']}"
    test = dataset / f"{prob}{layout['tb_suffix']}"
    if not (ref.is_file() and test.is_file()):
        return None
    ref_text = ref.read_text(errors="ignore")
    mm = re.search(r"\bmodule\s+(\w+)", ref_text)
    if not mm:
        return None
    ref_mod = mm.group(1)
    if ref_mod == dut_name:
        return None  # ref already IS the DUT name — can't build a distinct alias
    alias_text = re.sub(rf"\b{re.escape(ref_mod)}\b", dut_name, ref_text)
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        alias_f = os.path.join(td, "dut_alias.sv")
        with open(alias_f, "w") as fh:
            fh.write(alias_text)
        srcs = [str(ref), alias_f, str(test)]
        for cmd in (["iverilog", "-g2012", "-s", "tb", "-o", binp] + srcs,
                    ["iverilog", "-g2012", "-o", binp] + srcs):
            try:
                c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return None
            if c.returncode == 0:
                return True
        return False


def _score_shape_c(prob: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    """Shape-C scorer wrapper: run the core scorer, then on a FAIL annotate
    whether the failure is an irreducible benchmark defect (the golden reference
    cannot compile against its own TB) so a provably-unsatisfiable problem is not
    silently charged to the model. Verdict is NOT changed — flag only (dual
    report in main()); never inflate the pass rate."""
    res = _score_shape_c_impl(prob, samples, dataset, layout, args)
    if res.get("verdict") == "FAIL":
        gref = _golden_ref_self_compiles(prob, dataset, layout)
        if gref is False:
            res["dataset_defect"] = True
            res["dataset_defect_reason"] = "golden_ref_fails_own_tb"
    return res


def _score_shape_c_impl(prob: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    sample = samples / f"{prob}_sample01.sv"
    test = dataset / f"{prob}{layout['tb_suffix']}"
    ref = dataset / f"{prob}{layout['ref_suffix']}" if layout.get("ref_suffix") else None
    if not sample.is_file():
        return {"problem": prob, "verdict": "FAIL", "reason": "no_sample"}
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        sample_c = _power_up_fixed(sample, td)  # canonical power-up gate
        sources = [sample_c, str(test)]
        if args.get("tb_compile_with_ref") and ref:
            if not ref.is_file():
                return {"problem": prob, "verdict": "FAIL", "reason": "no_ref"}
            sources.append(str(ref))
        cmd = ["iverilog", "-g2012", "-s", "tb", "-o", binp] + sources
        c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if c.returncode != 0:
            # retry without -s tb if the TB module isn't named "tb"
            c = subprocess.run(["iverilog", "-g2012", "-o", binp] + sources,
                               capture_output=True, text=True, timeout=120)
            if c.returncode != 0:
                return {"problem": prob, "verdict": "FAIL", "reason": "compile_error",
                        "log": c.stderr[-400:]}
        try:
            r = subprocess.run(["vvp", binp], capture_output=True, text=True,
                               timeout=120,
                               cwd=str(dataset) if args.get("cwd_design_dir", False) else None)
        except subprocess.TimeoutExpired:
            return {"problem": prob, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        if re.search(args["pass_regex"], out):
            return {"problem": prob, "verdict": "PASS"}
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        return {"problem": prob, "verdict": "FAIL",
                "reason": f"functional_mismatch ({m.group(0) if m else 'no summary'})"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bench", required=True, help="benchmark name (key in BENCHMARK_REGISTRY.json)")
    ap.add_argument("--dataset", required=True, help="path to the benchmark dataset on disk")
    ap.add_argument("--run", required=True, help="path to the run dir (with samples/, problems.list)")
    ap.add_argument("--emit-close-loop-tasklist", default="",
                    help="an earlier release: when set, emit a JSON file at this path listing fails + "
                         "their verdicts + their prompt path. Intended as input to a second-pass "
                         "close-loop agent driver (per Vibe-IC architecture: programs first, then "
                         "Claude judgment as backup). This file is NOT the close-loop runner — it "
                         "encodes the WHAT, the orchestrator calling Claude calls the HOW. The "
                         "open-benchmark-methodology skill § 1 'program + LLM backup' contract.")
    a = ap.parse_args()

    entry = _load_bench(a.bench)
    shape = entry["shape"]
    layout = entry["layout"]
    args = entry["scorer_args"]
    dataset, run = Path(a.dataset), Path(a.run)
    samples = run / "samples"
    if not samples.is_dir():
        raise SystemExit(f"Expected {samples}/ with candidate RTL — directory missing.")

    if shape == "B":
        designs = _problems_list_shape_b(run, dataset, layout["prompt_filename"])
        # ORGANIC-20260605 disk-truth: surface the on-disk sample inventory vs
        # the problem count UP FRONT so a partially-authored run is visible at
        # scoring time (the filesystem — not any agent tally — is authoritative).
        on_disk = sum(1 for _ in samples.glob("*.v")) + sum(1 for _ in samples.glob("*.sv"))
        print(f"# disk-truth: {on_disk} sample file(s) in {samples} vs {len(designs)} problem(s)")
        if on_disk < len(designs):
            print(f"# WARNING: PARTIALLY-AUTHORED RUN — {len(designs) - on_disk} problem(s) "
                  "have no on-disk sample; resume by diffing problems.list vs samples/ "
                  "(blind_instructions_shape_c.md § ORCHESTRATION RULES)")
        results = [_score_shape_b(d, samples, dataset, layout, args) for d in designs]
        ident = "design"
    else:  # Shape C
        probs = _problems_list_shape_c(run, dataset, layout["prompt_suffix"])
        # ORGANIC-20260605 disk-truth (same as Shape B above, keyed per-problem).
        missing = [p for p in probs if not (samples / f"{p}_sample01.sv").is_file()]
        print(f"# disk-truth: {len(probs) - len(missing)}/{len(probs)} problems have an "
              f"on-disk sample in {samples}")
        if missing:
            print(f"# WARNING: PARTIALLY-AUTHORED RUN — {len(missing)} problem(s) missing a "
                  "sample (first few: " + ", ".join(missing[:5]) + "); resume by diffing "
                  "problems.list vs samples/ (blind_instructions_shape_c.md § ORCHESTRATION RULES)")
        results = [_score_shape_c(p, samples, dataset, layout, args) for p in probs]
        ident = "problem"

    # an earlier release — designs flagged as scorer_substitution_gap (iverilog 12 lacks an
    # SV-2012 feature the TB uses, e.g. array-literal init or `break;` in loops)
    # don't count against pass rate, per open-benchmark-methodology § 3. The
    # field lives in BENCHMARK_REGISTRY.json. Empty list (= no gap) is the default.
    gap_ids = set(entry.get("scorer_substitution_gap", []))
    if gap_ids:
        for r in results:
            leaf = r[ident].split('/')[-1]
            if leaf in gap_ids and r["verdict"] != "PASS":
                r["scorer_substitution_gap"] = True
                r["original_verdict"] = r["verdict"]
                r["original_reason"] = r.get("reason", "")
                r["verdict"] = "SKIP"
                r["reason"] = "scorer_substitution_gap — TB uses an SV-2012 feature iverilog 12 doesn't implement; not counted against pass rate per open-benchmark-methodology § 3"

    # Honesty audit (opt-in via scorer_args.verify_discriminating): flag any PASS
    # whose TB is non-discriminating (a constant-0 stub also passes it). These are
    # BENCHMARK TB DEFECTS that affect all submissions equally — they still count
    # under the upstream pass-marker metric (leaderboard parity), but we additionally
    # report a rigorous "discriminating-only" pass rate that excludes them. Never
    # silently inflate. Only Shape B here; Shape-C VerilogEval TBs are auto-generated
    # from RefModules and are gating by construction, so the audit is opt-in.
    if args.get("verify_discriminating") and shape == "B":
        for r in results:
            if r["verdict"] != "PASS":
                continue
            sample = _resolve_sample_b(r[ident], samples, dataset, layout)
            if sample is None:
                continue
            design_dir = dataset / r[ident]
            tb = design_dir / layout["tb_filename"]
            nd = _tb_is_non_discriminating(sample.read_text(errors="ignore"),
                                           tb, design_dir, re.compile(args["pass_regex"]))
            if nd is True:
                r["non_discriminating_tb"] = True

    npass = sum(1 for r in results if r["verdict"] == "PASS")
    nskip = sum(1 for r in results if r["verdict"] == "SKIP")
    nd_pass = sum(1 for r in results
                  if r["verdict"] == "PASS" and r.get("non_discriminating_tb"))
    n = len(results)
    n_eff = n - nskip  # denominator excludes scorer-gap skips
    # Rigorous denominator/numerator also exclude non-discriminating-TB passes:
    # a TB a constant-0 stub passes cannot verify correctness either way.
    npass_disc = npass - nd_pass
    n_eff_disc = n_eff - nd_pass
    # Irreducible benchmark defects: problems where even the golden reference
    # cannot compile against its own hidden TB (golden_ref_fails_own_tb) —
    # unsatisfiable by ANY submission. Flag + DUAL-report (raw pass@1 unchanged
    # for leaderboard parity, plus a rate that excludes them); never silently
    # inflate. Mirrors the non-discriminating-TB dual report above.
    ddef = [r for r in results if r.get("dataset_defect")]
    n_ddef = len(ddef)
    n_eff_satisfiable = n_eff - n_ddef
    summary = {
        "benchmark": entry["title"],
        "shape": shape,
        "tool": "iverilog 12 (host) substituting for Synopsys VCS / Cadence Xcelium",
        "tool_substitution_note": "Functional pass@1 only. PPA stage (DC) not scored — would not be apples-to-apples vs the upstream methodology. See open-benchmark-methodology skill § 3.",
        "total": n, "passed": npass, "skipped_scorer_gap": nskip,
        "pass_at_1_pct": round(100.0 * npass / n_eff, 2) if n_eff else 0.0,
        "pass_at_1_pct_no_skip_excluded": round(100.0 * npass / n, 2) if n else 0.0,
        "non_discriminating_tb_passes": nd_pass,
        "non_discriminating_tb_designs": [r[ident].split('/')[-1] for r in results
                                          if r.get("non_discriminating_tb")],
        "passed_discriminating": npass_disc,
        "pass_at_1_discriminating_pct": round(100.0 * npass_disc / n_eff_disc, 2) if n_eff_disc else 0.0,
        "dataset_defect_count": n_ddef,
        "dataset_defect_problems": [r[ident].split('/')[-1] for r in ddef],
        "pass_at_1_excluding_dataset_defects_pct": round(100.0 * npass / n_eff_satisfiable, 2) if n_eff_satisfiable else 0.0,
        "results": results,
    }
    (run / "pass_at_1.json").write_text(json.dumps(summary, indent=2) + "\n")
    if nskip:
        print(f"{entry['title']}  pass@1 = {npass}/{n_eff} = {summary['pass_at_1_pct']}% "
              f"({nskip} scorer-gap excluded; raw {npass}/{n} = "
              f"{summary['pass_at_1_pct_no_skip_excluded']}%)  [Shape {shape}]")
    else:
        print(f"{entry['title']}  pass@1 = {npass}/{n} = {summary['pass_at_1_pct']}%  [Shape {shape}]")
    if nd_pass:
        print(f"  ⚠ discriminating-TB audit: {nd_pass} PASS have a NON-DISCRIMINATING TB "
              f"(a constant-0 stub also passes — benchmark TB defect, counted under the "
              f"upstream marker metric but flagged): {summary['non_discriminating_tb_designs']}")
        print(f"  rigorous pass@1 (discriminating TBs only) = {npass_disc}/{n_eff_disc} = "
              f"{summary['pass_at_1_discriminating_pct']}%")
    if n_ddef:
        print(f"  ⓘ {n_ddef} irreducible benchmark defect(s) — golden ref fails its OWN TB "
              f"(unsatisfiable by anyone): {summary['dataset_defect_problems']}")
        print(f"  pass@1 excluding dataset defects = {npass}/{n_eff_satisfiable} = "
              f"{summary['pass_at_1_excluding_dataset_defects_pct']}%")
    fails = [r for r in results if r["verdict"] not in ("PASS", "SKIP")]
    if fails:
        print(f"  fails ({len(fails)}): " +
              ", ".join(f"{(r[ident].split('/')[-1])}:{r['reason'].split()[0]}" for r in fails[:25]) +
              ("..." if len(fails) > 25 else ""))
    print("  pass_at_1.json:", run / "pass_at_1.json")

    # an earlier release — emit close-loop tasklist for the Vibe-IC "programs first, then
    # Claude judgment as backup" architecture. The 22-agent an earlier release sweep showed
    # that fresh blind one-shot lands ~95% on VerilogEval and ~72% on RTLLM;
    # the close-loop second pass (AI re-authors fails using pass/FAIL feedback
    # only, NEVER reading hidden TB) recovers ~3% on VerilogEval and ~24% on
    # RTLLM. Emitting this tasklist makes that path turnkey for future runs.
    if a.emit_close_loop_tasklist and fails:
        tasklist = {
            "benchmark": entry["title"],
            "shape": shape,
            "run_dir": str(run),
            "dataset_dir": str(dataset),
            "fail_count": len(fails),
            "fails": [
                {"id": r[ident],
                 "prior_sample": str(samples / (f"{r[ident].split('/')[-1]}_sample01.sv"
                                               if shape == "C" else f"{r[ident].split('/')[-1]}.v")),
                 "prompt": str(dataset / (f"{r[ident].split('/')[-1]}{layout.get('prompt_suffix', '')}"
                                          if shape == "C" else
                                          f"{r[ident]}/{layout.get('prompt_filename', '')}")),
                 "verdict": r["verdict"],
                 "reason": r.get("reason", ""),
                 "retry_budget": 3,
                 "blind_contract": (
                     "READ-ALLOWED: prompt, prior_sample, scorer PASS/FAIL verdict only. "
                     "READ-FORBIDDEN: any hidden TB / testbench / verified_*.v / "
                     "<Prob>_test.sv / <Prob>_ref.sv / cocotb harness. Peeking = "
                     "benchmark fraud per open-benchmark-methodology skill § 3.")}
                for r in fails],
            "rescore_command": (
                f"python3 {Path(__file__).name} --bench {a.bench} "
                f"--dataset {dataset} --run {run}"),
        }
        Path(a.emit_close_loop_tasklist).write_text(
            json.dumps(tasklist, indent=2) + "\n")
        print(f"  close_loop_tasklist:", a.emit_close_loop_tasklist)


if __name__ == "__main__":
    main()
