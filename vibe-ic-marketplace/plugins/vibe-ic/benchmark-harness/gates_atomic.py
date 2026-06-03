#!/usr/bin/env python3
"""gates_atomic.py — Shape C per-problem gates for atomic-micro-problem benchmarks.

This is the parameterized version of the gates.py used in the 2026-05-28
VerilogEval-v2 + VerilogEval-Human runs (see
benchmark_external/verilogeval_v2/run_fresh_v0125/gates.py for the canonical
ancestor). Per open-benchmark-methodology skill § 2 Shape C: lightweight
gates-based harness for atomic micro-problems (≥100 of them) where the full
runner per problem is overhead-dominated.

The agent authors `spec.yaml` + `sample.sv` in `<workdir>/<prob>/`; this driver
runs the deterministic pipeline + gates and copies the scoreable sample on PASS.

Hard gates (must pass to emit the sample):
  1. phase1_engine run-all  <spec.yaml> → generated_docs/L*.json   (PROGRAM)
  2. spec_self_consistency_check --spec <prompt>                  (PROGRAM, pre-RTL lint)
  3. iverilog -g2012 syntax compile of sample.sv                  (PROGRAM)
  4. spec_conformance_check --rtl-dir . --spec <prompt> --top <M> (PROGRAM, ports/widths/reset)
  5a. ENFORCED: rtl_hygiene_lint --fix <sample>                    (PROGRAM — power-up determinism)
  5b. rtl_hygiene_lint --severity WARN <sample>                    (PROGRAM)

The 5a `--fix` enforcement is the v0.1.24 lesson (see memory
[[verilogeval-v0125-fresh-three-benchmark-run]]): reset-less registered outputs
get `initial = 0` inserted before emit, so the blind path can never leak a
power-up-X sample regardless of what the AI authoring step did.

Usage (called per-problem by the agent during a Shape C run):
    python3 gates_atomic.py --prob <Prob> --workdir <run>/work --dataset <ds> \\
                            --bench <bench>                         # registry lookup
    # or for benchmarks not in the registry yet:
    python3 gates_atomic.py --prob <Prob> --workdir <run>/work --dataset <ds> \\
                            --prompt-suffix _prompt.txt --top-module TopModule

The driver writes <workdir>/<prob>/gates.json with each step's verdict.
Exit 0 iff phase1_run_all + iverilog_compile pass (the two hard gates).
On hard-PASS the scoreable artifact lands at <workdir>/../samples/<prob>_sample01.sv.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../benchmark-harness/
PLUGIN = HERE.parent                            # .../vibe-ic/
PROGRAMS = PLUGIN / "programs"


def _registry_entry(bench: str) -> dict | None:
    reg_file = HERE / "BENCHMARK_REGISTRY.json"
    if not reg_file.is_file():
        return None
    reg = json.loads(reg_file.read_text())
    return reg.get("benchmarks", {}).get(bench)


def run(cmd, cwd=None, timeout=120, env=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def _l9_rendered(wd: Path) -> bool:
    """True if an L9 doc exists in EITHER the primary engine's out/ dir OR the
    bundled fallback runner's phase1_proj/phase1/ dir.

    Both are checked so a CLEAN plugin install passes the phase1 hard gate
    self-contained: tools/phase1_engine is NOT shipped in the plugin (it is a
    dev-only symlink to the monorepo), so on a clean machine the primary
    `tools.phase1_engine.cli run-all <spec> <wd>/out` path is dead and the
    bundled fallback `phase1_one_shot_runner.py` runs instead, writing L9 to
    <wd>/phase1_proj/phase1/generated_docs/ rather than <wd>/out/generated_docs/.
    (ORGANIC-20260603-ingest-engine-cli-missing-from-plugin-cache fix.)
    """
    for d in (wd / "out" / "generated_docs",
              wd / "phase1_proj" / "phase1" / "generated_docs"):
        if d.is_dir() and any(d.glob("L9*.json")):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prob", required=True, help="problem id (e.g. Prob001_zero)")
    ap.add_argument("--workdir", required=True, help="<run>/work/ (will be joined with --prob)")
    ap.add_argument("--dataset", required=True, help="dataset root (where <prob><prompt-suffix> lives)")
    ap.add_argument("--bench", default="", help="benchmark name (looks up layout from BENCHMARK_REGISTRY.json)")
    ap.add_argument("--prompt-suffix", default="", help="override: prompt filename suffix (e.g. _prompt.txt). Default from registry.")
    ap.add_argument("--top-module", default="", help="override: top module name. Default 'TopModule' for VerilogEval-style.")
    a = ap.parse_args()

    # registry-driven defaults
    prompt_suffix = a.prompt_suffix
    top_module = a.top_module
    if a.bench:
        e = _registry_entry(a.bench)
        if e and e.get("layout"):
            prompt_suffix = prompt_suffix or e["layout"].get("prompt_suffix", "")
            mns = e["layout"].get("module_name_strategy", "")
            if mns == "always_TopModule" and not top_module:
                top_module = "TopModule"
    prompt_suffix = prompt_suffix or "_prompt.txt"
    top_module = top_module or "TopModule"

    ds = Path(a.dataset)
    prompt = ds / f"{a.prob}{prompt_suffix}"
    wd = Path(a.workdir) / a.prob
    spec = wd / "spec.yaml"
    sample = wd / "sample.sv"
    steps = {}

    if not prompt.is_file():
        print(f"NO_PROMPT {prompt}")
        sys.exit(2)
    for f in (spec, sample):
        if not f.is_file():
            print(f"MISSING {f} — agent must author it first")
            sys.exit(2)

    # v0.1.38 fix (Bucket A — 3 agents reported): probe BOTH locations for
    # `tools/phase1_engine`. In a monorepo checkout the package lives at
    # `<vibe-ic-repo>/tools/phase1_engine` (= PLUGIN.parents[1]/tools/phase1_engine);
    # in a flat plugin install it lives at `<plugin>/tools/phase1_engine`. The
    # cwd for the python -m import + the PYTHONPATH must agree.
    candidates = []
    if PLUGIN.parts[-2:] == ("plugins", "vibe-ic"):
        candidates.append(PLUGIN.parents[1])         # monorepo: vibe-ic repo root
    candidates.append(PLUGIN)                         # flat plugin install
    cli_cwd = next((c for c in candidates if (c / "tools" / "phase1_engine" / "cli.py").is_file()),
                   PLUGIN)
    cli_env = os.environ.copy()
    cli_env["PYTHONPATH"] = str(cli_cwd) + os.pathsep + cli_env.get("PYTHONPATH", "")

    # 1. phase1_engine run-all  spec.yaml -> generated_docs/L*.json
    # v0.1.38 fix (Bucket A — 3 agents reported): pass `env=cli_env` so PYTHONPATH
    # propagates. Without env=, subprocess inherits a copy that DOES NOT include
    # cli_env modifications and `tools.phase1_engine` import fails.
    rc, out = run([sys.executable, "-m", "tools.phase1_engine.cli",
                   "run-all", str(spec), str(wd / "out")],
                  cwd=str(cli_cwd), timeout=180, env=cli_env)
    if rc != 0:
        # v0.1.38 fix (Bucket A — Human b7): phase1_one_shot_runner.py takes a
        # PROJECT DIR (positional), NOT --spec <yaml>. The Path-A bridge inside
        # the runner converts input/phase1_prompt.md → input/docs/design_description.md.
        # For Shape C we stage a minimal project: <wd>/input/docs/spec.md (copy of spec).
        proj = wd / "phase1_proj"
        (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
        try:
            (proj / "input" / "docs" / "design_description.md").write_text(spec.read_text())
        except Exception:
            pass
        rc, out = run([sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
                       str(proj)], timeout=180, env=cli_env)
    # L9 may land in the primary engine's out/ dir OR the bundled fallback's
    # phase1_proj/phase1/ dir — probe BOTH so a clean plugin install passes the
    # phase1 hard gate self-contained (see _l9_rendered).
    l9_ok = _l9_rendered(wd)
    steps["phase1_run_all"] = {"verdict": "PASS" if rc == 0 and l9_ok else "FAIL",
                               "rc": rc, "l9_rendered": l9_ok, "log": out[-400:]}

    # 2. pre-RTL spec self-consistency lint (prompt alone)
    rc, out = run([sys.executable, str(PROGRAMS / "spec_self_consistency_check.py"),
                   "--spec", str(prompt)], env=cli_env)
    steps["spec_self_consistency"] = {"verdict": "PASS" if "PASS" in out else "WARN",
                                      "rc": rc, "log": out[-300:]}

    # 3. iverilog -g2012 syntax compile (no test/ref)
    rc, out = run(["iverilog", "-g2012", "-o", str(wd / "syn.bin"), str(sample)])
    steps["iverilog_compile"] = {"verdict": "PASS" if rc == 0 else "FAIL",
                                 "rc": rc, "log": out[-400:]}

    # 4. spec_conformance_check vs prompt-derived contract
    sem_manifest = wd / "semantic_manifest.json"
    rc, out = run([sys.executable, str(PROGRAMS / "spec_conformance_check.py"),
                   "--rtl-dir", str(wd), "--spec", str(prompt), "--top", top_module,
                   "--semantic-manifest", str(sem_manifest)], env=cli_env)
    cverd = "PASS" if "PASS" in out.split("\n")[0] else ("WARN" if "WARN" in out else "FAIL")
    steps["spec_conformance"] = {"verdict": cverd, "rc": rc, "log": out[-500:]}
    if sem_manifest.is_file():
        try:
            steps["semantic_confirm"] = json.loads(sem_manifest.read_text())
        except Exception:
            pass

    # 5a. ENFORCED power-up determinism (v0.1.24 lesson) — repair reset-less
    #     registered outputs IN-PLACE before emit. Structural + prompt-blind.
    rc, out = run([sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
                   "--fix", str(sample)], env=cli_env)
    steps["rtl_hygiene_fix"] = {"verdict": "APPLIED" if "repaired" in out else "noop",
                                "rc": rc, "log": out[-300:]}

    # 5b. rtl_hygiene_lint at WARN (informational; v0.1.10 rule 5 + later additions)
    rc, out = run([sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
                   "--severity", "WARN", str(sample)], env=cli_env)
    hverd = "PASS" if rc == 0 else "WARN"
    steps["rtl_hygiene_lint"] = {"verdict": hverd, "rc": rc, "log": out[-600:]}

    hard_ok = (steps["phase1_run_all"]["verdict"] == "PASS"
               and steps["iverilog_compile"]["verdict"] == "PASS")
    if hard_ok:
        samples_dir = wd.parent.parent / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)
        dst = samples_dir / f"{a.prob}_sample01.sv"
        dst.write_text(sample.read_text())
        steps["sample_emitted"] = str(dst)

    (wd / "gates.json").write_text(json.dumps({"prob": a.prob,
                                               "hard_gates_pass": hard_ok,
                                               "top_module": top_module,
                                               "steps": steps}, indent=2) + "\n")
    print(json.dumps({"prob": a.prob, "hard_gates_pass": hard_ok,
                      "summary": {k: v.get("verdict") for k, v in steps.items()
                                  if isinstance(v, dict)}}, indent=2))
    sys.exit(0 if hard_ok else 1)


if __name__ == "__main__":
    main()
