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
import argparse, atexit, json, shlex, subprocess, tempfile, os, re, shutil, sys
from pathlib import Path
from typing import List, Optional

# ORGANIC #574 — the official testbenches carry `$dumpfile("wave.vcd")`; running
# vvp with cwd=None inherits the caller's cwd (e.g. the plugin tree under pytest),
# leaking a stray wave.vcd that the waveform-hygiene gate then flags. When we are
# NOT pinning cwd to the design dir (no relative $readmemh), run vvp in a process
# scratch dir instead of None, so every waveform dump lands in throwaway temp.
_VVP_SCRATCH_CWD = tempfile.mkdtemp(prefix="score_iverilog_vvp_scratch_")
atexit.register(lambda: shutil.rmtree(_VVP_SCRATCH_CWD, ignore_errors=True))

# ORGANIC #707 round-3 — the SCORE-SIDE pure-permutation rescue reuses the
# TB-inference helpers authored for the #707-r2 EXPORT path. They live in
# programs/shape_b_sample_export.py; put the plugin's programs/ dir on sys.path
# so the scorer (in benchmark/) can import them. Lazy + guarded — a missing
# programs/ dir never breaks scoring (the rescue simply becomes a no-op).
_PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"
if _PROGRAMS_DIR.is_dir() and str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))


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
_IV13_CONTAINER = os.environ.get("VIBEIC_IVERILOG13_CONTAINER", "vibeic-eda")
_CONT_DESIGNS_ROOT = os.environ.get("VIBEIC_DESIGNS_CONT_ROOT", "/foss/designs")

# PORTABILITY — the designs-root resolution LADDER.
#
# The "designs root" is whatever host directory is bind-mounted into the EDA
# container; its only job is to let the container see the caller's project
# files. It is a property of the USER's machine, so there is no sane shipped
# default. An earlier release hardcoded one developer's home directory, which
# (a) silently produced container paths wrong on every other machine and (b) got
# `mkdir(parents=True)`-ed into existence, materialising a phantom workspace
# directory on a clean install.
#
# Resolution order — note that steps 1-2 cover essentially every real call, so
# the user is almost never asked anything:
#
#   1. $VIBEIC_DESIGNS_HOST_ROOT — explicit; for power users and CI.
#   2. DERIVED FROM THE CALLER'S PROJECT. Every scoring entry point is already
#      handed a `design_dir`. We ask the container which host directory it has
#      mounted that CONTAINS that project and use it; if docker can't be
#      queried, we use the project directory itself. Zero configuration, zero
#      phantom directory, and what gets used is exactly the tree the user is
#      actually working in.
#   3. Neither available (rare: no project argument AND no env) — we do NOT
#      hard-exit and we do NOT invent a path. We return a STRUCTURED
#      needs-a-human-decision status. These programs are non-interactive and
#      are driven by an AI agent, which IS the interactive layer: the program
#      reports a machine-readable state with the concrete options, and the
#      agent relays the question to the user. Prompting from here would break
#      on a non-TTY; guessing would resurrect the original defect.
_HOST_DESIGNS_ROOT_ENV = "VIBEIC_DESIGNS_HOST_ROOT"
_DESIGNS_ROOT_ERROR_CODE = "DESIGNS_ROOT_UNRESOLVED"
_DESIGNS_ROOT_HELP = (
    "Cannot tell which host directory the EDA container can see. Choose one:\n"
    f"  (a) pass a project directory, so the root is derived from it "
    f"automatically; or\n"
    f"  (b) export {_HOST_DESIGNS_ROOT_ENV}=<an EXISTING directory you have "
    f"bind-mounted into the '{_IV13_CONTAINER}' container as "
    f"{_CONT_DESIGNS_ROOT}>.\n"
    "Nothing is created for you — the plugin never adds directories to your "
    "home directory."
)
_warned_no_designs_root = False


def _designs_root_undecided(detail: str = "") -> dict:
    """The structured 'a human must choose' status (ladder step 3).

    Deliberately a VALUE, not an exception or an exit: the caller is an AI agent
    that can surface the choice to the user.
    """
    return {
        "verdict": "SKIP",
        "error_code": _DESIGNS_ROOT_ERROR_CODE,
        "needs_user_decision": True,
        "reason": (detail + " " if detail else "") + _DESIGNS_ROOT_HELP,
        "options": [
            {"id": "derive_from_project",
             "how": "invoke with a project/design directory"},
            {"id": "explicit_env",
             "how": f"export {_HOST_DESIGNS_ROOT_ENV}=<existing directory>"},
        ],
    }


def _container_mount_sources(container: str) -> "List[Path]":
    """Host-side sources of the container's bind mounts. [] if unknowable."""
    try:
        out = subprocess.check_output(["docker", "inspect", container],
                                      text=True, stderr=subprocess.DEVNULL,
                                      timeout=20)
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return []
    if not data:
        return []
    srcs = []
    for m in (data[0].get("Mounts") or []):
        s = m.get("Source")
        if s:
            try:
                srcs.append(Path(s).resolve())
            except OSError:
                pass
    return srcs


def _host_designs_root(design_dir: "Optional[Path]" = None) -> Optional[Path]:
    """Resolve the host designs root via the ladder above. Never creates it.

    Returns None only when the caller supplied no project AND no env var is set
    — the case the caller must convert into `_designs_root_undecided()`.
    """
    global _warned_no_designs_root
    # ---- 1. explicit env -------------------------------------------------
    raw = os.environ.get(_HOST_DESIGNS_ROOT_ENV)
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            return p.resolve()
        if not _warned_no_designs_root:
            _warned_no_designs_root = True
            print(f"[score_iverilog_tb] ${_HOST_DESIGNS_ROOT_ENV}={raw} is not "
                  f"an existing directory — falling back to deriving the "
                  f"designs root from the project being scored (nothing is "
                  f"created).", file=sys.stderr)
    # ---- 2. derive from the caller's project ----------------------------
    if design_dir is not None:
        try:
            proj = Path(design_dir).resolve()
        except OSError:
            return None
        # Prefer the actual bind mount that CONTAINS the project: staging there
        # keeps host→container translation correct for the whole tree.
        for src in _container_mount_sources(_IV13_CONTAINER):
            if proj == src or src in proj.parents:
                return src
        # No queryable mount table (docker absent / container down): use the
        # project itself. It is the user's own directory, it already exists, and
        # it is the thing the container needs to see anyway.
        if proj.is_dir():
            return proj
    # ---- 3. undecidable --------------------------------------------------
    return None


def _to_container(p: str, design_dir: "Optional[Path]" = None) -> str:
    root = _host_designs_root(design_dir)
    if root is None:
        return p
    return p.replace(str(root), _CONT_DESIGNS_ROOT)


# CALL-scoped, not LINE-scoped (adversarial-verify finding on v1.3.83): the
# line-based predecessor deleted ANY line starting with $dumpfile/$dumpvars —
# including functional code SHARING that line. Reproduced verdict flip: a TB whose
# mismatch-checker forever-loop shared the $dumpvars line ("$dumpvars(0, tb);
# forever @(posedge clk) ... mismatch_count = mismatch_count + 1;") lost its whole
# checker, printed "Mismatches: 0 in 0 samples", and a genuinely-WRONG DUT scored
# PASS through the fork rung. Not exploitable by a candidate (the sample is
# preserved verbatim) and zero such lines exist in the real VerilogEval dataset —
# but the hazard is latent for any future Shape-C TB, so the strip removes ONLY
# the dump call itself.
#
# SYNTAX-ANCHORED (Step-2.7 reproduced INFLATION on the naive [^;]*; form): a bare
# "$dump…[^;]*;" match fires on the token ANYWHERE — a "// … $dumpvars …" comment
# or a `define body with no trailing ';' let [^;] eat ACROSS the newline into the
# next real statement, deleting a TB's sole checker while staying COMPILABLE (a
# wrong DUT then printed "Mismatches: 0" — false PASS, a regression vs the
# line-based form's structural comment immunity). The match is therefore anchored
# to a complete CALL STATEMENT — token, optional (args), then ';' immediately
# (whitespace only) — found on a COMMENT- AND STRING-MASKED copy (offset-
# preserving blanks) and spliced out of the RAW text:
#   * a $dump token inside a comment / string literal never matches (masked);
#   * a `define body with no ';' never matches (no immediate ';') — the macro
#     survives verbatim; if its expansion later trips the fork's forward-ref
#     quirk the build fails -> compile_error (deflation-only, never inflation);
#   * a ';' inside a $dumpfile string arg is masked, so the call is removed
#     WHOLE (upgrades the previously-disclosed dangling-fragment deflation);
#   * [^()] spans newlines, so a legit multi-line call is still removed whole.
_DUMP_CALL_RE = re.compile(r"\$dump(?:file|vars)\b\s*(?:\([^()]*\))?\s*;")
_DUMP_MASK_RE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def _strip_waveform_dumps(text: str) -> str:
    """Remove $dumpfile(...) / $dumpvars(...) CALLS — waveform-only output that
    never affects the Mismatches verdict. Some forked iverilog builds reject a
    $dumpvars that forward-references a module-scope wire declared textually
    later (a stricter elaboration order); stripping it lets the fork build run the
    TB WITHOUT changing what is verified. Only a complete call STATEMENT is
    removed (matched on a comment/string-masked copy — see _DUMP_CALL_RE), and
    it is replaced by an EMPTY STATEMENT `;` (not deleted outright) so a
    statement-prefix construct keeps its own statement: `if (dbg)
    $dumpvars(...); else err=err+1;` stays legal with unchanged semantics, and
    an event-control prefix `@(posedge clk) $dumpvars(...);` cannot silently
    ATTACH to the following statement. §4.05: a wrong DUT still mismatches."""
    masked = _DUMP_MASK_RE.sub(lambda m: " " * len(m.group(0)), text)
    out, last = [], 0
    for m in _DUMP_CALL_RE.finditer(masked):
        out.append(text[last:m.start()])
        out.append(";")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


_FORK_IV_COUNTER = [0]

