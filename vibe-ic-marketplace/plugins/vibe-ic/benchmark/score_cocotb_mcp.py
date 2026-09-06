#!/usr/bin/env python3
"""score_cocotb_mcp.py — Shape D scorer wrapping the vibeic-eda container's icarus + cocotb.

This is a CLI fallback: a host-side runner that does the same thing the MCP
`eda_cocotb` tool does (Icarus + cocotb), but invocable directly via docker exec
so a new plugin user can score Shape-D benchmarks (CVDP-style) without writing
their own subprocess plumbing.

Substitution disclosure: official CVDP harness uses `nvidia/cvdp-sim:v1.0.0`
(gated). We substitute the `vibeic-eda` (hpretl/iic-osic-tools) container which
ships iverilog 13 + cocotb 2.0.1 + cocotb_tools. Per the methodology skill § 3.

Input layout (Shape D per BENCHMARK_REGISTRY.layout):
    <project>/work/rtl/<dut>.sv                       (candidate RTL — blind authored)
    <project>/work/PROMPT.txt                         (blind input)
    <project>/work/docs/specification.md              (blind input)
    <project>/score/src/test_<dut>.py                 (HIDDEN cocotb test — scoring only)
    <project>/score/src/harness_library.py            (HIDDEN helper)
    <project>/score/src/test_runner.py                (HIDDEN runner)

The candidate RTL + the hidden testbench Python need to be co-located inside
the vibeic-eda container's mount (typically /foss/designs). This script stages
both into a temp work_dir under the mount, sets PYTHONPATH, and runs
test_runner.py via `docker exec`.

Usage:
    python3 score_cocotb_mcp.py --project /path/to/cvdp_fixed_priority_arbiter \\
        --top fixed_priority_arbiter --rtl work/rtl/fixed_priority_arbiter.sv \\
        --mount-root /home/<user>/<your-designs-dir> \\
        --container vibeic-eda

Outputs <project>/reports/cocotb_score.json with the TESTS / PASS / FAIL counts.
"""
from __future__ import annotations
import argparse, json, subprocess, shutil, time, re
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
# The helpers live in `programs/`, NOT beside this file. A bootstrap
# pointing at this directory imports nothing and the gate dies at
# start-up with ModuleNotFoundError -- measured, as a SCRIPT, which is
# the only way this file is ever run.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "programs"))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated


def _docker_path(host_path: Path, mount_host: Path, mount_container: str = "/foss/designs") -> str:
    """Translate a host path under <mount_host> to the corresponding container path."""
    rel = host_path.resolve().relative_to(mount_host.resolve())
    return f"{mount_container}/{rel}"


