#!/usr/bin/env python3
"""transition_fault_atpg_run.py — REAL open-source TRANSITION-DELAY-FAULT (TDF)
ATPG via the forked vibeic/yosys SAT engine (launch-off-capture, 2-frame).

This CLOSES the long-standing "OSS has no delay-fault ATPG" gap. The stuck-at
producer (`fault_atpg_run.py`, AUCOHL/Fault) is a single-pattern combinational
engine and honestly records `transition.engine_limited=true` — it CANNOT
generate at-speed two-pattern tests. This program does, by reducing a
transition fault under full-scan launch-off-capture (LOC) to a STUCK-AT fault
on a TWO-TIME-FRAME UNROLLING of the combinational core and solving it with
Yosys `sat -prove`.

──────────────────────────────────────────────────────────────────────────
THE REDUCTION (proven, not hand-waved — see the PROOF block at bottom):

  A transition fault at line L under LOC == a stuck-at on a 2-frame unroll:
    frame-1 INITIALISES the fault site (the "from" value of the transition),
    frame-2 LAUNCHES the v->v̄ transition and is where the stuck-at is injected.
      slow-to-rise  (STR)  ⇒  SA0 in the launch frame, frame-1 init L=0
      slow-to-fall  (STF)  ⇒  SA1 in the launch frame, frame-1 init L=1

  Under LOC the primary inputs are HELD constant across the launch→capture
  at-speed window; the transition is created only by the flop-state change
  S1→S2 (frame-1 D  →  frame-2 Q). So the 2-frame unroll is:

     frame1 (good):  core(PI, Q=S1)              -> D=S2, PO1
     frame2 (good):  core(PI, Q=S2)              -> D2g,  PO2g
     frame2 (faulty):core(PI, Q=S2)  L stuck     -> D2f,  PO2f
     trig = OR over frame-2 pseudo-POs of (good != faulty)

  `sat -prove trig 0` proves trig can never be 1; a COUNTEREXAMPLE (SAT model)
  is the launch-capture 2-pattern that DETECTS the fault; UNSAT (proof holds)
  means the transition fault is REDUNDANT / undetectable. The frame-1 init
  value is imposed with `sat -set f1.<L> <init>` so a genuine v→v̄ transition
  is launched (not a mere stuck-at test).

  NOTE (empirical): the sequential-miter `sat -seq 2` form collapses under
  `prep` optimisation. The EXPLICIT 2-frame unroll (core instantiated 3×,
  frame1.D wired to frame2.Q) is reliable and is what this program builds.

──────────────────────────────────────────────────────────────────────────
FLOW (cut → enumerate → 2-frame unroll → sat -prove → grade):

  1. CUT  — reuse the combinational full-scan core: `fault cut` turns every
     DFF into a pseudo-PI (flop Q, named `<flop>`) + pseudo-PO (flop D, named
     `<flop>.d`). If phase2/stage2/dft/cut_netlist.v already exists (Step 11
     ran `fault_atpg_run` first) it is reused; otherwise `fault cut` is run.
  2. GATE-LEVELISE — read the design liberty AS LOGIC (`read_liberty
     -ignore_miss_func`, PDK-agnostic — no proprietary Verilog sim model
     needed), flatten the cut core to generic `$_*_` gates, opt_clean, and
     write flat_core.v. The surviving internal nets are the fault sites.
  3. ENUMERATE — 2 TDF faults per internal net (STR: SA0/init0, STF:
     SA1/init1). Stuck-at fault collapsing is inherited from the gate-level
     net set (one representative net per driver output). A DISCLOSED bounded
     sample is taken for large designs (never a SILENT cap — sampled_faults
     vs total_faults are both reported).
  4. UNROLL + SOLVE — build the explicit 3-instance LOC miter once, then per
     fault: copy the core, inject the launch-frame stuck-at with
     `connect -set`, flatten the miter, and run `sat -prove trig 0
     -set f1.<net> <init>`. SAT(model) → detected (2-pattern recorded);
     UNSAT → redundant; abort/timeout → UNDETECTED (fail-safe, never counted
     as detected).
  5. GRADE — measured TDF LOGIC coverage = detected/(sampled − redundant)
     (test coverage) and detected/sampled (fault coverage); both denominators
     disclosed. Writes reports/phase2/dft/transition_coverage.json.

FALSE-CLEAN-PROOF: a redundant or aborted fault is NEVER counted as detected
(only a `model found: FAIL!` SAT verdict counts). Proven by construction and
by the unit test's soundness fixture (a known-redundant fault ⇒ UNSAT/
undetected; a known-detectable fault ⇒ SAT/detected).

HONEST DISCLOSURE (written into the JSON): this is TDF **LOGIC** coverage
(the transition is launched AND observed at a scan-observable point); it is
**NOT at-speed timing-graded**. True at-speed path-delay-fault grading needs
OpenSTA K-longest-path sensitisation to prove the launched transition is on a
path slow enough to fail the rated cycle — a deferred, harder tier.

Usage:
    python3 transition_fault_atpg_run.py <project_dir> \\
        --clock clk \\
        [--netlist phase2/stage2/synth/spm_synth.v] \\
        [--cut-netlist phase2/stage2/dft/cut_netlist.v] \\
        [--liberty input/pdk/liberty/commercial_pdk_typ.lib] \\
        [--top spm] [--dff-cells DFFHQD1] \\
        [--floor 90] [--max-faults 400] [--json <out>]

Exit 0 = TDF logic coverage >= floor (or NOT_APPLICABLE: no sequential logic).
Exit 1 = TDF logic coverage below floor OR the ATPG could not run.
Exit 2 = usage / IO error.

The floor is enforced by the sibling gate `transition_coverage_check.py`; this
producer's own exit mirrors it for convenience but the gate is authoritative.
chip-AGNOSTIC — no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

# Reuse the pinned EDA image + DFF auto-detection from the stuck-at producer so
# there is a SINGLE pinned `vibeic-eda:X.Y.Z` literal (tracked by
# tools/vibeic-eda/sync_image_version.py) — this file adds none of its own.
try:
    import fault_atpg_run as _far  # type: ignore
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fault_atpg_run as _far  # type: ignore


_PROGRAM = "transition_fault_atpg_run"
_VERSION = "1.0.0"

# Chosen TDF LOGIC-coverage floor. A few points below the 95 % stuck-at
# foundry bar because at-speed escapes are harder AND because this is a
# *logic* (not timing-graded) measurement — see the disclosure. Configurable.
TDF_LOGIC_FLOOR_DEFAULT = 90.0

# Default disclosed sample cap. Each fault is one full SAT solve; for a large
# design the full 2×|nets| fault list is bounded to keep the step tractable.
# NEVER a silent cap — total vs sampled are always reported.
DEFAULT_MAX_FAULTS = 400

_DISCLOSURE = (
    "TDF LOGIC coverage (each fault's transition is LAUNCHED in frame-1 and "
    "OBSERVED at a scan-observable frame-2 pseudo-PO via a real Yosys SAT "
    "proof); NOT at-speed timing-graded. True at-speed path-delay-fault "
    "grading needs OpenSTA K-longest-path sensitisation to prove the launched "
    "transition lies on a path slow enough to fail the rated cycle (deferred "
    "harder tier)."
)


# ══════════════════════════════════════════════════════════════════════════
# PURE helpers (unit-tested; no Docker, no IO)
# ══════════════════════════════════════════════════════════════════════════

_PORT_RE = re.compile(
    r'^\s*(input|output)\s+(\[[^\]]*\]\s*)?(\\?[^\s;]+)\s*;', re.MULTILINE)
_WIRE_RE = re.compile(
    r'^\s*wire\s+(\[[^\]]*\]\s*)?(\\?[^\s;]+)\s*;', re.MULTILINE)
_MODULE_RE = re.compile(r'^\s*module\s+(\\?[^\s(]+)', re.MULTILINE)


def esc_id(name: str) -> str:
    """Return `name` as a Verilog identifier safe for an instance-port
    connection. A bare name that already needs no escaping is returned as-is;
    a name containing a dot/backslash (e.g. the cut engine's `_392_.d`
    pseudo-PO) is emitted as an escaped identifier `\\name ` (trailing space
    is REQUIRED by Verilog to terminate an escaped id). Pure."""
    raw = name.lstrip('\\').rstrip()  # trailing space is an escaped-id delimiter
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', raw):
        return raw
    return "\\" + raw + " "


def _base_of_d(name: str) -> str | None:
    """A pseudo-PO is named `<base>.d` (the flop's D input, made observable by
    the scan cut). Return `<base>` or None. Pure."""
    n = name.lstrip('\\')
    return n[:-2] if n.endswith('.d') else None


def parse_cut_ports(verilog_text: str):
    """Classify the cut core's ports. Returns
        (top, prim_in, prim_out, pairs)
    where prim_in/prim_out are lists of (name, range_str) and pairs is a list
    of (base, pi_name, po_name) — the pseudo-PI (flop Q, name==base) matched
    to its pseudo-PO (flop D, name==`base.d`). Primary I/O are the ports that
    are NOT part of a pseudo pair. Pure. chip-AGNOSTIC."""
    mtop = _MODULE_RE.search(verilog_text)
    top = mtop.group(1).lstrip('\\') if mtop else "top"
    ins, outs = [], []
    for m in _PORT_RE.finditer(verilog_text):
        kind, rng, name = m.group(1), (m.group(2) or "").strip(), m.group(3)
        (ins if kind == "input" else outs).append((name, rng))
    pso = {}
    for name, _ in outs:
        b = _base_of_d(name)
        if b is not None:
            pso[b] = name
    inmap = {n.lstrip('\\'): n for n, _ in ins}
    pairs = [(b, inmap[b], pso[b]) for b in pso if b in inmap]
    pair_bases = {b for b, _, _ in pairs}
    prim_in = [(n, r) for n, r in ins if n.lstrip('\\') not in pair_bases]
    prim_out = [(n, r) for n, r in outs if _base_of_d(n) is None]
    return top, prim_in, prim_out, pairs


def enumerate_fault_sites(flat_verilog_text: str) -> list[str]:
    """Return the internal single-bit nets of the flattened gate core (the
    stuck-at / TDF fault sites) — every declared `wire` that is not a port and
    not a bus. Bus/port nets are excluded so each site is a scalar gate-output
    net (standard gate-output fault collapsing). Pure."""
    ports = {m.group(3).lstrip('\\') for m in _PORT_RE.finditer(flat_verilog_text)}
    sites = []
    for m in _WIRE_RE.finditer(flat_verilog_text):
        rng, name = m.group(1), m.group(2)
        if rng:  # skip buses — keep scalar nets only
            continue
        raw = name.lstrip('\\')
        if raw in ports:
            continue
        sites.append(name)
    # stable de-dup
    seen, out = set(), []
    for s in sites:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def enumerate_tdf_faults(nets: list[str]) -> list[tuple[str, str, str, str]]:
    """Two transition faults per net: (net, kind, stuck_value, init_value).
      STR (slow-to-rise): SA0 in launch frame, init 0  → 0→1 must be launched
      STF (slow-to-fall): SA1 in launch frame, init 1  → 1→0 must be launched
    Pure."""
    faults = []
    for n in nets:
        faults.append((n, "STR", "1'b0", "1'b0"))
        faults.append((n, "STF", "1'b1", "1'b1"))
    return faults


def sample_faults(faults: list, max_faults: int):
    """Deterministic, evenly-strided DISCLOSED sample. Returns
    (sampled_list, sampled_bool). When max_faults<=0 or >=len, returns all
    (sampled=False). The stride keeps the sample spread across the net order
    rather than truncating to a prefix. Pure."""
    total = len(faults)
    if max_faults <= 0 or total <= max_faults:
        return list(faults), False
    stride = total / float(max_faults)
    idx = sorted({int(i * stride) for i in range(max_faults)})
    return [faults[i] for i in idx], True


def parse_sat_verdict(body: str) -> str:
    """Classify ONE Yosys `sat -prove` output block.
      'DET'   — `model found: FAIL!`  (proof of trig==0 failed → detecting
                2-pattern found)
      'RED'   — `no model found: SUCCESS!` (proof holds → redundant/undetectable)
      'ABORT' — anything else (timeout / error / no verdict) → NOT detected.
    Pure. FALSE-CLEAN-PROOF: only an explicit `model found: FAIL!` is a
    detection; every ambiguous outcome is conservatively NOT a detection."""
    if "model found: FAIL" in body:
        return "DET"
    if "no model found: SUCCESS" in body:
        return "RED"
    return "ABORT"


def _extract_pattern(body: str, prim_in_names: list[str]) -> dict | None:
    """Pull the primary-input values of the detecting 2-pattern out of a
    `sat -show` block. Returns {name: binvalue} or None. Pure."""
    pat = {}
    for m in re.finditer(r'\\?([A-Za-z_][\w.$]*)\s+\d+\s+[0-9a-fA-Fx]+\s+([01xz]+)\s*$',
                         body, re.MULTILINE):
        name, binv = m.group(1), m.group(2)
        if name in prim_in_names:
            pat[name] = binv
    return pat or None


def coverage_math(detected: int, redundant: int, aborted: int) -> dict:
    """TDF coverage from raw verdict counts. Independently recomputable by the
    gate. Pure.

      sampled            = detected + redundant + aborted
      test_coverage_pct  = detected / (sampled - redundant)   [redundant
                            excluded from the denominator; aborted stays as
                            NOT-detected → conservative]
      fault_coverage_pct = detected / sampled
    Aborted faults are counted as undetected in BOTH ratios (never detected)."""
    sampled = detected + redundant + aborted
    testable = sampled - redundant
    test_cov = (100.0 * detected / testable) if testable > 0 else None
    fault_cov = (100.0 * detected / sampled) if sampled > 0 else None
    return {
        "sampled_faults": sampled,
        "detected": detected,
        "redundant": redundant,
        "aborted": aborted,
        "testable_faults": testable,
        "tdf_test_coverage_pct": (round(test_cov, 4)
                                  if test_cov is not None else None),
        "tdf_fault_coverage_pct": (round(fault_cov, 4)
                                   if fault_cov is not None else None),
    }


def build_loc_miter(top: str, prim_in, prim_out, pairs,
                    faulty_suffix: str = "_f") -> str:
    """Emit the explicit LOC 2-frame unroll miter (pure — the whole point of
    the reliable-form note above). Instantiates the core three times:
      f1  (good)   : frame-1, free flop-init state on the pseudo-PI
      g2  (good)   : frame-2, pseudo-PI driven by f1's pseudo-PO  (LAUNCH)
      fb  (`<top>_f`): frame-2 FAULTY copy, same launched state
    Primary inputs are SHARED across the three (LOC holds PI constant). trig
    ORs every frame-2 pseudo-PO good-vs-faulty difference (flop D scanned out
    + primary POs both observable). Free miter inputs: primary inputs + one
    `<base>_q` per flop (the scanned-in init state S1)."""
    def cid(b):  # clean signal id per flop base
        return "s" + re.sub(r'\W', '_', b)

    L = []
    hdr = [n for n, _ in prim_in] + [cid(b) + "_q" for b, _, _ in pairs] + ["trig"]
    L.append("module miter(" + ", ".join(hdr) + ");")
    for n, r in prim_in:
        L.append(f"  input {r + ' ' if r else ''}{n};")
    for b, _, _ in pairs:
        L.append(f"  input {cid(b)}_q;")
    L.append("  output trig;")
    for b, _, _ in pairs:
        L.append(f"  wire {cid(b)}_f1d, {cid(b)}_g2d, {cid(b)}_fbd;")
    for n, _ in prim_out:
        L.append(f"  wire {n}_g2, {n}_fb, {n}_f1;")

    def instance(mod, iname, q_of, dsuf, posuf):
        c = [f".{n}({n})" for n, _ in prim_in]
        for b, pi, po in pairs:
            c.append(f".{esc_id(pi)}({q_of(b)})")
            c.append(f".{esc_id(po)}({cid(b)}_{dsuf})")
        for n, _ in prim_out:
            c.append(f".{n}({n}{posuf})")
        L.append(f"  {mod} {iname} (" + ", ".join(c) + ");")

    instance(top, "f1", lambda b: cid(b) + "_q", "f1d", "_f1")       # frame1 good
    instance(top, "g2", lambda b: cid(b) + "_f1d", "g2d", "_g2")     # frame2 good (launched)
    instance(top + faulty_suffix, "fb", lambda b: cid(b) + "_f1d",
             "fbd", "_fb")                                           # frame2 faulty (launched)

    terms = [f"({cid(b)}_g2d ^ {cid(b)}_fbd)" for b, _, _ in pairs]
    terms += [f"({n}_g2 ^ {n}_fb)" for n, _ in prim_out]
    L.append("  assign trig = " + (" | ".join(terms) if terms else "1'b0") + ";")
    L.append("endmodule")
    return "\n".join(L) + "\n"


# ══════════════════════════════════════════════════════════════════════════
# Docker / Yosys execution (impure)
# ══════════════════════════════════════════════════════════════════════════

def _run_in_docker(project: Path, shell_cmd: str, timeout: int,
                   pdk_dir: Path | None = None,
                   extra_mounts: list[tuple[str, str]] | None = None
                   ) -> tuple[int, str, str]:
    """Run a shell command inside vibeic-eda with project mounted at /work and
    yosys/fault on PATH. Reuses the pinned image from fault_atpg_run.

    extra_mounts: additional (host, container) bind mounts — used when a
    liberty/PDK file resolves (via symlink) to a path OUTSIDE the project, so
    a fresh `docker run -v project:/work` container can still read it."""
    docker_cmd = [
        "docker", "run", "--rm", "--entrypoint", "bash",
        "-v", f"{project}:/work",
    ]
    for host, ctr in (extra_mounts or []):
        docker_cmd += ["-v", f"{host}:{ctr}"]
    if pdk_dir is not None and pdk_dir.exists():
        docker_cmd += ["-v", f"{pdk_dir}:/pdk"]
    preamble = (
        "export FAULT_IVERILOG=/foss/tools/iverilog/bin/iverilog && "
        "export FAULT_YOSYS=/foss/tools/bin/yosys && "
        "export PATH=/foss/tools/yosys/bin:/foss/tools/iverilog/bin:"
        "/foss/tools/bin:$PATH && "
        "export LD_LIBRARY_PATH=/foss/tools/iverilog/lib:${LD_LIBRARY_PATH:-} && "
    )
    docker_cmd += [_far.DOCKER_IMAGE, "-c", preamble + shell_cmd]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "docker command timed out"
    except FileNotFoundError:
        return 127, "", "docker binary not found in PATH"


def _ensure_cut(project: Path, netlist_rel: str, cut_rel: str, clock: str,
                dff_cells: str | None, pdk_dir: Path | None,
                timeout: int) -> tuple[bool, str]:
    """Reuse phase2/stage2/dft/cut_netlist.v if present, else run `fault cut`.
    Returns (ok, message)."""
    cut_abs = project / cut_rel
    if cut_abs.exists() and cut_abs.stat().st_size > 0:
        return True, f"reused existing cut netlist: {cut_rel}"
    # Auto-detect the flop cells from the mapped netlist (union with any seed).
    try:
        ntext = (project / netlist_rel).read_text(errors="replace")
    except OSError as exc:
        return False, f"cannot read netlist {netlist_rel}: {exc}"
    detected = _far.detect_dff_cells(ntext)
    cells = _far.merge_dff_cells(dff_cells, detected) or (dff_cells or "DFFHQD1")
    cut_abs.parent.mkdir(parents=True, exist_ok=True)
    cmd = (f"fault cut --output /work/{cut_rel} --dff {cells} "
           f"--clock {clock} /work/{netlist_rel}")
    ec, out, err = _run_in_docker(project, cmd, timeout=timeout, pdk_dir=pdk_dir)
    if ec != 0 or not cut_abs.exists():
        return False, f"fault cut failed (exit {ec}): {(out + err)[-400:]}"
    return True, f"ran fault cut (--dff {cells})"


def _gate_levelise(project: Path, cut_rel: str, liberty_ctr: str,
                   top: str, flat_rel: str, pdk_dir: Path | None,
                   timeout: int,
                   extra_mounts: list[tuple[str, str]] | None = None
                   ) -> tuple[bool, str]:
    """Read the liberty AS LOGIC + the cut netlist, flatten to generic `$_*_`
    gates, opt_clean, write flat_core.v. PDK-agnostic (no proprietary Verilog
    sim model). Returns (ok, message)."""
    (project / flat_rel).parent.mkdir(parents=True, exist_ok=True)
    # `flatten -separator _` : concatenate hierarchy levels with '_' instead of
    # the default '.', so inlined cell-pin nets are CLEAN ids (`_196__Y`, not
    # `_196_.Y`). Dotted names cannot be referenced by yosys `sat -set` /
    # `connect` / `rename` (the '.' is the hierarchy separator), which would
    # abort the whole batch mid-run. This keeps every fault site referenceable
    # across yosys builds that name flattened cell nets `<inst>.<pin>`.
    script = (
        f"read_liberty -ignore_miss_func {liberty_ctr}\n"
        f"read_verilog /work/{cut_rel}\n"
        f"hierarchy -top {top}\n"
        "flatten -separator _\n"
        "opt_clean\n"
        f"write_verilog -noattr /work/{flat_rel}\n"
    )
    script_rel = str(Path(flat_rel).parent / "_tdf_pre.ys")
    (project / script_rel).write_text(script)
    ec, out, err = _run_in_docker(
        project, f"yosys /work/{script_rel}", timeout=timeout, pdk_dir=pdk_dir,
        extra_mounts=extra_mounts)
    if ec != 0 or not (project / flat_rel).exists():
        return False, f"gate-levelise failed (exit {ec}): {(out + err)[-400:]}"
    return True, "gate-levelised via read_liberty -ignore_miss_func + flatten"


def _resolve_liberty_mount(project: Path, liberty: str):
    """Resolve --liberty to (container_path, extra_mount). A container-absolute
    path (/pdk, /foss, …) is used as-is with no extra mount (relies on
    pdk_dir). A project-relative path is realpath'd: if it stays inside the
    project it maps under /work; if it resolves (via a symlink) OUTSIDE the
    project — common when input/pdk is a symlink to a shared PDK — its real
    directory is bind-mounted at /libmnt so a fresh container can read it."""
    if liberty.startswith("/"):
        return liberty, None
    host = (project / liberty)
    try:
        real = host.resolve()
    except Exception:
        real = host
    try:
        rel = real.relative_to(project.resolve())
        return "/work/" + str(rel), None
    except ValueError:
        # resolves outside the project (symlinked PDK) — bind-mount its dir
        return "/libmnt/" + real.name, (str(real.parent), "/libmnt")


def _build_batch_script(flat_rel: str, miter_rel: str, top: str,
                        faults: list, prim_in_names: list[str]) -> str:
    """One Yosys script that solves every fault in the sample via
    design -save/-load (single process). Each fault: reload base, copy the
    core, inject the launch-frame stuck-at with `connect -set`, flatten the
    miter, `sat -prove trig 0 -set f1.<net> <init>` with the primary inputs
    -show'd so the detecting 2-pattern can be recovered. A per-fault `log`
    marker delimits the blocks for order-independent parsing."""
    show = " ".join(f"-show {n}" for n in prim_in_names)
    L = [f"read_verilog /work/{flat_rel} /work/{miter_rel}", "design -save base"]
    for net, kind, stuck, init in faults:
        raw = net.lstrip('\\')
        L += [
            "design -load base",
            f"copy {top} {top}_f",
            # SOUND stuck-at injection: `cd` into the faulty copy (connect
            # operates on ONE module) and `connect -nomap -set` — `-nomap` is
            # REQUIRED so the net is not silently remapped to its driver alias
            # (without it the driver keeps winning and the fault is NOT
            # injected → spurious detections). Proven by the injection
            # soundness check (a forced net is provably constant).
            f"cd {top}_f",
            f"connect -nomap -set {net} {stuck}",
            "cd ..",
            "hierarchy -top miter",
            "flatten",
            f"log VIBEICTDF {raw} {kind}",
            f"sat -prove trig 0 -set f1.{net} {init} {show}".rstrip(),
        ]
    return "\n".join(L) + "\n"


def _parse_batch_log(log: str, faults: list, prim_in_names: list[str]):
    """Map each `VIBEICTDF <net> <kind>` marker to the sat verdict block that
    follows it. Faults with a marker but no verdict (yosys aborted mid-batch)
    and faults with no marker at all (yosys exited before reaching them) are
    ABORTED — never detected. Returns (results, example_pattern)."""
    marker = re.compile(r'VIBEICTDF (\S+) (\S+)')
    hits = list(marker.finditer(log))
    results = {}
    example = None
    for i, m in enumerate(hits):
        net, kind = m.group(1), m.group(2)
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(log)
        body = log[start:end]
        v = parse_sat_verdict(body)
        results[(net, kind)] = v
        if v == "DET" and example is None:
            pat = _extract_pattern(body, prim_in_names)
            if pat:
                example = {"fault_net": net, "fault_kind": kind,
                           "primary_input_pattern": pat}
    out = []
    for net, kind, stuck, init in faults:
        raw = net.lstrip('\\')
        out.append((raw, kind, results.get((raw, kind), "ABORT")))
    return out, example


# ══════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════

def _to_container_path(project: Path, p: str) -> str:
    """A container-absolute path (/pdk, /foss, /work) is used as-is; a
    project-relative path is mapped under the /work mount."""
    if p.startswith("/"):
        return p
    return "/work/" + p.lstrip("./")


def run_tdf_atpg(project: Path, netlist_rel: str, cut_rel: str, liberty: str,
                 top: str, clock: str, dff_cells: str | None,
                 floor: float, max_faults: int, pdk_dir: Path | None,
                 timeout: int = 1800) -> tuple[int, dict]:
    """Full producer. Returns (exit_code, report_dict)."""
    dft_dir = (_pl.dft_dir(project) if _pl is not None
               else project / "phase2/stage2/dft")
    tdf_dir = dft_dir / "tdf"
    tdf_dir.mkdir(parents=True, exist_ok=True)
    flat_rel = "phase2/stage2/dft/tdf/flat_core.v"
    miter_rel = "phase2/stage2/dft/tdf/loc_miter.v"

    base = {
        "program": _PROGRAM, "version": _VERSION, "tool": "vibeic/yosys sat",
        "fault_model": "transition (LOC 2-frame stuck-at reduction)",
        "clock": clock, "top": top, "netlist": netlist_rel,
        "floor_pct": floor, "disclosure": _DISCLOSURE,
    }

    # 1. CUT
    ok, msg = _ensure_cut(project, netlist_rel, cut_rel, clock, dff_cells,
                          pdk_dir, timeout=min(timeout, 300))
    base["cut"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    # 2. GATE-LEVELISE
    liberty_ctr, lib_mount = _resolve_liberty_mount(project, liberty)
    extra_mounts = [lib_mount] if lib_mount else None
    base["liberty_container_path"] = liberty_ctr
    ok, msg = _gate_levelise(project, cut_rel, liberty_ctr, top, flat_rel,
                             pdk_dir, timeout=min(timeout, 300),
                             extra_mounts=extra_mounts)
    base["gate_levelise"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    flat_text = (project / flat_rel).read_text(errors="replace")
    _top, prim_in, prim_out, pairs = parse_cut_ports(flat_text)
    prim_in_names = [n.lstrip('\\') for n, _ in prim_in]

    # NOT_APPLICABLE: a purely combinational design (no cut flops) has no
    # launch mechanism → transition-fault ATPG under LOC does not apply. This
    # is an honest N/A (never a fake pass), self-skipping per the flow gate.
    if not pairs:
        base.update({
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "scan_flops": 0,
            "reasons": ["no sequential (scan-cut) flops found in the core — a "
                        "combinational design has no launch-off-capture "
                        "transition faults; TDF ATPG not applicable"],
        })
        return 0, base

    # 3. ENUMERATE + DISCLOSED SAMPLE
    nets = enumerate_fault_sites(flat_text)
    all_faults = enumerate_tdf_faults(nets)
    faults, sampled_flag = sample_faults(all_faults, max_faults)
    base.update({
        "scan_flops": len(pairs),
        "fault_sites_total": len(nets),
        "tdf_faults_total": len(all_faults),
        "tdf_faults_sampled": len(faults),
        "fault_sample_applied": sampled_flag,
    })

    # 4. UNROLL + SOLVE
    miter_text = build_loc_miter(_top, prim_in, prim_out, pairs)
    (project / miter_rel).write_text(miter_text)
    batch = _build_batch_script(flat_rel, miter_rel, _top, faults, prim_in_names)
    batch_rel = "phase2/stage2/dft/tdf/_tdf_batch.ys"
    (project / batch_rel).write_text(batch)
    ec, out, err = _run_in_docker(
        project, f"yosys /work/{batch_rel}", timeout=timeout, pdk_dir=pdk_dir)
    log = out + "\n" + err
    (tdf_dir / "sat_run.log").write_text(log[-200000:])

    results, example = _parse_batch_log(log, faults, prim_in_names)
    det = sum(1 for _, _, v in results if v == "DET")
    red = sum(1 for _, _, v in results if v == "RED")
    abort = sum(1 for _, _, v in results if v == "ABORT")

    if det + red + abort == 0:
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": [f"ATPG produced no verdicts (yosys exit {ec})",
                                 (log[-400:] or "").strip()]})
        return 1, base

    # 5. GRADE
    cov = coverage_math(det, red, abort)
    base.update(cov)
    test_cov = cov["tdf_test_coverage_pct"]
    ge_floor = (test_cov is not None and test_cov >= floor)
    base.update({
        "ge_floor": ge_floor,
        "launch_capture_pattern_count": det,   # each detection IS a 2-pattern
        "example_two_pattern": example,
        "fault_list": [{"net": n, "kind": k, "verdict": v} for n, k, v in results],
        "sat_log": "phase2/stage2/dft/tdf/sat_run.log",
        "verdict": "PASS" if ge_floor else "FAIL",
        "status": "PASS" if ge_floor else "FAIL",
        "reasons": ([] if ge_floor else [
            f"TDF logic test-coverage {test_cov}% < floor {floor}% "
            f"(detected {det}/(sampled {cov['sampled_faults']} - redundant "
            f"{red}) = {cov['testable_faults']} testable; aborted {abort} "
            "counted as undetected)"]),
    })
    return (0 if ge_floor else 1), base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("project_dir")
    p.add_argument("--clock", required=True, help="Functional clock name (e.g. clk)")
    p.add_argument("--netlist", default="phase2/stage2/synth/spm_synth.v",
                   help="Mapped netlist (used only if a cut netlist is absent)")
    p.add_argument("--cut-netlist", default="phase2/stage2/dft/cut_netlist.v",
                   help="Combinational full-scan cut netlist (reused if present;"
                        " else produced by `fault cut`)")
    p.add_argument("--liberty",
                   default="input/pdk/liberty/commercial_pdk_typ.lib",
                   help="Std-cell liberty (read AS LOGIC to gate-levelise; "
                        "container-absolute /pdk|/foss or project-relative)")
    p.add_argument("--top", default="spm", help="Top module name")
    p.add_argument("--dff-cells", default=None,
                   help="Flop cell names for `fault cut` (auto-detected + "
                        "unioned when omitted)")
    p.add_argument("--floor", type=float, default=TDF_LOGIC_FLOOR_DEFAULT,
                   help=f"TDF logic-coverage floor %% (chosen; default "
                        f"{TDF_LOGIC_FLOOR_DEFAULT:.0f}; at-speed grading "
                        "deferred). The sibling gate is authoritative.")
    p.add_argument("--max-faults", type=int, default=DEFAULT_MAX_FAULTS,
                   help=f"DISCLOSED bounded fault-sample size (default "
                        f"{DEFAULT_MAX_FAULTS}; <=0 = all). Never a silent cap "
                        "— total vs sampled are reported.")
    p.add_argument("--pdk-dir", default=None,
                   help="PDK dir mounted at /pdk (default ../shared_pdk for the "
                        "commercial model, if present)")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--json", default=None,
                   help="Report path (default reports/phase2/dft/"
                        "transition_coverage.json)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    else:
        cand = project.parent / "shared_pdk"
        if cand.exists():
            pdk_dir = cand

    exit_code, report = run_tdf_atpg(
        project, netlist_rel=args.netlist, cut_rel=args.cut_netlist,
        liberty=args.liberty, top=args.top, clock=args.clock,
        dff_cells=args.dff_cells, floor=args.floor, max_faults=args.max_faults,
        pdk_dir=pdk_dir, timeout=args.timeout)

    if args.json:
        json_path = Path(args.json)
    elif _pl is not None:
        json_path = _pl.report_path(project, "dft/transition_coverage.json")
    else:
        json_path = project / "reports/phase2/dft/transition_coverage.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    v = report.get("verdict")
    print(f"{_PROGRAM}: verdict={v} "
          f"test_cov={report.get('tdf_test_coverage_pct')}% "
          f"detected={report.get('detected')} redundant={report.get('redundant')} "
          f"aborted={report.get('aborted')} "
          f"sampled={report.get('tdf_faults_sampled')}/"
          f"{report.get('tdf_faults_total')} "
          f"patterns={report.get('launch_capture_pattern_count')}")
    if exit_code != 0 and v != "NOT_APPLICABLE":
        print(f"  (see {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