# ─── ORGANIC #643 — the timeout has to reach the SIMULATION, not the client ───
#
# Every scored simulation below is bounded the ordinary way:
#
#     subprocess.run(["vvp", binp], timeout=N)
#
# which kills its DIRECT CHILD. When `vvp` on PATH is a host binary that child IS
# the simulation and the bound is exactly right. When it is a shim —
#
#     #!/usr/bin/env bash
#     exec docker exec -w "$PWD" <container> /foss/tools/bin/vvp "$@"
#
# — the direct child is the docker CLIENT, and `docker exec` has no
# kill-on-disconnect. The client dies; the simulation inside the container runs
# to completion or forever. MEASURED on `.114`, ~4 h after the RTLLM run that
# started them had already written its RESULT: four `vvp` at 99.9 % CPU,
# ELAPSED 03:5x, parented by `containerd-shim`, their `TemporaryDirectory()`
# roots long since removed from the host.
#
# The waste is the smaller half. `sim_timeout` is a SCORED verdict, so a leak
# feeds itself: a hung TB steals a core, the next design is scored on a smaller
# machine, a design near the bound now exceeds it and is scored `sim_timeout`,
# which leaks another core. By the end of a sweep the designs scored last were
# measured under conditions the ones scored first never saw, the verdict depends
# on ordering, and a re-score is not idempotent — it starts with the previous
# run's leaks still burning.
#
# WHY NOTHING CAUGHT IT: `programs/container_exec_deadline_check.py` exists for
# precisely this defect, and its population is "an argv literal that STARTS a
# `docker exec`". These call sites say `vvp`. The containerization is in PATH,
# not in the argv, so the gate could not see them — the fix belongs at the call,
# where the routing is discoverable at run time.
#
# So: ask what `vvp` on PATH actually IS, and put the bound where the work is.

# Cache: "unresolved" | None (a real binary) | (container, remote_vvp_path).
_VVP_ROUTE = ["unresolved"]
# `docker exec` flags that CONSUME the next token — needed to find the container
# name, which is the first token that is neither a flag nor a flag's value.
_DOCKER_EXEC_VALUE_FLAGS = {"-w", "--workdir", "-u", "--user", "-e", "--env",
                            "--env-file", "--detach-keys"}


def _resolve_vvp_route(which=None):
    """(container, remote_vvp) when `vvp` on PATH routes into a container, else
    None. Reads the resolved file rather than assuming any particular harness —
    the shim is written by the benchmark host, not by this repo, so the only
    honest way to know is to look at the one actually on PATH."""
    if _VVP_ROUTE[0] != "unresolved":
        return _VVP_ROUTE[0]
    _VVP_ROUTE[0] = _vvp_route_of(which or shutil.which("vvp"))
    return _VVP_ROUTE[0]


def _vvp_route_of(path):
    """The pure half of `_resolve_vvp_route`, so it is testable without PATH."""
    if not path:
        return None
    try:
        head = Path(path).read_bytes()[:8192].decode("utf-8", "replace")
    except OSError:
        return None
    if not head.startswith("#!"):          # a real ELF binary — the bound is fine
        return None
    m = re.search(r"\bdocker\s+exec\b(.*)$", head, re.M)
    if not m:
        return None
    try:
        toks = shlex.split(m.group(1), comments=True)
    except ValueError:
        return None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _DOCKER_EXEC_VALUE_FLAGS:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        container = t
        remote = toks[i + 1] if i + 1 < len(toks) else "vvp"
        if remote.startswith("-") or remote.startswith("$"):
            remote = "vvp"
        return (container, remote)
    return None


_CONTAINER_HAS_TIMEOUT = {}


