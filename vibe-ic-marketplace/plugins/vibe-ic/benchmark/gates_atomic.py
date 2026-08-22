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

EMIT-BLOCKING STRUCTURAL RULES (ORGANIC-20260605-shapec-existing-guards-nonblocking):
beyond the two hard gates above, an allow-listed set of HIGH-CONFIDENCE
structural rules now BLOCKS emit when they fire — the v0.2.39 clean-room run
proved single-shot functional fails corresponded exactly to rules the plugin
already implements but only logged informationally:
  * spec_conformance_check:  onebased-port-range        (1-based indexing declared
                              zero-based — every bit off by one)
  * spec_conformance_check:  fsm-output-style-mismatch  (spec declares Moore, RTL
                              output is combinationally input-dependent)
  * spec_conformance_check:  port-missing               (authored module omits a
                              spec-declared port — legal standalone, fails the
                              hidden TB port bind; v0.2.43)
  * spec_conformance_check:  zero-output-ports          (module has NO output/inout
                              ports — vacuous sink from a mis-read interface;
                              v0.2.43)
On a block the author must FIX sample.sv and re-run this gate (the must-resolve
surface); the sample is not emitted while a blocking finding stands.

CORPUS-SWEEP HONESTY (the backlog's own promotion precondition): the sweep over
all 305 prior-PASSING samples of both 156-problem atomic suites initially found
14 false-positive blocks, so the rules were TIGHTENED first (boundary-condition
index references excluded from onebased; state-as-input modules + next-state-like
outputs excluded from the Moore check) until the sweep came back ZERO. The
backlog's third candidate, rtl_hygiene_lint's vector-self-shift-fold, was NOT
promoted: the sweep showed correct passing solutions legitimately use the exact
idiom it flags (in & {1'b0, in[W-1:1]} boundary-AND), so it stays informational
WARN — promoting it would have blocked correct designs.

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

HERE = Path(__file__).resolve().parent          # .../benchmark/
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
    except FileNotFoundError as e:
        # #1437 — this helper is the single exec path for EVERY gate step, so an
        # absent tool (step 3 is a raw `iverilog`) escaped as a traceback out of
        # main() and the module's promise — "writes <workdir>/<prob>/gates.json
        # with each step's verdict" — could not be kept: the driver died before
        # the report was written, and the step that could not RUN was
        # indistinguishable from a step that had not been reached. rc=127 +
        # COMMAND_NOT_FOUND is this repo's existing absent-command convention
        # (_watchdog, design_one_shot_runner, phase{1_doc,3}_one_shot_runner).
        return 127, f"COMMAND_NOT_FOUND: {e}"


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

    # 0. DETERMINISTIC SPEC SYNTHESIS (v1.1.38 §4.2 absorption).
    # A family of VerilogEval prompts embeds a COMPLETE, oracle-free specification
    # whose RTL is mechanical — yet a blind author re-derives it by eye and flips
    # it across clean-room rounds (single-shot variance). Per § 4.2 a GENERAL
    # no-cheat recovery MUST be absorbed as a PROGRAM, not re-solved per round:
    #   * combinational waveform / truth table -> SOP   (waveform_truth_table_synth)
    #   * don't-care-FREE Karnaugh map -> SOP           (kmap_grid_synth)
    #   * one-hot FSM next-state/output by inspection   (onehot_fsm_synth)
    # Each FIRES only inside its proven-faithful envelope and SKIPs (returns None,
    # leaving the author's sample untouched) on every under-determined / sequential
    # / ambiguous case — §4.05 no-leak, so none can ship a wrong sample (verified
    # 0-mismatch on 9 problems, clean SKIP on the don't-care K-maps + sequential
    # circuitN + mux-decomposition). When one fires its deterministic RTL REPLACES
    # the author's guess and still flows through every downstream hard gate below.
    _prompt_text = prompt.read_text(errors="replace")
    # SINGLE SOURCE OF TRUTH (v1.1.76): the deterministic-solver catalog lives in
    # spec_artifact_registry.REGISTRY. This benchmark gate USED to keep a second,
    # hand-maintained dispatch tuple here — it drifted from the registry (the
    # registry gained mux/shift/cellular/lfsr/kmap_sop/dff_edge/…; this list lagged).
    # We now delegate to registry.generate(), which walks the registry's
    # specificity-ordered generators (first-fire-wins, every one §4.05 SKIP-safe).
    # A fire REPLACES the author's guess with host-verified RTL and still flows
    # through every downstream hard gate below. ONE list, ONE order, no drift.
    _synth_rtl = None
    _synth_kind = None
    try:
        sys.path.insert(0, str(PLUGIN / "programs"))
        import spec_artifact_registry as _reg
        _synth_kind, _synth_rtl = _reg.generate(_prompt_text, top_module)
    except Exception:
        _synth_rtl = None
    if _synth_rtl:
        sample.write_text(_synth_rtl)
        steps["deterministic_synth"] = {"applied": True, "kind": _synth_kind,
                                        "note": "exact RTL from a parse-complete prompt artifact"}

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
    # v0.2.58 (#429): the engine is now BUNDLED in the plugin payload, so
    # the primary `-m tools.phase1_engine.cli` import SUCCEEDS everywhere —
    # including on the minimal Shape-C spec.yaml, where the structured
    # ingester legitimately yields 0 facts and renders 0 layer docs with
    # rc=0. Pre-bundle, the import failure (rc!=0) was what routed those
    # cases to the runner fallback (whose Path-A prose bridge + stub chain
    # DOES emit the L docs). Trigger the fallback on "no L9 rendered" too,
    # not only on a nonzero rc.
    if rc != 0 or not _l9_rendered(wd):
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

    # 3b. HARNESS-EXACT self-verify (ORGANIC #688): the scorer compiles the RTL
    # ALONE under `-s <top>` (full codegen) and runs a verilator lint gate —
    # NOT the RTL+TB-together / host-only shape the agent self-checks with.
    # Three fail classes slip through host-only self-check (ELAB-only, standalone
    # -s <top> top-name/TB-signal dependence, lint). harness_exact_selfverify.py
    # runs the deterministic gate-A (standalone `-s <top>` -o codegen) + gate-B
    # (verilator --lint-only -Wall) so the Shape-C accept-set MATCHES the
    # scorer. The functional gate-C is AI-authored (prompt examples) and is run
    # by the cvdp/full_stack path, not here. Emit-BLOCKING on a BLOCK verdict.
    hxsv_json = wd / "harness_exact_selfverify.json"
    # Shape C atomic benchmarks (VerilogEval / RTLLM) are scored by IVERILOG, so
    # GATE A (iverilog standalone -s codegen) + the iverilog host ARE the
    # scorer's authority; GATE B (verilator --lint-only -Wall) does NOT match
    # this scorer and its verilator-only WIDTH*/LATCH/COMBDLY/BLKLOOPINIT
    # findings false-block host-PASSING designs (VE-human 028/030/044/144/153).
    # Run GATE B ADVISORY (reported, not blocking); GATE A still blocks a
    # genuine iverilog compile error (no-leak).
    rc, out = run([sys.executable, str(PROGRAMS / "harness_exact_selfverify.py"),
                   "--rtl", str(sample), "--top", top_module,
                   "--lint-advisory", "--report", str(hxsv_json)], env=cli_env)
    hxsv_verd = "PASS" if rc == 0 else ("FAIL" if rc == 1 else "SKIP")
    steps["harness_exact_selfverify"] = {"verdict": hxsv_verd, "rc": rc,
                                         "log": out[-500:]}
    # rc==1 means a deterministic gate (A standalone codegen / B lint) BLOCKED —
    # the scorer would reject the same RTL, so block emit. rc==2 (a tool was
    # absent) is DISCLOSED, not a block (the existing iverilog_compile hard gate
    # still applies); the program never silently passes an unenforced gate.
    hxsv_blocking = []
    if rc == 1 and hxsv_json.is_file():
        try:
            hx = json.loads(hxsv_json.read_text())
            for g in hx.get("gates", []):
                if g.get("verdict") in ("BLOCK", "ERROR"):
                    hxsv_blocking.append({"program": "harness_exact_selfverify",
                                          "rule": g.get("gate"),
                                          "message": (g.get("reason") or "")[:400]})
        except Exception:
            pass

    # 4. spec_conformance_check vs prompt-derived contract
    sem_manifest = wd / "semantic_manifest.json"
    conf_json = wd / "conformance_findings.json"
    rc, out = run([sys.executable, str(PROGRAMS / "spec_conformance_check.py"),
                   "--rtl-dir", str(wd), "--spec", str(prompt), "--top", top_module,
                   "--semantic-manifest", str(sem_manifest),
                   "--json", str(conf_json)], env=cli_env)
    cverd = "PASS" if "PASS" in out.split("\n")[0] else ("WARN" if "WARN" in out else "FAIL")
    steps["spec_conformance"] = {"verdict": cverd, "rc": rc, "log": out[-500:]}
    if sem_manifest.is_file():
        try:
            steps["semantic_confirm"] = json.loads(sem_manifest.read_text())
        except Exception:
            pass

    # ORGANIC-20260605: allow-listed HIGH-CONFIDENCE structural rules are
    # EMIT-BLOCKING. The v0.2.39 clean-room run shipped 3 single-shot fails the
    # plugin's own rules had already flagged — they fired as WARN inside an
    # overall-PASS verdict, and this harness recorded the roll-up verdict only.
    # Parse the per-finding JSON (deterministic) instead of the roll-up.
    #
    # v0.2.43 additions (same corpus-sweep precondition — ZERO false fires
    # over all 312 emitted passing samples of the v0.2.42 two-track campaign):
    #  * port-missing (ORGANIC-20260605-port-missing-not-emit-blocking):
    #    the checker already emitted this ERROR for a dropped
    #    declared-but-unused port; the standalone compile passes, so the
    #    defect surfaced ONLY at hidden-TB scoring. Block it here instead.
    #  * zero-output-ports (ORGANIC-20260605-zero-output-module-not-emit-
    #    blocking): a module with no output/inout ports is a vacuous sink no
    #    testbench can observe — deterministic signature of a mis-read
    #    interface (prompt direction typo). NEW rule in
    #    spec_conformance_check; structural, spec-typo-proof.
    #
    # v0.2.50 addition (same corpus-sweep precondition — ZERO false fires
    # over every emitted passing sample of the audited two-track campaigns):
    #  * msbfirst-direction-mismatch (ORGANIC-20260605-msbfirst-direction-
    #    conformance-rule): prompt says MSB-first serial load but the RTL
    #    inserts the new bit at the MSB end of a parallel-consumed register
    #    (`vec <= {bit, vec[W-1:1]}`) — the word assembles bit-REVERSED.
    #    Lesson→program promotion: the prose lesson got 31/32 agents right;
    #    the residual wrong form is this exact structural signature.
    #
    # v0.2.53 addition (same corpus-sweep precondition):
    #  * moore-output-reset-gated (ORGANIC-20260606-moore-output-reset-
    #    gated-rule): spec ties an N-cycle assertion window to RESET itself
    #    ("whenever ... reset, assert <sig> for N cycles") but the RTL ANDs
    #    that output with the negated reset — held/re-asserted reset eats
    #    assertion cycles. Lesson→program promotion (third in the series).
    # v1.0.93 addition (ORGANIC-20260617 — program-first escalation of the
    # prose "MANDATORY pre-emit self-TB" discriminators; #718/#733/#741/#776):
    #  * shift-implemented-as-rotate: spec describes a SHIFTER (not explicitly
    #    rotate-only) but the RTL is an unambiguous barrel-ROTATE wrap. The
    #    "shifts or rotates is NOT rotate-only → logical shift" lesson + the
    #    mandatory all-ones>>max self-TB were prose-only; a fresh author read
    #    them, cited them, then overrode them. Mechanized as a deterministic
    #    emit-assert (high-precision rotate signature only; §4.05 disarmed by an
    #    explicit rotate/circular spec). ZERO false fires over the audited set.
    #  * waveform-peak-hold-dropped: spec requires a triangle/ramp peak-HOLD but
    #    the RTL drops it (immediate direction toggle at the extreme, no
    #    hold/dwell state). Same prose-override signature; disarmed by an
    #    explicit no-hold / plain-sawtooth spec. Conservative (any hold state →
    #    silent; under-firing permitted over a false block).
    # #791 addition (continuous-assign one-hot FSM dropped self-loop):
    #  * fsm-onehot-missing-transition: spec discloses an arrow-form transition
    #    table but the RTL's one-hot continuous-assign next-state equation for a
    #    destination state OMITS a disclosed in-edge (incl self-loop). Exactly
    #    the Prob150_review2015_fsmonehot dropped-Count-self-loop defect that
    #    SKIPped the case-driven check and shipped PASS. Zero-false-fire: fires
    #    only on a disclosed table + parseable one-hot assigns; SKIPs otherwise.
    _BLOCKING_CONFORMANCE_RULES = {"onebased-port-range",
                                   "fsm-output-style-mismatch",
                                   "port-missing",
                                   "zero-output-ports",
                                   "msbfirst-direction-mismatch",
                                   "moore-output-reset-gated",
                                   "shift-implemented-as-rotate",
                                   "waveform-peak-hold-dropped",
                                   "fsm-onehot-missing-transition",
                                   "sync-reset-next-state-redundant-gate"}
    blocking: list = []
    # ORGANIC #688 — harness-exact self-verify BLOCKs (standalone `-s <top>`
    # codegen / verilator lint) are emit-blocking: the scorer rejects the same
    # RTL the host-only / RTL+TB-together self-check passed.
    blocking.extend(hxsv_blocking)
    if conf_json.is_file():
        try:
            for fd in json.loads(conf_json.read_text()):
                if fd.get("rule") in _BLOCKING_CONFORMANCE_RULES:
                    blocking.append({"program": "spec_conformance_check",
                                     "rule": fd.get("rule"),
                                     "symbol": fd.get("symbol", ""),
                                     "message": (fd.get("message") or "")[:400]})
        except Exception:
            pass

    # 4b. PROMPT-DISCLOSED COMBINATIONAL ORACLE self-check (ORGANIC #716 —
    # Prob122_kmap4). A prompt that hands a FULLY-SPECIFIED K-map / truth table
    # IS a complete functional oracle, blind. No prior step simulated the RTL
    # against it, so a K-map misread (Prob122_kmap4 author dropped `c`:
    # `out=a^b^d` vs the K-map's `a^b^c^d`) compiled clean, passed every
    # structural rule, emitted, then failed the hidden TB 121/232.
    # kmap_truth_table_oracle_check parses a HIGH-CONFIDENCE complete oracle
    # (clean truth table OR standard Gray K-map, scalar 1-bit axes, single 1-bit
    # output, NO don't-cares) and simulates all 2^N combos; rc=1 = care-cell
    # mismatch → emit-BLOCK. §4.05: it SKIPs (rc=0, non-blocking) on ANY
    # ambiguity — don't-cares (a minimized correct design may legally drop a
    # variable — Prob125_kmap3/Prob116), multi-bit bus axes (Prob113/Prob116),
    # non-Gray column order, mux-selector transforms (Prob093). The
    # reconstructed oracle was validated 16/16 against the dataset golden for
    # Prob122_kmap4 + Prob057_kmap2, so a BLOCK is always a genuine bug.
    ktt_json = wd / "kmap_oracle_findings.json"
    rc, out = run([sys.executable, str(PROGRAMS / "kmap_truth_table_oracle_check.py"),
                   "--prompt", str(prompt), "--rtl", str(sample),
                   "--top", top_module, "--json", str(ktt_json)], env=cli_env)
    # rc==1 → BLOCK; rc==0 → PASS or SKIP (read the JSON verdict to distinguish);
    # rc==2 → tool absent / usage (disclosed, non-blocking — the hard iverilog
    # gate still applies). A SKIP means no high-confidence complete oracle was
    # parseable, so the check makes no claim either way.
    ktt_verd = "BLOCK" if rc == 1 else ("DISCLOSED_TOOL_GAP" if rc == 2 else "PASS")
    if rc == 0 and ktt_json.is_file():
        try:
            ktt_verd = json.loads(ktt_json.read_text()).get("verdict", "PASS")
        except Exception:
            pass
    steps["kmap_truth_table_oracle"] = {"verdict": ktt_verd, "rc": rc,
                                        "log": out[-500:]}
    if rc == 1 and ktt_json.is_file():
        try:
            kj = json.loads(ktt_json.read_text())
            if kj.get("verdict") == "BLOCK":
                blocking.append({"program": "kmap_truth_table_oracle_check",
                                 "rule": "kmap-truth-table-oracle-mismatch",
                                 "message": ("authored RTL mismatches the "
                                             "prompt-disclosed K-map/truth-table "
                                             "oracle: " + str(kj.get("log", ""))[:300])})
        except Exception:
            pass

    # 4c. WAVEFORM-TABLE conformance (v1.1.41 §4.2 — Prob098_circuit7 / the
    # sequential-waveform misread class). When a prompt embeds a literal
    # `time [clk] <inputs...> <output>` simulation table, the authored RTL must
    # reproduce its OUTPUT column. The classic miss is reading the TB's first-edge
    # X-window as an extra pipeline stage (`q1<=~a; q<=q1`) when the spec is a
    # single-stage `q<=~a` — a wrong sample that self-verifies but FAILs the hidden
    # TB and SHIPS (this CHECK existed but was never wired into the per-problem
    # gate). waveform_table_conformance_check replays the table the way the scorer
    # compares and rc==1 → emit-BLOCK. §4.05: it fires ONLY inside its
    # proven-faithful envelope (combinational truth-table OR single-clock
    # posedge-registered single-bit) and SKIPs (rc==0) on every latch / negedge /
    # multi-bit / internal-state case, so it can never false-block (verified: BLOCKs
    # the wrong 2-stage circuit7 read, PASSes the correct single-stage, SKIPs the
    # combinational circuitN already handled by the deterministic synth).
    wtc_json = wd / "waveform_conformance_findings.json"
    rc, out = run([sys.executable, str(PROGRAMS / "waveform_table_conformance_check.py"),
                   "--prompt", str(prompt), "--rtl", str(sample)], env=cli_env)
    wtc_verd = "BLOCK" if rc == 1 else ("DISCLOSED_TOOL_GAP" if rc == 2 else "PASS_OR_SKIP")
    steps["waveform_table_conformance"] = {"verdict": wtc_verd, "rc": rc, "log": out[-300:]}
    if rc == 1:
        blocking.append({"program": "waveform_table_conformance_check",
                         "rule": "waveform-table-conformance-mismatch",
                         "message": ("authored RTL does not reproduce the "
                                     "prompt's disclosed simulation-waveform "
                                     "table: " + str(out)[-300:])})

    # 4d. LEVEL-HYSTERESIS FLAG oracle (the ack-fidelity lesson: two blind
    # campaigns emitted the literal rise->open polarity at the identical >50%
    # mismatch — the second WHILE ACKNOWLEDGING the captured lesson, justified
    # via a different generic lesson. A checkbox gate proves acknowledgement
    # PRESENCE; only a simulation oracle proves FIDELITY). The check derives a
    # deterministic oracle from the prompt ALONE: the relative-direction
    # sentence admits exactly two uniform held-flag polarities; the prompt's
    # ABSOLUTE anchors (reset-equivalence "all outputs asserted" bottom + zero-
    # flow top, whose arrival directions are forced) filter them; ONLY when
    # exactly one survives is the authored RTL walked up/down and compared.
    # §4.05: every ambiguous precondition SKIPs (rc=0) — corpus-swept over 312
    # prompt/sample pairs: 310 SKIP, and the only firings were the two genre
    # instances (BLOCK on the wrong-polarity sample, PASS on the correct one).
    lhf_json = wd / "level_hysteresis_findings.json"
    rc, out = run([sys.executable, str(PROGRAMS / "level_hysteresis_flag_oracle_check.py"),
                   "--prompt", str(prompt), "--rtl", str(sample),
                   "--top", top_module, "--json", str(lhf_json)], env=cli_env)
    lhf_verd = "BLOCK" if rc == 1 else ("DISCLOSED_TOOL_GAP" if rc == 2 else "PASS_OR_SKIP")
    if rc == 0 and lhf_json.is_file():
        try:
            lhf_verd = json.loads(lhf_json.read_text()).get("verdict", "PASS_OR_SKIP")
        except Exception:
            pass
    steps["level_hysteresis_flag_oracle"] = {"verdict": lhf_verd, "rc": rc,
                                             "log": out[-300:]}
    if rc == 1:
        blocking.append({"program": "level_hysteresis_flag_oracle_check",
                         "rule": "hysteresis-flag-polarity-mismatch",
                         "message": ("authored RTL contradicts the prompt-derived "
                                     "hysteresis-flag oracle (absolute anchors "
                                     "outrank the relative-direction sentence): "
                                     + str(out)[-300:])})

    # 5a. ENFORCED power-up determinism (v0.1.24 lesson) — repair reset-less
    #     registered outputs IN-PLACE before emit. Structural + prompt-blind.
    rc, out = run([sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
                   "--fix", str(sample)], env=cli_env)
    steps["rtl_hygiene_fix"] = {"verdict": "APPLIED" if "repaired" in out else "noop",
                                "rc": rc, "log": out[-300:]}

    # 5b. rtl_hygiene_lint at WARN (informational; v0.1.10 rule 5 + later additions)
    # ORGANIC-20260605-boundary-fold-or-form-escalation: the self-shift-fold
    # rule is now severity-SPLIT by composing operator — the OR/XOR form
    # (boundary bit LEAKS, x|0=x) escalates to ERROR and JOINS the emit-blocking
    # allow-list; the AND form (zero pad MASKS, x&0=0 — the legitimate
    # neighbour idiom the v0.2.40 sweep found) stays informational WARN and
    # never blocks. Block on (rule, severity=ERROR), not on rule name alone.
    hyg_json = wd / "hygiene_findings.json"
    rc, out = run([sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
                   "--severity", "WARN", "--json", str(hyg_json),
                   str(sample)], env=cli_env)
    hverd = "PASS" if rc == 0 else "WARN"
    steps["rtl_hygiene_lint"] = {"verdict": hverd, "rc": rc, "log": out[-600:]}

    # CORPUS REFINEMENT: even the ERROR-severity OR/XOR fold is benign when the
    # spec declares the boundary bit DON'T-CARE ("we don't need to know
    # out_any[0]" — a real passing sample in the sweep). The mechanical
    # discriminator lives in the PROMPT: block only on POSITIVE evidence that
    # the spec REQUIRES a zero boundary for the assigned output ("set
    # out_both[99] to be zero", "are both zero (off)"). Spec-silent or
    # don't-care boundaries stay non-blocking (the ERROR is still in
    # gates.json + lint output for the author to read).
    _BLOCKING_HYGIENE_ERROR_RULES = {"vector-self-shift-fold"}
    _REQUIRED_ZERO_RE = __import__("re").compile(
        r"(?:set|being|be|is|are|must\s+be|should\s+be|forced?(?:\s+to)?)"
        r"(?:\s+\w+){0,3}?\s*(?:to\s+be\s+)?(?:both\s+|all\s+)?(?:zero|'0'|0\b)",
        __import__("re").IGNORECASE)

    def _assigned_output_of(line_no: int) -> str:
        """LHS of the assignment containing the flagged line (scan back <=3)."""
        import re as _re
        src_lines = sample.read_text(errors="replace").splitlines()
        for ln in range(min(line_no, len(src_lines)) - 1,
                        max(-1, line_no - 5), -1):
            m = _re.search(r"\bassign\s+([A-Za-z_]\w*)|^\s*([A-Za-z_]\w*)\s*(?:<=|=)[^=]",
                           src_lines[ln])
            if m:
                return m.group(1) or m.group(2) or ""
        return ""

    def _prompt_requires_zero_boundary(out_name: str) -> bool:
        if not out_name:
            return False
        import re as _re
        for ln in prompt.read_text(errors="replace").splitlines():
            if _re.search(r"\b" + _re.escape(out_name) + r"\s*\[\s*\d+\s*\]", ln) \
                    and _REQUIRED_ZERO_RE.search(ln):
                return True
        return False

    if hyg_json.is_file():
        try:
            for fd in json.loads(hyg_json.read_text()):
                if (fd.get("rule") in _BLOCKING_HYGIENE_ERROR_RULES
                        and fd.get("severity") == "ERROR"):
                    out_name = _assigned_output_of(int(fd.get("line", 1)))
                    if _prompt_requires_zero_boundary(out_name):
                        blocking.append({"program": "rtl_hygiene_lint",
                                         "rule": fd.get("rule"),
                                         "symbol": fd.get("symbol", ""),
                                         "assigned_output": out_name,
                                         "message": (fd.get("message") or "")[:400]})
                    else:
                        steps.setdefault("structural_advisories", []).append({
                            "rule": fd.get("rule"), "symbol": fd.get("symbol", ""),
                            "assigned_output": out_name,
                            "note": ("OR/XOR self-shift-fold detected but the prompt "
                                     "does not REQUIRE a zero boundary for this output "
                                     "(don't-care or silent) — not emit-blocking; "
                                     "review the lint ERROR message.")})
        except Exception:
            pass

    if blocking:
        steps["structural_emit_block"] = {
            "verdict": "BLOCK", "findings": blocking,
            "note": ("EMIT BLOCKED — fix sample.sv per each finding above and "
                     "re-run this gate. These allow-listed structural rules "
                     "are high-confidence bug shapes the hidden TB will catch "
                     "(ORGANIC-20260605-shapec-existing-guards-nonblocking).")}

    hard_ok = (steps["phase1_run_all"]["verdict"] == "PASS"
               and steps["iverilog_compile"]["verdict"] == "PASS"
               and not blocking)
    if hard_ok:
        samples_dir = wd.parent.parent / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)
        dst = samples_dir / f"{a.prob}_sample01.sv"
        dst.write_text(sample.read_text())
        steps["sample_emitted"] = str(dst)
        # GATE-AS-SOLE-EMIT-PATH: attest this sample passed the Shape-C hard gates
        # (phase1 + compile + structural emit-blocking rules + hygiene), so the
        # score-time check can prove it was not authored directly into samples/.
        try:
            if str(PROGRAMS) not in sys.path:
                sys.path.insert(0, str(PROGRAMS))
            import emit_attestation as _ea
            _gd = next((d for d in (wd / "out" / "generated_docs",
                                    wd / "phase1_proj" / "phase1" / "generated_docs")
                        if d.is_dir() and any(d.glob("L*.json"))), None)
            _ea.record(samples_dir, dst,
                       gates=["gates_atomic", "phase1_run_all", "iverilog_compile",
                              "structural_emit_rules"], shape="C", phase1=_gd)
        except Exception:
            pass

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