def _container_mounts(container: str):
    """Return list of (host_source, container_destination) tuples from `docker inspect`.

    Empty list means the container doesn't exist or has no bind mounts. Raises
    SystemExit on container-not-found so we fail fast before scoring.
    """
    try:
        out = subprocess.check_output(
            ["docker", "inspect", container], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"docker inspect {container!r} failed (is the container running?): {e.output.strip()}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if not data:
        return []
    mounts = data[0].get("Mounts", []) or []
    return [(Path(m["Source"]).resolve(), m["Destination"]) for m in mounts if m.get("Source")]


def _validate_mount(container: str, mount_host: Path, mount_container: str):
    """Refuse to proceed if --mount-root + --mount-container don't match an actual
    docker bind mount. Captured from v0.1.53 CVDP run: a wrong --mount-root produced
    a silent TESTS=0 PASS=0 FAIL=0 SKIP=0 with the real error ('cd: ... No such file
    or directory') buried in log_tail. Fail loudly instead."""
    actual = _container_mounts(container)
    if not actual:
        # container has no mounts at all — proceeding is futile
        raise SystemExit(
            f"Container {container!r} has no bind mounts; cannot reach project from host.\n"
            f"  Expected mount: {mount_host} → {mount_container}")
    # accept either an EXACT match or a parent-of relationship (mount_host is under an actual source)
    for src, dst in actual:
        if (mount_host == src or src in mount_host.parents) and dst == mount_container:
            return
    listing = "\n".join(f"    {s} → {d}" for s, d in actual)
    raise SystemExit(
        f"--mount-root {mount_host} → {mount_container} is NOT an actual bind mount on container {container!r}.\n"
        f"Actual mounts:\n{listing}\n"
        f"Fix: either pass --mount-root that matches one of the above sources, or rsync the\n"
        f"project under one of them and re-run with the matching --mount-root.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True, help="Shape-D project dir (work/ + score/ subdirs)")
    ap.add_argument("--top", required=True, help="DUT top module name")
    ap.add_argument("--rtl", required=False, default=None,
                    help="RTL file path (relative to --project) — the candidate to score. "
                         "If omitted (v0.1.59 R10), auto-discover from canonical runner output "
                         "locations: work/rtl/<top>.{sv|v} → phase2/stage1/rtl/<top>.{sv|v}. "
                         "Pass --rtl explicitly to score a non-canonical RTL file.")
    ap.add_argument("--mount-root", required=True, help="host path mounted into the container as /foss/designs (e.g. /home/<user>/<your-designs-dir>)")
    ap.add_argument("--mount-container", default="/foss/designs")
    ap.add_argument("--container", default=_pin.default_container_name())
    ap.add_argument("--simulator", default="icarus")
    ap.add_argument("--waves", type=int, default=0,
                    help="WAVES env for the cocotb runner (0=off default, 1=dump FST/VCD). "
                         "Pinned into the container env so cocotb 2.0.1 runner.py "
                         "int(os.getenv('WAVES', waves)) never sees None (the 1.x->2.0 gap).")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    project = Path(a.project).resolve()
    mount_host = Path(a.mount_root).resolve()
    if mount_host not in project.parents and project != mount_host:
        raise SystemExit(
            f"Project must live UNDER --mount-root ({mount_host}) so the container can see it.\n"
            f"  project    = {project}\n"
            f"Symlinks are NOT followed across the docker mount; rsync the project under the mount.")

    # Verify the host-side mount-root is actually bind-mounted into the container.
    # Without this, a wrong --mount-root produces a silent TESTS=0 PASS=0 FAIL=0 SKIP=0
    # with the real error ('cd: ... No such file or directory') buried in log_tail.
    _validate_mount(a.container, mount_host, a.mount_container)

    # v0.1.59 R10: auto-discover RTL from canonical locations when --rtl omitted.
    if a.rtl:
        rtl_host = project / a.rtl
        if not rtl_host.is_file():
            raise SystemExit(f"RTL not found: {rtl_host}")
    else:
        rtl_host = _autodiscover_rtl(project, a.top)
        if rtl_host is None:
            raise SystemExit(
                f"--rtl omitted and no canonical RTL found for top={a.top!r}.\n"
                f"  Searched: work/rtl/{a.top}.sv, work/rtl/{a.top}.v, "
                f"phase2/stage1/rtl/{a.top}.sv, phase2/stage1/rtl/{a.top}.v\n"
                f"  under {project}\n"
                f"Pass --rtl <relpath> explicitly to score a non-canonical RTL.")

    score_src_host = project / "score" / "src"
    test_py = next(score_src_host.glob(f"test_{a.top}.py"), None)
    if not test_py:
        # any test_*.py EXCEPT test_runner.py (which is the pytest entry point,
        # not the cocotb test module). Pick deterministically (sorted).
        cands = sorted(p for p in score_src_host.glob("test_*.py") if p.name != "test_runner.py")
        test_py = cands[0] if cands else None
    if not test_py:
        raise SystemExit(f"No test_*.py under {score_src_host}")
    if not (score_src_host / "test_runner.py").is_file():
        raise SystemExit(f"No test_runner.py under {score_src_host}")

    # Stage a clean work_dir inside the project (same mount) — colocate RTL + score/src/*.py
    work_dir = project / "cocotb_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    # copy RTL
    shutil.copy2(rtl_host, work_dir / rtl_host.name)
    # copy all sibling .py from score/src (mcp eda_cocotb v0.1.13 convention)
    for py in score_src_host.glob("*.py"):
        shutil.copy2(py, work_dir / py.name)

    rtl_c = _docker_path(work_dir / rtl_host.name, mount_host, a.mount_container)
    work_c = _docker_path(work_dir, mount_host, a.mount_container)
    test_module = test_py.stem

    # vibeic-eda container ships iverilog under /foss/tools/bin and libvvp.so under
    # /foss/tools/iverilog/lib — those paths are only injected by the container's
    # login profile (`bash -lc`), NOT by plain `docker exec`. Use bash -lc so the
    # session inherits the full toolchain PATH + LD_LIBRARY_PATH.
    # cocotb 2.0.1 runner.py L508-509 do int(os.getenv("WAVES", waves)) /
    # int(os.getenv("GUI", gui)). int(None) raises TypeError when a 1.x-style
    # harness passes waves=None / gui=None AND the env var is unset (the
    # nvidia/cvdp-sim harness was written for cocotb 1.x, which tolerated it).
    # Pin WAVES+GUI to 0 so cocotb's int() always sees the string "0"
    # (int("0")==0), never None. The cocotb runner reads the WAVES *env var*
    # BEFORE falling back to the harness's waves= param, so our export wins even
    # when the harness passes waves=None (empirically: priority_encoder PASSes).
    # We ALSO mirror it to WAVE (singular): some harnesses read wave=os.getenv(
    # "WAVE") and could feed it into their OWN int(); WAVE=0 defends that path
    # too. This is an ENV adaptation of the cocotb-2.0 runner (our disclosed § 3
    # substitution layer), NOT a change to the hidden per-project harness.
    #
    # We deliberately DO NOT export TARGET. TARGET is read only inside the
    # xcelium coverage gate (harness covt_report_check(): float(os.getenv(
    # "TARGET"))), which opens /code/rundir/coverage.log FIRST — a file only
    # Cadence imc produces, so under the icarus substitution it never exists and
    # the gate FileNotFounds before TARGET is ever read. Injecting a fabricated
    # TARGET would risk a SPURIOUS coverage pass if real xcelium output were ever
    # mounted; the coverage dimension is genuinely unmeasurable here and is
    # surfaced honestly as a non-blocking coverage_gate Cat-D, never papered over.
    waves_v = '1' if a.waves else '0'
    inner = (
        f"export VERILOG_SOURCES={rtl_c}; "
        f"export SIM={a.simulator}; "
        f"export TOPLEVEL={a.top}; "
        f"export MODULE={test_module}; "
        f"export WAVES={waves_v}; "
        f"export WAVE={waves_v}; "
        f"export GUI=0; "
        f"export PYTHONPATH={work_c}:${{PYTHONPATH:-}}; "
        f"cd {work_c} && python3 -m pytest -rA -s test_runner.py"
    )
    cmd = _ce.docker_exec_argv(a.container, "bash", "-lc", inner)
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
    elapsed = time.time() - t0
    out = p.stdout + p.stderr

    # --- Functional verdict: cocotb's OWN results.xml is AUTHORITATIVE --------
    # A post-test xcelium coverage-gate (covt_report_check/imc, see below) can
    # crash AFTER the functional tests ran+passed, swallowing pytest's
    # "TESTS=N PASS=M..." summary line. cocotb flushes its JUnit results.xml at
    # end-of-test, BEFORE that post-test coverage step, so the XML carries the
    # true functional result even when stdout is truncated. Prefer it; fall back
    # to the pytest marker only when no parseable cocotb XML exists.
    func = _parse_cocotb_results_xml(work_dir)
    m = re.search(r"TESTS\s*=\s*(\d+)\s+PASS\s*=\s*(\d+)\s+FAIL\s*=\s*(\d+)\s+SKIP\s*=\s*(\d+)", out)
    if func is not None:
        tests, passed, failed, skipped = func
        functional_source = "results.xml"
    elif m:
        tests, passed, failed, skipped = (int(x) for x in m.groups())
        functional_source = "pytest-marker"
    else:
        tests = passed = failed = skipped = 0
        functional_source = "none"

    # functional_verdict is derived from cocotb results.xml ONLY (null when no
    # XML found — the functional dimension is then not independently measurable).
    if func is None:
        functional_verdict = None
    elif tests > 0 and failed == 0 and skipped == 0:
        functional_verdict = "PASS"
    else:
        functional_verdict = "FAIL"

    # v0.1.57 capture: distinguish DUT-FAIL from HARNESS-SUBSTITUTION error.
    # When tests==0 AND pytest reported a TypeError/ImportError/ModuleNotFoundError
    # raised by the harness (cocotb-tools / harness_library.py) BEFORE any cocotb
    # test ran, the scorer was looking at a tool-substitution gap (per § 3 +
    # § 4 Cat D), not a DUT bug. We pass the AUTHORITATIVE tests count
    # (results.xml-derived when available) so a coverage-gate crash on a PASSING
    # functional run short-circuits to None (_detect_harness_error's first guard
    # is `if tests>0: return None`) instead of masking the PASS.
    harness_error = _detect_harness_error(out, tests, p.returncode)

    # The xcelium assertion-coverage gate (covt_report_check/imc reading
    # coverage.log) cannot run under the icarus substitution (§3). Detect it
    # from the SCORER OUTPUT ONLY (blind rule: never read harness_library.py)
    # and surface it as a SEPARATE, non-blocking coverage-only Cat-D gap so it
    # does NOT mask the functional verdict.
    coverage_gate = None
    cov_sig = _detect_coverage_gate(out)
    if cov_sig is not None:
        cov_blocking = not (tests > 0 and failed == 0)
        coverage_gate = {
            "detected": True,
            "kind": "xcelium-coverage-gate-unmeasurable-under-icarus",
            "signal": cov_sig,
            "category": "coverage-only",
            "blocking": cov_blocking,
            "note": ("covt_report_check()/imc reads coverage.log which only xcelium "
                     "populates; the icarus substitution (§3) cannot produce it. "
                     "Functional tests are scored from cocotb results.xml "
                     "independently; coverage is a DISCLOSED Cat-D gap."),
        }
        # When the coverage gate is the blocking failure before any test ran,
        # tag the (existing) harness_error so consumers can distinguish it.
        if harness_error is not None:
            harness_error["category"] = "coverage-only"

    # Single-pass scorer. We do NOT silently retry with alternative RTL variants
    # (sync→async, etc.) — that would over-fit to the hidden harness's reset
    # convention, violating the open-benchmark-methodology skill § 4 Cat A/E
    # doctrine ("leave spec-faithful, do NOT over-fit to the hidden oracle").
    # If the spec↔harness inconsistency forces a workaround, the AI must
    # document it as Cat-A FLOOR in RESULT.md and run the alternative variant
    # as a SEPARATE score with a SEPARATE --rtl arg — never silently inside one
    # score invocation.
    verdict = "PASS" if (tests > 0 and failed == 0 and skipped == 0 and passed == tests) else "FAIL"
    summary = {
        "project": str(project),
        "top": a.top,
        "shape": "D",
        "tool": f"docker exec {a.container} (iverilog + cocotb)",
        "tool_substitution_note": "Substitutes nvidia/cvdp-sim:v1.0.0 (gated). cocotb 2.0.1; see open-benchmark-methodology skill § 3.",
        "tests": tests, "passed": passed, "failed": failed, "skipped": skipped,
        "verdict": verdict,
        # functional_verdict (results.xml only; null when no XML) lets a consumer
        # trust the functional dimension even when the overall verdict was
        # historically conflated with the (unmeasurable) coverage gate.
        "functional_verdict": functional_verdict,
        "functional_source": functional_source,
        "elapsed_s": round(elapsed, 2),
        "log_tail": out[-2000:],
        # v0.1.57: when verdict==FAIL with tests==0, harness_error tells the
        # consumer whether to triage as Cat D (tool gap) vs unknown.
        "harness_error": harness_error,
        # coverage_gate: non-null when the xcelium coverage step appears; when
        # blocking==False the functional tests still passed and this is purely a
        # DISCLOSED Cat-D coverage gap (NOT a functional FAIL).
        "coverage_gate": coverage_gate,
    }
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "cocotb_score.json").write_text(json.dumps(summary, indent=2) + "\n")
    note = ""
    if harness_error and tests == 0:
        note = f"  ← {harness_error['kind']} in cocotb runner (Cat-D candidate; see harness_error in cocotb_score.json)"
    elif coverage_gate and not coverage_gate["blocking"]:
        note = "  ← xcelium coverage gate unmeasurable under icarus (Cat-D coverage-only; functional verdict unaffected)"
    print(f"{a.top} (Shape D)  TESTS={tests} PASS={passed} FAIL={failed} SKIP={skipped}  → verdict {verdict}{note}")
    print(f"  cocotb_score.json: {reports / 'cocotb_score.json'}")
    raise SystemExit(0 if verdict == "PASS" else 1)


# Patterns that indicate a HARNESS-SIDE failure (cocotb-tools / runner / version
# mismatch / missing import / docker substitution gap), NOT a DUT bug. When
# tests==0 AND one of these fires, the right § 4 triage is Cat D
# (tool-substitution gap), not Cat F-H (agent-fixable).
_HARNESS_ERROR_PATTERNS = (
    # cocotb runner.test() internal — what we saw in CVDP priority_encoder v0.1.56
    (re.compile(r"TypeError: int\(\) argument must be a string"),
     "cocotb-tools-typeerror"),
    # Safety net for a harness-side numeric coercion of an unset env var (e.g.
    # float(os.getenv("TARGET")) in a coverage gate) that crashes BEFORE any
    # test ran (tests==0). When tests>0 the _detect_harness_error guard already
    # short-circuits to None, so this only fires for a genuine pre-test crash.
    (re.compile(r"TypeError: float\(\) argument must be a string"),
     "harness-float-coercion-typeerror"),
    (re.compile(r"ModuleNotFoundError: No module named"),
     "cocotb-import-missing-module"),
    (re.compile(r"ImportError:"),
     "cocotb-import-error"),
    # Container / env mismatch
    (re.compile(r"command not found"), "container-tool-missing"),
    (re.compile(r"docker: Error"), "container-error"),
    # Iverilog couldn't elaborate at ALL (no harness gets to run) — distinguish
    # this from "iverilog elaborated but cocotb crashed inside runner.test()"
    (re.compile(r"^error: ", re.MULTILINE), "iverilog-elaboration-error"),
    # General Python traceback in harness layer
    (re.compile(r"harness_library\.py:\d+:"), "harness-library-internal-error"),
)


def _autodiscover_rtl(project: Path, top: str) -> Path | None:
    """v0.1.59 R10: locate a candidate RTL file under the runner's canonical
    output locations when the scorer was called without --rtl. Returns the
    first match in priority order:
      1. work/rtl/<top>.sv       (Shape-D blind-instructions step 3 target)
      2. work/rtl/<top>.v        (.v fallback for Verilog-2001)
      3. phase2/stage1/rtl/<top>.sv  (the spec-to-rtl skill emits here)
      4. phase2/stage1/rtl/<top>.v   (.v fallback)
    Returns None if nothing matches; caller emits an explicit error then.
    """
    candidates = [
        project / "work" / "rtl" / f"{top}.sv",
        project / "work" / "rtl" / f"{top}.v",
        project / "phase2" / "stage1" / "rtl" / f"{top}.sv",
        project / "phase2" / "stage1" / "rtl" / f"{top}.v",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _detect_harness_error(out: str, tests: int, returncode: int) -> dict | None:
    """Inspect pytest stdout/stderr for harness-side errors that fired BEFORE
    any cocotb test could run. Returns a dict {kind, signal_lines} when one
    pattern matches and tests==0; None otherwise.

    Honesty: this scans ONLY the SCORER OUTPUT (stdout/stderr from pytest),
    not the contents of score/src/harness_library.py — the blind rule still
    holds. The output is something the user already sees in log_tail; this
    helper just classifies it so the consumer doesn't have to parse it by eye.
    """
    if tests > 0:
        # If any cocotb test reported, FAIL/PASS are DUT-level signals.
        return None
    if returncode == 0:
        # Clean exit with tests==0 — likely no tests were collected, not a
        # harness error. Don't fabricate a Cat-D label.
        return None
    for pat, kind in _HARNESS_ERROR_PATTERNS:
        m = pat.search(out)
        if m:
            return {"kind": kind, "signal": m.group(0)[:200]}
    return None


def _parse_cocotb_results_xml(work_dir: Path):
    """Parse cocotb's OWN JUnit results to recover the FUNCTIONAL verdict,
    independently of pytest's stdout marker (which a post-test xcelium
    coverage-gate crash can swallow). Reads ONLY cocotb-emitted XML under the
    scorer's work_dir — never score/src/*.py — so the blind rule is preserved.

    cocotb 2.0.1 writes per-test JUnit XML at sim_build/<module>.result.xml (or
    the legacy results.xml in the run cwd). XML shape (confirmed on real
    Shape-D runs):
      <testsuites><testsuite>
        <testcase .../>                 -> PASSED
        <testcase><failure/></testcase> -> FAILED
        <testcase><error/></testcase>   -> FAILED
        <testcase><skipped/></testcase> -> SKIPPED

    Returns (tests, passed, failed, skipped) aggregated + de-duped by
    (classname, name) across all matched XML files, or None when no parseable
    cocotb XML exists. Pure stdlib (xml.etree) so it is unit-testable without
    docker. Glob is SCOPED to work_dir (project/cocotb_work) so it never picks
    up a Vibe-IC sim/results.xml artifact (which is JSON, not cocotb XML).
    """
    patterns = ("sim_build/*.result.xml", "*.result.xml", "results.xml")
    files, seen = [], set()
    for pat in patterns:
        for f in sorted(work_dir.glob(pat)):
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(f)
    if not files:
        return None
    total = failed = skipped = 0
    seen_cases = set()
    parsed_any = False
    for f in files:
        try:
            root = ET.parse(str(f)).getroot()
        except (ET.ParseError, OSError):
            continue  # e.g. a JSON results.xml artifact — skip, don't crash
        parsed_any = True
        for tc in root.iter("testcase"):
            dedup_key = (tc.get("classname") or "", tc.get("name") or "")
            if dedup_key in seen_cases:
                continue
            seen_cases.add(dedup_key)
            total += 1
            if tc.find("failure") is not None or tc.find("error") is not None:
                failed += 1
            elif tc.find("skipped") is not None:
                skipped += 1
    if not parsed_any:
        return None
    passed = total - failed - skipped
    return (total, passed, failed, skipped)


# The xcelium assertion-coverage gate (harness covt_report_check()/coverage_report()
# invoking Cadence imc, which reads coverage.log) cannot run under the icarus
# substitution (§3) — imc is not in the container and coverage.log is never
# produced. Detected from SCORER OUTPUT ONLY (blind rule). Generic CVDP-family
# tokens — NO project / module / host-path literal — so this stays chip-agnostic.
_COVERAGE_GATE_PATTERNS = (
    re.compile(r"coverage\.log"),
    re.compile(r"covt_report_check"),
    re.compile(r"coverage_report"),
    re.compile(r"\bimc\b"),
)


def _detect_coverage_gate(out: str):
    """Return the matched xcelium/imc coverage-gate signature (str, <=200 chars)
    when the unmeasurable-under-icarus coverage step appears in the scorer
    output, else None. Independent of _detect_harness_error: this runs even when
    tests>0 (the whole point — to surface the DISCLOSED Cat-D coverage gap on a
    PASSING functional run), whereas _detect_harness_error returns None once
    tests>0.
    """
    for pat in _COVERAGE_GATE_PATTERNS:
        mt = pat.search(out)
        if mt:
            return mt.group(0)[:200]
    return None


if __name__ == "__main__":
    main()