def _container_has_timeout(container: str) -> bool:
    """Whether GNU `timeout` exists in the container. Probed once per container;
    a container without it still runs, just unbounded — the same behaviour as
    before this fix, never worse."""
    if container not in _CONTAINER_HAS_TIMEOUT:
        try:
            ok = subprocess.run(["docker", "exec", container,
                                 "timeout", "--version"],
                                capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _CONTAINER_HAS_TIMEOUT[container] = ok
    return _CONTAINER_HAS_TIMEOUT[container]


def _bounded_vvp(binp, *, timeout, cwd, route=None):
    """`vvp binp`, bounded where the SIMULATION lives.

    Raises `subprocess.TimeoutExpired` on either route, so every call site's
    existing `except subprocess.TimeoutExpired` keeps its meaning unchanged —
    the container rung reports its deadline through rc 124/137 (GNU `timeout`,
    137 when it had to escalate to KILL), translated back here.

    `timeout --kill-after=5` puts the simulation in its own process group and
    signals the GROUP, so a tool that spawns children is torn down whole; it
    fires 5 s BEFORE the host bound, so the container side is already dead when
    the host would have given up. Same shape `_docker_watchdog.
    wrap_with_container_timeout` uses for every other supervised tool.

    NO SHELL, deliberately — not even the `bash -lc` that wrapper needs. The
    container's login profile PRINTS (`[INFO] Final PATH variable: …`), and this
    call's stdout is the exact text `pass_regex`/`fail_regex` are matched
    against; a banner in there is a scoring hazard, not a cosmetic one. The
    remote path comes out of the shim already absolute, so no profile is needed
    to resolve it — and running the tool directly is also what the shim itself
    does."""
    route = _resolve_vvp_route() if route is None else route
    if route is None:
        return subprocess.run(["vvp", str(binp)], capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
    container, remote = route
    argv = ["docker", "exec", "-w", str(cwd), container]
    if _container_has_timeout(container):
        argv += ["timeout", "--kill-after=5", str(max(1, int(timeout) - 5))]
    argv += [remote, str(binp)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode in (124, 137):
        raise subprocess.TimeoutExpired(cmd=["vvp", str(binp)], timeout=timeout)
    return r


# Fork-rung vvp wall-clock cap (seconds). Module-level so tests can shrink it.
_FORK_VVP_TIMEOUT = 120
# Sentinel returned when the fork BUILD succeeded but the simulation hit the
# wall-clock cap. MUST stay distinct from any vvp output: a SIGTERM'd vvp still
# executes `final` blocks, and a hung VerilogEval TB then prints
# "Mismatches: 0 in 0 samples" — which MATCHES the pass regex. Returning the
# raw output would convert a hang into a false PASS (Step-2.7 reproduced
# finding), so the call site must see the timeout, not the output.
FORK_SIM_TIMEOUT = "__FORK_SIM_TIMEOUT__"


def _fork_iverilog_compile_run(sources, top: str, preserve=()):
    """SV-2012 escalation rung ABOVE host iverilog: compile+run under the FORKED
    iverilog (Icarus 14-devel) in the EDA container ($VIBEIC_IVERILOG13_CONTAINER,
    default vibeic-eda). The fork build handles SV enum type-casts (States'(...))
    that stock host iverilog 11 rejects with "sorry: This cast operation is not
    yet supported" — a genuine tool-substitution gap (VCS/Xcelium handle it), NOT a
    candidate-RTL bug. Non-functional $dumpfile/$dumpvars are stripped (see
    _strip_waveform_dumps) from the benchmark's OWN files (TB / golden ref) only —
    any path listed in `preserve` (the CANDIDATE sample) is copied VERBATIM, so a
    candidate whose own dump line is illegal still fails its deserved
    compile_error (Step-2.7 reproduced finding: stripping the candidate would
    repair a non-compiling submission into a PASS). Returns the vvp output string
    on a successful BUILD, FORK_SIM_TIMEOUT if the build succeeded but the
    simulation hit the wall-clock cap (a SIGTERM'd TB's `final` block can print a
    pass-shaped summary — never expose it), or None if even the fork build fails
    (a genuine tool-gap / real error stays a compile_error at the call site).
    §4.05 no-leak: the real forked simulator runs, so a wrong DUT still reports
    Mismatches>0 — the verdict is never inflated (proven: an all-zero stub on
    VerilogEval Prob151 reports Mismatches 4152/5069 through this exact path)."""
    container = _IV13_CONTAINER
    _FORK_IV_COUNTER[0] += 1
    tagdir = f"/tmp/vibeic_forkiv_{os.getpid()}_{_FORK_IV_COUNTER[0]}"
    preserve = {str(Path(p)) for p in preserve}
    host_tmps = []
    try:
        # opportunistic sweep of stale sibling dirs (a SIGKILLed scorer never
        # reaches its finally) before creating this invocation's dir
        if subprocess.run(["docker", "exec", container, "bash", "-lc",
                           f"find /tmp -maxdepth 1 -name 'vibeic_forkiv_*' "
                           f"-mmin +240 -exec rm -rf {{}} + 2>/dev/null; "
                           f"rm -rf {tagdir} && mkdir -p {tagdir}"],
                          capture_output=True, timeout=60).returncode != 0:
            return None
        cont_srcs = []
        for i, s in enumerate(sources):
            txt = Path(s).read_text(errors="ignore")
            if str(Path(s)) not in preserve:
                txt = _strip_waveform_dumps(txt)
            tf = tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False)
            tf.write(txt); tf.close(); host_tmps.append(tf.name)
            base = f"src{i}.sv"
            if subprocess.run(["docker", "cp", tf.name, f"{container}:{tagdir}/{base}"],
                              capture_output=True, timeout=60).returncode != 0:
                return None
            cont_srcs.append(f"{tagdir}/{base}")
        srcs = " ".join(f"'{x}'" for x in cont_srcs)
        build = (f"cd {tagdir} && (iverilog -g2012 -s {top} -o bin {srcs} 2>err "
                 f"|| iverilog -g2012 -o bin {srcs} 2>err) && echo __FBUILT__ "
                 f"&& {{ timeout {int(_FORK_VVP_TIMEOUT)} vvp bin 2>&1; "
                 f"echo __FORKRC=$?; }}")
        r = subprocess.run(["docker", "exec", container, "bash", "-lc", build],
                           capture_output=True, text=True,
                           timeout=int(_FORK_VVP_TIMEOUT) + 180)
        out = r.stdout + r.stderr
        if "__FBUILT__" not in out:
            return None
        out = out.split("__FBUILT__", 1)[1]
        rc = re.search(r"__FORKRC=(\d+)", out)
        if rc and rc.group(1) == "124":     # GNU timeout: the sim hit the cap
            return FORK_SIM_TIMEOUT
        return out
    except Exception:
        return None
    finally:
        for t in host_tmps:
            try:
                os.unlink(t)
            except OSError:
                pass
        try:
            # cleanup must never raise past the verdict (a docker-less host would
            # otherwise crash the WHOLE scoring run with FileNotFoundError here —
            # Step-2.7 reproduced finding)
            subprocess.run(["docker", "exec", container, "bash", "-lc",
                            f"rm -rf {tagdir}"],
                           capture_output=True, timeout=30)
        except Exception:
            pass


def _iverilog_toolgap_signature(text: str) -> bool:
    """True when a host-iverilog compile failure looks like an SV-2012 tool-gap the
    forked iverilog 14 may handle (enum cast / stricter elaboration), NOT a plain
    RTL syntax error. Keeps the fork escalation from masking a real candidate bug."""
    low = text.lower()
    return ("sorry:" in low or "internal error" in low
            or "unable to bind" in low
            or "i don't know how to elaborate" in low)


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
    # Ladder step 2: derive the root from the project we were handed.
    root = _host_designs_root(design_dir)
    if root is None:
        # Undecidable (no project, no env). Report "not built" (inconclusive)
        # rather than mkdir-ing an invented path; the dict-returning caller
        # below surfaces the structured needs-a-decision status.
        global _warned_no_designs_root
        if not _warned_no_designs_root:
            _warned_no_designs_root = True
            print(f"[score_iverilog_tb] {_DESIGNS_ROOT_HELP}", file=sys.stderr)
        return (False, False)
    stage_dir = root / ".vibeic_scorer_tmp"
    stage_dir.mkdir(parents=True, exist_ok=True)
    p = stage_dir / f"{re.sub(r'[^A-Za-z0-9_]', '_', design.split('/')[-1])}_{tag}.v"
    try:
        p.write_text(text)
        cs = _to_container(str(p.resolve()), design_dir)
        cd = _to_container(str(Path(design_dir).resolve()), design_dir)
        ctb = _to_container(str(Path(tb).resolve()), design_dir)
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
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", binp, str(sp), str(tb)],
                               capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            # #1437 — an ABSENT iverilog raised before returning, so this probe
            # crashed the scorer instead of reaching the "inconclusive" outcome
            # its own contract declares. No compiler ran, so nothing was learned
            # about whether the TB discriminates: None, and the design stays
            # counted (never silently excluded from the denominator).
            return None
        clow = (c.stdout + c.stderr).lower()
        if "sorry:" in clow or "internal error" in clow or "i don't know how to elaborate" in clow:
            built, stub_pass = _verilator_run_text(
                stub, design_dir.name, tb, design_dir, pass_re, "zstub")
            return bool(stub_pass) if built else None
        if c.returncode != 0 or not os.path.exists(binp):
            return None
        try:
            r = _bounded_vvp(binp, timeout=30, cwd=str(design_dir))
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
    # Ladder step 2: derive the root from the project we were handed.
    root = _host_designs_root(design_dir)
    if root is None:
        # Ladder step 3 — hand the caller a STRUCTURED decision request rather
        # than exiting or inventing (and creating) a workspace directory.
        return _designs_root_undecided(
            "cannot resolve a designs root for this run.")
    try:
        # The power-up-fixed sample lives in a host /tmp dir the container can't
        # see (only the designs root is bind-mounted). Stage it UNDER the designs
        # root so _to_container maps it to a path Verilator-in-container can read.
        sample_c = Path(sample_c)
        if str(root) not in str(sample_c.resolve()):
            stage_dir = root / ".vibeic_scorer_tmp"
            stage_dir.mkdir(parents=True, exist_ok=True)
            staged = stage_dir / f"{re.sub(r'[^A-Za-z0-9_]', '_', design.split('/')[-1])}.v"
            shutil.copyfile(sample_c, staged)
            sample_c = staged
        # Resolve to ABSOLUTE host paths first — the dataset/run args are often
        # relative (e.g. _extbench/RTLLM/...), and _to_container only rewrites the
        # absolute designs-root prefix. A relative `cd` would fail inside the
        # container (different default cwd) → spurious build failure → false SKIP.
        cd = _to_container(str(Path(design_dir).resolve()), design_dir)
        cs = _to_container(str(Path(sample_c).resolve()), design_dir)
        ctb = _to_container(str(Path(tb).resolve()), design_dir)
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


def _aliased_golden_srcs(design: str, dataset: Path, layout: dict,
                         refs: "List[Path]", tmpdir: str):
    """ORGANIC #709 — shared golden-module-name canonicalization for BOTH the
    #690 COMPILE audit and the #679 RUNTIME audit (so they can never drift again).

    The Shape-B `verified_*.v` convention names the golden module `verified_<X>`
    while the hidden TB instantiates the canonical DUT name `<X>` (the spec's
    `Module name:`). A VERBATIM compile of such a golden + TB ALWAYS fails
    elaboration (`Unknown module type: <X>`), so the audit must first ALIAS the
    golden's top-module name to the canonical DUT name the TB binds.

    Returns (srcs, golden_ports):
      srcs        — [aliased_first_ref] + [str(p) for p in refs[1:]] (the FIRST
                    ref's top module renamed to the canonical DUT name, written
                    into `tmpdir`; remaining refs verbatim for multi-file goldens).
      golden_ports— the golden header's declared port set.
    Returns (None, set()) when the canonical name or the golden's module name
    cannot be resolved (→ no determination; the caller returns its undetermined
    sentinel). chip-AGNOSTIC: registry layout + the spec's own Module-name line."""
    dut_name = _canonical_dut_name_shape_b(design, dataset, layout)
    if not dut_name:
        return (None, set())
    golden_text = refs[0].read_text(errors="ignore")
    mm = re.search(r"\bmodule\s+(\w+)", golden_text)
    if not mm:
        return (None, set())
    golden_mod = mm.group(1)
    golden_ports = _module_declared_ports(golden_text)
    aliased = (golden_text if golden_mod == dut_name
               else re.sub(rf"\b{re.escape(golden_mod)}\b", dut_name, golden_text))
    alias_f = os.path.join(tmpdir, "golden_alias.v")
    with open(alias_f, "w") as fh:
        fh.write(aliased)
    srcs = [alias_f] + [str(p) for p in refs[1:]]
    return (srcs, golden_ports)


def _golden_ref_fails_own_tb_runtime(design: str, dataset: Path,
                                     layout: dict, args: dict):
    """Shape-B RUNTIME golden-fails-own-TB audit (#679). Mirror of the Shape-C
    `golden_ref_fails_own_tb` dataset-defect flag, but at the FUNCTIONAL level:
    the Shape-C audit is COMPILE-only (does ref+TB elaborate?), whereas a
    standalone Shape-B benchmark can have a golden that compiles cleanly yet
    FAILs its own official TB at RUNTIME — a desc<->TB contradiction or a
    handshake race (e.g. a TB holding res_ready tied high for the whole run, or
    a clock-generator whose golden never prints the pass marker). Such a golden may
    OR MAY NOT indicate an unsatisfiable TB — a wrong reference implementation fails
    its own TB exactly as an unsatisfiable TB would. So a model FAIL here is DISCLOSED
    as a SUSPECTED defective golden (non-excluding), never auto-charged as an
    irreducible dataset defect. (Runtime is unsound for irreducibility; only the
    COMPILE-level audit — a TB port neither golden nor spec provides — is sound.)

    Resolves the golden via `layout.ref_glob` (e.g. `verified_*.v`) in the design
    dir, iverilog -g2012 compiles it with `layout.tb_filename`, runs vvp with
    cwd=design_dir (the same cwd_design_dir rule the main scorer obeys — see
    benchmark_score_cwd_guard.py), and checks the golden's own stdout against
    `pass_regex`/`fail_regex`.

    Returns:
      True  — golden COMPILES but FAILs its own TB at runtime (no pass marker, or
              a fail_regex match) → the shipped GOLDEN is buggy. This is DISCLOSURE-
              ONLY (suspected), NOT proof of irreducibility: a runtime functional
              mismatch cannot distinguish "TB unsatisfiable by anyone" from "the
              reference is a wrong implementation while a correct submission passes"
              (measured: radix2_div — golden fails 3/8 of its own TB, yet a correct
              signed/unsigned divider passes all 8). The caller therefore routes this
              to the non-excluding `dataset_defect_suspected` channel; it must NEVER
              be auto-excluded from the denominator.
      False — golden PASSes its own TB at runtime → the design IS satisfiable;
              a candidate FAIL stays a real model FAIL (no flag).
      None  — no determination (no ref_glob, no glob match, no TB, golden fails to
              COMPILE — which is the existing compile-audit's job, not double-
              counted here, or a timeout / tool error). No flag.

    Deterministic + chip-AGNOSTIC: driven entirely by registry
    layout.ref_glob/tb_filename + scorer_args regex; NO design/vendor literal.
    Honesty: touches the hidden golden/TB at SCORING time only (same as the main
    scorer), never during blind authoring.
    """
    ref_glob = layout.get("ref_glob")
    tb_name = layout.get("tb_filename")
    if not ref_glob or not tb_name:
        return None
    design_dir = dataset / design
    tb = design_dir / tb_name
    if not tb.is_file():
        return None
    refs = sorted(design_dir.glob(ref_glob))
    if not refs:
        return None
    pass_re = re.compile(args["pass_regex"])
    fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
    use_cwd = args.get("cwd_design_dir", True)
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "golden_bin")
        # ORGANIC #709 — alias the golden's top-module name to the canonical DUT
        # name the TB instantiates (the #690 compile audit already did this; the
        # #679 runtime audit did NOT, so for the `verified_*.v` convention the
        # verbatim compile ALWAYS failed `Unknown module type` and this helper
        # returned None — silently charging an irreducible dataset defect to the
        # model). Shared with #690 via `_aliased_golden_srcs` so they can't drift.
        aliased_srcs, _golden_ports = _aliased_golden_srcs(
            design, dataset, layout, refs, td)
        if aliased_srcs is None:
            # Could not resolve the canonical DUT name / golden module name → no
            # determination (don't flip a model FAIL on an unattributable case).
            return None
        srcs = aliased_srcs + [str(tb)]
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", binp] + srcs,
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return None
        if c.returncode != 0 or not os.path.exists(binp):
            # Golden fails to COMPILE — that is the existing compile-audit's
            # domain (a candidate compile_error is already its own FAIL reason),
            # not a runtime defect. Don't double-count; leave it to the main path.
            return None
        try:
            r = _bounded_vvp(binp, timeout=120, cwd=str(design_dir) if use_cwd else _VVP_SCRATCH_CWD)
        except subprocess.TimeoutExpired:
            # Golden's own TB hangs — treat as no determination (could be a TB
            # that waits forever); don't flip a model FAIL into a defect on a
            # timeout we can't attribute.
            return None
        out = r.stdout + r.stderr
        golden_passes = bool(pass_re.search(out)) and not (
            fail_re and fail_re.search(out))
        return (not golden_passes)


def _canonical_dut_name_shape_b(design: str, dataset: Path, layout: dict):
    """Resolve the canonical DUT module name a Shape-B candidate is authored under
    (the same name the TB instantiates). For the RTLLM convention this is the spec's
    `Module name:` line; fall back to the design dir leaf. Returns a name or None.
    Chip-AGNOSTIC: registry-driven prompt_filename + the spec's own Module-name line."""
    spec = dataset / design / layout.get("prompt_filename", "design_description.txt")
    if spec.is_file():
        m = re.search(r"Module\s*name:\s*\n?\s*([A-Za-z_]\w*)",
                      spec.read_text(errors="ignore"))
        if m:
            return m.group(1)
    leaf = design.split("/")[-1]
    return leaf or None


def _spec_declares_port(design: str, dataset: Path, layout: dict, port: str) -> bool:
    """True iff the prose design description names `port` as a whole word ANYWHERE.
    This is the §4.05 no-leak guard for the unsatisfiable-TB audit: a port the spec
    mentions at all is NOT spec-absent (a candidate that omits it is the candidate's
    own bug → stays a model FAIL). Whole-word match avoids overfitting to a specific
    'Input ports:' prose layout and never flags a port the spec genuinely declares.
    Chip-AGNOSTIC: pure text search on the registry's prompt_filename."""
    spec = dataset / design / layout.get("prompt_filename", "design_description.txt")
    if not spec.is_file():
        # No spec to consult ⇒ cannot prove the port is spec-absent ⇒ treat as
        # DECLARED (fail-safe: never flag a defect we cannot substantiate).
        return True
    txt = spec.read_text(errors="ignore")
    return bool(re.search(r"\b" + re.escape(port) + r"\b", txt))


def _module_declared_ports(verilog_text: str) -> set:
    """Best-effort set of port identifiers declared in the FIRST module header of
    `verilog_text` (ANSI-style `input/output/inout [wire|reg|logic] [width] name`).
    Used to confirm a TB-demanded missing port is one the GOLDEN declares."""
    m = re.search(r"\bmodule\s+\w+\s*\((.*?)\)\s*;", verilog_text, re.S)
    if not m:
        return set()
    hdr = m.group(1)
    return set(re.findall(
        r"\b(?:input|output|inout)\b(?:\s+(?:wire|reg|logic))?"
        r"(?:\s+signed)?(?:\s*\[[^\]]*\])?\s+([A-Za-z_]\w*)", hdr))


def _golden_ref_compiles_with_tb_shape_b(design: str, dataset: Path, layout: dict):
    """Compile the Shape-B golden reference + the hidden TB ALONE (no candidate),
    aliasing the golden's module to the canonical DUT name so the TB's
    `<canonical> uut(...)` instantiation binds to it. COMPILE-level mirror of
    `_golden_ref_fails_own_tb_runtime` (which is RUNTIME-level).

    Returns (compiles: bool|None, golden_ports: set).
      compiles True  — golden(aliased)+TB elaborates: the TB IS satisfiable by some
                       design (the golden). A candidate compile_error here is the
                       candidate's own problem UNLESS it is a spec-absent golden port
                       (case (b), checked by the caller).
      compiles False — golden(aliased)+TB ALSO fails to elaborate: the TB is
                       unsatisfiable by ANY submission (case (a)).
      compiles None  — no determination (no ref_glob/glob-match/TB, no canonical
                       name, or a tool error) ⇒ no flag.
    `golden_ports` is the golden header's declared port set (empty when undetermined).

    Deterministic + chip-AGNOSTIC: registry layout.ref_glob/tb_filename + the spec's
    own Module-name line; NO design/vendor literal. Honesty: touches the hidden
    golden/TB at SCORING time only, never during blind authoring."""
    ref_glob = layout.get("ref_glob")
    tb_name = layout.get("tb_filename")
    if not ref_glob or not tb_name:
        return (None, set())
    design_dir = dataset / design
    tb = design_dir / tb_name
    if not tb.is_file():
        return (None, set())
    refs = sorted(design_dir.glob(ref_glob))
    if not refs:
        return (None, set())
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "golden_alias_bin")
        # ORGANIC #709 — shared golden-name canonicalization (the FIRST ref's top
        # module renamed to the canonical DUT name; remaining refs verbatim).
        aliased_srcs, golden_ports = _aliased_golden_srcs(
            design, dataset, layout, refs, td)
        if aliased_srcs is None:
            return (None, golden_ports)
        srcs = aliased_srcs + [str(tb)]
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", binp] + srcs,
                               capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            return (None, golden_ports)
        return (c.returncode == 0 and os.path.exists(binp), golden_ports)


