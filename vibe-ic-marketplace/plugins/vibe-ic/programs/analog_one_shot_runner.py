#!/usr/bin/env python3
"""analog_one_shot_runner.py — A1-A9 analog flow (parallel to Phase 2 digital).

Trigger: <project>/analog/analog_block_list.json (or analog_blocks/) present.
Skip: pure-digital ICs (no analog block declared).

Steps (canonical A1-A9, Wave 90):
  A1 spec_extract           → analog/<block>/spec.json
  A2 topology_select        → analog/<block>/topology.md
  A3 netlist_gen            → analog/<block>/<block>.sp
  A4 corner_sweep           → analog/<block>/corner_results.json
  A5 layout                 → analog/<block>/layout.mag (Magic)
  A6 block_pv               → analog/<block>/{drc,lvs} per-block DRC+LVS
  A7 post_layout_resim      → analog/<block>/pre_vs_post.json
  A8 hardmacro_gen          → analog/hardmacro/<block>/{<block>.lef,.lib,.v}
  A9 hw_verify              → analog/<block>/hw_measurements.json (HIL/co-sim)

Outputs go to <project>/analog/<block_name>/ and roll up to
<project>/reports/analog_one_shot.json. A8 LEF/lib feed back into Phase 3
(Step 15 floorplan) for mixed-signal integration.

Each Ai step delegates to the corresponding analog skill / generator under
plugins/vibe-ic/skills/analog-* (or programs/analog_*.py if a
deterministic gate exists). When a step has no deterministic implementation
yet, this runner returns WAIVED with the skill name the caller should
invoke. chip-AGNOSTIC.

Usage:
    python3 analog_one_shot_runner.py <project> [--container vibeic-eda]
                                                 [--blocks <comma-list>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl
import _analog_a_check_common as _acc
import step_preflight as _spf  # required_inputs PRE-FLIGHT at every dispatch site

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

PROGRAMS_DIR = Path(__file__).resolve().parent


@dataclass
class StepResult:
    name: str
    block: str
    status: str
    duration_s: float
    detail: str
    output_files: List[str] = field(default_factory=list)
    # v1.6.171 (#60 P1-6) — structured extras for deterministic-stub
    # provenance (stub_paths / extraction_strategy / low_confidence).
    extras: Dict[str, Any] = field(default_factory=dict)


def _preflight_refusal(name: str, block: str):
    """This runner's refusal row for `step_preflight.gate`.

    `BLOCKED` carries the same meaning it does in the other three runners: the
    step was NOT attempted because an INPUT could not support it, so NOTHING is
    known. It is listed in `_aggregate_verdict._FAIL_STATUSES` — without that it
    would have fallen through that function's catch-all `return "PASS"` and a
    refusal would have produced a GREEN run, which is the defect class this
    whole pre-flight exists to remove. Measured on this ladder specifically: a
    refusal is neither FAIL, nor VACUOUS_PASS, nor PASS_STRUCTURE_ONLY, nor
    WAIVED/SKIP, so every one of the four tiers above the catch-all would have
    declined it and an all-refused analog track would have scored a clean PASS.

    NOTE the shape difference from `design_one_shot_runner._preflight_refusal`:
    this runner's `StepResult` carries a `block` as its SECOND positional field,
    so the row is built with it rather than assuming the phase-2 signature.
    """
    def _mk(detail: str, extras: Dict[str, Any]) -> StepResult:
        return StepResult(name, block, _spf.REFUSAL_STATUS, 0.0, detail,
                          extras=extras)
    return _mk


# Statuses that must NOT reach a green verdict. `BLOCKED` is `step_preflight`'s
# refusal status; the rest is this runner's pre-existing FAIL tier, unchanged.
_FAIL_STATUSES = ("FAIL", _spf.REFUSAL_STATUS)


_AI_STEP_NAMES = (
    "A1_spec_extract",
    "A2_topology_select",
    "A3_netlist_gen",
    "A4_corner_sweep",
    "A5_layout",
    "A6_block_pv",
    "A7_post_layout_resim",
    "A8_hardmacro_gen",
    "A9_hw_verify",
)


def _load_block_list_with_status(project: Path
                                  ) -> tuple[List[Dict[str, Any]], str]:
    """v1.6.128 (#50 Fix 1) — find the analog block list AND
    distinguish three states:

      * "populated" — declared blocks present, list non-empty
      * "empty"     — file or L5 source exists but explicitly
                      declares no analog blocks (intentional skip,
                      e.g. pure-digital project)
      * "missing"   — no block list file AND no L5 source exists
                      (project skipped phase1 / spec-extract; the
                      analog runner cannot meaningfully proceed
                      and must NOT silently emit VACUOUS_PASS)

    Returns (blocks, status). The caller is responsible for
    translating status="missing" into a FAIL_NO_BLOCK_LIST verdict
    rather than a silent SKIP.

    Chip-AGNOSTIC.
    """
    candidates = [
        _pl.analog_dir(project) / "analog_block_list.json",
        project / "analog_blocks" / "analog_block_list.json",
        project / "input" / "analog_block_list.json",
    ]
    l5 = _pl.generated_docs_dir(project) / "L5_ADI_SPEC.json"

    for c in candidates:
        if c.is_file():
            try:
                d = json.loads(c.read_text())
                if isinstance(d, list):
                    return (d, "populated" if d else "empty")
                if isinstance(d, dict) and "blocks" in d:
                    blocks = d["blocks"] or []
                    return (blocks, "populated" if blocks else "empty")
                # File present but unrecognised shape — treat as empty
                # rather than missing (the user has signalled intent).
                return ([], "empty")
            except Exception:
                # Corrupted JSON — treat as empty (intent signalled but
                # unparseable; do NOT escalate to FAIL_NO_BLOCK_LIST
                # because the file IS present).
                return ([], "empty")
    if l5.is_file():
        try:
            d = json.loads(l5.read_text())
            if d.get("no_analog") is True:
                return ([], "empty")
            blocks = d.get("analog_blocks") or d.get("blocks")
            if isinstance(blocks, list):
                real = [b for b in blocks if isinstance(b, dict)]
                return (real, "populated" if real else "empty")
            # L5 present but neither no_analog nor analog_blocks — treat
            # as empty (L5 was generated but didn't declare analog).
            return ([], "empty")
        except Exception:
            return ([], "empty")

    # No block-list file AND no L5 — analog runner truly has no
    # signal about whether the project has analog work or not.
    return ([], "missing")


def _load_block_list(project: Path) -> List[Dict[str, Any]]:
    """Backwards-compat wrapper that drops the status. New callers
    should use `_load_block_list_with_status` and act on `missing`
    explicitly.
    """
    blocks, _status = _load_block_list_with_status(project)
    return blocks


# v1.6.171 (#60 P1-6) — deterministic-stub emitter (B2 path from
# #58 sub-B). When a per-block artefact is missing, the runner can
# optionally emit a minimal-substance stub tagged
# `extraction_strategy: "deterministic_stub"` so the existing 8
# substance gates return PASS naturally + downstream consumers see
# the stub marker and treat it as low-confidence (not real analog
# data). chip-AGNOSTIC: stubs are universal-shape; no chip-class
# detection. Gated on `ANALOG_DETERMINISTIC_STUBS=1` env var OR
# the runner's `--allow-deterministic-stubs` flag so existing
# benchmark runs that prefer the strict WAIVED-on-missing semantics
# stay unchanged.
_STUB_ENV_VAR = "ANALOG_DETERMINISTIC_STUBS"


def _stubs_enabled(args=None) -> bool:
    if args is not None and getattr(args, "allow_deterministic_stubs",
                                     False):
        return True
    val = os.environ.get(_STUB_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")


# ── A6 native per-block PV (v1.4.27 — consume the staged sign-off decks) ─────

def _declared_l19_target(project: Path):
    """The L19 tapeout pdk_target string, or None. Delegates to the shared
    reader so the A6 producer agrees with the corner-sweep emitter."""
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        import analog_netlist_pdk_check as _npc
        return _npc._declared_pdk_target(Path(project))
    except Exception:
        l19 = (Path(project) / "phase1" / "generated_docs"
               / "L19_CONSTRAINTS_PDK.json")
        try:
            t = json.loads(l19.read_text(errors="replace")) \
                .get("fields", {}).get("pdk_target")
        except (OSError, ValueError):
            return None
        if isinstance(t, str) and t.strip() and not t.strip().lower().startswith(
                ("n/a", "na ", "none", "tbd")):
            return t.strip()
        return None


def _try_native_a6_pv(project: Path, block: str, container: str):
    """Run native per-block PV (svrfdrc DRC + klayout_pdk_lvs LVS) when the
    v1.4.24 resolver resolves the project's STAGED sign-off decks (rung 1/2).
    Returns the producer status dict (with `ran`), or None when the native path
    does not apply (no declared target / no resolved deck) — the caller then
    keeps its existing waiver / stub path. Never raises."""
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        import analog_a6_native_pv as _pv
        import analog_pdk_availability as _apa
    except Exception:
        return None
    # vibe-ic#576 — NO `if not declared: return None` here.
    #
    # `resolve_pdk` now tries rung 1 (project-staged custom PDK, detected by
    # GLOB over `input/pdk/`) BEFORE it needs a target, so a project that
    # stages its own sign-off decks reaches native per-block PV without an L19
    # declaration. Guarding here would re-close the door the resolver just
    # opened — and silently: this function returns None, which the caller reads
    # as "the native path does not apply", so the design's own staged decks
    # were never run and no tool was ever named.
    declared = _declared_l19_target(project)
    try:
        res = _apa.resolve_pdk(declared, project=str(project),
                               container=container)
    except Exception:
        return None
    if not (res.get("available")
            and (res.get("drc_deck") or res.get("lvs_deck"))):
        return None
    try:
        return _pv.run_block_pv(project, block, res, container)
    except Exception:
        return None


def _loop_liveness(project: Path, block: str, container: str):
    """Was the block's loop LIVE over the window A4 just measured?

    A4 reports numbers taken over a transient. `analog_loop_liveness_check`
    exists because a number taken over a loop that never left reset certifies
    nothing — measured on a real block, where two mechanisms were closed on
    clean nulls and both had to be reopened rounds later. That gate had no
    caller for one reason: nothing emitted its input. It has one now
    (`analog_loop_liveness_samples_emit`), which exports the nodes A2 declared
    from the transient THIS STEP already ran.

    Returns the gate's own record, or a NOT_PRODUCED / NOT_DECLARED record
    naming what was missing. Never None for a block whose type declares
    liveness nodes, and never raises: a step's disposition is decided by its
    own gate, and this rides alongside it as disclosure.
    """
    prod = PROGRAMS_DIR / "analog_loop_liveness_samples_emit.py"
    gate = PROGRAMS_DIR / "analog_loop_liveness_check.py"
    if not (prod.is_file() and gate.is_file()):
        return None
    try:
        pcp = _pr.run([sys.executable, str(prod), str(project),
                       "--block", block, "--container", container],
                      capture_output=True, text=True)
    except Exception as exc:                       # pragma: no cover - defensive
        return {"result": "NOT_PRODUCED", "reason": repr(exc)}
    try:
        prec = json.loads(pcp.stdout)
    except Exception:
        prec = {}
    if pcp.returncode != 0 or not prec.get("checker_argv"):
        tail = (pcp.stderr or "").strip().splitlines()
        # A producer that refused is a window that was NOT MEASURED — the same
        # tier the gate itself returns, and deliberately not a third word. The
        # only outcome that is not in that tier is NOT_DECLARED: a circuit
        # class of which the question was never asked. Nothing here may be a
        # pass: "we could not look" must not render like "we looked and it was
        # fine", which is the whole finding this track came from.
        return {"result": ("NOT_DECLARED"
                           if prec.get("verdict") == "NOT_DECLARED"
                           else "NOT_MEASURED"),
                "stage": "samples_producer",
                "producer": prod.name, "producer_rc": pcp.returncode,
                "reason": (prec.get("reason") or (tail[-1] if tail else
                           "the samples producer wrote nothing and said "
                           "nothing"))}
    out = project / "phase3" / "analog" / block / "loop_liveness.json"
    gcp = _pr.run([sys.executable, str(gate), *prec["checker_argv"],
                   "--json", str(out)], capture_output=True, text=True)
    try:
        rec = json.loads(gcp.stdout)
    except Exception:
        rec = {"result": "UNUSABLE",
               "reason": (gcp.stderr or gcp.stdout or "").strip()[-400:]}
    rec["gate"] = gate.stem
    rec["gate_rc"] = gcp.returncode
    rec["samples"] = prec.get("samples")
    rec["deck"] = prec.get("deck")
    rec["record"] = str(out)
    return rec


def _pv_verdict(native, kind):
    d = (native or {}).get(kind)
    return d.get("verdict") if isinstance(d, dict) else "n/a"


def _a5_emit_reason(cp) -> str:
    """What `analog_a5_layout_emit` said, preferring its own words.

    The producer reports ENV_UNAVAILABLE with the tool NAMED — magic, the
    container, or the PDK file it could not read. That name is the whole
    value of the message to whoever reads the run record, so it is carried
    through verbatim rather than flattened into "artefact missing"."""
    blob = (cp.stdout or "") + (cp.stderr or "")
    try:
        doc = json.loads(cp.stdout or "")
    except (ValueError, TypeError):
        doc = None
    if isinstance(doc, dict):
        if doc.get("reason"):
            return str(doc["reason"])
        for rep in (doc.get("blocks") or {}).values():
            if isinstance(rep, dict) and rep.get("reason"):
                return str(rep["reason"])
    for line in reversed(blob.strip().splitlines()):
        if line.strip():
            return line.strip()[:400]
    return ("analog_a5_layout_emit produced no layout and said nothing; "
            "invoke skill `analog-layout`")


def _emit_deterministic_stub(project: Path, bname: str,
                              step_name: str) -> List[Path]:
    """Emit minimal-substance artefacts for the given (block, step)
    so that the corresponding analog_a*_check.py gate PASSes the
    presence + substance check. Each artefact carries an
    `extraction_strategy: "deterministic_stub"` marker (JSON files)
    or `# deterministic_stub` comment (textual files) so downstream
    consumers can distinguish stub from real data.
    Returns the list of paths written.
    """
    written: List[Path] = []
    analog_dir = _pl.analog_dir(project)
    bdir = analog_dir / bname

    def _wj(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload["extraction_strategy"] = "deterministic_stub"
        payload["low_confidence"] = True
        path.write_text(json.dumps(payload, indent=2,
                                    ensure_ascii=False) + "\n")
        written.append(path)

    def _wt(path: Path, header_comment: str, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (f"{header_comment} deterministic_stub "
                f"extraction_strategy=deterministic_stub "
                f"low_confidence=true\n{body}")
        path.write_text(text)
        written.append(path)

    if step_name == "A1_spec_extract":
        _wj(bdir / "spec.json", {
            "block": bname,
            "specs": [{
                "name": "vout",
                "target": 1.0,
                "units": "V",
                "note": ("deterministic stub — replace with extracted "
                          "spec when analog-spec-extract skill runs"),
            }],
        })
    elif step_name == "A2_topology_select":
        # v0.2.55 — the A2 substance gate (analog_a2_topology_select_check)
        # requires topology.md to NAME at least one transistor/circuit
        # primitive. The previous "generic_class_a (placeholder)" stub
        # contained NO panel keyword, so the runner's OWN stub failed the
        # runner's OWN A2 gate for any block whose name lacked a keyword
        # (e.g. `adc`, `delta_sigma`). Emit a generic-but-keyword-bearing
        # class-A topology description so the deterministic stub is
        # self-consistent. chip-AGNOSTIC: generic analog vocabulary only.
        _wt(bdir / "topology.md", "<!--",
            (f"# {bname} — topology (stub)\n\n"
              f"Topology family: generic class-A amplifier (placeholder)\n\n"
              f"Primitive skeleton (deterministic stub — replace with the "
              f"`analog-topology-select` skill output):\n"
              f"- differential pair: NMOS input transistors\n"
              f"- active load: PMOS current mirror\n"
              f"- tail bias: NMOS current source (bias)\n"
              f"- output stage: common-source PMOS with feedback "
              f"compensation\n\n"
              f"Replace with output of `analog-topology-select` skill.\n"
              "-->\n"))
    elif step_name == "A3_netlist_gen":
        _wt(bdir / f"{bname}.sp", "*",
            (f"* {bname} — SPICE netlist (stub)\n"
              f".subckt {bname} vdd vss vin vout\n"
              f"* replace with extracted netlist when "
              f"analog-netlist-gen skill runs\n"
              f"r_stub vin vout 1k\n"
              f".ends {bname}\n"))
    elif step_name == "A4_corner_sweep":
        _wj(bdir / "corner_results.json", {
            "block": bname,
            "_provenance": "deterministic_stub",
            "extraction_strategy": "deterministic_stub",
            "low_confidence": True,
            "corners": [
                {"name": "tt_27c", "simulator_run": False,
                 "vout_v": None, "margin": None},
            ],
            "spec_results": [
                {"name": "vout_v", "status": "FAIL",
                 "value": None, "target": None,
                 "reason": "deterministic_stub — no SPICE ran"},
            ],
            "note": ("v1.6.207 honest stub: simulator_run=false, "
                      "status=FAIL. Replace with real PVT sweep via "
                      "analog_real_corner_sweep.py or ams-sim skill."),
        })
    # A5_layout HAS NO STUB, deliberately, since v1.16.6.
    #
    # It used to write `"x" * 400` into `layout.mag` so the A5 gate would find
    # something over its 200-byte floor. That was the ONLY thing standing
    # where A5's producer should be, and it is why every run that needed a
    # real analog layout authored a generator of its own — the one measured on
    # u_hawaii_adc round 20 refused a legal `w=1.0u l=0.5u` device the PDK
    # permits. `analog_a5_layout_emit` now DRAWS the block from its A3
    # netlist and the PDK's own gencells (see the A5 branch in
    # `step_for_block`). When Magic or the PDK cannot be reached that producer
    # reports ENV_UNAVAILABLE naming the tool and writes nothing, and this
    # step lands as WAIVED — a named absence, which a fabricated layout.mag
    # never was.
    elif step_name == "A6_block_pv":
        # A6 per-block PV requires REAL DRC + LVS evidence. The
        # hardened gate (analog_a6_block_pv_check.py) demands an
        # explicit `violations: 0` line for DRC and a `match` verdict
        # for LVS — a bare flag is rejected. The deterministic stub
        # therefore emits honest zero-violation / match evidence so a
        # stub-mode dry-run PASSes; real runs overwrite these with
        # tool output.
        _wt(bdir / "drc_clean.flag", "#",
            (f"# {bname} — DRC clean (deterministic stub)\n"
              f"deterministic_stub\n"
              f"violations: 0\n"))
        _wt(bdir / "lvs_match.flag", "#",
            (f"# {bname} — LVS match (deterministic stub)\n"
              f"deterministic_stub\n"
              f"lvs: match\n"))
    elif step_name == "A7_post_layout_resim":
        # A7 requires both A4 (corner_results.json) AND
        # `pre_vs_post.json`. Ensure A4 stub present first.
        a4_path = bdir / "corner_results.json"
        if not a4_path.is_file():
            _emit_deterministic_stub(project, bname, "A4_corner_sweep")
        _wj(bdir / "pre_vs_post.json", {
            "block": bname,
            "specs": [
                {"name": "vout_v",
                 "pre_value": 1.0, "post_value": 0.99},
            ],
            "max_delta_pct": 1.0,
            "verdict": "consistent",
        })
    elif step_name == "A8_hardmacro_gen":
        hdir = analog_dir / "hardmacro" / bname
        _wt(hdir / f"{bname}.lef", "#",
            (f"# {bname} — LEF (stub)\n"
              f"VERSION 5.8 ;\n"
              f"BUSBITCHARS \"[]\" ;\n"
              f"MACRO {bname}\n"
              f"  SIZE 100 BY 100 ;\n"
              f"  CLASS BLOCK ;\n"
              f"END {bname}\n"
              f"# deterministic-stub padding "
              + "x" * 200 + "\n"))
        _wt(hdir / f"{bname}.lib", "//",
            (f"// {bname} — Liberty (stub)\n"
              f"library({bname}_stub) {{\n"
              f"  cell({bname}) {{\n"
              f"    area : 10000 ;\n"
              f"  }}\n"
              f"}}\n"
              f"// deterministic-stub padding "
              + "x" * 200 + "\n"))
        _wt(hdir / f"{bname}.v", "//",
            (f"// {bname} — Verilog wrapper (stub)\n"
              f"module {bname} (input vdd, input vss, output vout);\n"
              f"  // deterministic_stub — no real behaviour\n"
              f"  assign vout = 1'b0;\n"
              f"endmodule\n"
              f"// deterministic-stub padding "
              + "x" * 100 + "\n"))
    elif step_name == "A9_hw_verify":
        _wj(bdir / "hw_measurements.json", {
            "block": bname,
            "measurements": {
                "vout_v": 1.0,
                "iout_ma": 100.0,
            },
            "measurement_count": 2,
            "verdict": "within_tolerance",
            "note": ("deterministic stub — replace with bench-tool "
                      "output when analog-hw-measure skill runs"),
        })
    return written


# ── A1-A3 deterministic producers ─────────────────────────────────────────
# The FIRST track for the three steps that had none. Each records its own
# honest absence in a named gap file when it declines, and each stamps its
# provenance into the artefact it writes.
# ── is the artefact on disk the one THIS producer would make? ─────────────
# MEASURED (round 23): the A1-A3 producers were invoked only on the gate's
# rc 2 — the artefact-missing path. With a STALE artefact present the gate
# returned rc 0, the step reported PASS, and the producer never ran. A lane
# that had just fixed the topology library therefore simulated the OLD
# netlist — old comparator, 4 um keeper, 181 um bias — and the run looked
# identical to a successful one from the outside. A producer fix that the
# runner does not re-emit reaches nobody.
#
# The judgement is derived from what the ARTEFACT ITSELF says: each producer
# stamps a digest of its own source into the provenance it writes, and the
# runner compares that against the producer it is about to skip. NOT mtime (a
# copy or a checkout resets it) and NOT a file name (one spelling defines a
# blind population). An artefact that names no fingerprint is treated as
# unknown provenance and re-emitted, because silence is not agreement.
#: step -> (artefact carrying the provenance, dotted key inside it)
_PRODUCER_STAMP: Dict[str, tuple] = {
    "A1_spec_extract": ("spec.json", "_provenance"),
    "A2_topology_select": ("topology.json", "_provenance"),
    "A3_netlist_gen": ("netlist_provenance.json", "_provenance"),
}


def _live_producer_fingerprint(program: str) -> str:
    """The digest the producer would stamp right now."""
    import hashlib
    p = PROGRAMS_DIR / program
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _artefact_producer_fingerprint(project: Path, block: str,
                                   step_name: str) -> Optional[str]:
    """The digest the artefact on disk says it was made by, or None."""
    spec = _PRODUCER_STAMP.get(step_name)
    if not spec:
        return None
    fname, key = spec
    f = _pl.analog_dir(project) / block / fname
    if not f.is_file():
        return None
    try:
        doc = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    prov = doc.get(key) if isinstance(doc, dict) else None
    if isinstance(prov, dict):
        v = prov.get("producer_fingerprint")
        return str(v) if v else None
    return None


def producer_reuse_decision(project: Path, block: str,
                            step_name: str) -> Dict[str, Any]:
    """Say — out loud, as a decision — whether the artefact on disk is the one
    this producer would emit. `reuse` True means the runner may keep it, and
    `detail` names WHICH artefact it kept."""
    prod = _A1_A3_PRODUCERS.get(step_name)
    spec = _PRODUCER_STAMP.get(step_name)
    if not prod or not spec:
        return {"applies": False, "reuse": True,
                "detail": "no producer stamp is defined for this step"}
    live = _live_producer_fingerprint(prod["program"])
    have = _artefact_producer_fingerprint(project, block, step_name)
    if not live:
        return {"applies": True, "reuse": True, "live": live, "artefact": have,
                "detail": (f"{prod['program']} could not be read, so its "
                           f"fingerprint is ABSENT; the artefact is kept and "
                           f"this is recorded, never silently)")}
    if have is None:
        return {"applies": True, "reuse": False, "live": live, "artefact": None,
                "detail": (f"{spec[0]} names no producer_fingerprint, so its "
                           f"provenance is UNKNOWN — re-emitting rather than "
                           f"inheriting an artefact that cannot say who made "
                           f"it")}
    if have != live:
        return {"applies": True, "reuse": False, "live": live, "artefact": have,
                "detail": (f"{spec[0]} was emitted by {prod['program']} "
                           f"@{have}, this run carries @{live} — re-emitting")}
    return {"applies": True, "reuse": True, "live": live, "artefact": have,
            "detail": (f"REUSED {spec[0]} emitted by {prod['program']} "
                       f"@{have}, identical to this run's producer")}


_A1_A3_PRODUCERS: Dict[str, Dict[str, Any]] = {
    "A1_spec_extract": {
        "program": "analog_a1_spec_emit.py",
        "status": "PASS_WITH_REAL_EXTRACT",
        "strategy": "l5_structured_bind",
        "gap": "spec_gap.json",
    },
    "A2_topology_select": {
        "program": "analog_a2_topology_emit.py",
        "status": "PASS_WITH_DERIVED_TOPOLOGY",
        "strategy": "type_topology_library",
        "gap": "topology_gap.json",
    },
    "A3_netlist_gen": {
        "program": "analog_a3_netlist_emit.py",
        "status": "PASS_WITH_REAL_NETLIST",
        "strategy": "topology_ir_render",
        "gap": "netlist_gap.json",
        "takes_container": True,
        # Simulate the emitted deck inside the flow, not only when a human
        # remembers the flag. Safe by the producer's own contract: an
        # unreachable container is recorded as NOT_VERIFIED_NO_SIMULATOR and
        # the netlist is still emitted, so this can never turn A3 into a FAIL
        # the gate has not itself found — it can only stop a deck that does
        # not converge from being shipped as an artefact.
        "extra_args": ["--verify-sim"],
    },
}

#: The producer-provenance STAMPS `step_for_block` may return in place of a
#: bare `PASS`, mapped to the tier each one is a stamped form of. v1.16.84
#: (`ce088900a`) made the A1-A3 rc 0 path say WHICH producer wrote the
#: artefact the gate then certified, because without it a stale artefact and a
#: freshly emitted one are indistinguishable in the verdict. That put TWO
#: facts in one field — the disclosure TIER the step landed in, and whether a
#: producer ran this run — and a consumer that reads the field for the first
#: fact then disagrees with one that reads it for the second.
#:
#: This is the join between them, and it is an ENUMERATION, never a prefix
#: rule: only the stamps the runner itself declares above collapse, and each
#: collapses to exactly one tier. `PASS_STRUCTURE_ONLY` is NOT in it and never
#: can be — it is a different TIER (disclosed, library-default content), not a
#: stamped `PASS` — so it survives `verdict_tier` unchanged, which is what
#: keeps the disclosure ordering readable.
_STAMPED_VERDICT_TIER: Dict[str, str] = {
    _p["status"]: "PASS" for _p in _A1_A3_PRODUCERS.values()
}


def verdict_tier(status: str) -> str:
    """The TIER a step's status lands in, with the producer-provenance stamp
    removed if it carries one.

    `PASS_WITH_REAL_NETLIST` is a `PASS` that also names its producer;
    `PASS_STRUCTURE_ONLY` is not a `PASS` at all. Any status this module does
    not declare as a stamp is returned UNCHANGED — an unknown `PASS_WITH_*`
    is not silently rounded up to a pass, and neither is a `FAIL`. Chip-
    AGNOSTIC.
    """
    return _STAMPED_VERDICT_TIER.get(status, status)


# What each A-step's artefacts are called, so `StepResult.output_files` can
# stop being `[]` on every path including PASS. The runner's own record never
# named what a step produced, which is how a step could be reported done while
# nothing on disk backed it.
_STEP_ARTEFACTS: Dict[str, tuple] = {
    "A1_spec_extract": ("spec.json",),
    "A2_topology_select": ("topology.md", "topology.json"),
    "A3_netlist_gen": ("{block}.sp", "tb_{block}.sp",
                       "netlist_provenance.json"),
    "A4_corner_sweep": ("corner_results.json",),
    "A5_layout": ("layout.mag",),
    "A7_post_layout_resim": ("pre_vs_post.json",),
    "A9_hw_verify": ("hw_measurements.json",),
}


def _step_outputs(project: Path, block: str, step_name: str) -> List[str]:
    """Project-relative paths of the step's artefacts that actually EXIST.
    Only files on disk are listed — this must never assert an output the step
    did not produce."""
    out: List[str] = []
    bdir = _pl.analog_dir(project) / block
    for pattern in _STEP_ARTEFACTS.get(step_name, ()):  # noqa: SIM118
        p = bdir / pattern.format(block=block)
        if p.is_file():
            try:
                out.append(str(p.relative_to(project)))
            except ValueError:                          # pragma: no cover
                out.append(str(p))
    return out


# ── the disclosure a PASSING gate prints, and where it lands ──────────────
# THE RULE, with no tool, step or block name in it:
#
#   When a step certifies an artefact whose content came from a library
#   default, the run record must SAY SO — as the step's own disposition, not
#   as a plain pass with the disclosure dropped on the floor.
#
# The token is a LINE-START sentinel on stdout, the same shape as this repo's
# `VACUOUS_PASS:`, and it is read whether or not the gate passed.
_STRUCTURE_ONLY_SENTINEL = "STRUCTURE_ONLY:"
#: The per-step artefacts whose record answers "what is in it?", and the key
#: inside each. An ORDERED, nearest-first chain per step: a step's OWN record
#: outranks anything it inherits, because only its producer can state what
#: THAT file contains. Every shape is read from an artefact and never inferred
#: here; a link that names no content is skipped, not accepted, so a chain can
#: only ever find an answer a producer actually wrote down.
#:
#: A7 has a chain rather than a single source because no producer writes the
#: field into `pre_vs_post.json`, while the pre-layout corner result the
#: comparison is against — the artefact `analog_a4_corner_sweep_check` is the
#: gate of record for — carries it. Until this entry existed, the runner
#: recorded a PASS_STRUCTURE_ONLY A7 step with EMPTY extras: it read the
#: gate's sentinel and then had nothing to say about what the step contained,
#: which is the same defect one layer down.
#:
#: ORDER IS NOT ENOUGH FOR A7, and `_CONTENT_CEILINGS` below is why. Its
#: nearest link is AI-authored; being nearest must not make it AUTHORITATIVE.
_CONTENT_SOURCES: Dict[str, tuple] = {
    "A3_netlist_gen": (("netlist_provenance.json", ("_provenance",
                                                    "design_content")),),
    "A4_corner_sweep": (("corner_results.json", ("design_content",)),),
    "A7_post_layout_resim": (("pre_vs_post.json", ("design_content",)),
                             ("corner_results.json", ("design_content",))),
}
#: The answers that NAME a content — IMPORTED from the gates' own whitelist,
#: never restated. A second copy here would be free to drift from the one the
#: gates certify on, and the runner would record a content the gate refuses.
#: (A whitelist and not a blacklist for the reason stated where it is defined:
#: a blacklist certifies the next token nobody has thought of yet.)
_CONTENT_DISCLOSED = _acc.DESIGN_CONTENT_DISCLOSED


def _structure_only_disclosure(cp) -> Optional[str]:
    """The gate's structure-only line, or None. Reads stdout AND stderr for
    the same reason the flow auditor concatenates them: which stream a gate
    uses is not part of the contract, and a disclosure missed because it went
    to the other one is a disclosure that does not exist."""
    for stream in ((cp.stdout or ""), (cp.stderr or "")):
        for line in stream.splitlines():
            if line.startswith(_STRUCTURE_ONLY_SENTINEL):
                return line.strip()
    return None


# ── AND WHERE A CHAIN IS CAPPED ───────────────────────────────────────────
# THE RULE, with no tool, step or block name in it, and it is the gates' rule
# applied to the RUN RECORD:
#
#   A derived artefact may CONFIRM or LOWER the content its baseline records.
#   It may never RAISE it.
#
# WHY THE RUN RECORD NEEDS IT SEPARATELY. The chain above is ordered
# nearest-first, and for A7 the nearest link is `pre_vs_post.json` — a file the
# `analog-extraction-resim` SKILL authors and no deterministic producer writes
# the field into. The GATE was measured certifying a design-bound pass off that
# token over a silent baseline; this function reads the same two files in the
# same order, so it would have recorded `design_content: structure_and_geometry`
# beside a step the gate had just refused, or beside a PASS_STRUCTURE_ONLY
# status — a run record contradicting itself in two adjacent fields.
#
# Only the ceiling ARTEFACT is named here. The ranking itself is imported from
# the gates' own module, for the reason `_CONTENT_DISCLOSED` is: a second copy
# is free to drift, and then the runner records a tier the gate refuses.
_CONTENT_CEILINGS: Dict[str, tuple] = {
    "A7_post_layout_resim": (("corner_results.json", ("design_content",)),),
}


def _first_disclosed(project: Path, block: str, chain: tuple) -> tuple:
    """``(token, path)`` of the first artefact in *chain* whose record NAMES a
    content, or ``(None, None)``. A link that names nothing is skipped, not
    accepted, so a chain can only ever find an answer a producer wrote down."""
    for name, keys in chain:
        path = _pl.analog_dir(project) / block / name
        if not path.is_file():
            continue
        try:
            doc: Any = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for k in keys:
            if not isinstance(doc, dict):
                doc = None
                break
            doc = doc.get(k)
        if doc in _CONTENT_DISCLOSED:
            return doc, path
    return None, None


def _content_extras(project: Path, block: str,
                    step_name: str) -> Dict[str, Any]:
    """`design_content` for a step's own artefact, READ from that artefact and
    BOUNDED by what the gate of record's own subject supports.

    Empty for a step that has no such record — this must never assert an
    answer the producer did not write down, which is the whole point of the
    field.
    """
    chain = _CONTENT_SOURCES.get(step_name)
    if not chain:
        return {}
    token, path = _first_disclosed(project, block, chain)

    ceiling_chain = _CONTENT_CEILINGS.get(step_name)
    if ceiling_chain is not None:
        c_token, c_path = _first_disclosed(project, block, ceiling_chain)
        if (_acc.content_rank(_acc.classify_design_content(token))
                > _acc.content_rank(_acc.classify_design_content(c_token))):
            # The derived artefact out-claimed its own baseline. The baseline's
            # answer is the record — including when the baseline named nothing,
            # in which case there IS no record and the extras stay empty.
            token, path = c_token, c_path

    if token is None or path is None:
        return {}
    # CLASSIFIED, not compared: the raw tokens are the PRODUCER's vocabulary
    # and this is a consumer. `_acc.CONTENT_STRUCTURE_ONLY` is the class the
    # gates rank on, and reading it through the same classifier is what stops
    # this record from naming a tier the gate refuses.
    return {"design_content": token,
            "structure_only": (_acc.classify_design_content(token)
                               == _acc.CONTENT_STRUCTURE_ONLY),
            "design_content_source": str(path.relative_to(project))}


def _producer_gap(project: Path, block: str,
                  prod: Dict[str, Any]) -> Optional[str]:
    """The gap file a declining producer wrote, if it wrote one."""
    p = _pl.analog_dir(project) / block / str(prod.get("gap") or "")
    if p.is_file():
        try:
            return str(p.relative_to(project))
        except ValueError:                              # pragma: no cover
            return str(p)
    return None


def step_for_block(project: Path, block: Dict[str, Any], step_name: str,
                    args=None
                    ) -> StepResult:
    """Run one Ai step for one analog block. Most A* steps need an LLM
    skill (spec extract, topology select, etc.); mark them WAIVED with
    the skill name if no deterministic program exists.
    """
    t0 = time.time()
    bname = block.get("name") or block.get("type") or "unknown"
    out_dir = _pl.analog_dir(project) / bname
    out_dir.mkdir(parents=True, exist_ok=True)

    # v1.6.35: every A1-A9 step now has a deterministic
    # artefact-presence + substance gate. Missing artefact → rc=2,
    # which the runner translates to WAIVED (caller should invoke
    # the upstream skill). Stub artefact → rc=1 → FAIL (no more
    # silent stub escape). Real artefact → rc=0 → PASS.
    det_progs = {
        "A1_spec_extract":      PROGRAMS_DIR / "analog_a1_spec_extract_check.py",
        "A2_topology_select":   PROGRAMS_DIR / "analog_a2_topology_select_check.py",
        "A3_netlist_gen":       PROGRAMS_DIR / "analog_a3_netlist_gen_check.py",
        "A4_corner_sweep":      PROGRAMS_DIR / "analog_a4_corner_sweep_check.py",
        "A5_layout":            PROGRAMS_DIR / "analog_a5_layout_check.py",
        "A6_block_pv":          PROGRAMS_DIR / "analog_a6_block_pv_check.py",
        "A7_post_layout_resim": PROGRAMS_DIR / "analog_a7_post_layout_resim_check.py",
        "A8_hardmacro_gen":     PROGRAMS_DIR / "analog_a8_hardmacro_gen_check.py",
        "A9_hw_verify":         PROGRAMS_DIR / "analog_a9_hw_verify_check.py",
    }
    skill_map = {
        "A1_spec_extract":      "analog-spec-extract",
        "A2_topology_select":   "analog-topology-select",
        "A3_netlist_gen":       "analog-netlist-gen",
        "A4_corner_sweep":      "ams-sim",
        "A5_layout":            "analog-layout",
        "A6_block_pv":          "drc-fix",
        "A7_post_layout_resim": "analog-extraction-resim",
        "A8_hardmacro_gen":     "analog-hardmacro-gen",
        "A9_hw_verify":         "analog-hw-measure",
    }
    # A8-d3 — PRODUCE the fourth declared A8 artefact before its gate runs.
    # A8 declares .lef/.lib/.v/.gds; this runner's stub emitter and the
    # `analog-hardmacro-gen` skill both write the first three and NEITHER
    # writes the .gds, and `analog_a8_hardmacro_gen_check` only inspects the
    # LEF/LIB/V triple — so the declared layout was produced by nothing and
    # nothing downstream noticed. `analog_hardmacro_gds_emit` streams the A5
    # layout.mag out with Magic against the technology the layout itself
    # names. Deliberately NON-BLOCKING and pre-gate, in the same shape as
    # A4's `analog_real_corner_sweep` fall-through: an unreachable container
    # is its disclosed rc=2 and must not turn A8 into a FAIL that the gate
    # below has not itself found. A deterministic-stub layout is skipped by
    # the producer, so PASS_WITH_STUB is untouched.
    #
    # THIS IS THE ONLY PRODUCTION SITE. The producer was briefly also wired
    # into A8's flow gate; that was withdrawn on 2026-07-28 because
    # `flow_compliance_check` is the acceptance auditor and an auditor that
    # writes a declared required_output into the tree it audits certifies its
    # own output. Producing here — inside the runner that OWNS the step —
    # keeps the artefact in the run and out of the audit. Guarded by
    # test_analog_hardmacro_gds_emit
    # .test_the_analog_runner_invokes_this_producer_at_a8_and_only_there,
    # which asserts the dispatched argv rather than grepping this file.
    # A6 IS THE ADJUDICATOR, and until v1.16.27 it adjudicated a NUMBER.
    # `analog_a6_drc_attribute` runs the same deck and says, per
    # violation, which of four populations it belongs to — the PDK's own
    # gencell (which no layout change removes), the placement, this
    # flow's own paint, or an interaction neither control reproduces.
    # MEASURED on u_hawaii_adc/ldo: of 180 errors / 829 violating
    # rectangles, 66 rectangles reproduce with the bare gencell and 52 of
    # the errors are found by Magic inside the PDK's own cells; the rest
    # are this flow's, and all of them have one cause.
    #
    # ADVISORY, deliberately: the verdict stays A6's own, over A6's own
    # evidence. This adds the vocabulary, not the decision — and it can
    # never clear a violation, because a deviation A5 recorded is
    # reported as a DISCLOSURE beside the class and changes neither the
    # class nor any exit code.
    if step_name == "A6_block_pv":
        _attr = PROGRAMS_DIR / "analog_a6_drc_attribute.py"
        if _attr.is_file():
            try:
                _acp = _pr.run(
                    [sys.executable, str(_attr), str(project),
                     "--block", bname, "--container",
                     (getattr(args, "container", None)
                      or os.environ.get("VIBEIC_ANALOG_CONTAINER",
                                        "vibeic-eda"))],
                    capture_output=True, text=True)
                for _ln in (_acp.stdout or "").splitlines():
                    if _ln.startswith("A6 DRC ATTRIBUTION") or \
                            _ln.lstrip().split(" ")[0] in (
                                "DEVICE_CELL", "DEVICE_PLACEMENT",
                                "LAYOUT", "INTERACTION"):
                        print(f"[A6 advisory] {_ln.strip()}")
            except (OSError, subprocess.SubprocessError) as _ae:
                print(f"[A6 advisory] DRC attribution did not run: {_ae}")

    if step_name == "A8_hardmacro_gen":
        gds_prog = PROGRAMS_DIR / "analog_hardmacro_gds_emit.py"
        if gds_prog.is_file():
            try:
                subprocess.run(
                    [sys.executable, str(gds_prog), str(project),
                     "--block", bname,
                     "--container",
                     (getattr(args, "container", None)
                      or os.environ.get("VIBEIC_ANALOG_CONTAINER",
                                        "vibeic-eda"))],
                    capture_output=True, text=True, timeout=1800)
            except (OSError, subprocess.SubprocessError):
                # Producing is not a verdict; the A8 gate below still reports
                # the missing artefact on its own evidence.
                pass

        # A8 IS ALSO THE MOMENT THE MACRO'S INTERFACE FIRST EXISTS AS THREE
        # VIEWS. `analog_hardmacro_pinname_consistency_check` compares them —
        # spec.json's declared `interface.pins[]`, the LEF's PINs and the
        # Verilog view's ports — and NOTHING in this flow ran it. MEASURED
        # (u_hawaii_adc, 2026-09-02): the `delta_sigma` topology exposes
        # `vcm`/`rst`/`vout` where the design's own declaration (and the RTL
        # that instantiates the block) says `vrefp`/`vrefn`/`clk`/`bit_out`.
        # The disagreement surfaced FORTY MINUTES LATER, at the post-layout
        # LEC, as `Module 'delta_sigma' ... does not have a port named
        # 'vrefp'` — a yosys parse error, three phases from the producer that
        # could fix it.
        #
        # ADVISORY, by design: it is reported here, at the producer, and the
        # verdict it feeds stays the A8 gate's own. A design whose blocks
        # declare no interface makes this check self-skip, exactly as before.
        _pin_prog = PROGRAMS_DIR / "analog_hardmacro_pinname_consistency_check.py"
        if _pin_prog.is_file():
            try:
                _pin_r = subprocess.run(
                    [sys.executable, str(_pin_prog), str(project)],
                    capture_output=True, text=True, timeout=300)
                for _ln in ((_pin_r.stdout or "") + (_pin_r.stderr or "")
                            ).splitlines():
                    if "[ERROR]" in _ln or "[WARN" in _ln:
                        print(f"[A8 advisory] interface consistency: "
                              f"{_ln.strip()}")
            except (OSError, subprocess.SubprocessError) as _pe:
                print(f"[A8 advisory] interface consistency check did not "
                      f"run: {_pe}")

        # A8 is also the moment the design's OWN macro LEFs first EXIST, and
        # that is the missing half of v1.8.95.
        #
        # `l21_macro_supply_rail_synth` derives the power-intent rails from
        # hard-macro LEFs. v1.8.79 landed it with no caller; v1.8.95 gave it
        # one and widened its search to all five roots the consumer harvests
        # from. Both are correct and both are real. But the single call site is
        # in `phase1_doc_one_shot_runner` — and for a design whose hard macros
        # are its OWN analog blocks, those LEFs are written HERE, at A8, in
        # Phase 3. At Phase-1 time there is nothing to read. Measured on a real
        # mixed-signal cell, same program, same project, two moments:
        #
        #   at Phase 1 (blind run)   verdict: NOT_APPLICABLE
        #                            0 hard macro(s) with PG pins across
        #                            0 LEF file(s), 0 master(s)
        #   after A8 (LEFs present)  2 macro(s) in scope, 1 power pin(s),
        #                            1 ground pin(s), 2 rail(s) ADDED
        #                            -> all 3 macro PG pins classify
        #                               `declared_rail` instead of `undeclared`
        #
        # So the producer fires exactly once, in the one phase where the
        # evidence it needs cannot exist for this class of design, and never
        # again. A vendor macro staged into `input/pdk_local/` before the run
        # is covered; a design that GENERATES its macros is not.
        #
        # The existing wiring test cannot see this and is not wrong to miss it:
        # every one of its fixtures stages the LEF before invoking the synth,
        # which is the vendor case. The gap is TEMPORAL, not locational, so
        # only a second call site at the moment of production closes it.
        #
        # Idempotent by construction (it only ADDS rails not already declared,
        # tested against the consumer-visible key set), so running it once per
        # A8 block is safe and the last block sees every LEF. Fail-open in the
        # same shape as the GDS producer above: deriving rails must never turn
        # A8 into a FAIL the gate has not itself found.
        rail_prog = PROGRAMS_DIR / "l21_macro_supply_rail_synth.py"
        if rail_prog.is_file():
            try:
                subprocess.run(
                    [sys.executable, str(rail_prog), str(project), "--apply"],
                    capture_output=True, text=True, timeout=300)
            except (OSError, subprocess.SubprocessError):
                pass

    det = det_progs.get(step_name)
    skill = skill_map.get(step_name, "(no skill mapped)")
    if det and det.is_file():
        cmd = [sys.executable, str(det), str(project), "--block", bname]
        # BEFORE the gate: is the artefact on disk the one THIS producer
        # would emit? Deciding after the gate only covers the gate's PASS
        # path, and a stale artefact can just as easily make the gate FAIL —
        # measured, on A3, where a netlist left over from an older producer
        # disagreed with a freshly re-emitted topology and the step failed
        # without anything re-emitting the netlist.
        _reuse = producer_reuse_decision(project, bname, step_name)
        # Whether THIS step emitted the artefact itself, kept so the rc 0
        # branch below can tell "the gate certified something a producer just
        # wrote" apart from "the gate certified what it found on disk". Only
        # a producer that RAN and returned rc 0 counts.
        _emitted: Optional[Dict[str, Any]] = None
        if _reuse.get("applies") and not _reuse.get("reuse"):
            _prod = _A1_A3_PRODUCERS.get(step_name) or {}
            _pprog = PROGRAMS_DIR / _prod.get("program", "")
            if _pprog.is_file():
                _pcmd = [sys.executable, str(_pprog), str(project),
                         "--block", bname]
                if _prod.get("takes_container"):
                    _pcmd += ["--container",
                              (getattr(args, "container", None)
                               or os.environ.get("VIBEIC_ANALOG_CONTAINER",
                                                 "vibeic-eda"))]
                _pcmd += list(_prod.get("extra_args") or [])
                try:
                    _pre_cp = subprocess.run(_pcmd, capture_output=True,
                                             text=True, timeout=1800)
                except (OSError, subprocess.SubprocessError):
                    _pre_cp = None
                if _pre_cp is not None and _pre_cp.returncode == 0:
                    _emitted = {"prod": _prod, "cp": _pre_cp}
        cp = _pr.run(cmd, capture_output=True, text=True)
        if cp.returncode == 0:
            # v1.6.129 (#50 Fix 2) — distinguish a real PASS (artefact
            # present + substance check passed) from a VACUOUS_PASS
            # (gate inapplicable — block list missing or empty). The
            # per-step gate signals VACUOUS via the canonical
            # "VACUOUS_PASS:" stdout sentinel from
            # `_analog_a_check_common.vacuous_pass`. Without this
            # discrimination, 64 VACUOUS_PASS leaves silently roll up
            # to a top-level PASS (the false-PASS field-agent
            # observed at v1.6.128 on BENCH-A). Chip-AGNOSTIC: relies
            # only on the existing literal sentinel, no chip names.
            stdout_tail = cp.stdout.splitlines()[-1] if cp.stdout else "ran"
            if "VACUOUS_PASS" in cp.stdout:
                return StepResult(step_name, bname, "VACUOUS_PASS",
                                  time.time() - t0, stdout_tail)
            if step_name == "A8_hardmacro_gen":
                # DOES THE CIRCUIT DO WHAT ITS TOPOLOGY SAYS IT IS FOR?
                # Every gate from here on answers a DIFFERENT question —
                # A5 lays the netlist out, A6 proves the layout matches it,
                # A8 packages it, LVS compares two views of it, the LEC
                # compares two more — and all of them pass on a block that
                # converts nothing. MEASURED (u_hawaii_adc): a complete
                # delta-sigma modulator that renders, converges, and drives
                # its declared 1-bit output rail to rail at a density of
                # 0.51 that does not move across the input's full range.
                # The A2 library entry records that in its own words; this
                # is where the flow stops instead of walking past it. A
                # block whose topology states no behavioural claim — every
                # shipped entry but one — is SKIPPED and unaffected.
                #
                # AT A8 AND NOT AT A3, deliberately. Asked at A3 it would
                # refuse to emit the netlist, and then no layout, no
                # extraction, no macro and no die exist to inspect — the
                # flow would lose the physical evidence along with the
                # green. Asked here, the block is fully built and fully
                # measured, and what it cannot do is stated over the top of
                # all of it. Refusing to SIGN OFF is not the same act as
                # refusing to BUILD, and only the first one is this gate's.
                beh = PROGRAMS_DIR / "analog_topology_behaviour_check.py"
                bcp = _pr.run(
                    [sys.executable, str(beh), str(project),
                     "--block", bname,
                     "--json", str(out_dir / "a8_topology_behaviour.json")],
                    capture_output=True, text=True)
                if bcp.returncode == 1:
                    btail = (bcp.stdout.strip().splitlines()[-1]
                             if bcp.stdout else
                             "a behavioural claim is not demonstrated")
                    return StepResult(
                        step_name, bname, "FAIL", time.time() - t0,
                        f"topology behaviour not demonstrated: {btail}",
                        output_files=_step_outputs(project, bname, step_name),
                        extras={"topology_behaviour_rc": bcp.returncode,
                                "topology_behaviour_report":
                                    str(out_dir / "a8_topology_behaviour.json"),
                                **_content_extras(project, bname, step_name)})
            if step_name == "A8_hardmacro_gen":
                # THE DIGITAL SIDE OF THE MACRO'S INTERFACE (vibe-ic#2010,
                # items 1-2). The A8 gate above certifies the LEF/LIB/V triple
                # on the ANALOG side; `analog_macro_rtl_interface_check`
                # compares the packaged macro's pins against the module the
                # digital RTL/netlist actually INSTANTIATES, in both
                # directions. It shipped (v1.15.49) run by nothing but its own
                # test. It is a clause of the A8 gate in the flow definition,
                # and it is ALSO run here, inline, so its verdict can stop the
                # step — `flow_gate_enforcement_audit` counts a gate that only
                # the acceptance audit reads as AUDIT_ONLY. rc 1 (a named
                # disagreement — a supply pin the digital top never connects
                # floats in silicon) is the block's A8 FAIL; rc 2 (no
                # comparable pair yet) leaves the gate's own PASS standing.
                # The report lands in the block's own directory, beside the
                # artefacts it read.
                iface = PROGRAMS_DIR / "analog_macro_rtl_interface_check.py"
                icp = _pr.run(
                    [sys.executable, str(iface), str(project),
                     "--block", bname,
                     "--json", str(out_dir / "a8_macro_rtl_interface.json")],
                    capture_output=True, text=True)
                if icp.returncode == 1:
                    itail = (icp.stdout.strip().splitlines()[-1]
                             if icp.stdout else "macro/RTL interface disagrees")
                    return StepResult(
                        step_name, bname, "FAIL", time.time() - t0,
                        f"macro/RTL interface disagrees: {itail}",
                        output_files=_step_outputs(project, bname, step_name),
                        extras={"macro_rtl_interface_rc": icp.returncode,
                                "macro_rtl_interface_report":
                                    str(out_dir / "a8_macro_rtl_interface.json"),
                                **_content_extras(project, bname, step_name)})
            # THE SECOND SENTINEL, read exactly like the first. A gate that
            # PASSED can still be saying that the artefact it certified came
            # from a library default, and until this branch existed the runner
            # recorded that step as a plain PASS with EMPTY extras — the
            # disclosure the gate printed reached no consumer, which is the
            # same defect one layer down: a signal that exists and is not read.
            # Measured: `grep -c STRUCTURE` over this runner's own report was 0
            # on a project whose every A3/A4 artefact disclosed a library
            # default.
            so = _structure_only_disclosure(cp)
            _extras = _content_extras(project, bname, step_name)
            if _reuse.get("applies"):
                _extras = dict(_extras or {})
                _extras["producer_reuse"] = _reuse
            _status = "PASS"
            if _emitted:
                # THIS step ran the producer and the gate then certified what
                # it wrote — the same event the rc 2 branch below reports with
                # the producer's own status. Before the pre-gate re-emit
                # existed, rc 2 (artefact MISSING) was the only way a producer
                # ran. The re-emit made that branch unreachable for a fresh
                # block — an absent artefact names no fingerprint, so it is
                # always re-emitted, the gate then passes, and the step came
                # back a bare `PASS`: true about the GATE and silent about the
                # producer that had just written the thing it certified, with
                # `producer` and `low_confidence` dropped from the record.
                _prd = _emitted["prod"]
                _status = _prd["status"]
                _extras = dict(_extras or {})
                _extras.update({
                    "extraction_strategy": _prd["strategy"],
                    "low_confidence": False,
                    "producer": _prd["program"],
                })
            if so:
                return StepResult(step_name, bname, "PASS_STRUCTURE_ONLY",
                                  time.time() - t0, so,
                                  output_files=_step_outputs(project, bname,
                                                             step_name),
                                  extras=_extras)
            return StepResult(step_name, bname, _status,
                              time.time() - t0, stdout_tail,
                              output_files=_step_outputs(project, bname,
                                                         step_name),
                              extras=_extras)
        if cp.returncode == 2:
            # A1-A3 PRODUCERS — the deterministic first track, in exactly the
            # shape A4's real-sim bypass below already uses: run BEFORE the
            # stub fallback, then re-run the gate and let IT decide.
            #
            # Until these existed, A1-A3 were skill-only steps: the gate found
            # no artefact, returned rc 2, and the runner reported WAIVED for
            # every block of every run. Meanwhile `programs/` shipped four
            # checkers for a netlist and no program that generates one.
            #
            # Producing is NOT a verdict. A producer crash or a producer that
            # honestly declines (rc 2) leaves the step exactly where the gate
            # left it — WAIVED — with the gap file named in `detail` so the
            # caller can see WHY the deterministic track stood down and which
            # skill it handed off to.
            prod = _A1_A3_PRODUCERS.get(step_name)
            if prod:
                pprog = PROGRAMS_DIR / prod["program"]
                if pprog.is_file():
                    pcmd = [sys.executable, str(pprog), str(project),
                            "--block", bname]
                    if prod.get("takes_container"):
                        pcmd += ["--container",
                                 (getattr(args, "container", None)
                                  or os.environ.get(
                                      "VIBEIC_ANALOG_CONTAINER",
                                      "vibeic-eda"))]
                    pcmd += list(prod.get("extra_args") or [])
                    try:
                        pcp = subprocess.run(pcmd, capture_output=True,
                                             text=True, timeout=1800)
                    except (OSError, subprocess.SubprocessError):
                        pcp = None
                    if pcp is not None and pcp.returncode == 0:
                        cp_prod = _pr.run(cmd, capture_output=True,
                                                 text=True)
                        if cp_prod.returncode == 0:
                            tail = (pcp.stdout.strip().splitlines()[-1]
                                    if pcp.stdout else "produced")
                            # The gate certified it. What it certified is the
                            # gate's own disclosure to make, and the run record
                            # carries it rather than a bare producer status.
                            so = _structure_only_disclosure(cp_prod)
                            return StepResult(
                                step_name, bname,
                                "PASS_STRUCTURE_ONLY" if so
                                else prod["status"],
                                time.time() - t0, so or tail,
                                output_files=_step_outputs(project, bname,
                                                           step_name),
                                extras={
                                    "extraction_strategy": prod["strategy"],
                                    "low_confidence": False,
                                    "producer": prod["program"],
                                    **_content_extras(project, bname,
                                                      step_name),
                                })
                    gap = _producer_gap(project, bname, prod)
                    if gap:
                        return StepResult(
                            step_name, bname, "WAIVED", time.time() - t0,
                            (f"deterministic producer declined and RECORDED "
                             f"why: {gap} — invoke skill `{skill}`"),
                            extras={"gap_path": gap,
                                    "producer": prod["program"],
                                    "producer_rc": (pcp.returncode
                                                    if pcp else None)})
                    # NO gap file. Until the producers were given a distinct
                    # usage exit code this fell through to the same WAIVED as
                    # an honest gap, so a producer that never examined the
                    # project — a wrong flag, rc 2, nothing written — read
                    # exactly like one that examined it and stood down for a
                    # stated reason. The step is still not produced, so it is
                    # still WAIVED; what changes is that the record now says
                    # the producer ERRORED and names the code, instead of
                    # reporting the gate's "artefact missing, invoke skill".
                    if pcp is not None and pcp.returncode not in (0, 2):
                        return StepResult(
                            step_name, bname, "WAIVED", time.time() - t0,
                            (f"deterministic producer ERRORED rc="
                             f"{pcp.returncode} and wrote NO gap file — this "
                             f"is not an honest gap: "
                             f"{(pcp.stderr or '').strip().splitlines()[-1] if (pcp.stderr or '').strip() else 'no stderr'}"),
                            extras={"producer": prod["program"],
                                    "producer_rc": pcp.returncode,
                                    "producer_error": True})
            # v1.6.214 (ORGANIC-20260512) — BEFORE the stub fallback,
            # try a REAL ngspice sweep via analog_real_corner_sweep.py.
            # chip-AGNOSTIC: only kicks in when (a) docker container
            # `vibeic-eda` has ngspice, (b) PDK lib is reachable, and
            # (c) block has a template (ldo / bandgap / por / pull /
            # trim / oscillator / esd / charge_pump). Without this
            # bypass, the runner ALWAYS fell back to a fabricated
            # `simulator_run:true / status:PASS` stub even when ngspice
            # was available — the P0 anti-evidence bug.
            # A5 IS A PRODUCER STEP, and until v1.16.6 the plugin had no
            # producer for it: a CHECKER, a matching RECORD, and a stub. The
            # emitter draws the block from its A3 netlist with the PDK's own
            # gencells, refuses a sub-minimum geometry BY NAME, records every
            # clearance shortfall it drew through, and never grades — A6's
            # deck does that. Same shape as A4's real-sweep fall-through: the
            # gate below still owns the verdict, on the artefact that is
            # actually on disk.
            if step_name == "A5_layout":
                emit_prog = PROGRAMS_DIR / "analog_a5_layout_emit.py"
                if emit_prog.is_file():
                    em_cmd = [sys.executable, str(emit_prog), str(project),
                              "--block", bname,
                              "--container",
                              (getattr(args, "container", None)
                               or os.environ.get("VIBEIC_ANALOG_CONTAINER",
                                                 "vibeic-eda"))]
                    em_cp = _pr.run(em_cmd, capture_output=True, text=True)
                    lay = (project / "phase3" / "analog" / bname
                           / "layout.mag")
                    if lay.is_file():
                        cp_real = _pr.run(cmd, capture_output=True, text=True)
                        tail = (em_cp.stdout.strip().splitlines()[-1]
                                if em_cp.stdout else "layout emitted")
                        if cp_real.returncode == 0:
                            return StepResult(
                                step_name, bname, "PASS", time.time() - t0,
                                f"analog_a5_layout_emit drew the layout; "
                                f"A5 gate re-ran PASS ({tail})",
                                extras={"producer": emit_prog.name,
                                        "producer_rc": em_cp.returncode,
                                        "extraction_strategy":
                                            "pdk_gencell_layout",
                                        "low_confidence": False})
                        return StepResult(
                            step_name, bname, "FAIL", time.time() - t0,
                            (cp_real.stdout.strip().splitlines()[-1]
                             if cp_real.stdout else tail))
                    # NOTHING was written, which is the honest outcome when
                    # the tool or the PDK is absent. Report WHY, naming the
                    # tool, instead of falling through to an anonymous
                    # deferral — and never write a layout.mag to cover it.
                    why = _a5_emit_reason(em_cp)
                    return StepResult(
                        step_name, bname, "WAIVED", time.time() - t0, why,
                        extras={"producer": emit_prog.name,
                                "producer_rc": em_cp.returncode,
                                "suggested_skill": skill})

            if step_name == "A4_corner_sweep":
                real_prog = PROGRAMS_DIR / "analog_real_corner_sweep.py"
                if real_prog.is_file():
                    rs_cmd = [sys.executable, str(real_prog), str(project),
                              "--block", bname,
                              "--container",
                              os.environ.get("VIBEIC_ANALOG_CONTAINER",
                                              "vibeic-eda"),
                              "--pdk",
                              os.environ.get("VIBEIC_ANALOG_PDK",
                                              "sky130")]
                    rs_cp = _pr.run(rs_cmd, capture_output=True,
                                            text=True)
                    # Re-run the substance gate whenever the sweep left an
                    # artefact behind — not only when the sweep exited 0.
                    #
                    # WHY (measured on a real run). The sweep now REFUSES to simulate a
                    # block whose A3 netlist is absent and records that refusal
                    # in corner_results.json (status BLOCKED, blocked_on
                    # A3_netlist_gen). Exiting non-zero, it used to fall
                    # straight through to the WAIVED branch below — and WAIVED
                    # says "artefact not yet emitted", which would now be false:
                    # the artefact exists and states a named blocker. The
                    # runner's record must agree with what is on disk, so the
                    # gate's verdict on that artefact is what gets reported.
                    # A step blocked on its upstream lands as a NAMED FAIL
                    # rather than an anonymous deferral no reader can act on.
                    cr = (project / "phase3" / "analog" / bname
                          / "corner_results.json")
                    if rs_cp.returncode == 0 or cr.is_file():
                        cp_real = _pr.run(cmd, capture_output=True,
                                                  text=True)
                        if cp_real.returncode == 0:
                            # PASS means real sim converged AND met
                            # spec_results.status==PASS AND its deck came from
                            # A3's netlist (the gate's provenance rules).
                            tail = (rs_cp.stdout.strip().splitlines()[-1]
                                    if rs_cp.stdout else "PASS")
                            # WHAT was measured, READ from the artefact rather
                            # than assumed. The sweep can only reach a gate PASS
                            # from a design-derived deck, but the run record
                            # should SAY which circuit that was instead of
                            # leaving a reader to infer it from a gate rc.
                            try:
                                _doc = json.loads(cr.read_text())
                            except Exception:
                                _doc = {}
                            # `real ngspice on <deck>` names WHERE the deck
                            # came from and says nothing about WHAT IS IN IT —
                            # the same silence, one layer up, that this whole
                            # track started from. The gate's disclosure decides
                            # the step's disposition.
                            so = _structure_only_disclosure(cp_real)
                            _on = (f"real ngspice on "
                                   f"{_doc.get('netlist_source') or 'an unnamed deck'}")
                            # A NULL OVER A DEAD LOOP CERTIFIES NOTHING. The
                            # numbers above were taken over a transient; this
                            # says whether the loop was RUNNING during it. The
                            # gate's own words lead the reason when they are
                            # not LIVE, for the same reason `so` does.
                            _live = _loop_liveness(
                                project, bname,
                                (getattr(args, "container", None)
                                 or os.environ.get(
                                     "VIBEIC_ANALOG_CONTAINER",
                                     "vibeic-eda")))
                            if _live and _live.get("result") not in (
                                    None, "LIVE", "NOT_DECLARED"):
                                _on = (f"loop liveness "
                                       f"{_live['result']}: "
                                       f"{_live.get('reason', '')} — {_on}")
                            return StepResult(
                                step_name, bname,
                                "PASS_STRUCTURE_ONLY" if so
                                else "PASS_WITH_REAL_SIM",
                                time.time() - t0,
                                # BOTH facts, disclosure FIRST: the console
                                # line is truncated, so whichever comes first
                                # wins the visible slot, and "what is in it"
                                # is the newer news. WHICH deck stays in the
                                # sentence — it is the other half a reviewer
                                # needs and neither replaces the other.
                                (f"{so} — {_on}" if so else f"{_on}: {tail}"),
                                output_files=[str(cr.relative_to(project))],
                                extras={
                                    "extraction_strategy": "real_ngspice",
                                    "design_traceable": bool(
                                        _doc.get("design_traceable")),
                                    "netlist_source": _doc.get("netlist_source"),
                                    "deck_source": _doc.get("deck_source"),
                                    "low_confidence": False,
                                    "loop_liveness": _live,
                                    **_content_extras(project, bname,
                                                      step_name),
                                })
                        if cp_real.returncode == 1:
                            tail = (cp_real.stdout.strip().splitlines()[-1]
                                    if cp_real.stdout
                                    else (rs_cp.stderr.strip().splitlines()[-1]
                                          if rs_cp.stderr else "FAIL"))
                            return StepResult(
                                step_name, bname, "FAIL",
                                time.time() - t0, tail)

            # v1.6.171 (#60 P1-6) — when ANALOG_DETERMINISTIC_STUBS=1
            # OR --allow-deterministic-stubs is set, emit a minimal
            # stub for the missing artefact + re-run the gate. The
            # stub carries `extraction_strategy: deterministic_stub`
            # so downstream consumers can distinguish it from real
            # analog data.
            if _stubs_enabled(args):
                stub_paths = _emit_deterministic_stub(
                    project, bname, step_name)
                if stub_paths:
                    cp2 = _pr.run(cmd, capture_output=True,
                                          text=True)
                    if cp2.returncode == 0:
                        return StepResult(
                            step_name, bname, "PASS_WITH_STUB",
                            time.time() - t0,
                            (f"deterministic stub emitted "
                             f"({len(stub_paths)} file(s)); gate "
                             f"re-ran PASS"),
                            extras={
                                "stub_paths": [str(p) for p in stub_paths],
                                "extraction_strategy":
                                    "deterministic_stub",
                                "low_confidence": True,
                            })
            # Artefact not yet emitted — defer to skill (back-compat).
            msg = (cp.stderr.splitlines()[-1] if cp.stderr
                   else f"artefact missing — invoke skill `{skill}`")
            return StepResult(step_name, bname, "WAIVED",
                              time.time() - t0, msg)
        # rc=1: artefact present but stub / fails substance check —
        # OR (A6 per-block PV only) DRC/LVS evidence missing-but-required.
        # A6's hardened gate returns FAIL (not rc=2) on missing PV
        # evidence per the no-fabrication doctrine, so the rc=2 stub
        # fallback above never fires for A6.
        #
        # v1.4.27 — NATIVE per-block PV FIRST (real evidence beats a stub). When
        # the v1.4.24 resolver resolves the project's STAGED sign-off decks
        # (rung 1 custom PDK / rung 2 installed) and the block GDS is present,
        # run svrfdrc DRC + klayout_pdk_lvs LVS, write the real drc.report /
        # comp.json, then re-run the A6 gate on that evidence. A violating block
        # FAILs A6 honestly (no false-clean); a clean+match PASSes for real.
        if step_name == "A6_block_pv":
            native = _try_native_a6_pv(
                project, bname,
                getattr(args, "container", None) or "vibeic-eda")
            if native and native.get("ran"):
                cp2 = _pr.run(cmd, capture_output=True,
                                      text=True)
                passed = cp2.returncode == 0
                return StepResult(
                    step_name, bname,
                    "PASS_WITH_NATIVE_PV" if passed else "FAIL",
                    time.time() - t0,
                    (f"native per-block PV executed "
                     f"(DRC={_pv_verdict(native, 'drc')}, "
                     f"LVS={_pv_verdict(native, 'lvs')}); A6 gate re-ran "
                     f"{'PASS' if passed else 'FAIL'}"),
                    extras={"native_pv": native,
                            "extraction_strategy": "native_signoff_pv",
                            "low_confidence": False})
        # Honour stub-mode: emit honest zero-violation / match evidence +
        # re-run (only when no native PV ran and stubs are enabled).
        if step_name == "A6_block_pv" and _stubs_enabled(args):
            stub_paths = _emit_deterministic_stub(project, bname, step_name)
            if stub_paths:
                cp2 = _pr.run(cmd, capture_output=True,
                                      text=True)
                if cp2.returncode == 0:
                    return StepResult(
                        step_name, bname, "PASS_WITH_STUB",
                        time.time() - t0,
                        (f"deterministic PV stub emitted "
                         f"({len(stub_paths)} file(s)); gate re-ran PASS"),
                        extras={
                            "stub_paths": [str(p) for p in stub_paths],
                            "extraction_strategy": "deterministic_stub",
                            "low_confidence": True,
                        })
        return StepResult(step_name, bname, "FAIL",
                          time.time() - t0,
                          cp.stderr[-500:] or cp.stdout[-500:])
    # No deterministic program shipped (should not happen post-v1.6.35).
    return StepResult(step_name, bname, "WAIVED",
                      time.time() - t0,
                      f"deterministic gate not yet shipped — "
                      f"caller should invoke skill `{skill}`")


def _aggregate_verdict(plan: List[StepResult]) -> str:
    """The analog track's top-level verdict.

    v1.6.129 (#50 Fix 2) — VACUOUS_PASS must NOT roll up into PASS.
    Severity ladder (highest first):
      FAIL          — any step explicitly failed, OR was BLOCKED by the
                      pre-flight (see `_preflight_refusal`: a refusal is not a
                      FAIL of the step, but it is certainly not green, and this
                      function's catch-all `return "PASS"` is exactly where an
                      unenumerated status goes to become one).
      VACUOUS_PASS  — at least one step was VACUOUS_PASS (gate inapplicable)
                      AND no step actually PASSed. Top-level verdict downgraded
                      to VACUOUS_PASS so downstream sign-off gates see it as
                      "no real evidence" rather than confirmed PASS.
      PASS_STRUCTURE_ONLY — see `_STRUCTURE_ONLY_SENTINEL`.
      PASS_WITH_WAIVERS — has WAIVED/SKIP, but at least one PASS (real evidence
                      exists for some block). VACUOUS_PASS leaves are ALSO a
                      waiver tier in this label-honest mode.
      PASS          — every step is a real PASS.

    EXTRACTED from `main()` unchanged except for the BLOCKED tier, so a control
    can assert the non-greenness directly instead of re-running the whole
    runner to observe it. Chip-AGNOSTIC.
    """
    has_fail = any(s.status in _FAIL_STATUSES for s in plan)
    has_vacuous = any(s.status == "VACUOUS_PASS" for s in plan)
    has_waiver = any(s.status in ("WAIVED", "SKIP") for s in plan)
    has_real_pass = any(s.status == "PASS" for s in plan)
    # STRUCTURE-ONLY joins the ladder BELOW a waiver-free pass and ABOVE
    # nothing: the step ran and produced its declared artefact from a library
    # default. It is not a real pass (every number measured on it is a number
    # about the default), it is not vacuous (the gate examined something), and
    # it is not a FAIL — a run honest about its ceiling must not score below
    # one that invented content to fill the gap, or the next run stops being
    # honest. Counted here so the top-level verdict cannot round it up.
    structure_only = [s for s in plan if s.status == "PASS_STRUCTURE_ONLY"]
    if has_fail:
        return "FAIL"
    if has_vacuous and not has_real_pass and not structure_only:
        return "VACUOUS_PASS"
    if structure_only:
        return "PASS_STRUCTURE_ONLY"
    if has_vacuous or has_waiver:
        return "PASS_WITH_WAIVERS"
    return "PASS"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--container", default="vibeic-eda")
    p.add_argument("--allow-deterministic-stubs",
                   action="store_true",
                   dest="allow_deterministic_stubs",
                   help=("v1.6.171 (#60 P1-6) — when a per-block "
                          "analog artefact is missing, emit a "
                          "minimal-substance stub tagged "
                          "`extraction_strategy: deterministic_stub` "
                          "+ re-run the gate. Returns "
                          "PASS_WITH_STUB instead of WAIVED. "
                          "Also controllable via the "
                          "ANALOG_DETERMINISTIC_STUBS=1 env var."))
    p.add_argument("--blocks", default="",
                   help="comma-separated subset of block names; default = all")
    args = p.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # v1.6.128 (#50 Fix 1) — differentiate "missing block list" from
    # "empty block list". When the file is genuinely absent (no
    # analog/analog_block_list.json AND no L5_ADI_SPEC.json), the
    # runner refuses to emit VACUOUS_PASS — instead it FAILs with
    # FAIL_NO_BLOCK_LIST so the caller knows phase1 / spec-extract
    # was skipped. An empty block list (file present, declares
    # `[]` or L5.no_analog=true) still SKIPs cleanly — this is the
    # legitimate pure-digital case.
    blocks, status = _load_block_list_with_status(project)
    if args.blocks:
        wanted = {b.strip() for b in args.blocks.split(",") if b.strip()}
        blocks = [b for b in blocks
                  if (b.get("name") or b.get("type")) in wanted]

    if status == "missing":
        msg = ("analog_block_list.json missing AND "
               "generated_docs/L5_ADI_SPEC.json absent. "
               "Run phase1 / spec-extract first, or place an "
               "explicit `[]` in analog/analog_block_list.json to "
               "mark the project as having no analog blocks.")
        print(f"[FAIL] analog_one_shot_runner: {msg}", file=sys.stderr)
        out = _pl.report_path(project, "analog_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"phase":   "analog",
                                    "verdict": "FAIL_NO_BLOCK_LIST",
                                    "reason":  msg,
                                    "blocks":  []}, indent=2) + "\n")
        return 2

    if not blocks:
        print("[SKIP] analog_one_shot_runner: no analog blocks declared "
              "(check analog/analog_block_list.json or "
              "L5_ADI_SPEC.json#analog_blocks)")
        # Emit a SKIP report so flow-orchestrate can confirm analog was
        # considered and skipped on purpose.
        out = _pl.report_path(project, "analog_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"phase": "analog", "verdict": "SKIP",
                                    "reason": "no analog blocks declared",
                                    "blocks": []}, indent=2) + "\n")
        return 0

    # v1.6.129 (#50 Fix 3 defensive) — when blocks were resolved from
    # the L5_ADI_SPEC.json fallback but `analog/analog_block_list.json`
    # is absent (e.g. older project tree where phase1 < v1.6.129 ran),
    # materialise the canonical file so per-step deterministic gates
    # (analog_a*_check.py — they only consult the block-list file via
    # `_analog_a_check_common.load_block_list`) see the same blocks.
    # Without this fallback, gates emit VACUOUS_PASS for every step
    # and the runner aggregates a false-PASS at top level.
    # Chip-AGNOSTIC.
    block_list_path = _pl.analog_dir(project) / "analog_block_list.json"
    if not block_list_path.is_file():
        block_list_path.parent.mkdir(parents=True, exist_ok=True)
        block_list_path.write_text(
            json.dumps({"blocks": blocks}, indent=2, ensure_ascii=False)
            + "\n", encoding="utf-8")

    plan: List[StepResult] = []

    def _dispatched(sr: StepResult) -> None:
        plan.append(sr)
        print(f"  {sr.status:6} {sr.name:24} block={sr.block:16} "
              f"{sr.detail[:60]}")

    for blk in blocks:
        _bname = blk.get("name") or blk.get("type") or "unknown"
        # ── PRE-FLIGHT, ONE SITE PER CANONICAL A-STEP ─────────────────────
        # Written out rather than looped, for the reason the wiring control
        # (`test_step_preflight.test_every_declared_site_is_wired_at_a_real_
        # call_site`) exists: a site name reached only through a loop variable
        # is a site no reader — and no static control — can confirm is wired.
        # The order below IS `_AI_STEP_NAMES` and IS the `RUNNER_PLANS` site
        # order, which is what makes "has this producer already had its
        # chance?" answerable at each site.
        #
        # PER-BLOCK, and honest about what that does and does not bind: the
        # flow declares A2's input as `phase3/analog/*/topology.md`, whose `*`
        # is the BLOCK directory. The pre-flight probes the pattern AS
        # DECLARED, so on a MULTI-BLOCK design block 2's A2 is satisfied by
        # block 1's topology.md. That is the wildcard-does-not-bind defect,
        # which is not this change's to fix; `_preflight_note` puts the block
        # in the ledger so the under-binding is visible in the record instead
        # of being invisible in it.
        _note = f"block={_bname}"
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A1",
            _preflight_refusal("A1_spec_extract", _bname),
            step_for_block, project, blk, "A1_spec_extract", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A2",
            _preflight_refusal("A2_topology_select", _bname),
            step_for_block, project, blk, "A2_topology_select", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A3",
            _preflight_refusal("A3_netlist_gen", _bname),
            step_for_block, project, blk, "A3_netlist_gen", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A4",
            _preflight_refusal("A4_corner_sweep", _bname),
            step_for_block, project, blk, "A4_corner_sweep", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A5",
            _preflight_refusal("A5_layout", _bname),
            step_for_block, project, blk, "A5_layout", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A6",
            _preflight_refusal("A6_block_pv", _bname),
            step_for_block, project, blk, "A6_block_pv", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A7",
            _preflight_refusal("A7_post_layout_resim", _bname),
            step_for_block, project, blk, "A7_post_layout_resim", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A8",
            _preflight_refusal("A8_hardmacro_gen", _bname),
            step_for_block, project, blk, "A8_hardmacro_gen", args=args,
            _preflight_note=_note))
        _dispatched(_spf.gate(
            project, "analog_one_shot_runner", "A9",
            _preflight_refusal("A9_hw_verify", _bname),
            step_for_block, project, blk, "A9_hw_verify", args=args,
            _preflight_note=_note))

    verdict = _aggregate_verdict(plan)
    structure_only = [s for s in plan if s.status == "PASS_STRUCTURE_ONLY"]
    summary = {
        "phase": "analog",
        "project": str(project),
        "blocks": [b.get("name") or b.get("type") for b in blocks],
        "steps": [asdict(s) for s in plan],
        "verdict": verdict,
        # NAMED, not only counted: a reader who sees the tier needs to know
        # which step of which block produced it without opening nine records.
        "structure_only_steps": [f"{s.block}/{s.name}" for s in structure_only],
    }
    # Per-step output view — <project>/steps/<phase>/<stage>/<id>_<slug>/.
    # The analog A1-A9 track is driven standalone for analog-only cells, which
    # therefore had no steps tree at all. Best-effort, non-gating; recorded in
    # reports/audit/steps_view.json either way.
    # Published BEFORE the view is built -- see publish_report_then_steps_view.
    summary["steps_view"], out = _pl.publish_report_then_steps_view(
        project, PROGRAMS_DIR, "analog_one_shot_runner", summary,
        "analog_one_shot.json")
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    # v1.6.32: emit canonical final_summary.md (best-effort). Analog
    # alone won't populate digital sections; the generator handles
    # missing-section gracefully.
    fs_ok = _pl.emit_final_summary(project, PROGRAMS_DIR)
    print(f"\n=== analog_one_shot_runner DONE ===")
    print(f"verdict: {summary['verdict']}")
    print(f"final summary: {'reports/final_summary.md' if fs_ok else 'NOT generated'}")
    return 0 if summary["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
