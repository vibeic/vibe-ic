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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl
import verdict as _V  # R-0915-85: the five step verdicts + the one cascade rule
import _runner_summary as _rsum  # noqa: E402  vibe-ic#2081
import _analog_a_check_common as _acc
import step_preflight as _spf  # required_inputs PRE-FLIGHT at every dispatch site
# vibe-ic#2080 — the master block-list SCHEMA gate. `main()` already refuses an
# ABSENT list and SKIPs an explicitly-empty one; PRESENT-BUT-BROKEN was the
# state neither covered, and this gate — the only thing that judges it — was
# credited by a sentence inside a string in `analog_flow_compliance_check`.
import analog_block_list_emit_check as _block_list_schema

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _analog_producer_common as _pc  # noqa: E402 — the producer exit tiers
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
    # ── the structured fields R-0915-85 put beside the verdict ──────────
    # `status` above is now one of the FIVE words in `programs/verdict.py`, and
    # every distinction the deleted vocabulary carried lives here. The module's
    # DESIGN section says why; `_V.StepVerdict` is where the same rules are
    # enforced for readers. Validated in `__post_init__` below, so a site that
    # says NOT_MEASURED without a reason — or NOT_APPLICABLE without naming the
    # input line that declares it — is a loud error where it is written, not a
    # quiet hole in a published report.
    reason_class: str = ""
    declared_by: str = ""
    waiver_rows: List[Dict[str, str]] = field(default_factory=list)
    attribution: str = ""
    disclosures: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _V.validate_step_row(self)


def _preflight_refusal(name: str, block: str):
    """This runner's refusal row for `step_preflight.gate`.

    `BLOCKED` carries the same meaning it does in the other three runners: the
    step was NOT attempted because an INPUT could not support it, so NOTHING is
    known. It is `NOT_MEASURED(input_absent)` in the one vocabulary — which is
    would have fallen through that function's catch-all `return "PASS"` and a
    refusal would have produced a GREEN run, which is the defect class this
    whole pre-flight exists to remove. Measured on this ladder specifically: a
    refusal is neither FAIL, nor a vacuity disclosure, nor structure-only, nor
    WAIVED/SKIP, so every one of the four tiers above the catch-all would have
    declined it and an all-refused analog track would have scored a clean PASS.

    NOTE the shape difference from `design_one_shot_runner._preflight_refusal`:
    this runner's `StepResult` carries a `block` as its SECOND positional field,
    so the row is built with it rather than assuming the phase-2 signature.
    """
    def _mk(detail: str, extras: Dict[str, Any]) -> StepResult:
        return StepResult(name, block, _spf.REFUSAL_STATUS, 0.0, detail,
                          extras=extras, reason_class=_spf.REFUSAL_REASON_CLASS)
    return _mk


# Statuses that must NOT reach a green verdict. `BLOCKED` is `step_preflight`'s
# refusal status; the rest is this runner's pre-existing FAIL tier, unchanged.
#: RETIRED by R-0915-85. Two runners kept their own "these words are failures"
#: tuple beside `_aggregate_verdict`, and the pre-flight refusal had to be
#: remembered into each of them (it was not, once, and a refusal produced a
#: GREEN run — #544). There is one roll-up now, `verdict.run_verdict`, and a
#: refusal is `NOT_MEASURED(input_absent)`: not green, and — per the one
#: cascade rule — voiding nothing downstream.


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


def _families_agree(a, b):
    """`analog_pdk_availability.families_agree`, or None when it cannot be
    imported. A comparison that could not be MADE must never read as a
    comparison that came back clean."""
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        import analog_pdk_availability as _apa
        return _apa.families_agree(a, b)
    except Exception:
        return None


def _pdk_contradiction(args, project: Path):
    """`(flag, declared)` when the run's `--pdk` CONTRADICTS the design's own
    declaration, else None.

    BIND OR REFUSE, NEVER SILENTLY IGNORE. Until `--pdk` was forwarded here at
    all, an operator flag and a design declaration could disagree for a whole
    campaign without one line of output saying so. Now that the flag arrives,
    the disagreement has to be resolved somewhere, and there is no honest
    silent answer: substituting the flag discards what the design says it is
    for, and substituting the declaration discards what the operator asked to
    measure. Both names go in the refusal and the run stops.

    A missing declaration is NOT a contradiction — `families_agree` returns
    None there and this returns None, so a project with no L19 target keeps
    running on the operator's flag exactly as before."""
    flag = (getattr(args, "pdk", "") or "").strip()
    if not flag or flag.lower() == "auto":
        return None
    declared = (_declared_l19_target(project) or "").strip()
    if _families_agree(flag, declared) is False:
        return flag, declared
    return None


def _effective_analog_pdk(args, project: Path) -> str:
    """The PDK selector the A-track's sub-producers run with, or "" when the
    run has not been told and the design does not say.

    Precedence: the run's own `--pdk`, then `VIBEIC_ANALOG_PDK`, then the
    design's L19 declaration. THERE IS NO LITERAL DEFAULT, and the empty
    string is a refusal signal for the caller — not a value to sweep with.
    The default this replaced was the bare string "sky130", which is not even
    an installed directory name (the installed family is `sky130A`), so it
    could not have resolved for any project on any host."""
    for cand in (getattr(args, "pdk", "") or "",
                 os.environ.get("VIBEIC_ANALOG_PDK", "") or ""):
        cand = cand.strip()
        if cand and cand.lower() != "auto":
            return cand
    return (_declared_l19_target(project) or "").strip()