def _unsatisfiable_tb_compile_audit_shape_b(design: str, dataset: Path,
                                            layout: dict, candidate_log: str):
    """Shape-B COMPILE-level unsatisfiable-TB audit (#690). Runs PRECISELY on the
    `reason=='compile_error'` path the RUNTIME audit (#679) excludes. Tells an
    irreducible dataset defect (a TB no spec-faithful submission can satisfy) from a
    genuine model compile error.

    Returns (defect: bool, reason: str|None):
      (a) golden(aliased)+TB ALSO fails to elaborate  → (True,
          'golden_ref_fails_own_tb_compile') — TB unsatisfiable by ANY design.
      (b) golden+TB compiles AND the candidate's compile error is
          `port 'P' is not a port of uut` where P is a port the GOLDEN declares yet
          the prose spec NEVER names → (True, 'tb_requires_spec_absent_port') — the
          TB demands a handshake/port no spec-faithful design could provide.
      otherwise → (False, None): the candidate's own compile bug (a syntax error, or
          a missing port the SPEC declares) stays a model FAIL — §4.05 no-leak.

    Deterministic + chip-AGNOSTIC: registry layout + iverilog exit code + the
    candidate's own elaboration error text; NO design-id branching."""
    compiles, golden_ports = _golden_ref_compiles_with_tb_shape_b(
        design, dataset, layout)
    if compiles is None:
        return (False, None)
    if compiles is False:
        # (a) Even the golden cannot elaborate against its own TB.
        return (True, "golden_ref_fails_own_tb_compile")
    # (b) golden+TB compiles — only a SPEC-ABSENT, GOLDEN-DECLARED missing port is a
    # defect. Extract the offending port from the candidate's own elaboration error.
    m = re.search(r"port\s+[`'\"]*([A-Za-z_]\w*)[`'\"]*\s+is not a port of",
                  candidate_log or "", re.I)
    if not m:
        return (False, None)            # not a missing-port error ⇒ candidate's bug
    port = m.group(1)
    # Must be a port the GOLDEN declares (the TB binds it onto a golden-satisfiable
    # instance) AND one the spec NEVER names (no spec-faithful design could add it).
    if port not in golden_ports:
        return (False, None)
    if _spec_declares_port(design, dataset, layout, port):
        return (False, None)            # spec DOES name it ⇒ candidate's omission
    return (True, "tb_requires_spec_absent_port")


# ── ORGANIC #707 round-3 — SCORE-SIDE pure-permutation port rescue ───────────
# WHY THIS IS HERE AND NOT IN THE EXPORTER (the #707 r2 reopen)
# ------------------------------------------------------------
# #707's positional-TB port reorder originally lived in the EXPORT step
# (`programs/shape_b_sample_export.py`). r2 made the exporter INFER the bind
# order from the hidden `testbench.v` — but that inference is on the WRONG side
# of the blindness boundary: at blind AUTHORING time the TB is FORBIDDEN, and the
# canonical `benchmark/benchmark_dispatch.py` step-3b export invocation passes NO
# `--testbench`/`--dataset`, so the inference path NEVER fires in the real flow →
# the exporter ships the candidate VERBATIM. The Shape-B (RTLLM-style) corpus
# binds positionally PER-DESIGN (an `alu` TB is inputs-first, an `LFSR` TB is
# outputs-first), so NO authoring-side policy can satisfy both. The ONLY
# disambiguator is the hidden corpus — which the SCORER may legitimately touch
# (it already touches the TB/golden via `_power_up_fixed`, `_aliased_golden_srcs`,
# `_golden_ref_compiles_with_tb_shape_b`, `_unsatisfiable_tb_compile_audit_*`).
#
# So the reorder moves SCORE-SIDE: on a Shape-B `reason=='compile_error'`, attempt
# a PURE PERMUTATION of the candidate's port-declaration list, recompile, and adopt
# the result ONLY if it now PASSES.
#
# ── round-3 HARDENING (adversarial Lens-1 leak fix) ──────────────────────────
# THE LEAK an earlier round-3 draft had: the target order was inferred FROM THE TB
# by direction+width with name-affinity as the ONLY tie-break. For a non-commutative
# op with two SAME-WIDTH SAME-DIRECTION operands (e.g. `gt = a > b`), a TB whose
# driver-net names (`a_tb`/`b_tb`) carry affinity that CONTRADICTS the positional
# ground truth let a wrong-operand candidate (`gt = b > a`) be bound so the TB
# pass-marker fired → a wrong submission rescued to PASS. The affinity guess never
# validated against how the GOLDEN is positionally wired and trusted the pass-marker.
#
# THE FIX — derive the target order from the GOLDEN's DECLARATION order, matched by
# port NAME (no TB-net-affinity, no width-guessing for ordering):
#   The golden `verified_<X>.v` compiles AND passes the TB POSITIONALLY, so the
#   golden's port-DECLARATION order IS the correct positional bind order (ground
#   truth). A spec-faithful candidate shares the spec's port NAMES with the golden.
#   Therefore re-emit the candidate with its port segments reordered to the GOLDEN's
#   port-NAME order — a pure permutation BY NAME. The wrong-operand `gt = b > a`
#   candidate, whatever its declared order, permutes to the golden name-order
#   (a,b,gt) and its WRONG LOGIC still RUNTIME-FAILs → NOT rescued. No width/affinity
#   guessing remains, so a same-width operand swap can never be silently bound.
#
# A pure permutation can NEVER rescue a logically-incorrect submission (§4.05):
#   * candidate port-NAME set ≠ golden port-NAME set → REFUSE (not a permutation).
#   * wrong-logic-but-correct-order → byte-identical no-op (or permute RUNTIME-fails)
#     → stays the original FAIL.
#   * golden+TB does NOT elaborate (dataset defect) → permutation NOT attempted.
#   * a named-binding TB (`.clk(clk_tb)`, no positional list) → no rescue.
#
# chip-AGNOSTIC: structural Verilog grammar + registry layout only — it reuses the
# exporter's port parser + `_apply_order`, the scorer's own golden-aliasing infra,
# and `_tb_positional_args` ONLY to confirm the TB binds positionally at all.

def _shape_b_export_helpers():
    """Lazy import of the #707-r2 port helpers from the exporter program.
    Returns the module, or None when programs/shape_b_sample_export.py is
    unavailable (the rescue then becomes a no-op — never a hard error)."""
    try:
        import shape_b_sample_export as _S  # noqa: WPS433 (intentional lazy)
        return _S
    except Exception:
        return None


