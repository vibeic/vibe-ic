#!/usr/bin/env python3
"""eda_image_preflight.py — verify the CVDP scoring sim image matches the
official Dockerfile.sim tool spec BEFORE any scoring run (ORGANIC #536).

Field evidence: a self-built image carried Yosys 0.62 while the official
Dockerfile.sim pins yosys-0.40. 0.62's `stat` output format (columnar
`891 cells`) differs from the 0.40 format the harness `parse_yosys_log`
expects (`Number of cells: 891`) → every synth-gate problem false-FAILed
via `KeyError: 'Number of cells'` even though the RTL synthesized fully.
Three scoring rounds were polluted and the misdiagnosis burned two
close-loop rounds. The deviation was SILENT because the sim half of the
image (icarus/cocotb) happened to match.

This preflight runs the image and compares each tool's version against the
official spec at the MAJOR/TAG level (patch/build-string tolerance — an
icarus devel build suffix must not false-refuse). Any mismatch → REFUSE
scoring (exit 1, deviations listed).

Official spec (from the upstream cvdp-benchmark Dockerfile.sim, v1.1.0):
    iverilog  v13_0   (Icarus Verilog 13.x)
    yosys     0.40
    cocotb    2.0.1
    verilator v5.038

Exit codes:
    0  image matches the official spec
    1  ≥1 deviation (listed on stderr) — scoring must not proceed
    2  bad input / docker unavailable / image not runnable

chip-AGNOSTIC: pure tool-version comparison; no design knowledge.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

# The official Dockerfile.sim spec — (tool, expected, comparison level).
# Comparison levels: 'major' (first numeric component), 'major.minor',
# 'exact-3' (three components). Build/suffix strings are always ignored.
OFFICIAL_SPEC = {
    "iverilog": ("13", "major"),
    "yosys": ("0.40", "major.minor"),
    "cocotb": ("2.0.1", "exact-3"),
    "verilator": ("5.038", "major.minor"),
}

_PROBE_CMD = (
    "iverilog -V 2>&1 | head -1; "
    "echo '---'; yosys -V 2>&1 | head -1; "
    "echo '---'; verilator --version 2>&1 | head -1; "
    "echo '---'; python3 -c 'import cocotb; print(cocotb.__version__)' 2>&1"
)


def _extract_version(tool: str, line: str) -> Optional[str]:
    """Pull the numeric version out of a tool's banner line."""
    line = line.strip()
    if not line:
        return None
    if tool == "iverilog":
        # 'Icarus Verilog version 13.0 (devel) (s20221226-568-g62b00ee6d)'
        m = re.search(r"version\s+(\d+)[._](\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "yosys":
        # 'Yosys 0.40 (git sha1 ...)' / 'Yosys 0.62+...'
        m = re.search(r"Yosys\s+(\d+)\.(\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "verilator":
        # 'Verilator 5.038 2025-...'
        m = re.search(r"Verilator\s+(\d+)\.(\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "cocotb":
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", line)
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None
    return None


def _matches(found: str, expected: str, level: str) -> bool:
    f = found.split(".")
    e = expected.split(".")
    if level == "major":
        return f[0] == e[0]
    if level == "major.minor":
        return f[0] == e[0] and (len(e) < 2 or (len(f) > 1 and f[1] == e[1]))
    return f[:3] == e[:3]


def probe_image(image: str, runner=None) -> Tuple[int, str]:
    """Run the probe command in the image; returns (rc, combined output).
    `runner` is injectable for tests."""
    if runner is None:
        def runner(cmd):
            cp = _pr.run_best_effort(cmd, capture_output=True, text=True)
            return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
    # A probe container is still a container: one unbounded `docker run` is all
    # it takes for a tool inside to eat the host. (This gate was added earlier
    # today and this call tripped it the moment the file was renamed — the
    # ratchet keyed the exemption to the old filename.)
    import _docker_memory as _dmem  # noqa: PLC0415
    return runner(["docker", "run", "--rm", *_dmem.docker_memory_flags(),
                   "--entrypoint", "sh", image, "-c", _PROBE_CMD])


def check_versions(probe_output: str) -> Tuple[List[Dict], List[str]]:
    """Parse the 4-section probe output → ([{tool, found, expected, ok}],
    [deviation strings])."""
    sections = [s.strip() for s in probe_output.split("---")]
    order = ["iverilog", "yosys", "verilator", "cocotb"]
    results: List[Dict] = []
    deviations: List[str] = []
    for i, tool in enumerate(order):
        line = sections[i] if i < len(sections) else ""
        found = _extract_version(tool, line)
        expected, level = OFFICIAL_SPEC[tool]
        if found is None:
            results.append({"tool": tool, "found": None,
                            "expected": expected, "ok": False})
            deviations.append(f"{tool}: version not detectable from "
                              f"{line!r} (expected {expected})")
            continue
        ok = _matches(found, expected, level)
        results.append({"tool": tool, "found": found,
                        "expected": expected, "ok": ok})
        if not ok:
            deviations.append(
                f"{tool}: image has {found}, official Dockerfile.sim pins "
                f"{expected} ({level} comparison) — output formats may "
                f"differ and silently false-FAIL the harness (#536)")
    return results, deviations


# ── ORGANIC #714: OSS_PNR_IMAGE (synth) requirement preflight ───────────────
# CVDP area-opt (cid007) problems carry a synth Dockerfile whose BASE image is
# the `__OSS_PNR_IMAGE__` template variable (distinct from `__OSS_SIM_IMAGE__`).
# If the scoring driver sets only OSS_SIM_IMAGE, OSS_PNR_IMAGE defaults to the
# UNPULLABLE proprietary commercial image, the synth container never builds,
# yosys never runs, and the synth subtest FALSE-FAILS on correct RTL. This
# preflight detects the requirement and FAILS CLOSED (REFUSE) when the env is
# unset — it never hardcodes a "magic image to force a pass" (no-cheating).
# chip-AGNOSTIC: keys on the official CVDP template token, same family as the
# existing __OSS_SIM_IMAGE__ handling; no design / vendor literal.
_OSS_PNR_TEMPLATE = "__OSS_PNR_IMAGE__"
_HARNESS_SCAN_SUFFIXES = (
    ".synth", ".sim", ".mk", ".sh", ".yaml", ".yml", ".json", ".env", ".cfg")
# After `run_benchmark.py` MATERIALIZES a harness, the `__OSS_PNR_IMAGE__`
# template is already SUBSTITUTED to whatever `OSS_PNR_IMAGE` resolved to — and
# in CVDP v1.1.0 the default is the GATED proprietary `nvidia/cvdp-sim:<tag>`
# (the upstream README pins `OSS_PNR_IMAGE=nvidia/cvdp-sim:v1.0.0`). A preflight
# that only looks for the pre-substitution `__OSS_PNR_IMAGE__` token therefore
# returns "not required" on the very score dir whose synth container pulls the
# gated image → `pull access denied` → the synth subtest FALSE-FAILS on correct
# RTL (field-measured: 16/302 area-opt problems, all logged as a ~650-byte
# "TRUNCATED"). Detect the materialized gated literal too. chip-AGNOSTIC: keys on
# the official CVDP gated-image repository name, no design/vendor-SKU literal.
#
# The GATED thing is the proprietary REPO `nvidia/cvdp-sim`, regardless of how it
# is referenced — `:tag` (the pinned `:v1.0.0` default), `@sha256:<digest>`, or
# tagless (→ `:latest`). All three need auth and `pull access denied` on a
# clean-room host, so the detector keys on the repo name and treats the optional
# `:tag` / `@digest` as cosmetic. The trailing `(?![\w.\-/])` keeps a longer repo
# (`nvidia/cvdp-sim-extended`, `nvidia/cvdp-sim/sub`) from matching; the leading
# `\b` keeps `mynvidia/cvdp-sim` out while still matching a registry prefix
# (`nvcr.io/nvidia/cvdp-sim:…`).
_GATED_PNR_LITERAL = re.compile(
    r"\bnvidia/cvdp-sim(?:[:@][\w.\-]+)?(?![\w.\-/])", re.I)


def _strip_hash_comments(text: str) -> str:
    """Blank each line's `#`…EOL comment so a gated-image NAME that is merely
    MENTIONED in a comment (e.g. a materialized Dockerfile documenting the gated
    default it replaced) is not mistaken for the ACTIVE base image. A real base
    reference (`FROM …`, `image: …`, `OSS_PNR_IMAGE=…`) never sits after a `#`
    (a leading `#` comments the whole line), so this can only drop comment text,
    never an active reference. Dockerfile / shell / make / yaml / env / cfg all
    use `#`; JSON has none, so this is a no-op there."""
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def _has_gated_pnr_literal(text: str) -> bool:
    """True iff the COMMENT-STRIPPED text references the gated proprietary
    `nvidia/cvdp-sim` base image as an ACTIVE reference. A `#`-comment mention of
    the image name is NOT a pull and must not REFUSE a correct OSS harness."""
    return bool(_GATED_PNR_LITERAL.search(_strip_hash_comments(text)))


# --------------------------------------------------------------------------- #
# Harness compose WORKING_DIR normalization (read-only-build-dir false-FAIL).
# --------------------------------------------------------------------------- #
# A CVDP harness `docker-compose.yml` mounts `./src:/src:ro` (read-only) and runs
# `pytest /src/test_runner.py`. cocotb's `runner.build()` creates its `sim_build/`
# directory RELATIVE TO THE WORKING DIRECTORY; when the compose service declares
# `working_dir: /code/rundir` (the scorer mounts `rundir` writable) the build lands
# in a writable dir and the test runs. A harness whose compose OMITS `working_dir`
# leaves the cwd at the image default, so cocotb tries to mkdir `sim_build` under
# the read-only `/src` mount → `OSError: [Errno 30] Read-only file system:
# '/src/sim_build'` → pytest exits nonzero → the WHOLE problem false-FAILs even
# though the RTL is correct (field-measured on fibonacci_series_0001: the DUT
# PASSes 2/2 when a writable cwd is provided, FAILs at collection otherwise).
#
# This is a harness PACKAGING gap, not a DUT defect: sibling problems (sorter,
# dice) ship `working_dir: /code/rundir` and score fine. The normalizer injects
# the same `working_dir` into any service that lacks one, making the OSS score
# reproduce the writable-build-dir the well-formed harnesses already get.
# chip-AGNOSTIC: a pure compose-env fix; no design/vendor knowledge.
_RUNDIR_WORKDIR = "/code/rundir"
_COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml")


def _compose_service_blocks(text: str) -> bool:
    """Cheap check: does this look like a compose file with a `services:` map and
    at least one `command:`/`image:` service (i.e. a harness runner)?"""
    return "services:" in text and ("command" in text or "image:" in text)


def compose_missing_working_dir(problem_dir: Path) -> List[Path]:
    """Return every harness compose file under `problem_dir` that declares a
    runnable service but NO `working_dir:` — the read-only-build-dir false-FAIL
    shape. Pure text scan (no YAML dependency); a `working_dir` anywhere in the
    file is treated as already-set (compose files here carry one service)."""
    hits: List[Path] = []
    if not problem_dir.is_dir():
        return hits
    for f in sorted(problem_dir.rglob("*")):
        if not (f.is_file() and f.name in _COMPOSE_NAMES):
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        if _compose_service_blocks(txt) and not re.search(
                r"^\s*working_dir\s*:", txt, re.M):
            hits.append(f)
    return hits


def inject_working_dir(text: str, workdir: str = _RUNDIR_WORKDIR) -> str:
    """Return the compose text with `working_dir: <workdir>` added to every
    service that lacks one. A service is a 4-space-indented `image:`/`command:`
    key under `services:`; the new line is inserted just before the service's
    `command:` (or `image:` if no command) at the same indent. Idempotent: a file
    that already has a `working_dir` is returned unchanged."""
    if re.search(r"^\s*working_dir\s*:", text, re.M):
        return text
    lines = text.splitlines(keepends=True)
    # find the FIRST service-level `image:`/`env_file:`/`command:` key (6-space
    # indent under `  service:` which is 2-space) and insert before it.
    anchor_re = re.compile(r"^(\s+)(image|command|env_file)\s*:", )
    for i, ln in enumerate(lines):
        m = anchor_re.match(ln)
        if m:
            indent = m.group(1)
            lines.insert(i + 1 if m.group(2) == "image" else i,
                         f"{indent}working_dir : {workdir}\n")
            return "".join(lines)
    return text


# A harness compose whose command does `pip install <pkg> && pytest …` fails under
# the OSS scorer because the harness container runs as `--user $UID:$GID` (non-root)
# against a PEP-668 externally-managed system Python: bare `pip install` REFUSES
# (`error: externally-managed-environment`), the `&&` short-circuits, pytest never
# runs, and the WHOLE problem false-FAILs on correct RTL (field-measured on
# fibonacci_series_0001 — the ONLY no_commercial problem with a `pip install` in its
# harness command). The fix adds `--break-system-packages`, the supported way to
# install into the system env, idempotently. chip-AGNOSTIC: a pip-invocation env fix.
_PIP_INSTALL_RE = re.compile(
    r"\bpip(?:3)?\s+install\s+(?!--break-system-packages\b)")


def compose_pip_needs_break_system(problem_dir: Path) -> List[Path]:
    """Harness compose files whose command runs a bare `pip install` (no
    `--break-system-packages`) — the PEP-668 non-root false-FAIL shape."""
    hits: List[Path] = []
    if not problem_dir.is_dir():
        return hits
    for f in sorted(problem_dir.rglob("*")):
        if not (f.is_file() and f.name in _COMPOSE_NAMES):
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        if _PIP_INSTALL_RE.search(txt):
            hits.append(f)
    return hits


def inject_pip_break_system(text: str) -> str:
    """Add `--break-system-packages` to every bare `pip install` in the text.
    Idempotent (an already-fixed invocation is not matched)."""
    return _PIP_INSTALL_RE.sub(
        lambda m: m.group(0) + "--break-system-packages ", text)


def normalize_compose_working_dir(problem_dir: Path) -> List[Path]:
    """FIX every harness compose under `problem_dir` whose scoring would false-FAIL
    on correct RTL because of a read-only build dir (missing `working_dir`) AND/OR a
    PEP-668 non-root `pip install` (missing `--break-system-packages`). Applies both
    fixes idempotently; returns the list of files changed."""
    changed: List[Path] = []
    targets = set(compose_missing_working_dir(problem_dir)) | \
        set(compose_pip_needs_break_system(problem_dir))
    for f in sorted(targets):
        try:
            txt = f.read_text(errors="ignore")
            new = inject_pip_break_system(inject_working_dir(txt))
            if new != txt:
                f.write_text(new)
                changed.append(f)
        except OSError:
            continue
    return changed


def compose_needs_env_fix(problem_dir: Path) -> List[Path]:
    """Union of the two false-FAIL shapes (missing working_dir OR bare pip install)."""
    return sorted(set(compose_missing_working_dir(problem_dir)) |
                  set(compose_pip_needs_break_system(problem_dir)))


def harness_requires_pnr_image(problem_dir: Path) -> Tuple[bool, List[Path]]:
    """True iff any harness file under `problem_dir` references the
    `__OSS_PNR_IMAGE__` template (a pre-materialization area-opt / synth problem)
    OR a MATERIALIZED gated `nvidia/cvdp-sim:<tag>` base image (the template
    already substituted to the proprietary default). Returns (required, [files…]).
    Scans only cheap harness-shaped files."""
    hits: List[Path] = []
    if not problem_dir.is_dir():
        return False, hits
    for f in sorted(problem_dir.rglob("*")):
        if not f.is_file():
            continue
        if not (f.name.startswith("Dockerfile")
                or f.suffix in _HARNESS_SCAN_SUFFIXES):
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        if _OSS_PNR_TEMPLATE in txt or _has_gated_pnr_literal(txt):
            hits.append(f)
    return (len(hits) > 0), hits


def _image_pullable(image: str, runner=None) -> Optional[bool]:
    """Best-effort: True if the image is present locally or its manifest is
    reachable; False if a CLEAR not-found; None if undeterminable (no docker /
    network error) — None must NOT trigger a false-refuse."""
    if shutil.which("docker") is None:
        return None
    if runner is None:
        def runner(cmd):
            return _pr.run_best_effort(cmd, capture_output=True, text=True)
    try:
        if runner(["docker", "image", "inspect", image]).returncode == 0:
            return True
        r = runner(["docker", "manifest", "inspect", image])
        return True if r.returncode == 0 else False
    except Exception:
        return None


# ── ORGANIC (run_v1239_converge) — DETERMINISTIC sim-hang watchdog env ──────
# A handful of CVDP problems HANG inside cocotb with no watchdog (a non-advancing
# sim never returns), so a scoring run STALLS until a human `docker kill`s the
# container. The official harness ALREADY honours DOCKER_TIMEOUT / TASK_TIMEOUT
# (read from os.environ via its ConfigManager, defaults 600s / 300s); the gap is
# that our scoring DRIVER did not pin them, so the kill was manual.
#
# This is a ROBUSTNESS / reproducibility fix, NOT a score lever: the watchdog
# only AUTOMATES the kill of an already-doomed hung sim. A hung DUT is a genuine
# bug and still scores as a FAIL — the timeout merely makes that FAIL
# deterministic and unattended. The values are set GENEROUSLY (the harness's own
# defaults, ≈ the manual ~8-min kill threshold) so the watchdog changes ZERO
# existing pass/fail verdicts — a passing sim finishes in well under the budget.
#
# chip-AGNOSTIC: pure scoring-infrastructure env; no design / vendor knowledge.
_SCORING_WATCHDOG_ENV: Dict[str, str] = {
    # per-container hard cap (the official ConfigManager default is 600).
    "DOCKER_TIMEOUT": "600",
    # per-task (cocotb test) cap (the official default is 300); a sim that has
    # not advanced in 300s is hung — a generous budget vs the seconds a real
    # functional test takes.
    "TASK_TIMEOUT": "300",
}


def recommended_scoring_env() -> Dict[str, str]:
    """The deterministic-watchdog environment a CVDP scoring driver SHOULD export
    before invoking the official `run_benchmark.py`, so a hung cocotb sim becomes
    an UNATTENDED timeout-FAIL instead of a manual `docker kill` stall. Returns a
    fresh dict (caller may merge into os.environ / a shell export block). The
    values are the harness's own generous defaults, chosen to be verdict-neutral:
    they only bound a non-advancing sim, never a passing one."""
    return dict(_SCORING_WATCHDOG_ENV)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP scoring-image preflight (#536 sim-image tool-spec "
                    "+ #714 OSS_PNR_IMAGE synth requirement).")
    ap.add_argument("--image", default=None,
                    help="the OSS_SIM_IMAGE docker tag to verify (#536)")
    ap.add_argument("--problem-dir", default=None,
                    help="a CVDP problem dir to scan for an OSS_PNR_IMAGE "
                         "(area-opt synth) requirement (#714)")
    ap.add_argument("--fix-compose-workdir", action="store_true",
                    help="inject `working_dir: /code/rundir` into any harness "
                         "compose under --problem-dir that lacks one (fixes the "
                         "read-only-build-dir false-FAIL); requires --problem-dir")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    ap.add_argument("--print-scoring-env", action="store_true",
                    help="print the deterministic sim-hang watchdog env "
                         "(DOCKER_TIMEOUT/TASK_TIMEOUT) as `export K=V` lines a "
                         "scoring driver can `eval`/source before run_benchmark.py "
                         "— so a hung cocotb sim is an unattended timeout-FAIL "
                         "instead of a manual docker-kill stall (verdict-neutral)")
    args = ap.parse_args(argv)

    # The watchdog-env emit is a standalone utility (no image/problem-dir needed).
    if args.print_scoring_env:
        for k, v in recommended_scoring_env().items():
            print(f"export {k}={v}")
        return 0

    if not args.image and not args.problem_dir:
        print("ERROR: pass --image and/or --problem-dir", file=sys.stderr)
        return 2

    verdict: Dict = {}
    refuse = False
    deviations: List[str] = []

    # ── #536: sim-image tool-spec check (only when --image given) ──
    if args.image:
        if shutil.which("docker") is None:
            print("ERROR: docker not available — cannot verify the sim image; "
                  "refusing to bless scoring (#536)", file=sys.stderr)
            return 2
        rc, out = probe_image(args.image)
        if rc != 0 and not out.strip():
            print(f"ERROR: image {args.image!r} not runnable (rc={rc})",
                  file=sys.stderr)
            return 2
        results, sim_dev = check_versions(out)
        verdict.update({
            "image": args.image,
            "official_spec": {k: v[0] for k, v in OFFICIAL_SPEC.items()},
            "tools": results,
        })
        deviations.extend(sim_dev)

    # ── harness compose env scan / fix (when --problem-dir) ──
    # Two false-FAIL shapes a harness compose can carry under the OSS scorer's
    # non-root / read-only env: a missing `working_dir` (read-only build dir) and a
    # bare `pip install` (PEP-668 externally-managed). Both make a CORRECT-RTL
    # problem score as FAIL; `--fix-compose-workdir` repairs both idempotently.
    if args.problem_dir:
        pdir = Path(args.problem_dir)
        if args.fix_compose_workdir:
            fixed = normalize_compose_working_dir(pdir)
            verdict["compose_env_fixed"] = [str(f) for f in fixed]
        else:
            needs = compose_needs_env_fix(pdir)
            verdict["compose_needs_env_fix"] = [str(f) for f in needs]
            if needs:
                deviations.append(
                    f"{len(needs)} harness compose file(s) would false-FAIL under "
                    f"the OSS scorer (missing `working_dir` and/or a bare "
                    f"`pip install`); pass --fix-compose-workdir to repair")

    # ── #714: OSS_PNR_IMAGE (synth) requirement scan (when --problem-dir) ──
    if args.problem_dir:
        required, hit_files = harness_requires_pnr_image(Path(args.problem_dir))
        verdict["oss_pnr_image_required"] = required
        if required:
            verdict["oss_pnr_image_template_files"] = [
                str(f) for f in hit_files]
            # A MATERIALIZED harness already baked the gated `nvidia/cvdp-sim`
            # literal into its synth Dockerfile — the env no longer matters for
            # THIS dir; it will pull the gated image and false-fail. Flag it
            # regardless of OSS_PNR_IMAGE so a post-materialization preflight
            # (the realistic check point) catches the block #714 only caught
            # pre-materialization.
            baked_gated = any(
                _has_gated_pnr_literal(f.read_text(errors="ignore"))
                for f in hit_files if f.is_file())
            verdict["oss_pnr_image_materialized_gated"] = baked_gated
            pnr = (os.environ.get("OSS_PNR_IMAGE") or "").strip()
            verdict["oss_pnr_image_set"] = bool(pnr)
            if baked_gated:
                # The fix is to RE-MATERIALIZE the harness from the OSS image —
                # NOT to retag the OSS image to the gated name. Retagging is
                # rejected on two counts: (1) this gate intentionally REFUSEs on
                # the baked gated literal regardless of local pullability, so a
                # retag would never clear it; (2) a clean-room / OSS-reproducible
                # score must build from the verified open base, so depending on a
                # locally-retagged gated name defeats the reproducibility this
                # gate exists to enforce.
                deviations.append(
                    "area-opt synth harness has a MATERIALIZED gated "
                    "`nvidia/cvdp-sim` base image baked into its synth "
                    "Dockerfile — that container pulls the proprietary image "
                    "(`pull access denied`) and the synth gate FALSE-FAILS on "
                    "correct RTL (#714 round-2: the __OSS_PNR_IMAGE__ template "
                    "was already substituted to the gated default). RE-MATERIALIZE "
                    "the harness with OSS_PNR_IMAGE set to a verified OSS PnR "
                    "image so the synth container builds from a pullable open "
                    "base.")
            elif not pnr:
                deviations.append(
                    "area-opt synth harness references __OSS_PNR_IMAGE__ but "
                    "OSS_PNR_IMAGE is UNSET — the synth container would default "
                    "to the unpullable proprietary image and the synth gate "
                    "would FALSE-FAIL (#714). Set OSS_PNR_IMAGE to the verified "
                    "OSS PnR image before scoring.")
            else:
                pull = _image_pullable(pnr)
                verdict["oss_pnr_image_pullable"] = (
                    "unverified-no-docker" if pull is None else pull)
                if pull is False:
                    deviations.append(
                        f"OSS_PNR_IMAGE={pnr!r} is set but NOT pullable / "
                        f"present — synth container build would fail (#714).")

    if deviations:
        refuse = True
    verdict["deviations"] = deviations
    verdict["verdict"] = "REFUSE" if refuse else "PASS"

    text = json.dumps(verdict, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        import _atomic_artefact as _atomic  # noqa: PLC0415
        _atomic.write_text(Path(args.json), text + "\n")
    print(text)
    if refuse:
        for d in deviations:
            print(f"DEVIATION: {d}", file=sys.stderr)
        print("REFUSING to score: scoring-environment preflight failed "
              "(#536 sim-image spec and/or #714 OSS_PNR_IMAGE) — results "
              "would not be comparable.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