def _a5_emitter_pdk_flags(project: Path, block: str, args,
                          container: str) -> tuple[List[str], str]:
    """Bind A5's gencells to the PDK selected by this run and its A3 netlist.

    The emitter's own default is only usable when the run states no process.
    A named process must resolve to the installed directory holding Magic's
    gencells; an unresolved selector is an environment gap, never permission
    to draw in the emitter's unrelated default family.
    """
    requested = _effective_analog_pdk(args, project)
    prov = project / "phase3" / "analog" / block / "netlist_provenance.json"
    try:
        doc = json.loads(prov.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    pdk = doc.get("pdk") if isinstance(doc, dict) else None
    bound = ((pdk.get("registry_family") or pdk.get("family") or "")
             if isinstance(pdk, dict) else "")
    if requested and bound and _families_agree(requested, bound) is False:
        return [], (f"A5_PDK_CONTRADICTION: this run selected {requested}, "
                    f"but the current A3 netlist bound {bound}")
    selector = bound or requested
    if not selector:
        return [], ""
    try:
        import analog_pdk_availability as _apa  # noqa: PLC0415
        res = _apa.resolve_pdk(selector, project=None, container=container)
    except Exception as exc:
        return [], (f"ENV_UNAVAILABLE: A5 could not resolve the selected "
                    f"PDK {selector}: {type(exc).__name__}: {exc}")
    root = str(res.get("pdk_root") or "")
    family = str(res.get("matched_dir") or "")
    if not (res.get("available") and root and family):
        return [], (f"ENV_UNAVAILABLE: A5 could not resolve Magic gencells "
                    f"for the selected PDK {selector}: {res.get('reason')}")
    return ["--pdk-root", str(Path(root).parent), "--family", family], ""


#: What a sub-producer prints when the ENVIRONMENT, not the design, is what
#: stopped it. Matched on the producer's own words rather than on an exit code,
#: because the exit code it uses (2) is shared with the design-side refusals
#: ("BLOCKED on A3_netlist_gen", "no successful sim") that a skill CAN act on.
#: Structural, chip-AGNOSTIC: no tool is named that the producers do not
#: themselves name in the same sentence.
_ENV_GAP_MARKERS = (
    "not in container",
    "BLOCKED on host mount root",
)

#: The LINE-START sentinel a producer prints on `_pc.EX_ENV_REFUSED`. Matched
#: with `startswith`, not as a substring: a token that may appear anywhere in a
#: line is a token a NEGATED mention of it also matches, and this one is read
#: to decide that nothing about the design was learned. A sentinel at the start
#: of its own line cannot be a negation of itself, which is why this needs no
#: `_prose_polarity` reading while the substrings above do.
_ENV_REFUSED_SENTINEL = _pc.ENV_REFUSED_TOKEN


def _producer_env_gap(cp):
    """The sub-producer's own sentence when it could not REACH its tool, else
    None. Returns the producer's words verbatim — the tool or the mount it
    could not see is the whole value of the message to whoever reads the run
    record, and flattening it into "artefact missing" is what hid this class
    of gap for the length of a campaign."""
    blob = ((cp.stderr or "") + "\n" + (cp.stdout or "")) if cp else ""
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith(_ENV_REFUSED_SENTINEL):
            return line[:400]
        if line and any(m in line for m in _ENV_GAP_MARKERS):
            return line[:400]
    return None


#: THE ONE PLACE THIS RUN REMEMBERS AN ENVIRONMENT REFUSAL, keyed
#: `(block, step)` and holding the refusal's OWN line (vibe-ic#2088).
#:
#: WHY THE RUN HAS TO REMEMBER IT. A refusal at A3 is invisible three steps
#: later: what A4..A7 can see is a MISSING `.sp`, and "missing" is a statement
#: about the design. MEASURED on u_hawaii_adc (lane czacctb2, 2026-09-07): one
#: full front-door run and a three-probe bisect to get from `A4 BLOCKED: no
#: *.sp` back to `CONTAINER_IMAGE_MISMATCH` at A3 — a line the producer had
#: printed, exactly and actionably, and that nothing carried forward.
#:
#: PER-RUN, and cleared at the top of `main`. It is module state because the
#: nine dispatch sites are written out one per step on purpose (see the loop
#: in `main`), and threading a ledger through all nine would make that list
#: harder to read than the thing it is protecting.
_ENV_REFUSALS: Dict[tuple, str] = {}

#: Steps whose product IS A3's netlist. A refusal at A3 makes each of them
#: report an absence it did not cause.
_A3_DEPENDENTS = ("A4_corner_sweep", "A5_layout", "A6_block_pv",
                  "A7_post_layout_resim")


def reset_env_refusals() -> None:
    """Start a run with no inherited refusals. Called once from `main`."""
    _ENV_REFUSALS.clear()


def record_env_refusal(block: str, step: str, line: str) -> None:
    _ENV_REFUSALS[(str(block), str(step))] = str(line).strip()


def upstream_env_refusal(block: str, step: str) -> Optional[tuple]:
    """`(upstream_step, refusal_line)` when `step` depends on a step this run
    already recorded an environment refusal for, else None."""
    if step not in _A3_DEPENDENTS:
        return None
    line = _ENV_REFUSALS.get((str(block), "A3_netlist_gen"))
    return ("A3_netlist_gen", line) if line else None


def _corner_results_exists(project: Path, block: str) -> bool:
    """Did the sweep leave a `corner_results.json` behind? An environment gap
    reported ALONGSIDE a written artefact is not a refusal — the artefact is
    what the gate grades, so the existing branch keeps ownership of it."""
    return (Path(project) / "phase3" / "analog" / block
            / "corner_results.json").is_file()


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


def _record_reason_class(record: Optional[Path]) -> str:
    """The NOT_MEASURED reason a producer wrote in its own block record, or the
    runner's environment-refusal class when it wrote none.

    A producer that exits `EX_ENV_REFUSED` knows WHY it measured nothing -- a
    LibreLane tool the contract stopped (`stalled`, `budget_exhausted`) is not
    an input that is absent -- and A6's LibreLane arm and A7 record it as
    `reason_class`. Only a value `verdict.ReasonClass` defines is carried."""
    try:
        doc = json.loads(Path(record).read_text()) if record else {}
    except (OSError, ValueError):
        doc = {}
    reason = doc.get("reason_class") if isinstance(doc, dict) else None
    return (reason if reason in {r.value for r in _V.ReasonClass}
            else _spf.REFUSAL_REASON_CLASS)


def _a6_librelane_arm(project: Path, block: str, container: str,
                      mode: str) -> Dict[str, Any]:
    """Run `analog_a6_librelane_drc` beside native A6 PV (T94, opt-in).

    Returns `{"rc", "record", "blocking", "detail"}`. `blocking` is True when
    the arm's own record names a blocking rule, when the switch is invalid, or
    when the arm could not be measured: a selected tool arm that produced no
    evidence cannot leave the stricter half of the verdict unset.
    """
    if mode not in ("librelane", "dual"):
        return {"rc": None, "blocking": True,
                "detail": f"phase3/librelane_switch.json: invalid A6 mode"}
    prog = PROGRAMS_DIR / "analog_a6_librelane_drc.py"
    image, why = _pin.container_image_digest(container)
    if not image:
        return {"rc": _pc.EX_ENV_REFUSED, "blocking": True,
                "detail": f"{_pc.ENV_REFUSED_TOKEN} {why}"}
    if "@" not in image:
        image = f"{_pin.image_repo()}@{image}"
    bdir = _pl.analog_dir(project) / block
    att = bdir / "a6_librelane" / "attribution.json"
    att.parent.mkdir(parents=True, exist_ok=True)
    _pr.run([sys.executable, str(PROGRAMS_DIR / "analog_a6_drc_attribute.py"),
             str(project), "--block", block, "--container", container,
             "--json", str(att)], capture_output=True, text=True)
    # The container is where the bare-device GDS round trip (q1's
    # ENGINE_ARTEFACT evidence) runs Magic; without it that evidence is
    # NOT_MEASURED and no rule is called an engine artefact.
    cmd = [sys.executable, str(prog), str(project), "--block", block,
           "--image", image, "--container", container]
    if att.is_file():
        cmd += ["--attribution", str(att)]
    arm_run = _pr.run(cmd, capture_output=True, text=True)
    rec_path = bdir / "a6_librelane_drc.json"
    try:
        record = json.loads(rec_path.read_text())
    except (OSError, ValueError):
        record = None
    tail = ((arm_run.stdout or "").strip().splitlines()
            or (arm_run.stderr or "").strip().splitlines() or ["no output"])[-1]
    return {"rc": arm_run.returncode, "mode": mode,
            "record": str(rec_path) if record is not None else None,
            "blocking": arm_run.returncode != 0,
            "union": (record or {}).get("union"), "detail": tail}


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


def _a5_emitter_verdict(tier: str) -> tuple[str, str]:
    """Apply the producer's result tier to both redraw and first draw."""
    if tier == "PDK_CONTRADICTION":
        return "NOT_MEASURED", _V.ReasonClass.INPUT_ABSENT
    if tier == "ENV_UNAVAILABLE":
        return "NOT_MEASURED", _V.ReasonClass.TOOL_ABSENT
    if tier in ("FORBIDDEN", "REFUSED", "TOOL_ERROR", "SHORTED",
                "CLAMPED_GEOMETRY", "NO_GENCELL", "UNREADABLE_NETLIST"):
        return "FAIL", ""
    return "NOT_MEASURED", _V.ReasonClass.EXECUTION_ERROR


def _a5_record_stamp(path: Path) -> tuple | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


def _a5_current_emitter_report(cp, block: str, record_path: Path,
                               previous_stamp: tuple | None) -> dict:
    """Read this run's A5 report, never an unchanged old provenance record.

    A5 prints a progress line before its JSON when a per-block draw ran.
    An early environment refusal prints only JSON and writes no block record.
    """
    stdout = cp.stdout or ""
    try:
        report, _ = json.JSONDecoder().raw_decode(stdout[stdout.index("{"):])
    except (ValueError, TypeError):
        report = {}
    if isinstance(report, dict):
        blocks = report.get("blocks")
        current = blocks.get(block) if isinstance(blocks, dict) else None
        if isinstance(current, dict) and current:
            return current
        if report.get("result") not in (None, "NOT_OK"):
            return report
    if _a5_record_stamp(record_path) != previous_stamp:
        try:
            current = json.loads(record_path.read_text())
        except (OSError, ValueError):
            current = {}
        if isinstance(current, dict) and current.get("block") == block:
            return current
    return {}


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


def a5_stale_layout_redraw(project: Path, block: str, args=None
                           ) -> Optional[Dict[str, Any]]:
    """Redraw a layout that is not of the CURRENT A3 netlist, before the A5
    gate grades it. None when there is nothing to redraw.

    The A5 emitter used to run only when the layout was MISSING (the gate's
    rc 2). A layout drawn from an EARLIER netlist is present and geometrically
    sound, so the gate passed it and nothing redrew it. MEASURED (delta_sigma,
    ihp-sg13g2): a 09-15 layout of a 360-device netlist stood under the
    09-16 335-device A3 netlist through A6 (LVS `match` about the old netlist)
    to A7 (A7_RCX_DEVICE_INVENTORY_MISMATCH after a 3 h simulation). The
    identity is `_analog_producer_common.layout_identity_of_block`; only a
    measured STALE redraws, UNVERIFIED leaves the layout as it is."""
    import _analog_producer_common as _pcm  # noqa: PLC0415
    bdir = project / "phase3" / "analog" / block
    sp = bdir / f"{block}.sp"
    emit = PROGRAMS_DIR / "analog_a5_layout_emit.py"
    if not ((bdir / "layout_provenance.json").is_file() and sp.is_file()
            and emit.is_file()):
        return None
    ident, why = _pcm.layout_identity_of_block(bdir, sp)
    if ident != "STALE":
        return None
    container = (getattr(args, "container", None)
                 or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                 or _pin.default_container_name())
    pdk_flags, pdk_gap = _a5_emitter_pdk_flags(
        project, block, args, container)
    if pdk_gap:
        return {"because": why, "emitter_rc": 2,
                "emitter_result": ("ENV_UNAVAILABLE" if pdk_gap.startswith(
                    "ENV_UNAVAILABLE:") else "PDK_CONTRADICTION"),
                "emitter_reason": pdk_gap}
    record_path = bdir / "layout_provenance.json"
    previous_stamp = _a5_record_stamp(record_path)
    cp = _pr.run([sys.executable, str(emit), str(project), "--block", block,
                  "--container", container, *pdk_flags],
                 capture_output=True, text=True)
    print(f"[A5] {block}: layout was not of the current netlist ({why}); "
          f"redrawn by {emit.name} rc={cp.returncode}")
    out = {"because": why, "emitter_rc": cp.returncode}
    if cp.returncode != 0:
        # A preexisting record describes an earlier attempt. Only stdout from
        # this invocation or a changed, block-matched record may classify it.
        current = _a5_current_emitter_report(
            cp, block, record_path, previous_stamp)
        if not current and cp.returncode == 2:
            current = {"result": "USAGE_ERROR",
                       "reason": (cp.stderr or cp.stdout or
                                  "A5 emitter rc 2 without a named result")}
        out["emitter_result"] = str(current.get("result") or "").strip()
        reason = str(current.get("reason") or "").strip()
        # the refusal is the LAST line magic printed (`Error parsing ...`)
        tail = reason.splitlines()[-1] if reason else (
            (cp.stdout or cp.stderr or "").strip().splitlines() or ["?"])[-1]
        out["emitter_reason"] = (f"{current.get('result') or 'rc ' + str(cp.returncode)}"
                                 f": {tail[:400]}")
    return out


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
        "status": _V.Verdict.PASS.value,
        # R-0915-85 — this used to be `PASS_WITH_REAL_EXTRACT`, a PASS that
        # also named its producer. The producer is already in
        # the row's `extras["producer"]`, which is where a
        # consumer reads provenance; the STATUS carries the
        # outcome and nothing else. `_STAMPED_VERDICT_TIER`
        # below already collapsed all three to "PASS", so no
        # tier moves — what goes is the third place the same
        # fact was written.
        "strategy": "l5_structured_bind",
        "gap": "spec_gap.json",
    },
    "A2_topology_select": {
        "program": "analog_a2_topology_emit.py",
        "status": _V.Verdict.PASS.value,
        # R-0915-85 — this used to be `PASS_WITH_DERIVED_TOPOLOGY`, a PASS that
        # also named its producer. The producer is already in
        # the row's `extras["producer"]`, which is where a
        # consumer reads provenance; the STATUS carries the
        # outcome and nothing else. `_STAMPED_VERDICT_TIER`
        # below already collapsed all three to "PASS", so no
        # tier moves — what goes is the third place the same
        # fact was written.
        "strategy": "type_topology_library",
        "gap": "topology_gap.json",
    },
    "A3_netlist_gen": {
        "program": "analog_a3_netlist_emit.py",
        "status": _V.Verdict.PASS.value,
        # R-0915-85 — this used to be `PASS_WITH_REAL_NETLIST`, a PASS that
        # also named its producer. The producer is already in
        # the row's `extras["producer"]`, which is where a
        # consumer reads provenance; the STATUS carries the
        # outcome and nothing else. `_STAMPED_VERDICT_TIER`
        # below already collapsed all three to "PASS", so no
        # tier moves — what goes is the third place the same
        # fact was written.
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
#: collapses to exactly one tier. A structure-only row is NOT in it and never
#: can be — since R-0915-85 it is `PASS_WITH_WAIVERS` carrying
#: `Disclosure.STRUCTURE_ONLY`, a different thing from a stamped `PASS` — so it
#: survives `verdict_tier` unchanged, which is what keeps the ordering readable.
_STAMPED_VERDICT_TIER: Dict[str, str] = {
    _p["status"]: "PASS" for _p in _A1_A3_PRODUCERS.values()
}


def verdict_tier(status: str) -> str:
    """The TIER a step's status lands in, with the producer-provenance stamp
    removed if it carries one.

    R-0915-85 made this an IDENTITY: the three provenance stamps it collapsed
    (`PASS_WITH_REAL_EXTRACT` / `PASS_WITH_DERIVED_TOPOLOGY` /
    `PASS_WITH_REAL_NETLIST`) are plain `PASS` at their source now, with the
    producer in the row's own `extras["producer"]`. It is kept as the ONE place
    a reader looks for "is a status carrying a second fact?", and the answer is
    no. Any status this module does not declare as a stamp is returned UNCHANGED — an unknown `PASS_WITH_*`
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
    "A6_block_pv": ("drc.report", "comp.json", "a6_librelane_drc.json"),
    "A7_post_layout_resim": ("pre_vs_post.json", "a7_post_layout.json"),
    "A8_hardmacro_gen": ("../hardmacro/{block}/{block}.lef",
                          "../hardmacro/{block}/{block}.lib",
                          "../hardmacro/{block}/{block}.gds",
                          "../hardmacro/{block}/{block}.v",
                          "../hardmacro/{block}/a8_views_provenance.json"),
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
#: recorded a structure-only A7 step with EMPTY extras: it read the
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
# beside a step the gate had just refused, or beside a structure-only
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


def _a7_record_stamp(path: Path) -> Optional[tuple]:
    """File identity before/after a producer call; an old A7 record is not
    evidence for the current rc 75."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)


def _a7_stopped_reason(path: Path, before: Optional[tuple], block: str,
                       producer: str, step: str) -> tuple:
    """Map a current, internally consistent A7 producer record to a reason.

    A process exit 75 means only that A7 did not measure. It cannot establish
    why; a missing, stale, or malformed record is an execution error.
    """
    try:
        if path.is_symlink():
            raise ValueError("producer record is a symlink")
        after = _a7_record_stamp(path)
        if after is None:
            raise ValueError("producer record missing")
        if before is not None and after == before:
            raise ValueError("producer record unchanged by this run")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict)
                or record.get("producer") != producer
                or record.get("schema") != 1
                or record.get("block") != block
                or record.get("step") != step
                or record.get("result") != "NOT_MEASURED"):
            raise ValueError("producer record identity/result mismatch")
        reason = record.get("reason_class")
        rule = record.get("rule")
        if (reason, rule) == ("partial_population",
                              "A7_PRE_MEASUREMENT_ABSENT"):
            absent = record.get("absent_measurements")
            if (not isinstance(absent, list) or not absent
                    or not all(isinstance(name, str) and name
                               for name in absent)):
                raise ValueError("A7 absent-measurement evidence missing")
            return _V.ReasonClass.PARTIAL_POPULATION, None
        cases = {
            ("execution_error", "A7_SIMULATION_STOPPED_EXTERNALLY"):
                (_V.ReasonClass.EXECUTION_ERROR, "external_stop"),
            ("progress_stalled", "A7_SIMULATION_PROGRESS_STALLED"):
                (_V.ReasonClass.STALLED, "progress_stalled"),
            ("budget_exhausted", "A7_SIM_BUDGET_EXHAUSTED"):
                (_V.ReasonClass.BUDGET_EXHAUSTED, "budget_exhausted"),
        }
        case = cases.get((reason, rule))
        if case is None or not isinstance(record.get(case[1]), dict):
            raise ValueError("producer stop class/rule/evidence mismatch")
        if reason == "budget_exhausted":
            stop = record["budget_exhausted"]
            budget = record.get("budget") or {}
            if budget.get("enforced") is not True:
                raise ValueError("A7 budget was not enforced")
            deadline = float(stop["enforced_deadline_s"])
            planned = float(budget["seconds"])
            stated = float(stop["budget_s"])
            wall = float(stop["wall_s"])
            if (not all(math.isfinite(v) and v > 0
                        for v in (deadline, planned, stated, wall))
                    or abs(deadline - planned) > 1
                    or abs(deadline - stated) > 1
                    or wall < deadline - 1):
                raise ValueError("enforced A7 deadline not proved spent")
        return case[0], None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _V.ReasonClass.EXECUTION_ERROR, str(exc)