def _module_header_port_name_order(verilog_text: str, top: str) -> Optional[list]:
    """ORGANIC #707 round-4 — return module `top`'s positional port-NAME order
    from its module HEADER, well-defined for BOTH ANSI and NON-ANSI (Verilog-2001
    bare-name) headers:
      * non-ANSI: `module LFSR (out, clk, rst);` → ['out','clk','rst']
      * ANSI:     `module add (input [3:0] a, output [4:0] s);` → ['a','s']
    Splits the header paren body on TOP-LEVEL commas (so a `[msb:lsb]` width or a
    `#(...)`-style default never splits a port) and takes each entry's TRAILING
    identifier — which is the port NAME in both styles. Returns None when the
    module/header cannot be located or any entry has no identifier (don't guess).
    chip-AGNOSTIC: pure Verilog header grammar, no chip/vendor literal."""
    import re as _re
    txt = _strip_comments_v(verilog_text)
    m = _re.search(r"\bmodule\s+" + _re.escape(top) + r"\b", txt)
    if not m:
        return None
    i, n = m.end(), len(txt)
    # Skip an optional `#( ... )` parameter block, then require the port `(`.
    while i < n and txt[i].isspace():
        i += 1
    if i < n and txt[i] == "#":
        i += 1
        while i < n and txt[i].isspace():
            i += 1
        if i >= n or txt[i] != "(":
            return None
        depth = 0
        while i < n:
            if txt[i] == "(":
                depth += 1
            elif txt[i] == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        while i < n and txt[i].isspace():
            i += 1
    if i >= n or txt[i] != "(":
        return None
    depth = 0
    j = i
    while j < n:
        if txt[j] == "(":
            depth += 1
        elif txt[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if j >= n:
        return None
    body = txt[i + 1:j]
    # Split on TOP-LEVEL commas (ignore commas inside [], (), {}).
    parts, buf, d = [], [], 0
    for ch in body:
        if ch in "([{":
            d += 1; buf.append(ch)
        elif ch in ")]}":
            d = max(0, d - 1); buf.append(ch)
        elif ch == "," and d == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    names = []
    for p in parts:
        ids = _re.findall(r"[A-Za-z_]\w*", p)
        if not ids:
            return None  # an empty / malformed entry → don't guess.
        names.append(ids[-1])  # trailing identifier = the port name (both styles)
    return names or None


def _strip_comments_v(text: str) -> str:
    import re as _re
    text = _re.sub(r"/\*.*?\*/", "", text, flags=_re.DOTALL)
    text = _re.sub(r"//[^\n]*", "", text)
    return text


def _golden_declaration_order_shape_b(design: str, dataset: Path, layout: dict,
                                      top: str, S) -> Optional[list]:
    """Return the GOLDEN's port-DECLARATION order (list of port NAMES) for the
    canonical DUT name `top`, or None when it cannot be resolved unambiguously.

    The golden is the hidden `verified_<X>.v` (registry `ref_glob`); its top
    module is ALIASED to the canonical DUT name `top` the TB binds (reusing the
    scorer's shared `_aliased_golden_srcs`). Because the golden compiles AND
    passes the TB POSITIONALLY (the caller's elaborate-gate already proved this),
    its module-HEADER port-NAME order IS the correct positional bind order — the
    ground truth.

    ORGANIC #707 round-4 — the order is read from the module HEADER's bare-name
    list (`_module_header_port_name_order`), which is well-defined for BOTH ANSI
    AND NON-ANSI (Verilog-2001) goldens. The earlier ANSI-only
    `_parse_portlist_segments` returned None on a non-ANSI golden
    (`module LFSR (out, clk, rst);` + body-declared directions), making the whole
    rescue a NO-OP on real RTLLM goldens (most of which are non-ANSI). The ANSI
    `_parse_portlist_segments` is still used for the CANDIDATE (which is permuted),
    where directional segments are needed; the GOLDEN only supplies the NAME
    order. chip-AGNOSTIC: registry layout + structural Verilog grammar only."""
    ref_glob = layout.get("ref_glob")
    if not ref_glob:
        return None
    refs = sorted((dataset / design).glob(ref_glob))
    if not refs:
        return None
    with tempfile.TemporaryDirectory() as td:
        aliased_srcs, _golden_ports = _aliased_golden_srcs(
            design, dataset, layout, refs, td)
        if not aliased_srcs:
            return None
        try:
            golden_text = Path(aliased_srcs[0]).read_text(errors="replace")
        except OSError:
            return None
    return _module_header_port_name_order(golden_text, top)


def _score_side_port_permutation_rescue_shape_b(
        design: str, sample: Path, dataset: Path, layout: dict,
        args: dict) -> Optional[dict]:
    """ORGANIC #707 round-3 (hardened) — on a Shape-B candidate that COMPILE-ERRORs
    against its hidden TB, try a PURE PERMUTATION of its port-declaration list to
    the GOLDEN's port-DECLARATION order matched by NAME, recompile+run, and return a
    PASS verdict iff the permuted candidate now passes. Returns None on ANY failure
    to rescue (caller then keeps the original compile_error FAIL).

    Algorithm (round-3 HARDENED — golden-decl-order + name-match):
      1. GATE (dataset-defect): the golden(aliased)+TB must ELABORATE. If it does
         NOT (or is undetermined), the TB is a #690 dataset defect, not a candidate
         port-ORDER problem → do not attempt the permutation (return None).
      2. CONFIRM POSITIONAL BIND: the TB must instantiate the DUT POSITIONALLY
         (`_tb_positional_args` returns a list). A NAMED bind (`.clk(clk_tb)`) is
         order-independent → no rescue. This is the ONLY use of the TB text here.
      3. TARGET ORDER FROM THE GOLDEN: parse the GOLDEN's port-declaration order
         (the ground-truth positional order — the golden passes the TB positionally),
         by port NAME. Require the candidate's port-NAME set == the golden's
         port-NAME set (case-sensitive, exact); a mismatch → REFUSE (not a pure-
         permutation case — a candidate that doesn't use the spec's port names).
      4. PURE PERMUTATION BY NAME: re-emit the candidate with its port-declaration
         segments reordered to the golden's port-NAME order (`_apply_order` — never
         adds/drops/renames a port, never alters logic/width). An already-matching
         order is byte-identical, a no-op the caller discards.
      5. RECOMPILE + ADOPT: compile the permuted candidate + TB (cwd=design for
         `$readmemh`), run it, and return PASS iff pass_regex matches and no
         fail_regex. Any compile/runtime failure → None (stays the original FAIL).

    §4.05: no width/affinity guessing remains for choosing the order, so a same-
    width operand swap (`gt=b>a` vs `gt=a>b`) permutes to the golden NAME order and
    its WRONG LOGIC still runtime-FAILs → never rescued (the Lens-1 leak is closed).

    chip-AGNOSTIC: structural grammar + registry layout; no design/vendor literal.
    Honesty: touches the hidden golden/TB at SCORING time only (like the rest of
    this scorer), never during blind authoring."""
    if not shutil.which("iverilog"):
        return None
    S = _shape_b_export_helpers()
    if S is None:
        return None
    tb_name = layout.get("tb_filename")
    if not tb_name:
        return None
    design_dir = dataset / design
    tb = design_dir / tb_name
    if not (sample.is_file() and tb.is_file()):
        return None

    # 1. GATE — the golden(aliased)+TB must ELABORATE. A non-elaborating golden+TB
    #    is an irreducible dataset defect (#690), NOT a candidate port-ORDER bug,
    #    so the permutation must NOT be attempted (it could only mask the defect).
    golden_ok, _golden_ports = _golden_ref_compiles_with_tb_shape_b(
        design, dataset, layout)
    if golden_ok is not True:
        return None  # False (defect) or None (undetermined) → don't permute.

    # The canonical DUT module name the candidate + golden are authored under (the
    # same name the TB instantiates).
    top = _canonical_dut_name_shape_b(design, dataset, layout)
    if not top:
        return None
    cand_text = sample.read_text(errors="replace")
    parsed = S._parse_portlist_segments(cand_text, top)
    if parsed is None:
        return None  # no ANSI port list / a reorder hazard → can't permute.
    block, segs = parsed

    # 2. CONFIRM POSITIONAL BIND — the TB must instantiate the DUT positionally.
    #    A NAMED bind (`.clk(clk_tb)`) is order-independent → no rescue needed. This
    #    is the ONLY use of the TB text for the rescue (NOT for choosing the order).
    tb_text = tb.read_text(errors="replace")
    if S._tb_positional_args(tb_text, top) is None:
        return None  # named bind / no/ambiguous instantiation → no positional fix.

    # 3. TARGET ORDER FROM THE GOLDEN — the golden's port-DECLARATION order is the
    #    ground-truth positional bind order (the golden passes the TB positionally).
    #    Matched by NAME — NO TB-net-affinity / width guessing (closes the Lens-1
    #    leak where a same-width operand swap could be misbound by net-name affinity).
    golden_order = _golden_declaration_order_shape_b(
        design, dataset, layout, top, S)
    if golden_order is None:
        return None  # golden port order unresolved → cannot define a target.
    cand_names = [n for _seg, _d, n in segs]
    if sorted(cand_names) != sorted(golden_order):
        return None  # candidate port-NAME set ≠ golden's → REFUSE (not a permute).

    # 4. PURE PERMUTATION BY NAME — re-emit with the candidate's segments in the
    #    golden's port-NAME order. An already-matching order is byte-identical
    #    (no-op): a wrong-LOGIC candidate whose names/order already match gets NO
    #    change here, so it cannot be rescued.
    permuted = S._apply_order(cand_text, block, segs, golden_order)
    if permuted == cand_text:
        return None  # no-op reorder → nothing to re-evaluate; keep original FAIL.

    # 5. RECOMPILE + ADOPT — compile + run the permuted candidate against the TB.
    pass_re = re.compile(args["pass_regex"])
    fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
    use_cwd = args.get("cwd_design_dir", True)
    with tempfile.TemporaryDirectory() as td:
        permuted_v = os.path.join(td, f"{top}.permuted.v")
        with open(permuted_v, "w") as fh:
            fh.write(permuted)
        # Apply the same canonical power-up determinism fix the main path does, so
        # a sequential candidate that is only X-at-t0 is not spuriously failed.
        permuted_fixed = _power_up_fixed(Path(permuted_v), td)
        binp = os.path.join(td, "permuted_bin")
        try:
            c = subprocess.run(
                ["iverilog", "-g2012", "-o", binp, permuted_fixed, str(tb)],
                capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if c.returncode != 0 or not os.path.exists(binp):
            return None  # the permutation did NOT rescue the compile → keep FAIL.
        try:
            r = _bounded_vvp(binp, timeout=120, cwd=str(design_dir) if use_cwd else _VVP_SCRATCH_CWD)
        except subprocess.TimeoutExpired:
            return None  # permuted candidate hangs → not a rescue → keep FAIL.
    out = r.stdout + r.stderr
    if pass_re.search(out) and not (fail_re and fail_re.search(out)):
        return {"design": design, "verdict": "PASS",
                "reason": "recovered_via_scoreside_port_permutation"}
    return None  # permuted compiles but RUNTIME-fails → wrong logic → keep FAIL.


# ── ORGANIC #742 FACET A — PROACTIVE positional-port normalization ───────────
# WHY THIS IS PROACTIVE (the #742 reopen of the #707 family)
# ---------------------------------------------------------
# #707's score-side permutation rescue (above) is REACTIVE — it fires ONLY after
# the verbatim candidate has already produced a `compile_error` against the hidden
# TB. The motivating #742 designs are functionally correct (golden-self-
# consistent) yet declare ports in the spec's Input-then-Output prose order while
# the hidden TB binds the DUT POSITIONALLY outputs-first
# (`DUT u(out_tb, clk_tb, rst_tb)`) — so the blind first pass ALWAYS compile-errors
# (`rst_tb Unable to assign to unresolved wires`) before the reactive rescue can
# run. The blind first-pass emit/score ignored the hidden-TB binding contract.
#
# THE FIX: BEFORE the first iverilog compile, when the hidden TB instantiates the
# DUT POSITIONALLY (a bare positional port list — no `.name(...)` named
# connections), normalize the emitted module's port ORDER to the positional
# contract the TB expects (the GOLDEN's declaration order, matched by NAME — the
# ground-truth positional bind order). A PURE PERMUTATION of the SAME named ports
# (never invent / drop / rename a port, never change a width/direction/logic). The
# reactive rescue (#707) is kept as the backstop for the cases the proactive
# normalize cannot reach (e.g. a no-ANSI-portlist candidate).
#
# §4.05: identical to #707 — the order is the golden's, matched by name; a same-
# width operand swap (`gt=b>a`) permutes to the golden NAME order and its WRONG
# LOGIC still RUNTIME-FAILs. The normalize NEVER decides PASS/FAIL — it only
# re-orders before the SAME compile+vvp gate runs. chip-AGNOSTIC: structural
# grammar + registry layout; the TB is touched at SCORING time only (like the
# rest of this scorer), never during blind authoring.
def _proactive_positional_port_normalize_shape_b(
        cand_text: str, design: str, dataset: Path, layout: dict) -> str:
    """Return `cand_text` with the candidate's port-DECLARATION list reordered to
    the GOLDEN's positional bind order (matched by NAME) WHEN the hidden TB binds
    the DUT POSITIONALLY. Returns `cand_text` UNCHANGED on ANY of:
      * iverilog / the exporter helpers unavailable,
      * no positional TB (named bind / no instantiation / ambiguous),
      * the golden(aliased)+TB does NOT elaborate (a #690 dataset defect — not a
        port-order problem; the reactive #690 audit must own it),
      * the candidate's port-NAME set != the golden's (not a pure permutation),
      * the candidate has no parseable ANSI port list, or the order already matches.
    A PURE PERMUTATION — never adds/drops/renames a port, never alters logic.
    chip-AGNOSTIC: structural grammar + registry layout only."""
    if not shutil.which("iverilog"):
        return cand_text
    S = _shape_b_export_helpers()
    if S is None:
        return cand_text
    tb_name = layout.get("tb_filename")
    if not tb_name:
        return cand_text
    tb = dataset / design / tb_name
    if not tb.is_file():
        return cand_text
    top = _canonical_dut_name_shape_b(design, dataset, layout)
    if not top:
        return cand_text
    parsed = S._parse_portlist_segments(cand_text, top)
    if parsed is None:
        return cand_text  # no ANSI port list / reorder hazard → leave verbatim.
    block, segs = parsed
    # The TB must bind POSITIONALLY for an order contract to exist at all.
    try:
        tb_text = tb.read_text(errors="replace")
    except OSError:
        return cand_text
    if S._tb_positional_args(tb_text, top) is None:
        return cand_text  # named bind / ambiguous → order is irrelevant.
    # GATE: the golden(aliased)+TB must elaborate (otherwise it is a #690 dataset
    # defect, NOT a port-order problem — leave it to the reactive audit path).
    golden_ok, _golden_ports = _golden_ref_compiles_with_tb_shape_b(
        design, dataset, layout)
    if golden_ok is not True:
        return cand_text
    golden_order = _golden_declaration_order_shape_b(
        design, dataset, layout, top, S)
    if golden_order is None:
        return cand_text
    cand_names = [n for _seg, _d, n in segs]
    if sorted(cand_names) != sorted(golden_order):
        return cand_text  # name-set mismatch → not a pure permutation → REFUSE.
    permuted = S._apply_order(cand_text, block, segs, golden_order)
    return permuted  # byte-identical when already in order (a safe no-op).


# ── ORGANIC #742 FACET B — named-parameter-override passthrough auto-retry ────
# A hidden TB binds `dut #(.STG_WIDTH(16)) u(...)` but the prose names NO such
# parameter → the blind first-pass emit has no `parameter STG_WIDTH`, and iverilog
# aborts elaboration with EXACTLY `parameter `STG_WIDTH' not found in `<inst>'`.
# This is an UNDISCLOSED binding contract on a functionally-correct, latency-
# AGNOSTIC design. When the compile fails with ONLY that error (and no other),
# auto-retry ONCE injecting a PASSTHROUGH `parameter <X>=<default>` (unread by the
# RTL, so the vvp pass/fail comparison is unchanged — §4.05). A mixed error set,
# or a candidate that already declares the param, is NOT normalized.
def _param_passthrough_retry_shape_b(
        sample_c: str, tb: Path, design: str, dataset: Path, layout: dict,
        args: dict, compile_log: str, td: str) -> Optional[dict]:
    """On a candidate whose iverilog compile failed with ONLY
    `parameter `X' not found` error(s), inject a passthrough `parameter X=<default>`
    into the emitted DUT header and retry the compile+run ONCE. Returns a verdict
    dict (PASS/FAIL) iff the injection produced a clean elaboration, else None
    (caller keeps the original compile_error). §4.05: a PURE ADD of a missing
    declaration — the functional vvp comparison is untouched, so a wrong-logic DUT
    still FAILs and an already-declared param is a no-op (None → keep FAIL).
    chip-AGNOSTIC: the iverilog error grammar + the TB's `#(.X(...))` grammar."""
    try:
        import port_convention_corpus as _PCC
    except Exception:
        return None
    if not _PCC.error_is_only_param_not_found(compile_log):
        return None  # a mixed / non-param error stays the candidate's own FAIL.
    missing = _PCC.iverilog_param_not_found(compile_log)
    if not missing:
        return None
    top = _canonical_dut_name_shape_b(design, dataset, layout)
    if not top:
        return None
    try:
        cand_text = Path(sample_c).read_text(errors="replace")
    except OSError:
        return None
    # Deterministic pre-emit gate: prefer the TB's OWN named-override value as the
    # injected default (a numeric literal); fall back to a benign 1 (unread).
    overrides = {}
    try:
        overrides = _PCC.tb_named_param_overrides(
            (dataset / design / layout["tb_filename"]).read_text(errors="replace"),
            top)
    except Exception:
        overrides = {}
    injected = cand_text
    added = False
    for p in missing:
        if _PCC.module_declares_param(injected, top, p):
            continue  # already declared (e.g. by a prior iteration) → skip.
        default = _PCC._default_for(p, overrides.get(p, ""))
        new_text = _PCC.inject_passthrough_param(injected, top, p, default)
        if new_text is None:
            return None  # could not inject (malformed header) → keep FAIL.
        injected, added = new_text, True
    if not added:
        return None
    pass_re = re.compile(args["pass_regex"])
    fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
    use_cwd = args.get("cwd_design_dir", True)
    inj_v = os.path.join(td, f"{top}.param_injected.v")
    with open(inj_v, "w") as fh:
        fh.write(injected)
    inj_fixed = _power_up_fixed(Path(inj_v), td)
    binp = os.path.join(td, "param_injected_bin")
    try:
        c = subprocess.run(["iverilog", "-g2012", "-o", binp, inj_fixed, str(tb)],
                           capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if c.returncode != 0 or not os.path.exists(binp):
        return None  # the injection did NOT clear the elaboration → keep FAIL.
    try:
        r = _bounded_vvp(binp, timeout=120, cwd=str(dataset / design) if use_cwd else _VVP_SCRATCH_CWD)
    except subprocess.TimeoutExpired:
        return {"design": design, "verdict": "FAIL", "reason": "sim_timeout"}
    out = r.stdout + r.stderr
    if pass_re.search(out) and not (fail_re and fail_re.search(out)):
        return {"design": design, "verdict": "PASS",
                "reason": "recovered_via_param_passthrough_injection"}
    # The injection cleared the elaboration but the design RUNTIME-FAILs the
    # functional check → an honest functional FAIL (NOT masked by injection).
    m = re.search(r"(\d+)\s*/\s*\d+\s*failures", out)
    return {"design": design, "verdict": "FAIL",
            "reason": f"functional_mismatch ({m.group(0) if m else 'test failed'})"}


def _score_shape_b(design: str, samples: Path, dataset: Path,
                   layout: dict, args: dict) -> dict:
    """Shape-B scorer wrapper (#679 + #690): run the core scorer, then audit the
    golden reference against its own official TB to tell an irreducible dataset
    defect from a real model FAIL. Two complementary audits:

      * RUNTIME (#679): on a FAIL whose cause is NOT a compile error, the golden
        compiles but FAILs its own TB at runtime → golden_ref_fails_own_tb_runtime.
      * COMPILE (#690): on a `reason=='compile_error'` FAIL, the golden(aliased)+TB
        ALSO fails to elaborate (TB unsatisfiable by anyone), OR the candidate's
        elaboration error is a TB-bound port the GOLDEN declares but the prose spec
        NEVER names (tb_requires_spec_absent_port) → dataset_defect. §4.05: a genuine
        candidate compile bug (syntax / a spec-declared port it omitted) stays a
        model FAIL.

    In every case the verdict is NOT changed (dual report in main(); never inflate
    the pass rate) — only the dataset_defect annotation is added."""
    res = _score_shape_b_impl(design, samples, dataset, layout, args)
    if res.get("verdict") != "FAIL":
        return res
    if res.get("reason") == "compile_error":
        defect, reason = _unsatisfiable_tb_compile_audit_shape_b(
            design, dataset, layout, res.get("log", ""))
        if defect:
            res["dataset_defect"] = True
            res["dataset_defect_reason"] = reason
            if reason == "tb_requires_spec_absent_port":
                res["reason"] = "tb_requires_spec_absent_port"
    else:
        gref = _golden_ref_fails_own_tb_runtime(design, dataset, layout, args)
        if gref is True:
            # DISCLOSURE-ONLY (suspected), NOT auto-exclude. A golden that COMPILES
            # but FAILs its own TB at RUNTIME proves only that the shipped GOLDEN is
            # buggy — it is NOT sound proof that the design is unsatisfiable by
            # anyone. A runtime functional mismatch has two indistinguishable causes:
            # (a) the TB is genuinely unsatisfiable, or (b) the reference is simply a
            # wrong implementation while a CORRECT submission still passes. Only (a)
            # is irreducible, and a golden failing its own TB cannot tell them apart.
            # MEASURED counter-example: RTLLM `radix2_div`'s golden fails 3/8 of its
            # own TB (e.g. unsigned 123/123 -> quotient 0x00 instead of 0x01), yet a
            # correct signed/unsigned radix-2 divider passes all 8 — the design is
            # satisfiable, so auto-excluding it removed a real, fixable design from
            # the denominator (a FALSE certificate that inflates the effective rate).
            # Route to the suspected (non-excluding) channel — the same contract the
            # comparable golden-disagreement audit (_canonical_disagrees_with_golden)
            # already obeys: FLAG, never EXCLUDE. Auto-exclusion stays reserved for
            # the COMPILE-level proven-irreducible class (tb_requires_spec_absent_port
            # / golden_ref_fails_own_tb_compile), where the TB binds a port neither
            # the golden nor the spec provides and NO spec-faithful author can satisfy
            # it. The verdict is unchanged either way (never inflate the pass rate).
            res["dataset_defect_suspected"] = True
            res["dataset_defect_reason"] = "golden_ref_fails_own_tb_runtime"
    return res


def _score_shape_b_impl(design: str, samples: Path, dataset: Path,
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
        # ORGANIC #742 FACET A — PROACTIVE positional-port normalization. BEFORE
        # the first compile, when the hidden TB binds the DUT POSITIONALLY, reorder
        # the emitted module's ports to the golden's positional bind order (a PURE
        # permutation by NAME). The blind first-pass emit declares ports in the
        # spec's prose order, which the per-design positional TB may not match — so
        # without this the first compile ALWAYS errors before the reactive #707
        # rescue can run. A no-op when the order already matches / there is no
        # positional contract / the name set differs (§4.05). Read+rewrite a temp
        # copy only — the original sample file is never mutated.
        try:
            _pre = Path(sample_c).read_text(errors="replace")
            _norm = _proactive_positional_port_normalize_shape_b(
                _pre, design, dataset, layout)
            if _norm != _pre:
                sample_c = os.path.join(td, f"normalized_{Path(sample_c).name}")
                Path(sample_c).write_text(_norm)
        except OSError:
            pass
        pass_re = re.compile(args["pass_regex"])
        fail_re = re.compile(args["fail_regex"]) if args.get("fail_regex") else None
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", binp, sample_c, str(tb)],
                               capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            # #1437 — an ABSENT iverilog raised here. It must NOT fall through to
            # the `returncode != 0` arm below: that arm returns
            # {"verdict": "FAIL", "reason": "compile_error"}, a claim ABOUT THE
            # CANDIDATE, and scoring a submission as FAILED on a compiler that
            # never ran is a fabricated finding — strictly worse than the
            # traceback, which at least announced itself. SKIP is the existing
            # verdict for "not scoreable here"; the log names the absent tool.
            return {"design": design, "verdict": "SKIP",
                    "reason": "iverilog_absent",
                    "log": f"COMMAND_NOT_FOUND: {e}"}
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
            compile_log = c.stdout + c.stderr
            # ORGANIC #742 FACET B — a compile_error that is ONLY
            # `parameter `X' not found in `<inst>'` is an UNDISCLOSED named-param-
            # override binding contract (the TB binds `#(.X(..))` but the prose
            # names no parameter). Inject a passthrough `parameter X=<default>`
            # (UNREAD by the RTL) and retry ONCE. §4.05: a PURE ADD — the vvp
            # comparison is unchanged, so a wrong-logic DUT still FAILs and an
            # already-declared param is a no-op. A MIXED error set is not retried.
            pinj = _param_passthrough_retry_shape_b(
                sample_c, tb, design, dataset, layout, args, compile_log, td)
            if pinj is not None:
                return pinj
            # ORGANIC #707 round-3 — a compile_error against the hidden TB MAY be
            # a pure positional-port-ORDER mismatch (a functionally-correct
            # candidate whose declaration order differs from the per-design TB
            # bind). Try a SCORE-SIDE pure permutation (golden+TB-elaborates gate +
            # unique direction/width map) and adopt it ONLY if it now PASSES. A
            # missing/extra/wrong-width port or wrong logic can NEVER be rescued
            # this way (§4.05). If the permutation does not rescue → stay FAIL.
            rescued = _score_side_port_permutation_rescue_shape_b(
                design, sample, dataset, layout, args)
            if rescued is not None:
                return rescued
            return {"design": design, "verdict": "FAIL", "reason": "compile_error",
                    "log": c.stderr[-400:]}
        try:
            # cwd=design dir so the TB's relative-path $readmemh works (skill §3)
            r = _bounded_vvp(binp, timeout=120, cwd=str(dataset / design) if args.get("cwd_design_dir", True) else _VVP_SCRATCH_CWD)
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
    which is the irreducible defect we want to flag.

    TWO layouts (#690 generalization — no longer always_TopModule-only):
      * VerilogEval-class: ref_suffix + tb_suffix + module_name_strategy
        ==always_TopModule (flat <Prob>_ref.sv / <Prob>_test.sv). DUT name is the
        fixed 'TopModule'.
      * Shape-B / RTLLM-class: ref_glob + tb_filename + a per-design subdir, where
        `prob` is the design subdir. DUT name comes from the spec's `Module name:`
        line. Delegates to _golden_ref_compiles_with_tb_shape_b so the compile-level
        unsatisfiable-TB detector also covers Shape-B benchmarks. The golden module
        is aliased to the canonical DUT name the TB instantiates (`uut`).
    Returns None for any layout providing neither shape's keys (no determination).
    """
    # Shape-B / RTLLM-class layout (ref_glob + tb_filename + per-design subdir).
    if layout.get("ref_glob") and layout.get("tb_filename"):
        compiles, _ports = _golden_ref_compiles_with_tb_shape_b(prob, dataset, layout)
        return compiles
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
        last_err = ""
        for cmd in (["iverilog", "-g2012", "-s", "tb", "-o", binp] + srcs,
                    ["iverilog", "-g2012", "-o", binp] + srcs):
            try:
                c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return None
            if c.returncode == 0:
                return True
            last_err = c.stdout + c.stderr
        # Same SV-2012 tool-gap escalation as the sample-scoring path: a golden
        # whose only host-compile failure is an iverilog tool-gap (e.g. the enum
        # type-cast States'(...) that stock iverilog 11 rejects with "sorry:")
        # is NOT an irreducible dataset defect — the fork rung that scores the
        # samples can satisfy it, so "unsatisfiable by anyone" would be false and
        # a genuinely-failing candidate would be wrongly removed from the
        # dataset-defect-excluding denominator. Escalate before concluding False.
        if _iverilog_toolgap_signature(last_err):
            if _fork_iverilog_compile_run(srcs, "tb") is not None:
                return True
        return False


_CANONICAL_DIR = Path(__file__).resolve().parent / "canonical_samples"


def _canonical_disagrees_with_golden(prob: str, dataset: Path, layout: dict,
                                     args: dict, bench: str):
    """ORGANIC-20260605-scorer-disagreeing-golden-flag: the SECOND
    dataset-defect audit class — a golden that consistently REJECTS the
    spec-correct canonical reading. When a core-vetted canonical sample
    exists at canonical_samples/<bench>/<prob>.sv (vetting policy in that
    tree's README), run it against the hidden golden; if it fails at a
    high mismatch rate (>=50%) return the evidence string, else None.
    DISCLOSURE-ONLY by contract: the caller flags, never excludes —
    auto-exclusion stays reserved for the scorer-PROVEN class
    (golden_ref_fails_own_tb). chip-AGNOSTIC mechanism: pure
    bench/prob path lookup + the scorer's own compile/sim path."""
    can = _CANONICAL_DIR / bench / f"{prob}.sv"
    test = dataset / f"{prob}{layout['tb_suffix']}"
    if not (can.is_file() and test.is_file()):
        return None
    ref = dataset / f"{prob}{layout['ref_suffix']}" if layout.get("ref_suffix") else None
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "bin")
        sources = [str(can), str(test)]
        if args.get("tb_compile_with_ref") and ref is not None and ref.is_file():
            sources.append(str(ref))
        for cmd in (["iverilog", "-g2012", "-s", "tb", "-o", binp] + sources,
                    ["iverilog", "-g2012", "-o", binp] + sources):
            try:
                c = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return None
            if c.returncode == 0:
                break
        else:
            return None
        try:
            r = _bounded_vvp(binp, timeout=120, cwd=_VVP_SCRATCH_CWD)
        except subprocess.TimeoutExpired:
            return None
        out = r.stdout + r.stderr
        if re.search(args["pass_regex"], out):
            return None            # golden agrees with the canonical — no flag
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        if not m:
            return None            # no mismatch summary — no determination
        mism, tot = int(m.group(1)), int(m.group(2))
        if tot == 0 or mism / tot < 0.5:
            return None            # low-rate disagreement — ambiguity, not defect
        return (f"vetted canonical sample mismatches the hidden golden: "
                f"{mism}/{tot} samples")


def _semantic_prompt_oracle_evidence(prob: str, dataset: Path,
                                     layout: dict) -> Optional[str]:
    """Return prompt-vs-golden contradiction evidence for a Shape-C problem.

    This scorer adapter deliberately owns no semantic rules.  It routes the
    prompt and golden reference through the general, fail-closed semantic floor
    program used by the benchmark tier pipelines.  Unsupported or ambiguous
    prompt classes return ``None``; scorer operation must never depend on this
    advisory audit being available.
    """
    prompt_suffix = layout.get("prompt_suffix")
    ref_suffix = layout.get("ref_suffix")
    if not prompt_suffix or not ref_suffix:
        return None
    prompt = dataset / f"{prob}{prompt_suffix}"
    ref = dataset / f"{prob}{ref_suffix}"
    if not (prompt.is_file() and ref.is_file()):
        return None
    try:
        from semantic_spec_floor_check import semantic_floor_evidence
        return semantic_floor_evidence(
            prompt.read_text(errors="replace"),
            ref.read_text(errors="replace"),
        )
    except Exception:
        return None


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
        elif str(res.get("reason", "")).startswith("functional_mismatch"):
            # Semantic prompt↔oracle contradiction (disclosure-only).  This is
            # stronger and more general than a curated canonical sample: it
            # cites an independently extracted prompt truth and uses the shared
            # semantic-floor program.  Raw verdict/pass@1 remain unchanged.
            ev = _semantic_prompt_oracle_evidence(prob, dataset, layout)
            if ev:
                res["dataset_defect_suspected"] = True
                res["dataset_defect_reason"] = \
                    "semantic_prompt_oracle_contradiction"
                res["semantic_floor_evidence"] = ev
                res["canonical_evidence"] = ev
            elif args.get("_bench"):
                # Curated canonical disagreement remains the fallback for
                # semantic classes the general floor program cannot extract.
                ev = _canonical_disagrees_with_golden(
                    prob, dataset, layout, args, args["_bench"])
                if ev:
                    res["dataset_defect_suspected"] = True
                    res["dataset_defect_reason"] = \
                        "suspected_defective_golden"
                    res["canonical_evidence"] = ev
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
                # SV-2012 tool-gap escalation: the FORKED iverilog 14 in the EDA
                # container handles SV enum type-casts (States'(...)) that stock
                # host iverilog 11 rejects ("sorry: cast not supported"). Escalate
                # ONLY on that tool-gap signature so a genuine RTL compile bug still
                # FAILs as compile_error. §4.05 no-leak: the fork runs the REAL
                # simulator, so a wrong DUT still mismatches (verdict never inflated).
                if _iverilog_toolgap_signature(c.stdout + c.stderr):
                    # preserve the CANDIDATE (sources[0]) verbatim — only the
                    # benchmark's own TB/ref get the dump-strip (see helper)
                    fout = _fork_iverilog_compile_run(sources, "tb",
                                                      preserve=(sources[0],))
                    if fout == FORK_SIM_TIMEOUT:
                        return {"problem": prob, "verdict": "FAIL",
                                "reason": "sim_timeout",
                                "tool": "fork-iverilog-14"}
                    if fout is not None:
                        if re.search(args["pass_regex"], fout):
                            return {"problem": prob, "verdict": "PASS",
                                    "tool": "fork-iverilog-14"}
                        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", fout)
                        return {"problem": prob, "verdict": "FAIL",
                                "reason": (f"functional_mismatch "
                                           f"({m.group(0) if m else 'no summary'})"),
                                "tool": "fork-iverilog-14"}
                return {"problem": prob, "verdict": "FAIL", "reason": "compile_error",
                        "log": c.stderr[-400:]}
        try:
            r = _bounded_vvp(binp, timeout=120, cwd=str(dataset) if args.get("cwd_design_dir", False) else _VVP_SCRATCH_CWD)
        except subprocess.TimeoutExpired:
            return {"problem": prob, "verdict": "FAIL", "reason": "sim_timeout"}
        out = r.stdout + r.stderr
        if re.search(args["pass_regex"], out):
            return {"problem": prob, "verdict": "PASS"}
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        return {"problem": prob, "verdict": "FAIL",
                "reason": f"functional_mismatch ({m.group(0) if m else 'no summary'})"}


def no_sample_disclosure(results, total, npass, ident="design"):
    """`(count, problems, pct_of_authored, partially_authored)`. vibe-ic#637.

    NEVER AUTHORED is not ANSWERED WRONGLY. Every other way a problem fails to
    be a real measurement already carries a count and a rate in this summary;
    the one that means THE RUN WAS NOT FINISHED carried neither.

    MEASURED on two PUBLISHED runs, whose summaries say none of this:

        verilogeval_human/run_kimi_k3_20260718  149/156 = 95.51%
                                                2 no_sample -> 149/154 = 96.75%
        verilogeval_v2/run_kimi_k3_20260718     147/156 = 94.23%
                                                4 no_sample -> 147/152 = 96.71%

    Six problems across two published numbers counted as submissions that were
    wrong, when nothing was submitted.

    It misleads most exactly when it matters most: `no_sample` is the signature
    of an INCOMPLETE run — an agent that died, hit a quota, or was stopped —
    which is the state someone opens this file to discover. A scorer invocation
    over a run that had barely started produced a fully-formed result claiming
    2.0%; re-scored after it finished, 79.59%.

    DERIVED from the per-result `reason` both shapes already write, so there is
    no second detector to keep in sync, and the rate EXCLUDES rather than
    REPLACES the headline.
    """
    nosamp = [r for r in results if r.get("reason") == "no_sample"]
    n_ns = len(nosamp)
    authored = total - n_ns
    return (n_ns,
            [str(r.get(ident, "?")).split("/")[-1] for r in nosamp],
            round(100.0 * npass / authored, 2) if authored else 0.0,
            bool(n_ns))


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
    args = dict(entry["scorer_args"])
    args["_bench"] = a.bench   # canonical_samples/<bench> lookup (#418 audit)
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
    # fails its own hidden TB — Shape C: it cannot COMPILE against its own TB
    # (golden_ref_fails_own_tb); Shape B (#679): it compiles but FAILs at RUNTIME
    # (golden_ref_fails_own_tb_runtime). Both are unsatisfiable by ANY submission.
    # Flag + DUAL-report (raw pass@1 unchanged for leaderboard parity, plus a rate
    # that excludes them); never silently inflate. Shape-agnostic: keys on the
    # per-result `dataset_defect` flag set by either shape's wrapper. Mirrors the
    # non-discriminating-TB dual report above.
    ddef = [r for r in results if r.get("dataset_defect")]
    n_ddef = len(ddef)
    n_eff_satisfiable = n_eff - n_ddef
    # Suspected-defective goldens (ORGANIC-20260605-scorer-disagreeing-golden-
    # flag): the vetted canonical sample fails the hidden golden at a high
    # mismatch rate. DISCLOSURE-ONLY dual report — raw pass@1 unchanged; the
    # excluding rate is advisory and never replaces the headline.
    dsus = [r for r in results if r.get("dataset_defect_suspected")]
    n_dsus = len(dsus)
    n_eff_unsuspected = n_eff_satisfiable - n_dsus
    # NEVER AUTHORED is not ANSWERED WRONGLY (vibe-ic#637). Every other way a
    # problem fails to be a real measurement already has a count and a rate in
    # this summary; the one that means THE RUN WAS NOT FINISHED had neither, so
    # `39/50 = 79.59%` read as "39 of 50 designs solved" when it was "39 of the
    # 48 that were authored", with two designs that produced nothing counted as
    # submissions that were wrong.
    #
    # It misleads most exactly when it matters most. `no_sample` is the
    # signature of an INCOMPLETE run — an agent that died, hit a quota, or was
    # stopped — which is precisely the state someone opens this file to discover.
    # Measured: a scorer invocation over a run that had barely started wrote a
    # fully-formed `pass_at_1.json` claiming 2.0%, and nothing in the file said
    # the run was still going. Re-scored after it finished: 79.59%.
    #
    # DERIVED from the per-result `reason` the scorer already writes, in both
    # shapes, so there is no second detector to keep in sync.
    #
    # The rate EXCLUDES them rather than replacing the headline, symmetric with
    # the dual reports above: "39 of 48 authored" beside "39 of 50 in scope",
    # neither hiding the other.
    n_nosamp, nosamp_problems, pct_authored, partially = \
        no_sample_disclosure(results, n, npass, ident)
    n_authored = n - n_nosamp
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
        "suspected_defective_golden_count": n_dsus,
        "suspected_defective_golden_problems": [
            {"problem": r[ident].split('/')[-1],
             "reason": r.get("dataset_defect_reason", ""),
             "evidence": r.get("canonical_evidence", "")} for r in dsus],
        "pass_at_1_excluding_suspected_defects_pct": round(
            100.0 * npass / n_eff_unsuspected, 2) if n_eff_unsuspected else 0.0,
        "no_sample_count": n_nosamp,
        "no_sample_problems": nosamp_problems,
        "pass_at_1_excluding_no_sample_pct": pct_authored,
        # The one bit a reader most needs and currently has to reconstruct by
        # counting the `results` array by hand.
        "partially_authored": partially,
        "results": results,
    }
    (run / "pass_at_1.json").write_text(json.dumps(summary, indent=2) + "\n")
    if nskip:
        print(f"{entry['title']}  pass@1 = {npass}/{n_eff} = {summary['pass_at_1_pct']}% "
              f"({nskip} scorer-gap excluded; raw {npass}/{n} = "
              f"{summary['pass_at_1_pct_no_skip_excluded']}%)  [Shape {shape}]")
    else:
        print(f"{entry['title']}  pass@1 = {npass}/{n} = {summary['pass_at_1_pct']}%  [Shape {shape}]")
    if n_nosamp:
        # Printed AND in the file. A disclosure that does not travel with the
        # number is not a disclosure: stdout is gone by the time anyone reads
        # the artefact, and the JSON is what survives, gets copied and quoted.
        print(f"  ⚠ PARTIALLY-AUTHORED RUN — {n_nosamp} of {n} problem(s) produced "
              f"no sample at all and are counted as FAIL in the headline. "
              f"Of the {n_authored} authored: "
              f"{summary['pass_at_1_excluding_no_sample_pct']}%. "
              f"Missing: {summary['no_sample_problems']}")
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
    if n_dsus:
        print(f"  ⓘ {n_dsus} SUSPECTED benchmark-oracle defect(s) — independent "
              f"prompt semantics or a vetted canonical sample contradicts the "
              f"golden (disclosure-only; counted in pass@1): " +
              ", ".join(f"{d['problem']} [{d['reason']}] ({d['evidence']})"
                        for d in summary['suspected_defective_golden_problems']))
        print(f"  advisory pass@1 excluding suspected defects = "
              f"{npass}/{n_eff_unsuspected} = "
              f"{summary['pass_at_1_excluding_suspected_defects_pct']}%")
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