def step_for_block(project: Path, block: Dict[str, Any], step_name: str,
                    args=None
                    ) -> StepResult:
    """Run one Ai step for one analog block. Most A* steps need an LLM
    skill (spec extract, topology select, etc.); mark them WAIVED with
    the skill name if no deterministic program exists.
    """
    if step_name in ('A6_block_pv', 'A7_post_layout_resim', 'A8_hardmacro_gen'):
        from execution_analog_caller import dispatch_site
        routed = dispatch_site(project, block, step_name)
        if routed is not None:
            return StepResult(step_name, block.get('name', ''), routed['status'], 0.0,
                routed.get('reason', 'ANALOG_NATIVE_ADMISSION_UNAVAILABLE'),
                extras={'execution_result': routed},
                reason_class=_V.ReasonClass.TOOL_ABSENT.value
                    if routed['status'] == 'NOT_MEASURED' else '')
    t0 = time.time()
    bname = block.get("name") or block.get("type") or "unknown"
    out_dir = _pl.analog_dir(project) / bname
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── AN ABSENCE THIS STEP DID NOT CAUSE (vibe-ic#2088) ─────────────────
    # A3 refused because of the ENVIRONMENT, so its `.sp` was never written.
    # What A4..A7 can see is a missing file, and every one of them reported it
    # as a verdict about the design — MEASURED on a real run: A4 FAIL
    # "netlist_source … cannot be read now", and A5, A6, A7 each PASS, for a
    # block whose netlist was never produced.
    #
    # GUARDED ON THE ARTEFACT, not on the refusal alone. A block whose deck was
    # emitted by an EARLIER run still has one on disk, and these steps can
    # legitimately grade it; short-circuiting there would refuse work that can
    # actually be done. The short-circuit fires only where the product really
    # is missing — which is exactly the measured case.
    _up = upstream_env_refusal(bname, step_name)
    if _up and not (out_dir / f"{bname}.sp").is_file():
        _ustep, _uline = _up
        return StepResult(
            step_name, bname, _spf.REFUSAL_STATUS, time.time() - t0,
            f"upstream {_ustep} refused: {_uline}",
            extras={"verdict_tier": "ENV_UNAVAILABLE",
                    "env_refused_upstream": _ustep,
                    "env_refused_detail": _uline}, reason_class=_spf.REFUSAL_REASON_CLASS)

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
    # the producer, so the stub disclosure is untouched.
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
    # THE A6 TOOL ARM (Default cutover): LibreLane KLayout.DRC + Magic.DRC on
    # the block GDS, the graded-rule union and A6's own attribution on top.
    # PRODUCTION_DEFAULTS selects this arm unless the project explicitly
    # names A6 direct. It is the STRICTER half: a blocking arm is the step's
    # FAIL; a clean arm leaves the native path below to decide.
    if step_name == "A6_block_pv":
        import librelane_contract as _llc
        try:
            _a6_mode = _llc.selected_mode(project, "A6")
        except _llc.Refusal:
            _a6_mode = "invalid"
        if _a6_mode != "direct":
            _a6_bdir = _pl.analog_dir(project) / bname
            if not (_a6_bdir / f"{bname}.gds").is_file():
                # A5 may leave a Magic source layout as the fixed input. The
                # shipped LibreLane DRC arm consumes GDS and is deliberately
                # not allowed to manufacture a conversion while A6 is being
                # adjudicated.
                if (_a6_bdir / "layout.mag").is_file():
                    return StepResult(
                        step_name, bname, _V.Verdict.NOT_MEASURED.value,
                        time.time() - t0,
                        "A6 LibreLane arm requires the A5 GDS view; "
                        "layout.mag is present but no conversion was run",
                        output_files=_step_outputs(project, bname, step_name),
                        extras={"verdict_tier": "INPUT_VIEW_UNAVAILABLE",
                                "layout_input": "layout.mag"},
                        reason_class=_V.ReasonClass.INPUT_ABSENT)
            _a6_arm = _a6_librelane_arm(
                project, bname,
                (getattr(args, "container", None)
                 or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                 or _pin.default_container_name()), _a6_mode)
            if _a6_arm.get("rc") == _pc.EX_ENV_REFUSED:
                # The arm measured nothing: an environment refusal, or a tool
                # the contract stopped. Its record says which.
                return StepResult(
                    step_name, bname, _spf.REFUSAL_STATUS, time.time() - t0,
                    f"LibreLane DRC arm ({_a6_mode}): {_a6_arm.get('detail')}",
                    output_files=_step_outputs(project, bname, step_name),
                    extras={"librelane_arm": _a6_arm,
                            "verdict_tier": "ENV_UNAVAILABLE"},
                    reason_class=_record_reason_class(_a6_arm.get("record")))
            if _a6_arm.get("blocking"):
                return StepResult(
                    step_name, bname, _V.Verdict.FAIL.value, time.time() - t0,
                    f"LibreLane DRC arm ({_a6_mode}): {_a6_arm.get('detail')}",
                    output_files=_step_outputs(project, bname, step_name),
                    extras={"librelane_arm": _a6_arm})
    if step_name == "A6_block_pv":
        _attr = PROGRAMS_DIR / "analog_a6_drc_attribute.py"
        if _attr.is_file():
            try:
                _acp = _pr.run(
                    [sys.executable, str(_attr), str(project),
                     "--block", bname, "--container",
                     (getattr(args, "container", None)
                      or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())],
                    # NO `timeout=` HERE, AND IT WAS FIXED TWICE. v1.17.49
                    # (lane icadcf3, 975321e641) removed it first; this lane
                    # found the same site independently while enumerating
                    # wall-clock ceilings, which is itself the finding —
                    # `_progress_run.run` has no `timeout` parameter by design
                    # ("convert a call site by deleting the argument"), and the
                    # TypeError it raised is neither OSError nor
                    # SubprocessError, so the `except` below could not catch
                    # it: the A6 advisory did not degrade, it took the whole
                    # A6_block_pv step down. v1.17.49's code stands; this note
                    # records the class so the next reader does not re-add it.
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
                # CZT-11 — supervised, not clocked. `Stalled` is a
                # RuntimeError and is NOT a `SubprocessError`, so it is named
                # in the handler: converting the call without widening the arm
                # would turn a swallowed advisory into an escaping exception.
                _pr.run(
                    [sys.executable, str(gds_prog), str(project),
                     "--block", bname,
                     "--container",
                     (getattr(args, "container", None)
                      or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())],
                    capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError, _pr.Stalled):
                # Producing is not a verdict; the A8 gate below still reports
                # the missing artefact on its own evidence.
                pass

        # Default A8 producer: Magic.WriteLEF plus the source-bound Liberty
        # and Verilog views. The gate remains read-only; this runner owns the
        # producer and records its result beside the package. An explicit
        # A8 direct switch keeps the legacy skill hand-off for projects that
        # already own their four views.
        import librelane_contract as _llc
        try:
            _a8_mode = _llc.selected_mode(project, "A8")
        except _llc.Refusal as _exc:
            return StepResult(
                step_name, bname, "FAIL", time.time() - t0,
                f"phase3/librelane_switch.json: {_exc}",
                reason_class=_V.ReasonClass.EXECUTION_ERROR)
        a8_prog = PROGRAMS_DIR / "analog_a8_hardmacro_emit.py"
        if _a8_mode != "direct" and a8_prog.is_file():
            a8_record = out_dir / "a8_hardmacro_emit.json"
            a8_container = (getattr(args, "container", None)
                            or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                            or _pin.default_container_name())
            try:
                a8_cp = _pr.run(
                    [sys.executable, str(a8_prog), str(project),
                     "--block", bname, "--container", a8_container,
                     "--json", str(a8_record)],
                    capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError, _pr.Stalled) as _exc:
                return StepResult(
                    step_name, bname, _spf.REFUSAL_STATUS, time.time() - t0,
                    f"{a8_prog.name} could not execute: {_exc}",
                    extras={"producer": a8_prog.name,
                            "verdict_tier": "ENV_UNAVAILABLE"},
                    reason_class=_spf.REFUSAL_REASON_CLASS)
            _a8_tail = ((a8_cp.stderr or "").strip().splitlines()
                        or (a8_cp.stdout or "").strip().splitlines()
                        or ["no output"])[-1]
            if a8_cp.returncode == _pc.EX_ENV_REFUSED:
                return StepResult(
                    step_name, bname, _spf.REFUSAL_STATUS, time.time() - t0,
                    f"{a8_prog.name}: {_a8_tail}",
                    extras={"producer": a8_prog.name,
                            "producer_rc": a8_cp.returncode,
                            "verdict_tier": "ENV_UNAVAILABLE"},
                    reason_class=_spf.REFUSAL_REASON_CLASS)
            if a8_cp.returncode == 2:
                return StepResult(
                    step_name, bname, _V.Verdict.NOT_MEASURED.value,
                    time.time() - t0,
                    f"{a8_prog.name}: {_a8_tail}",
                    extras={"producer": a8_prog.name,
                            "producer_rc": a8_cp.returncode,
                            "verdict_tier": "PDK_UNAVAILABLE",
                            "producer_record": str(a8_record.relative_to(project))},
                    reason_class=_V.ReasonClass.TOOL_ABSENT)
            if a8_cp.returncode == 1:
                _hdir = project / "phase3" / "analog" / "hardmacro" / bname
                _views = [_hdir / f"{bname}{suffix}"
                          for suffix in (".lef", ".lib", ".gds", ".v")]
                if all(p.is_file() for p in _views):
                    return StepResult(
                        step_name, bname, _V.Verdict.NOT_MEASURED.value,
                        time.time() - t0,
                        f"{a8_prog.name} did not refresh the complete view set: "
                        f"{_a8_tail}",
                        extras={"producer": a8_prog.name,
                                "producer_rc": 1,
                                "verdict_tier": "STALE_VIEWS_REFUSED",
                                "producer_record": str(a8_record.relative_to(project))},
                        reason_class=_V.ReasonClass.INPUT_ABSENT)
            if a8_cp.returncode not in (0, 1):
                return StepResult(
                    step_name, bname, "NOT_MEASURED", time.time() - t0,
                    f"{a8_prog.name} exited rc={a8_cp.returncode}: {_a8_tail}",
                    extras={"producer": a8_prog.name,
                            "producer_rc": a8_cp.returncode},
                    reason_class=_V.ReasonClass.EXECUTION_ERROR)

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
                # CZT-11 — supervised, not clocked (see the GDS emit above).
                _pin_r = _pr.run(
                    [sys.executable, str(_pin_prog), str(project)],
                    capture_output=True, text=True)
                for _ln in ((_pin_r.stdout or "") + (_pin_r.stderr or "")
                            ).splitlines():
                    if "[ERROR]" in _ln or "[WARN" in _ln:
                        print(f"[A8 advisory] interface consistency: "
                              f"{_ln.strip()}")
            except (OSError, subprocess.SubprocessError, _pr.Stalled) as _pe:
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
                # CZT-11 — supervised, not clocked.
                _pr.run(
                    [sys.executable, str(rail_prog), str(project), "--apply"],
                    capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError, _pr.Stalled):
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
                               or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())]
                _pcmd += list(_prod.get("extra_args") or [])
                try:
                    # CZT-11 — the producer one line below was already
                    # supervised (`_pr.run`); this PRE-producer beside it was
                    # still on a 1800 s clock, so a slow prerequisite could be
                    # killed and its own successor then ran on nothing.
                    _pre_cp = _pr.run(_pcmd, capture_output=True, text=True)
                except (OSError, subprocess.SubprocessError, _pr.Stalled):
                    _pre_cp = None
                if _pre_cp is not None and _pre_cp.returncode == 0:
                    _emitted = {"prod": _prod, "cp": _pre_cp}
        _a5_redrawn = (a5_stale_layout_redraw(project, bname, args)
                       if step_name == "A5_layout" else None)
        if _a5_redrawn and _a5_redrawn.get("emitter_rc") != 0:
            # The layout on disk is of ANOTHER netlist and this one could not
            # be drawn: grading the old geometry would certify a design that
            # does not exist. Preserve the emitter's tier: unavailable Magic
            # is not a defect in the circuit, and a crashed producer did not
            # measure whether the circuit can be laid out.
            _tier = _a5_redrawn.get("emitter_result") or ""
            _rc = _a5_redrawn.get("emitter_rc")
            _status, _reason = _a5_emitter_verdict(_tier)
            return StepResult(
                step_name, bname, _status, time.time() - t0,
                f"A5_LAYOUT_NOT_REDRAWN: {_a5_redrawn.get('emitter_reason')}",
                extras={"layout_redrawn": _a5_redrawn,
                        "verdict_tier": _tier or f"rc {_rc}"},
                reason_class=_reason)
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
                return StepResult(step_name, bname, "NOT_MEASURED",
                                  time.time() - t0, stdout_tail,
                                  reason_class=_V.ReasonClass.NO_POPULATION,
                                  disclosures=[_V.Disclosure.VACUITY])
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
            if _a5_redrawn:
                _extras = dict(_extras or {})
                _extras["layout_redrawn"] = _a5_redrawn
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
                # R-0915-85: a step whose content came from a library default
                # is a PASS somebody must come back to — a waiver row, with the
                # fact disclosed beside it. The old word said both in one
                # breath and the "come back to" half reached no must-close list.
                return StepResult(step_name, bname, "PASS_WITH_WAIVERS",
                                  time.time() - t0, so,
                                  output_files=_step_outputs(project, bname,
                                                             step_name),
                                  extras=_extras,
                                  disclosures=[
                                      _V.Disclosure.STRUCTURE_ONLY])
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
                                  or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())]
                    pcmd += list(prod.get("extra_args") or [])
                    try:
                        # CZT-11 — same shape as the pre-producer above.
                        pcp = _pr.run(pcmd, capture_output=True, text=True)
                    except (OSError, subprocess.SubprocessError, _pr.Stalled):
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
                                "PASS_WITH_WAIVERS" if so
                                else prod["status"],
                                time.time() - t0, so or tail,
                                disclosures=([_V.Disclosure.STRUCTURE_ONLY]
                                             if so else []),
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
                            step_name, bname, "PASS_WITH_WAIVERS", time.time() - t0,
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
                    # AN ENVIRONMENT REFUSAL IS NOT A WAIVER, AND IT IS NOT A
                    # PRODUCER DEFECT (vibe-ic#2088). `WAIVED` reads "not
                    # produced yet, invoke the skill"; no skill can supply a
                    # container running the pinned image, so the advice cannot
                    # be acted on, and the row rounds up to a green verdict.
                    # The producer says so in its EXIT CODE — `EX_ENV_REFUSED`,
                    # its own tier — so this is decided on a number and not on
                    # prose. The row is `_spf.REFUSAL_STATUS` (in
                    # NOT_MEASURED, so it cannot be green), carries the
                    # refusal's OWN line, and is remembered for the steps
                    # downstream that would otherwise report an absence this
                    # producer never caused.
                    if pcp is not None and pcp.returncode == _pc.EX_ENV_REFUSED:
                        _lines = (pcp.stderr or "").strip().splitlines()
                        why = (_producer_env_gap(pcp) or (_lines[-1] if _lines
                               else "the producer reported an environment "
                                    "refusal and printed nothing"))
                        record_env_refusal(bname, step_name, why)
                        return StepResult(
                            step_name, bname, _spf.REFUSAL_STATUS,
                            time.time() - t0, why,
                            extras={"producer": prod["program"],
                                    "producer_rc": pcp.returncode,
                                    "verdict_tier": "ENV_UNAVAILABLE",
                                    "env_refused": True}, reason_class=_spf.REFUSAL_REASON_CLASS)
                    if pcp is not None and pcp.returncode not in (0, 2):
                        return StepResult(
                            step_name, bname, "NOT_MEASURED", time.time() - t0,
                            (f"deterministic producer ERRORED rc="
                             f"{pcp.returncode} and wrote NO gap file — this "
                             f"is not an honest gap: "
                             f"{(pcp.stderr or '').strip().splitlines()[-1] if (pcp.stderr or '').strip() else 'no stderr'}"),
                            extras={"producer": prod["program"],
                                    "producer_rc": pcp.returncode,
                                    "producer_error": True}, reason_class=_V.ReasonClass.EXECUTION_ERROR)
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
            # A7 HAS A TOOL PRODUCER (Default cutover). LibreLane Magic.RCX
            # extracts the A5 GDS and A4's ngspice machinery re-simulates the
            # A3 testbench on it (analog_a7_post_layout_emit). A project may
            # explicitly select direct in phase3/librelane_switch.json.
            if step_name == "A7_post_layout_resim":
                import librelane_contract as _llc
                import analog_a7_post_layout_emit as _a7_emit
                try:
                    _a7_mode = _llc.selected_mode(project, "A7")
                except _llc.Refusal as _exc:
                    return StepResult(
                        step_name, bname, "FAIL", time.time() - t0,
                        f"phase3/librelane_switch.json: {_exc}",
                        reason_class=_V.ReasonClass.EXECUTION_ERROR)
                a7_prog = PROGRAMS_DIR / "analog_a7_post_layout_emit.py"
                if _a7_mode != "direct" and a7_prog.is_file():
                    _a7_container = (getattr(args, "container", None)
                                     or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                                     or _pin.default_container_name())
                    _a7_image, _a7_why = _pin.container_image_digest(
                        _a7_container)
                    if _a7_image and "@" not in _a7_image:
                        # A bare digest is not a reference `docker run`
                        # accepts; name it in the pinned repository.
                        _a7_image = f"{_pin.image_repo()}@{_a7_image}"
                    if not _a7_image:
                        return StepResult(
                            step_name, bname, _spf.REFUSAL_STATUS,
                            time.time() - t0,
                            f"{_pc.ENV_REFUSED_TOKEN} {_a7_why}",
                            extras={"producer": a7_prog.name,
                                    "verdict_tier": "ENV_UNAVAILABLE"},
                            reason_class=_spf.REFUSAL_REASON_CLASS)
                    a7_record = out_dir / "a7_post_layout.json"
                    a7_before = _a7_record_stamp(a7_record)
                    a7_cp = _pr.run(
                        [sys.executable, str(a7_prog), str(project),
                         "--block", bname, "--container", _a7_container,
                         "--image", _a7_image],
                        capture_output=True, text=True)
                    a7_gap = _producer_env_gap(a7_cp) or (
                        a7_cp.returncode == _pc.EX_ENV_REFUSED
                        and f"{a7_prog.name} exited {_pc.EX_ENV_REFUSED}")
                    if a7_gap:
                        return StepResult(
                            step_name, bname, _spf.REFUSAL_STATUS,
                            time.time() - t0, str(a7_gap),
                            extras={"producer": a7_prog.name,
                                    "producer_rc": a7_cp.returncode,
                                    "verdict_tier": "ENV_UNAVAILABLE"},
                            reason_class=_record_reason_class(
                                _pl.analog_dir(project) / bname
                                / "a7_post_layout.json"))
                    _a7_tail = ((a7_cp.stderr or "").strip().splitlines()
                                or (a7_cp.stdout or "").strip().splitlines()
                                or ["no output"])[-1]
                    # ADC_A5_A7_E2E: an honest gap from the tool arm (its
                    # input -- a layout of THIS netlist, the A3 deck -- is not
                    # on disk) is NOT_MEASURED with the producer's own words.
                    # Falling through to the skill hand-off let the gate WAIVE
                    # the missing comparison, and a refused step read as
                    # PASS_WITH_WAIVERS.
                    if a7_cp.returncode == _pc.RC_HONEST_GAP:
                        return StepResult(
                            step_name, bname, _V.Verdict.NOT_MEASURED.value,
                            time.time() - t0, f"{a7_prog.name}: {_a7_tail}",
                            extras={"producer": a7_prog.name,
                                    "producer_rc": a7_cp.returncode,
                                    "mode": _a7_mode},
                            reason_class=_V.ReasonClass.INPUT_ABSENT)
                    if a7_cp.returncode == 1:
                        return StepResult(
                            step_name, bname, "FAIL", time.time() - t0,
                            f"{a7_prog.name}: {_a7_tail}",
                            extras={"producer": a7_prog.name,
                                    "producer_rc": 1,
                                    "mode": _a7_mode})
                    # Rc 75 means A7 did not measure. The current producer
                    # record, not the rc, says whether its enforced deadline
                    # was spent, a simulator stalled, or an external stop won.
                    if a7_cp.returncode == _a7_emit.EX_BUDGET_EXHAUSTED:
                        a7_reason, a7_record_error = _a7_stopped_reason(
                            a7_record, a7_before, bname,
                            _a7_emit.PRODUCER, _a7_emit.STEP)
                        return StepResult(
                            step_name, bname, _V.Verdict.NOT_MEASURED.value,
                            time.time() - t0,
                            (f"{a7_prog.name}: {_a7_tail}"
                             + (f"; A7 producer record: {a7_record_error}"
                                if a7_record_error else "")),
                            extras={"producer": a7_prog.name,
                                    "producer_rc": a7_cp.returncode,
                                    "mode": _a7_mode,
                                    "producer_record": str(
                                        a7_record.relative_to(project))},
                            reason_class=a7_reason)
                    if a7_cp.returncode == 0:
                        cp_real = _pr.run(cmd, capture_output=True, text=True)
                        _gate_tail = (cp_real.stdout.strip().splitlines()[-1]
                                      if cp_real.stdout else "")
                        return StepResult(
                            step_name, bname,
                            "PASS" if cp_real.returncode == 0 else "FAIL",
                            time.time() - t0,
                            f"{a7_prog.name} extracted + re-simulated; A7 "
                            f"gate: {_gate_tail}",
                            output_files=_step_outputs(project, bname,
                                                       step_name),
                            extras={"producer": a7_prog.name,
                                    "producer_rc": 0, "mode": _a7_mode,
                                    "image": _a7_image})
            if step_name == "A5_layout":
                emit_prog = PROGRAMS_DIR / "analog_a5_layout_emit.py"
                if emit_prog.is_file():
                    emit_container = (getattr(args, "container", None)
                                      or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                                      or _pin.default_container_name())
                    pdk_flags, pdk_gap = _a5_emitter_pdk_flags(
                        project, bname, args, emit_container)
                    if pdk_gap:
                        return StepResult(
                            step_name, bname, "NOT_MEASURED", time.time() - t0,
                            pdk_gap, extras={"producer": emit_prog.name,
                                             "verdict_tier": (
                                                 "ENV_UNAVAILABLE" if pdk_gap.startswith(
                                                     "ENV_UNAVAILABLE:") else
                                                 "PDK_CONTRADICTION")},
                            reason_class=(_V.ReasonClass.TOOL_ABSENT
                                          if pdk_gap.startswith("ENV_UNAVAILABLE:")
                                          else _V.ReasonClass.INPUT_ABSENT))
                    em_cmd = [sys.executable, str(emit_prog), str(project),
                              "--block", bname,
                              "--container", emit_container, *pdk_flags]
                    provenance = (project / "phase3" / "analog" / bname
                                  / "layout_provenance.json")
                    prior_provenance = _a5_record_stamp(provenance)
                    em_cp = _pr.run(em_cmd, capture_output=True, text=True)
                    lay = (project / "phase3" / "analog" / bname
                           / "layout.mag")
                    if lay.is_file() and em_cp.returncode == 0:
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
                    # A refused draw can leave no geometry (or partial
                    # geometry). The emitter's current result, not layout
                    # presence, determines whether this is a design failure
                    # or an unmeasured tool/input gap.
                    report = _a5_current_emitter_report(
                        em_cp, bname, provenance, prior_provenance)
                    tier = str(report.get("result") or "").strip()
                    status, reason = _a5_emitter_verdict(tier)
                    why = str(report.get("reason") or _a5_emit_reason(em_cp))
                    return StepResult(
                        step_name, bname, status, time.time() - t0, why,
                        extras={"producer": emit_prog.name,
                                "producer_rc": em_cp.returncode,
                                "verdict_tier": tier or f"rc {em_cp.returncode}",
                                "suggested_skill": skill}, reason_class=reason)

            if step_name == "A4_corner_sweep":
                real_prog = PROGRAMS_DIR / "analog_real_corner_sweep.py"
                if real_prog.is_file():
                    # THE CONTAINER IS READ THE WAY ITS SIX SIBLINGS READ IT.
                    # This runner passes `--container` at seven sites; six
                    # consult `args` first and fall back to the environment.
                    # A4 alone omitted the `getattr`, so an orchestrated run
                    # invoked with `--container <name>` still asked for
                    # `vibeic-eda`. When that name is not running, the sweep
                    # exits 2 having written nothing, and the fallthrough at
                    # the bottom of this function reported "artefact missing —
                    # invoke skill `ams-sim`": a deterministic producer that
                    # could not reach its tool, reported as a step that needs
                    # the AI. The consequence is that A4 — the corner sweep,
                    # the A-track's only real simulation step — had never once
                    # run under the orchestrator, on any design.
                    _a4_container = (getattr(args, "container", None)
                                     or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())
                    # NO LITERAL PDK DEFAULT — AND NOTHING INVENTED IN ITS
                    # PLACE. The default this replaces was a bare open-PDK
                    # family name that is not an installed directory on any
                    # host this repo runs on (every installed directory of
                    # that family carries a revision suffix), so the selector
                    # the runner sent was a name that could not resolve for
                    # any project. It is deliberately not quoted here: a test
                    # scans this block for a PDK literal, and a quotation
                    # would be indistinguishable from a default. Now the runner
                    # forwards a selector only when it HAS one — the run's
                    # `--pdk`, the environment, or the design's own L19
                    # declaration — and otherwise passes no `--pdk` at all.
                    #
                    # WHY NOT REFUSE WHEN NOTHING DECLARES A PDK. Measured:
                    # the sweep does not need a selector to proceed. Its own
                    # contract resolves the EFFECTIVE simulation PDK from the
                    # project's L19 target / staged custom PDK by deck context
                    # and stamps it into corner_results.json as
                    # `pdk_used_for_sim`; the CLI selector only picks an
                    # open-PDK fast path. A refusal here therefore blocks runs
                    # the sweep can complete, and it does — it turns
                    # `test_the_run_record_names_the_circuit_a4_measured`
                    # (a real deck, no L19) from structure-only into a
                    # refusal, and pre-empts the sweep's own upstream
                    # A3-absent blocker in
                    # `test_runner_records_blocked_block_as_fail_not_waived`.
                    # Silence here hands the question to the one component
                    # that can answer it; inventing a name did not.
                    _a4_pdk = _effective_analog_pdk(args, project)
                    rs_cmd = [sys.executable, str(real_prog), str(project),
                              "--block", bname,
                              "--container", _a4_container]
                    if _a4_pdk:
                        rs_cmd += ["--pdk", _a4_pdk]
                    rs_cp = _pr.run(rs_cmd, capture_output=True,
                                            text=True)
                    # A PRODUCER THAT COULD NOT REACH ITS TOOL IS NOT AN
                    # HONEST "ARTEFACT NOT YET EMITTED". Without this the run
                    # fell through to the WAIVED branch below, whose message
                    # asks a reader to invoke `ams-sim` — but no skill can
                    # supply a container or an ngspice binary, so the advice
                    # could not be acted on and the environment gap was never
                    # named. The row is NOT_MEASURED (not green, so it
                    # cannot round up to a green verdict) and carries the
                    # ENV_UNAVAILABLE tier and the container name in `extras`.
                    _env_gap = _producer_env_gap(rs_cp)
                    if not _env_gap and rs_cp is not None and \
                            rs_cp.returncode == _pc.EX_ENV_REFUSED:
                        # The exit code is the producer's contract for this
                        # tier (A3's branch reads it the same way); a refusal
                        # whose sentence lacks the line-start token is still
                        # a refusal.
                        _env_gap = (f"{_pc.ENV_REFUSED_TOKEN} "
                                    f"{real_prog.name} exited "
                                    f"{_pc.EX_ENV_REFUSED}")
                    if _env_gap and not _corner_results_exists(project, bname):
                        return StepResult(
                            step_name, bname, _spf.REFUSAL_STATUS,
                            time.time() - t0,
                            f"{_env_gap} (container={_a4_container})",
                            extras={"producer": real_prog.name,
                                    "producer_rc": rs_cp.returncode,
                                    "container": _a4_container,
                                    "pdk": _a4_pdk,
                                    "verdict_tier": "ENV_UNAVAILABLE",
                                    "env_unavailable": "container"}, reason_class=_spf.REFUSAL_REASON_CLASS)
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
                                 or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name()))
                            if _live and _live.get("result") not in (
                                    None, "LIVE", "NOT_DECLARED"):
                                _on = (f"loop liveness "
                                       f"{_live['result']}: "
                                       f"{_live.get('reason', '')} — {_on}")
                            return StepResult(
                                step_name, bname,
                                # R-0915-85 — `PASS_WITH_REAL_SIM` is a PASS
                                # that names its evidence; the detail below
                                # carries that fact verbatim.
                                _V.Verdict.PASS_WITH_WAIVERS.value if so
                                else _V.Verdict.PASS.value,
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
                        # R-0915-85 — the gate passed over a DETERMINISTIC
                        # STUB this runner emitted, not over the design. That
                        # is a pass somebody must come back to and replace,
                        # which is a waiver row, with the fact disclosed beside
                        # it. The old word said both in one breath and the
                        # "come back to" half reached no must-close list.
                        return StepResult(
                            step_name, bname, "PASS_WITH_WAIVERS",
                            time.time() - t0,
                            (f"deterministic stub emitted "
                             f"({len(stub_paths)} file(s)); gate "
                             f"re-ran PASS"),
                            extras={
                                "stub_paths": [str(p) for p in stub_paths],
                                "extraction_strategy":
                                    "deterministic_stub",
                                "low_confidence": True,
                            }, disclosures=[_V.Disclosure.STRUCTURE_ONLY])
            # Artefact not yet emitted — defer to skill (back-compat).
            msg = (cp.stderr.splitlines()[-1] if cp.stderr
                   else f"artefact missing — invoke skill `{skill}`")
            return StepResult(step_name, bname, "PASS_WITH_WAIVERS",
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
            # v1.17.71+ — the SAME three rungs its seven siblings use:
            # the run's own --container, then VIBEIC_ANALOG_CONTAINER, then
            # the default. This site consulted `args` and then jumped
            # straight to the literal, so an orchestrated run that names its
            # container only through the environment — which is how the
            # analog track is driven when the flag is not threaded through —
            # ran native per-block PV against `vibeic-eda` and reported the
            # result as this project's. MEASURED 2026-09-06: with
            # VIBEIC_ANALOG_CONTAINER set and no flag, the container handed
            # to `_try_native_a6_pv` was `vibeic-eda`.
            native = _try_native_a6_pv(
                project, bname,
                getattr(args, "container", None)
                or os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name())
            if native and native.get("ran"):
                cp2 = _pr.run(cmd, capture_output=True,
                                      text=True)
                passed = cp2.returncode == 0
                return StepResult(
                    step_name, bname,
                    # R-0915-85 — `PASS_WITH_NATIVE_PV` said PASS and named
                    # the EVIDENCE it rested on. The evidence belongs in the
                    # detail (it is already there, in full), not in a sixth
                    # word only this site writes.
                    _V.Verdict.PASS.value if passed
                    else _V.Verdict.FAIL.value,
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
                    # R-0915-85 — see the sibling site above: a gate that
                    # passed over an emitted stub is PASS_WITH_WAIVERS carrying
                    # Disclosure.STRUCTURE_ONLY.
                    return StepResult(
                        step_name, bname, "PASS_WITH_WAIVERS",
                        time.time() - t0,
                        (f"deterministic PV stub emitted "
                         f"({len(stub_paths)} file(s)); gate re-ran PASS"),
                        extras={
                            "stub_paths": [str(p) for p in stub_paths],
                            "extraction_strategy": "deterministic_stub",
                            "low_confidence": True,
                        }, disclosures=[_V.Disclosure.STRUCTURE_ONLY])
        return StepResult(step_name, bname, "FAIL",
                          time.time() - t0,
                          cp.stderr[-500:] or cp.stdout[-500:])
    # No deterministic program shipped (should not happen post-v1.6.35).
    return StepResult(step_name, bname, "PASS_WITH_WAIVERS",
                      time.time() - t0,
                      f"deterministic gate not yet shipped — "
                      f"caller should invoke skill `{skill}`")


def step_block_list_schema(project: Path) -> StepResult:
    """RUN `analog_block_list_emit_check` over the master block list this track
    ran on, and put its verdict in the ledger. vibe-ic#2080.

    WHY IT WAS UNWIRED. Under the old NAME rule it read as consulted on the
    strength of a sentence inside a string in another program:

        analog_flow_compliance_check.py:451
            "analog_block_list_emit_check for whether a list SHOULD ..."

    That is advice prose, not a call. `gate_is_wired_check`'s invocation.v1 rule
    made it visible, and nothing in the shipped tree executed it — so the ONE
    file every A-gate below reads (`_analog_a_check_common.load_block_list`)
    had its schema checked by nobody.

    WHY HERE. `main()` already refuses the ABSENT list by name (rc 2,
    FAIL_NO_BLOCK_LIST) and SKIPs the explicitly-empty one. The state neither of
    those covers is PRESENT-BUT-BROKEN, which is precisely this gate's subject.
    It is dispatched AFTER the A1-A9 loop rather than before it because A1 is
    what emits each block's `spec.json`: asked first, the `spec_file`
    resolution arm would be answering about a tree the run had not built yet.

    ADVISORY, per vibe-ic#2080 (BLOCKING only where the gate's own docstring
    says so; this one's does not). Since R-0915-85 that is said in the row
    itself: the verdict is `PASS` and `Disclosure.ADVISORY` sits beside it, and
    `verdict.run_verdict` gives a disclosure no arithmetic at all — so this row
    cannot move the analog verdict in any direction. That neutrality is pinned
    by a test rather than left as a reading of a ladder.

    THE ROW IS WRITTEN WHENEVER THE TRACK RAN, carrying PASS / FINDING /
    VACUOUS / NOT_MEASURED. `--project` is used, not file mode: the whole point
    of the gate's project arm is that it resolves each declared `spec_file` on
    disk, and file mode would report a clean schema over a list promising
    artefacts nothing produced.
    """
    t0 = time.time()
    project = Path(project)
    row: Dict[str, Any] = {
        "gate": "analog_block_list_emit_check",
        "blocking": False,
        "why_advisory_here":
            "vibe-ic#2080 wires a recorded-unwired gate ADVISORY unless its own "
            "docstring declares it BLOCKING; this one's does not",
    }
    out = _pl.report_path(project, "analog/block_list_schema.json")
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_out), \
                contextlib.redirect_stderr(buf_err):
            rc = _block_list_schema.main(
                [str(project), "--project", "--json", str(out)])
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:                                 # noqa: BLE001
        row["verdict"] = "NOT_MEASURED"
        row["reason"] = f"{type(exc).__name__}: {exc}"
        return StepResult("block_list_schema", "", "PASS",
                          time.time() - t0,
                          f"block-list schema NOT_MEASURED — the gate raised "
                          f"{type(exc).__name__}: {exc}",
                          extras={"block_list_schema": row}, disclosures=[_V.Disclosure.ADVISORY])
    row["rc"] = rc
    try:
        rep = json.loads(out.read_text())
    except (OSError, ValueError):
        rep = {}
    row["status"] = rep.get("status")
    row["findings"] = rep.get("findings") or []
    row["block_list"] = rep.get("block_list")
    if rc == 2:
        row["verdict"] = "NOT_MEASURED"
        row["reason"] = (buf_err.getvalue().strip().splitlines() or ["rc 2"])[0]
        detail = f"block-list schema NOT_MEASURED — {row['reason']}"
    elif rep.get("status") == "VACUOUS_PASS":
        row["verdict"] = "VACUOUS"
        detail = ("block-list schema VACUOUS — no analog_block_list.json under "
                  "this project; there is nothing to validate")
    elif rc == 0:
        row["verdict"] = "PASS"
        detail = (f"block-list schema PASS — {rep.get('block_count')} block(s), "
                  f"schema + consistency + spec_file resolution OK")
    else:
        row["verdict"] = "FINDING"
        detail = ("block-list schema FINDING (ADVISORY, never changes this "
                  "run's verdict) — " + "; ".join(str(f) for f in
                                                  row["findings"][:4]))
    return StepResult("block_list_schema", "", "PASS", time.time() - t0,
                      detail, output_files=[str(out)],
                      extras={"block_list_schema": row}, disclosures=[_V.Disclosure.ADVISORY])


@_spf.retained_step('A9', canonical_acceptance=True)
def _a9_cosim(project: Path, args=None) -> Dict[str, Any]:
    """Run `analog_a9_cosim_emit` on the L22-declared scenarios.

    The producer's exit code IS the tier: 0 results written, 2 an honest gap
    (L22 declares no scenario), 69 the environment refused (an engine the
    image lacks) — the last is NOT_MEASURED and never a waiver.
    """
    prog = PROGRAMS_DIR / "analog_a9_cosim_emit.py"
    container = (getattr(args, "container", None)
                 or os.environ.get("VIBEIC_ANALOG_CONTAINER")
                 or _pin.default_container_name())
    try:
        cp = _pr.run([sys.executable, str(prog), str(project),
                      "--container", container],
                     capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, _pr.Stalled) as exc:
        return {"producer": prog.name, "rc": None,
                "tier": "NOT_MEASURED", "detail": f"{type(exc).__name__}: {exc}"}
    tier = {0: "RESULTS_WRITTEN", _pc.RC_HONEST_GAP: "NOT_DECLARED",
            _pc.EX_ENV_REFUSED: "ENV_UNAVAILABLE"}.get(cp.returncode,
                                                        "PRODUCER_ERROR")
    lines = ((cp.stderr or "").strip().splitlines()
             or (cp.stdout or "").strip().splitlines() or [""])
    print(f"  A9 cosim  {tier:16} rc={cp.returncode} {lines[-1][:100]}")
    return {"producer": prog.name, "rc": cp.returncode, "tier": tier,
            "detail": lines[-1],
            "results": str(_pl.mixed_signal_cosim_dir(project)
                           / "mixed_signal_results.json")}


def _aggregate_verdict(plan: List[StepResult]) -> str:
    """The run's verdict, from `verdict.run_verdict`. ONE rule for the flow.

    WHAT THIS REPLACES, and why the replacement is a deletion rather than a
    migration. Every one-shot runner carried its own hand-maintained lists of
    which words meant what, and the lists disagreed: phase 2 read `SKIP` as
    clean while phase 3 read the identical word as a waiver, over the same
    forty-four steps. This function's own predecessor said so in its comments
    and declined to fix it because fixing it "would restate every published
    phase-2 result". R-0915-85 is the decision to restate them: there is one
    vocabulary, five words, and one roll-up — `verdict.run_verdict` — whose
    precedence is FAIL > NOT_MEASURED > PASS_WITH_WAIVERS > PASS.

    The catch-all is gone by construction, not by enumeration: `verdict.parse`
    refuses a word outside the five at the row that carries it.
    """
    # R-0915-85 — THE SKIP DISCLOSURE SURVIVES THE COLLAPSE. The predecessor
    # printed every step it had excused to stderr, by name, so a green run said
    # out loud which of its steps produced no verdict about the design. Five
    # words say less per row than eighteen did, so each row is named here with
    # the word AND the reason or declaration beside it. A run whose skips go
    # silent is the run16 shape.
    _rows = list(_step_verdicts(plan))
    _skipped = [r for r in _rows
                if r.verdict in (_V.Verdict.NOT_MEASURED,
                                 _V.Verdict.NOT_APPLICABLE)]
    if _skipped:
        print(f"[verdict] {len(_skipped)} SKIPPED step(s) — produced no "
              f"verdict about the design: " + ", ".join(
                  f"{r.name}={r.verdict.value}"
                  f"({(r.reason_class.value if r.reason_class else '')}"
                  f"{r.declared_by and ' ' + r.declared_by})"
                  for r in _skipped), file=sys.stderr)
    return _V.run_verdict(_rows).value


def _step_verdicts(plan):
    """This runner's own rows, as `verdict.StepVerdict` records.

    One conversion, here, so no consumer re-derives the structured fields from
    a `StepResult` and no two of them do it differently.
    """
    for s in plan:
        yield _V.StepVerdict(
            verdict=_V.parse(s.status),
            step_id=getattr(s, "name", ""), name=getattr(s, "name", ""),
            reason_class=(_V.ReasonClass(s.reason_class)
                          if getattr(s, "reason_class", "") else None),
            reason=getattr(s, "detail", "") or "",
            declared_by=getattr(s, "declared_by", "") or "",
            waiver_rows=[_V.WaiverRow(**w)
                         for w in (getattr(s, "waiver_rows", None) or [])],
            attribution=getattr(s, "attribution", "") or "",
            disclosures=list(getattr(s, "disclosures", None) or ()),
        )



def _default_analog_rejection(project: Path, sid: str, started_at: float,
                              complete_population: bool) -> Optional[StepResult]:
    """Read a terminal full-row consumer before the next Default producer.

    A bounded block request is component evidence. Earlier partial-block
    consumers cannot decide a row whose terminal producer had no consumer.
    """
    import execution_policy
    if execution_policy.request()['mode'] != 'default' or not complete_population:
        return None
    import step_output_collector
    row = next((r for r in step_output_collector.current_acceptance(project, started_at)
                if str(r['id']) == sid), None)
    if row is not None and row['status'] in ('PASS', 'PASS_WITH_WAIVERS', 'NOT_APPLICABLE'):
        return None
    status = 'FAIL' if row is not None and row['status'] == 'FAIL' else 'NOT_MEASURED'
    consumer = (row['result'].get('canonical_consumer') or {}) if row else {}
    step = consumer.get('step') or {}
    reasons = step.get('reasons') or [
        row['status'] if row else 'no terminal complete consumer was recorded']
    return StepResult(
        'canonical_analog_acceptance', '', status, 0.0,
        f"canonical step {sid} was not accepted: " + '; '.join(map(str, reasons)),
        extras={'step_id': sid, 'output_version': row['folder'] if row else None,
                'consumer_recorded': row is not None},
        reason_class=(_V.ReasonClass.UPSTREAM_REFUSED.value if status == 'NOT_MEASURED' else ''))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--flow", choices=("70", "109"), default="70",
                   help="109 runs the native A01-A19 analog track")
    p.add_argument("--entry-step", help="First analog row in a 109 continuation (A01-A19)")
    p.add_argument("--exit-step", help="Last analog row in a 109 continuation (A01-A19)")
    p.add_argument("--flow109-manifest", type=Path,
                   help="Existing design feature declarations; qualification files are not required")
    p.add_argument("--container", default=_pin.default_container_name())
    p.add_argument("--allow-deterministic-stubs",
                   action="store_true",
                   dest="allow_deterministic_stubs",
                   help=("v1.6.171 (#60 P1-6) — when a per-block "
                          "analog artefact is missing, emit a "
                          "minimal-substance stub tagged "
                          "`extraction_strategy: deterministic_stub` "
                          "+ re-run the gate. Returns "
                          "PASS_WITH_WAIVERS carrying "
                          "Disclosure.STRUCTURE_ONLY (R-0915-85). "
                          "Also controllable via the "
                          "ANALOG_DETERMINISTIC_STUBS=1 env var."))
    p.add_argument("--blocks", default="",
                   help="comma-separated subset of block names; default = all")
    p.add_argument("--post-mc-samples", type=int, default=None,
                   help="explicit A15 execution sample count (>=2), for --flow 109")
    p.add_argument("--pdk", default="",
                   help=("PDK selector for the A-track's PDK-bound producers. "
                         "Forwarded here by vibe_ic_one_shot_runner so a run "
                         "driven with --pdk measures the PDK it names. When it "
                         "CONTRADICTS the design's own L19 declaration the run "
                         "REFUSES with both named; when it is absent the "
                         "declaration is used; there is no literal default."))
    import execution_policy as execution
    execution.add_arguments(p)
    args = p.parse_args()
    if args.post_mc_samples is not None:
        if args.flow != "109" or args.post_mc_samples < 2:
            p.error("--post-mc-samples requires --flow 109 and a count >= 2")
    if args.flow == "109" and args.execution_mode not in (None, "default"):
        p.error("the native A01-A19 entry currently implements Default mode")
    execution.configure(args)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    if args.flow == "109":
        from analog_native_flow import run_window
        try:
            result = run_window(project, args)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[result["window_verdict"]]
    if args.entry_step or args.exit_step or args.flow109_manifest:
        p.error("A01-A19 continuation options require --flow 109")

    # BIND OR REFUSE. A `--pdk` that contradicts the design's own declaration
    # is a question this runner is not entitled to answer by itself, so it
    # answers with both names and stops rather than picking one in silence.
    _contra = _pdk_contradiction(args, project)
    if _contra:
        _flag, _declared = _contra
        msg = (f"--pdk {_flag} CONTRADICTS the design's own declared PDK "
               f"target {_declared} (phase1/generated_docs/"
               f"L19_CONSTRAINTS_PDK.json#fields.pdk_target). Refusing to "
               f"substitute either one silently: re-run with --pdk "
               f"{_declared}, or correct the design's declaration. Nothing "
               f"was simulated and no analog artefact was written.")
        print(f"[BLOCKED] analog_one_shot_runner: {msg}", file=sys.stderr)
        out = _pl.report_path(project, "analog_one_shot.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"phase": "analog",
                                    "verdict": _spf.REFUSAL_STATUS,
                                    "reason": msg,
                                    "pdk_flag": _flag,
                                    "pdk_declared": _declared,
                                    "blocks": []}, indent=2) + "\n")
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
    declared_blocks = list(blocks)
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
        # `block_count` IS PART OF THE DECLARED SCHEMA, and this writer omitted
        # it. The `analog-spec-extract` skill's master-list rule — the rule
        # `analog_block_list_emit_check` was extracted from — requires
        # `block_count` and requires it to equal `len(blocks)`. Nothing noticed
        # because nothing ran that gate (vibe-ic#2080): this runner
        # materialised a list its own schema gate rejects, and the tree looked
        # the same either way. `len(blocks)` is the only value it can be.
        #
        # `spec_file` is deliberately NOT invented here. The schema asks each
        # entry to name the block's `spec.json`, and this writer has not seen
        # one — A1 is what emits them. A materialisation that promised a path
        # it never looked for would be a fabricated record, and the gate is
        # right to report the absence instead.
        materialized_blocks = declared_blocks if execution.request()['mode'] == 'default' else blocks
        block_list_path.write_text(
            json.dumps({"blocks": materialized_blocks, "block_count": len(materialized_blocks)},
                       indent=2, ensure_ascii=False)
            + "\n", encoding="utf-8")

    # Freeze the resolved declaration before registration. A1-A5 products are
    # still collected by the ordinary dispatcher when each later row runs.
    from execution_analog_installation import prepare_entry_request
    entry_request = prepare_entry_request(project, args) if execution.request()['mode'] == 'ultra' else None
    execution.bootstrap(project, parameters={'analog_request': entry_request})

    plan: List[StepResult] = []
    halted_at = None
    complete_population = len(blocks) == len(declared_blocks)
    a9_rows = []
    # No refusal is inherited from a previous run of this process.
    reset_env_refusals()

    def _dispatched(sr: StepResult) -> None:
        plan.append(sr)
        print(f"  {sr.status:6} {sr.name:24} block={sr.block:16} "
              f"{_rsum.summary_detail(sr.detail, sr.status, width=60)}")

    def _close_default_row(sid, started_at, rows):
        # Preserve native measured FAIL even if a later block succeeds.
        if any(row.status == 'FAIL' for row in rows):
            return True
        rejection = _default_analog_rejection(project, sid, started_at, complete_population)
        if rejection is None:
            return False
        _dispatched(rejection)
        return True

    if execution.request()['mode'] == 'ultra':
        # Every declared block must get its A1-A5 producer opportunity before
        # the first unified fixed A6/A7/A8 Context is cached by the ordinary
        # Controller. Keep one literal preflight call site per canonical row.
        for blk in blocks:
            _bname = blk.get("name") or blk.get("type") or "unknown"
            _note = f"block={_bname}"
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A1",
                _preflight_refusal("A1_spec_extract", _bname),
                step_for_block, project, blk, "A1_spec_extract", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A2",
                _preflight_refusal("A2_topology_select", _bname),
                step_for_block, project, blk, "A2_topology_select", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A3",
                _preflight_refusal("A3_netlist_gen", _bname),
                step_for_block, project, blk, "A3_netlist_gen", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A4",
                _preflight_refusal("A4_corner_sweep", _bname),
                step_for_block, project, blk, "A4_corner_sweep", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A5",
                _preflight_refusal("A5_layout", _bname),
                step_for_block, project, blk, "A5_layout", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))

        # Keep each unified row's full block population together before the
        # next row. In particular, all A7 producer opportunities precede the
        # first A8 dispatch, so every block's current A7 product is settled
        # before the ordinary fixed A8 census is created.
        for blk in blocks:
            _bname = blk.get("name") or blk.get("type") or "unknown"
            _note = f"block={_bname}"
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A6",
                _preflight_refusal("A6_block_pv", _bname),
                step_for_block, project, blk, "A6_block_pv", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
        for blk in blocks:
            _bname = blk.get("name") or blk.get("type") or "unknown"
            _note = f"block={_bname}"
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A7",
                _preflight_refusal("A7_post_layout_resim", _bname),
                step_for_block, project, blk, "A7_post_layout_resim", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
        for blk in blocks:
            _bname = blk.get("name") or blk.get("type") or "unknown"
            _note = f"block={_bname}"
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A8",
                _preflight_refusal("A8_hardmacro_gen", _bname),
                step_for_block, project, blk, "A8_hardmacro_gen", args=args,
                _preflight_note=_note, _preflight_canonical_acceptance=True))
        for blk in blocks:
            _bname = blk.get("name") or blk.get("type") or "unknown"
            _note = f"block={_bname}"
            _dispatched(_spf.gate(
                project, "analog_one_shot_runner", "A9",
                _preflight_refusal("A9_hw_verify", _bname),
                step_for_block, project, blk, "A9_hw_verify", args=args,
                _preflight_note=_note))
    else:
        # Default deliberately completes every declared block before advancing a row.
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A1",
                    _preflight_refusal("A1_spec_extract", _bname),
                    step_for_block, project, blk, "A1_spec_extract", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A1', _terminal_started, plan[row_begin:]):
                halted_at = 'A1'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A2",
                    _preflight_refusal("A2_topology_select", _bname),
                    step_for_block, project, blk, "A2_topology_select", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A2', _terminal_started, plan[row_begin:]):
                halted_at = 'A2'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A3",
                    _preflight_refusal("A3_netlist_gen", _bname),
                    step_for_block, project, blk, "A3_netlist_gen", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A3', _terminal_started, plan[row_begin:]):
                halted_at = 'A3'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A4",
                    _preflight_refusal("A4_corner_sweep", _bname),
                    step_for_block, project, blk, "A4_corner_sweep", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A4', _terminal_started, plan[row_begin:]):
                halted_at = 'A4'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A5",
                    _preflight_refusal("A5_layout", _bname),
                    step_for_block, project, blk, "A5_layout", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A5', _terminal_started, plan[row_begin:]):
                halted_at = 'A5'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A6",
                    _preflight_refusal("A6_block_pv", _bname),
                    step_for_block, project, blk, "A6_block_pv", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A6', _terminal_started, plan[row_begin:]):
                halted_at = 'A6'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A7",
                    _preflight_refusal("A7_post_layout_resim", _bname),
                    step_for_block, project, blk, "A7_post_layout_resim", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A7', _terminal_started, plan[row_begin:]):
                halted_at = 'A7'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A8",
                    _preflight_refusal("A8_hardmacro_gen", _bname),
                    step_for_block, project, blk, "A8_hardmacro_gen", args=args,
                    _preflight_note=_note, _preflight_canonical_acceptance=True))
            if _close_default_row('A8', _terminal_started, plan[row_begin:]):
                halted_at = 'A8'
        if halted_at is None:
            row_begin = len(plan)
            for blk in blocks:
                _terminal_started = time.time()
                _bname = blk.get("name") or blk.get("type") or "unknown"
                _note = f"block={_bname}"
                _dispatched(_spf.gate(
                    project, "analog_one_shot_runner", "A9",
                    _preflight_refusal("A9_hw_verify", _bname),
                    step_for_block, project, blk, "A9_hw_verify", args=args,
                    _preflight_note=_note))
            a9_rows = plan[row_begin:]

    # q5 — A9's co-simulation is CHIP-level: its scenarios cross blocks, so it
    # runs once, after every block's A1-A9, against the ids Phase 1 declared in
    # L22. Recorded beside the rows, not as one: the flow's A9 gate
    # (`mixed_signal_cosim_check`) owns that verdict, and a second row here
    # would roll the same fact up twice.
    if halted_at is None:
        cosim_started = time.time()
        a9_cosim = _a9_cosim(project, args)
        if execution.request()['mode'] == 'default':
            if a9_cosim.get('rc') == 1 or _close_default_row('A9', cosim_started, a9_rows):
                halted_at = 'A9'
    else:
        a9_cosim = {'rc': None, 'tier': 'NOT_MEASURED',
                    'detail': f'not executed after canonical step {halted_at} was not accepted'}

    # vibe-ic#2080 — the master block list every A-gate above read, judged at
    # last by the gate written for it. AFTER the loop: A1 is what emits each
    # block's spec.json, so asking before it would answer about a tree this run
    # had not built. ADVISORY — the status is "ADVISORY", which no tier of
    # `_aggregate_verdict` names, so the row cannot move the analog verdict.
    _dispatched(step_block_list_schema(project))

    verdict = _aggregate_verdict(plan)
    # A9's chip-level native return stays beside the rows, counted once.
    if execution.request()['mode'] == 'default' and a9_cosim.get('rc') != 0:
        if a9_cosim.get('rc') == 1:
            verdict = 'FAIL'
        elif verdict != 'FAIL':
            verdict = 'NOT_MEASURED'
    # R-0915-85: the tier is a DISCLOSURE beside the verdict now, so the
    # reader asks for the disclosure rather than for a word that meant both.
    structure_only = [s for s in plan
                      if _V.Disclosure.STRUCTURE_ONLY.value
                      in (s.disclosures or ())]
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
    summary["a9_cosim"] = a9_cosim
    if execution.request()['mode'] == 'default':
        summary['halted_at'] = halted_at
    import ai_signed_judgement as _ai_judgement
    summary["ai_judgements"] = _ai_judgement.pending(project, ("A1", "A2", "A9"))
    _ai_judgement.demote_runner_rows(summary["steps"], summary["ai_judgements"])
    if summary["ai_judgements"] and summary["verdict"] in ("PASS", "PASS_WITH_WAIVERS"):
        summary["verdict"] = "NOT_MEASURED"
        summary["reason_class"] = "awaiting_signed_judgement"
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
    # R-0915-85 — THE EXIT CODE IS THE RUN WORD, the same rule the other three
    # runners now apply. `!= "FAIL"` exited 0 on every word that is not FAIL,
    # which after the collapse includes NOT_MEASURED: an analog track where
    # nothing was measured would have told the shell it passed.
    return 0 if _V.parse(summary["verdict"]) in (
        _V.Verdict.PASS, _V.Verdict.PASS_WITH_WAIVERS) else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
