#!/usr/bin/env python3
"""lec_run.py — Step 13 LEC PRODUCER (RTL ≡ synthesized gate netlist).

The flow's step-13 gate `lec_equivalence_check.py` VALIDATES
`reports/lec.json`, but nothing ever PRODUCED that artefact — step 13 was
an orphan. This program is the missing executor: it runs a REAL Yosys
equivalence check in the vibeic-eda container and writes a TRUTHFUL
`reports/lec.json` + `reports/lec.rpt`.

It is a PRODUCER, not the judge. It exits 0 whenever it successfully wrote
a truthful report — even when the design turned out non-equivalent, or when
the SAT engine was model-limited on custom-PDK primitives. The downstream
gate `lec_equivalence_check.py` is what decides PASS/FAIL. It exits 1 only
when Yosys / Docker could not run at all (so the runner can fall back to a
disclosed-skip).

The Yosys recipe is PORTED from the mature `yosys_equiv` LVS mode in
`mcp-eda/src/index.js` (equiv_make → equiv_simple → equiv_induct -seq
4/16/64 → equiv_status), including its ANTI-FABRICATION honesty: when
equiv_induct's SAT engine aborts on Liberty cells it cannot model (e.g.
`sky130_fd_sc_hd__lpflow_isobufsrc_1`), we surface a STRUCTURED
`sat_model_unsupported_cells[]` + `verdict:"SKIPPED-CONDITION"` +
`verdict_explanation` — never a fake pass, never the ambiguous `-1`
sentinel. Two recipe adaptations proven necessary against real Vibe-IC
synth netlists (Yosys 0.66, sky130A):
  * `read_verilog -icells` — synth netlists here escape internal gate
    types as user identifiers (`\\$_NOT_`); -icells re-binds them to the
    internal primitives so `hierarchy -check` does not error. Harmless for
    Liberty-mapped netlists (their cells are not `$`-prefixed).
  * `flatten` on both designs — the RTL gold carries sub-module hierarchy
    (e.g. chip_top -> spm); without flatten equiv_make sees an unmodelable
    hierarchical instance and aborts on it. equiv is a comparison of two
    flat cones, so flattening both is sound.

CLI contract (the runner calls this exactly):
    python3 lec_run.py <project_dir> \\
        --gold-rtl-dir phase2/stage1/rtl \\
        --gate-netlist phase2/stage2/synth/netlist.v \\
        --top <top_module> \\
        [--container vibeic-eda] \\
        [--liberty <abs .lib path inside container>] \\
        [--json reports/lec.json]
    main(argv=None) -> int   0 = report produced (PASS or honest SKIP)
                             1 = could not run the tool at all (real error)

Chip-AGNOSTIC — no design-specific assumptions; pure Yosys driving + text
parsing. The only cell names referenced are the PDK's own documented cells.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
from _rtl_include_hub import (  # noqa: E402
    drop_include_hubs as _drop_include_hubs,
    macro_headers_first as _macro_headers_first,
)
import _hardmacro_stage as _hms  # noqa: E402 — staged SRAM/IP macro blackbox

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402
from _prose_polarity import is_denied, sentence_scope  # noqa: E402

PROGRAM = "lec_run"

DEFAULT_CONTAINER = _pin.default_container_name()
DEFAULT_LIBERTY = (
    "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
    "sky130_fd_sc_hd__tt_025C_1v80.lib"
)
# TOTAL budget for the LEC step, shared by every attempt (see StepBudget).
# It used to be a PER-INVOCATION budget that each retry re-armed; it is now a
# deadline drawn down across attempts. The equiv miter on a CPU-class gold (ibex:
# ~2k compared points through equiv_induct -seq 64) runs far past the old
# 1800s, and a killed run produced NO evidence — indistinguishable at the
# gate from a real mismatch. Tunable via --timeout for smaller budgets.
# ORGANIC-20260801 — VIBEIC_LEC_YOSYS_TIMEOUT_S overrides the default for very
# large (>1M-cell) golds whose MONOLITHIC equiv legitimately exceeds — or is
# deliberately bounded below (a giant gold that cannot converge in any open-tool
# budget honestly lands SKIPPED-CONDITION, never a fake PASS) — the historical
# 7200s. Symmetric with the synth step's VIBEIC_PHASE2_SYNTH_TIMEOUT_S. The
# runner reads this SAME constant for its outer subprocess budget and inherits
# the env into the lec_run subprocess, so both stay in lock-step. Byte-identical
# (7200) when the env var is unset. chip-AGNOSTIC.
def _env_yosys_timeout_default() -> int:
    try:
        v = int(os.environ.get("VIBEIC_LEC_YOSYS_TIMEOUT_S", "") or 0)
        if v > 0:
            return v
    except ValueError:
        pass
    return 7200


#: R-0915-48 — an OPT-IN hard bound on the equiv proof, and it is deliberately
#: NOT `DEFAULT_YOSYS_TIMEOUT_S`.
#:
#: This file has removed a bound on this leg TWICE, each time with a
#: measurement, and both are recorded above:
#:   * 2026-09-06 — pinning `wrap_with_container_timeout` to the budget
#:     SIGKILLed a proof at budget-5s that was emitting output at a full core
#:     (5360 s of 7195 s, 1374 points proved, 0 failed, still advancing), and
#:     "a bigger number would be the same defect with a later date";
#:   * earlier — a host-side SILENCE window "killed two healthy RTLLM LEC jobs
#:     ... while each Yosys process was still advancing at one full core".
#: So neither a wall clock nor a quiet-window may become the DEFAULT here.
#:
#: What is also true, MEASURED on sha256 run12: a proof stuck on ONE hard point
#: holds 99.9% CPU for ever, `_watchdog` counts CPU as progress (its signals are
#: an OR), and the run therefore never ends. Both facts are real, and the only
#: form that serves both is a bound the operator ASKS FOR.
#:
#: Set VIBEIC_LEC_YOSYS_TIMEOUT_S to a positive number of seconds and this leg
#: carries a container-side backstop at it; leave it unset (or 0) and the leg
#: behaves exactly as it does today, unbounded, and SAYS so. An expiry lands on
#: the container-timeout path that already exists: `_TIMEOUT_MARKER`, parsed as
#: INCONCLUSIVE / SKIPPED-CONDITION with the proof state reached, never a FAIL
#: and never a PASS.
def _env_lec_hard_bound_s() -> Optional[int]:
    """Seconds for the opt-in equiv backstop, or None when not asked for.

    PURE. Only an EXPLICIT positive value arms it: an unset variable is not a
    request for a bound, and `DEFAULT_YOSYS_TIMEOUT_S`'s 7200 is the attempt-
    admission budget, which `_docker`'s own docstring says is "not a fresh
    retry budget" and not a runtime deadline."""
    raw = os.environ.get("VIBEIC_LEC_YOSYS_TIMEOUT_S", "")
    if not str(raw).strip():
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if v > 0 else None


DEFAULT_YOSYS_TIMEOUT_S = _env_yosys_timeout_default()
DEFAULT_JSON_REL = "reports/lec.json"
DEFAULT_RPT_REL = "reports/lec.rpt"
# v3 — the ladder now emits an RTLIL CHECKPOINT after every rung, so the
# recipe text a proof is bound to is not the v2 one. The identity's
# `equivalence_script` sha already separates them; the version string is what
# makes that separation READABLE in a stored cache entry.
LEC_RECIPE_SCHEMA_VERSION = "vibeic.lec.recipe.v3-checkpointed"
LEC_PASS_CACHE_SCHEMA_VERSION = "vibeic.lec.pass-cache.v1"
LEC_TELEMETRY_SCHEMA_VERSION = "vibeic.lec.telemetry.v1"
LEC_CHECKPOINT_SCHEMA_VERSION = "vibeic.lec.checkpoint.v1"
#: WHAT ACTUALLY RAN, beside the identity that says WHAT WAS PROVED. The PASS
#: cache key is the recipe (`lec_cache_key` over the from-zero identity), so
#: this is where a resumed run names the bytes it executed and the two evidence
#: legs it reached its verdict from. It is REPORT-ONLY: nothing here is hashed
#: into a key, and nothing here can make a cache entry hit or miss.
LEC_PROOF_EXECUTION_SCHEMA_VERSION = "vibeic.lec.proof-execution.v1"
LEC_LADDER_SCHEMA_VERSION = "vibeic.lec.ladder.v3-joint-induction"
#: `_ladder_stop` when the loop climbed every rung. Named, not spelled
#: twice: it is also what tells the parser the closing `equiv_status` is
#: the LADDER's and not some intermediate leg's.
_LADDER_COMPLETE = "the ladder is complete"
DEFAULT_CACHE_REL = "reports/lec_pass_cache"
DEFAULT_CHECKPOINT_REL = "reports/lec_checkpoints"
CONTROLLED_LIMIT_RECEIPT_PREFIX = "lec_controlled_limit"
CONTROLLED_LIMIT_RECEIPT_SCHEMA_VERSION = "vibeic.lec.controlled-limit.v1"

# THE PROOF LADDER, in the order `build_equiv_script` emits it: (rung name,
# the yosys command(s) that constitute the rung). The rung NAMES are
# `lec_stage_from_output`'s OWN vocabulary, so there is one spelling of a
# ladder position in this file and not two.
LEC_LADDER: Tuple[Tuple[str, str], ...] = (
    ("equiv_simple_short", "equiv_simple -short\n"),
    # Prove the remaining state relation jointly before the full local SAT
    # pass rewires additional cutpoints. Partial simple proofs can discard a
    # useful relation between sequential aliases and leave an otherwise
    # provable full model stuck. Keep the existing fallback ladder intact.
    ("equiv_induct_joint_seq16", "equiv_induct -seq 16\n"),
    ("equiv_simple_full", "equiv_simple\n"),
    ("equiv_induct_seq4", "equiv_induct -seq 4\n"),
    ("equiv_induct_seq16", "equiv_induct -seq 16\n"),
    ("equiv_induct_seq64", "equiv_induct -seq 64\n"),
)
LEC_CHECKPOINT_RUNGS: Tuple[str, ...] = tuple(n for n, _ in LEC_LADDER)

# THE GATE'S OWN NET NAMES MUST BE CANONICAL, or the ladder forgets what it
# proved (LEC_CONVERGE, 2026-09-28). The tag marks every wire of a Liberty cell
# module; `flatten` copies it onto the wires it creates from a cell instance
# (`<inst>.<pin>`, `<inst>.IQ`), and `rename -hide` then hides exactly those.
#
# WHY. `equiv_make` pairs gold and gate by NAME and rewires every consumer of a
# paired bit to the `$equiv` output. It records the pair under the paired
# wire's own bits but looks consumers up by their `assign_map` CANONICAL bit
# (yosys passes/equiv/equiv_make.cc, `rd_signal_map.add(rdmap_gate, …)` against
# `rd_signal_map(assign_map(conn))`). Flattening a Liberty cell gives its pins
# public names too, and one of them, not the netlist's net name, can become
# canonical: on subservient every flop's canonical bit was `\_NNNN_.IQ1`, while
# the pair was made under the netlist's own name (`…bufreg2.dhi[0]`, an alias).
# So no gate consumer was rewired. A gate register was then tied to its gold
# twin only by the `$equiv` HYPOTHESIS, and a rung that proves a cell rewires
# its B to its A, so every LATER rung has lost that hypothesis.
#
# MEASURED (subservient, serv 1.4.0, gf180mcuD, yosys 4d572059c): the ladder
# stopped at 251/256. `equiv_induct -seq 4` proved the register pairs, and
# `-seq 16`, run on that output, could no longer prove
# `core.rf_mem_if.o_sram_wdata[0..4]`. Those five need 5–9 cycles, because
# `opt_dff` set the X-initialised, constant-D shift chain `wdata1_r` to 0
# (synth.log "Setting constant 0-bit at position 8 … 0"). `-seq 16`, `-seq 32`,
# `-undef` and `equiv_simple -seq 12` on that checkpoint all stayed at 5.
# With the pin names hidden, the UNCHANGED ladder proved 256/256, and
# `equiv_simple -short` alone proved 213 points instead of 1. A generic
# `$_`-cell gate has no cell pins to hide and is untouched (sha256: 4359
# consumers rewired by `equiv_make` either way).
#
# SOUND: renaming a wire changes no logic. It changes only WHICH NAME is
# canonical, so `equiv_make` connects the gate's consumers the way it already
# does whenever the netlist's name happens to win.
LIBERTY_PIN_ATTR = "vibeic_lec_liberty_pin"

# Written by a `log` command placed AFTER each `write_rtlil`. yosys executes a
# script strictly in order, so the sentinel's presence in the log is a positive
# attestation that THAT backend pass finished — which is the only thing that
# distinguishes a complete checkpoint from one truncated by a kill mid-write.
# The checkpoint is written as `<rung>.il.part` and PROMOTED to `<rung>.il` by
# the host only for the rungs the log attests. A file with no sentinel is never
# promoted and therefore never resumed from.
LEC_CHECKPOINT_SENTINEL = "LEC_CHECKPOINT_WRITTEN"
# The payload is `<checkpoint dir name>:<rung>`, not the bare rung. The
# directory is named by the checkpoint key, so an attestation READ OUT OF
# ANOTHER INVOCATION'S LOG (see `recover_orphan_checkpoints`) can be checked to
# belong to THIS design's ladder. Without the prefix, the verilog attempt's log
# would attest the slang attempt's `.part` of the same rung name.
_CHECKPOINT_SENTINEL_RE = re.compile(
    r"(?m)^" + re.escape(LEC_CHECKPOINT_SENTINEL)
    + r"[ \t]+(\S+?):(\S+)[ \t]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_file_streamed(path: Path, chunk: int = 1 << 20) -> str:
    """Same value as `_sha256_file`, without holding the file in memory.

    A checkpoint of a large miter is a large file; `read_bytes()` on it would
    make hashing the checkpoint cost more memory than the proof did.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Publish one complete file; a killed writer cannot leave a cache hit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def lec_cache_key(identity: Dict) -> str:
    """Content-address one exact proof identity (pure and order-sensitive)."""
    return _sha256_bytes(_canonical_json_bytes(identity))


# ---------------------------------------------------------------------------
# PROOF CHECKPOINTS — resume a killed leg instead of re-proving from zero.
# ---------------------------------------------------------------------------
# THE DEFECT THIS EXISTS TO REMOVE (measured, 8HD-9, 2026-09-06). yosys marks a
# `$equiv` key-point PROVEN by REWIRING that cell's \B input to the same signal
# as \A. That is ORDINARY RTLIL — no side table, no in-memory-only state — so
# `write_rtlil` / `read_rtlil` ROUND-TRIPS the proven set across a fresh
# process: on a 33-point miter a resumed leg's `equiv_induct` reports
# "Found 1 unproven $equiv cells" where the same pass from zero reports 33, and
# the same holds between induction depths (`-seq 4` -> `-seq 16`).
#
# The engine could therefore always resume. THIS PROGRAM NEVER ASKED IT TO: the
# emitted recipe contained no `write_rtlil` and no `read_rtlil` anywhere, and
# the PASS cache accepts only a COMPLETED proof. So every killed or stalled leg
# re-proved the same points from nothing — measured on sha256, whose two killed
# legs re-proved the same 1060 points twice for 14,390 s of CPU.
#
# WHAT IS AND IS NOT RESUMABLE. yosys writes nothing WHILE a pass runs, so the
# granularity is a whole rung: completed rungs are free on a restart, the rung
# that was in flight is not. That is a limit of the engine, not of this code,
# and it is why the ladder is checkpointed rung by rung rather than by time.
#
# A CHECKPOINT IS NOT A PASS. It carries no verdict, it never seeds or
# satisfies the PASS cache (`pass_cache_eligible` is untouched), and a resumed
# run reaches its verdict the only way any run does — by parsing the fresh
# yosys log its own `equiv_status` produced.


def lec_checkpoint_key(identity: Dict) -> str:
    """Content-address the DESIGN + TOOL a checkpoint belongs to.

    Deliberately NOT `lec_cache_key`: a RESUMED run's `equivalence_script` is a
    different script (it reads an .il instead of the sources), so keying the
    checkpoint on it would make a resuming run unable to find the very
    checkpoint it is resuming from — and it would be circular besides, since
    the script has to contain the checkpoint paths.

    Everything else in the identity is kept, so a checkpoint is bound to the
    gold RTL bytes, the GATE NETLIST bytes, the top, the scan wrappers, the
    Liberty, the yosys version, the container image digest, the gold frontend
    and its define set, and `recipe_schema_version`. The one thing that binding
    cannot see — WHICH LADDER wrote the file — is carried separately as
    `base_script_sha256` in the checkpoint manifest and is checked at resume.
    """
    subject = {k: v for k, v in identity.items() if k != "equivalence_script"}
    subject["checkpoint_schema_version"] = LEC_CHECKPOINT_SCHEMA_VERSION
    return _sha256_bytes(_canonical_json_bytes(subject))


def checkpoint_dir_for(project: Path, key: str) -> Path:
    """The one directory a given design+tool identity checkpoints into."""
    return Path(project) / DEFAULT_CHECKPOINT_REL / key.split(":", 1)[-1]


def ladder_index(rung: str) -> int:
    """Position of a rung in the ladder, or -1 for a name we do not emit."""
    try:
        return LEC_CHECKPOINT_RUNGS.index(rung)
    except ValueError:
        return -1


def checkpoints_attested_by_log(raw: str,
                                scope: Optional[str] = None) -> List[str]:
    """Rungs whose `write_rtlil` DEMONSTRABLY finished, in log order.

    The sentinel is emitted by a `log` command placed after the write, so it
    can only appear once that backend pass has returned. A run killed inside a
    write leaves the `.part` file behind and no sentinel, and the file is then
    never promoted — which is the whole reason the promotion is log-driven and
    not directory-driven.

    `scope` — the checkpoint directory's name. Given, only attestations naming
    that directory count; a log from a DIFFERENT recipe attempt cannot then
    vouch for this one's bytes.
    """
    out: List[str] = []
    for m in _CHECKPOINT_SENTINEL_RE.finditer(raw or ""):
        where, rung = m.group(1), m.group(2)
        if rung not in LEC_CHECKPOINT_RUNGS:
            continue
        if scope is not None and where != scope:
            continue
        out.append(rung)
    return out


def promote_and_record_checkpoints(
        ckpt_dir: Path, key: str, base_script_sha256: str, raw: str, *,
        yosys_version: Optional[str] = None,
        image_digest: Optional[str] = None,
        invocation_id: Optional[str] = None,
        resumed_from_rung: Optional[str] = None,
        evidence_log: Optional[Path] = None) -> List[str]:
    """Promote every log-attested `.part` and write its manifest. Returns the
    rungs recorded, in ladder order.

    Never raises: a checkpoint is an OPTIMISATION, and a filesystem that will
    not take one must not be able to fail a proof that already succeeded.
    """
    ckpt_dir = Path(ckpt_dir)
    recorded: List[str] = []
    for rung in checkpoints_attested_by_log(raw, scope=ckpt_dir.name):
        part = ckpt_dir / (rung + ".il.part")
        final = ckpt_dir / (rung + ".il")
        try:
            if not part.is_file() or part.stat().st_size == 0:
                continue
            os.replace(str(part), str(final))
            digest = _sha256_file_streamed(final)
            _st = final.stat()
            size = _st.st_size
            # WHEN THE RUNG FINISHED, not when the host filed it. `os.replace`
            # preserves the mtime yosys wrote, and that is the only record of
            # how long the rung took -- a copy that does not preserve mtimes
            # would otherwise lose it, and the manifest is what survives.
            written = datetime.fromtimestamp(
                _st.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            continue
        # THE LEG'S OWN LOG, COPIED IN BESIDE THE .il. A resumed run does not
        # re-run the rungs below its checkpoint, so its log cannot contain
        # their evidence -- and the classifier reads that evidence. Naming the
        # log is what lets a resumed run carry it forward instead of reaching a
        # different verdict about the same proof. Hash-bound, so a log that
        # changed is refused.
        #
        # WHY A COPY AND NOT A NAME. The log this points at is
        # `reports/lec.live.<invocation>.rpt` -- a per-invocation file that any
        # ordinary clean of `reports/` removes, while the checkpoint beside it
        # survives. Naming it there made RESUMABILITY depend on a file nothing
        # promised to keep: the .il stayed valid, its evidence vanished, and
        # `select_resume_checkpoint` then refused a perfectly good 43.8 MB rung
        # and re-proved it from zero. The evidence is part of the checkpoint,
        # so it lives in the checkpoint's own directory, under the RUNG's name
        # (one evidence file per rung, replaced when that rung is re-recorded),
        # and it is hash-bound THERE.
        _ev: Dict[str, Any] = {"state": "absent"}
        try:
            if evidence_log is not None and Path(evidence_log).is_file():
                _ev_name = rung + ".evidence.rpt"
                _atomic_write_bytes(ckpt_dir / _ev_name,
                                    Path(evidence_log).read_bytes())
                _ev = {"path": _ev_name,
                       "sha256": _sha256_file_streamed(ckpt_dir / _ev_name),
                       "bytes": (ckpt_dir / _ev_name).stat().st_size,
                       "copied_from": Path(evidence_log).name}
        except OSError:
            _ev = {"state": "unreadable"}
        try:
            _atomic_write_json(ckpt_dir / (rung + ".json"), {
                "schema_version": LEC_CHECKPOINT_SCHEMA_VERSION,
                "checkpoint_key": key,
                "rung": rung,
                "rung_index": ladder_index(rung),
                "base_script_sha256": base_script_sha256,
                "il": {"path": rung + ".il", "sha256": digest, "bytes": size,
                       "written_utc": written},
                "evidence_log": _ev,
                "yosys": {"version": yosys_version},
                "container": {"image_digest": image_digest},
                "invocation_id": invocation_id,
                "written_by_resumed_run": bool(resumed_from_rung),
                "resumed_from_rung": resumed_from_rung,
                "written_timestamp": _utc_now(),
            })
        except OSError:
            continue
        if rung not in recorded:
            recorded.append(rung)
    return sorted(recorded, key=ladder_index)


def list_checkpoint_rungs_declared(ckpt_dir: Path, key: str,
                                   base_script_sha256: str) -> List[str]:
    """Rungs whose MANIFEST claims this identity, in ladder order.

    Manifest-level only: this does NOT re-hash the .il, and it is used for the
    report field, never for a resume decision. The byte revalidation lives in
    `select_resume_checkpoint`, which is the ONE place a wrong answer could
    change what gets proved. Doing it twice would make every completed run pay
    a second full read of the whole ladder for a line in a report.
    """
    out: List[str] = []
    for rung in LEC_CHECKPOINT_RUNGS:
        try:
            manifest = json.loads(
                (Path(ckpt_dir) / (rung + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (manifest.get("schema_version") == LEC_CHECKPOINT_SCHEMA_VERSION
                and manifest.get("checkpoint_key") == key
                and manifest.get("base_script_sha256") == base_script_sha256
                and manifest.get("rung") == rung
                and (Path(ckpt_dir) / (rung + ".il")).is_file()):
            out.append(rung)
    return out


def select_resume_checkpoint(ckpt_dir: Path, key: str,
                             base_script_sha256: str) -> Optional[Dict]:
    """The FURTHEST checkpoint that revalidates, or None. Refuses on any doubt.

    Every field is re-checked against the caller's own current values, and the
    .il AND its carried evidence are RE-HASHED — so a checkpoint written for
    another netlist, by another ladder, or corrupted since it was written, is
    refused BY NAME rather than silently resumed from. `None` means "run from
    zero", which is exactly the behaviour before checkpoints existed.

    THE EVIDENCE IS RESOLVED BESIDE THE .il, never in `reports/`. The
    `reports_dir` parameter this function used to take made the evidence check
    OPTIONAL (absent argument -> no check at all) and pointed it at a
    per-invocation live log that an ordinary clean deletes. Both are gone: the
    requirement is unconditional, and it is asked of the copy the checkpoint
    owns.
    """
    ckpt_dir = Path(ckpt_dir)
    best: Optional[Dict] = None
    for rung in LEC_CHECKPOINT_RUNGS:
        man_path = ckpt_dir / (rung + ".json")
        il_path = ckpt_dir / (rung + ".il")
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        il_meta = manifest.get("il")
        if (manifest.get("schema_version") != LEC_CHECKPOINT_SCHEMA_VERSION
                or manifest.get("checkpoint_key") != key
                or manifest.get("base_script_sha256") != base_script_sha256
                or manifest.get("rung") != rung
                or manifest.get("rung_index") != ladder_index(rung)
                or not isinstance(il_meta, dict)
                or il_meta.get("path") != rung + ".il"
                or not isinstance(il_meta.get("sha256"), str)):
            continue
        try:
            if not il_path.is_file() or il_path.stat().st_size == 0:
                continue
            actual = _sha256_file_streamed(il_path)
        except OSError:
            continue
        if actual != il_meta["sha256"]:
            continue
        # THE CARRIED EVIDENCE IS PART OF THE CHECKPOINT. Without the prior
        # leg's log a resumed run reaches a DIFFERENT VERDICT about the same
        # proof -- measured on sha256: from-zero INCONCLUSIVE (798/1837 proven,
        # equiv_induct did not converge, 0 counterexamples) vs resumed FAIL
        # ("the RTL and gate netlist may genuinely differ"), because the
        # resumed log carries no equiv_induct pass for the classifier to read.
        # So a checkpoint whose evidence is gone is REFUSED, and the run starts
        # from zero -- slower, and the only answer that stays true.
        _ev = manifest.get("evidence_log")
        if not isinstance(_ev, dict) or not isinstance(_ev.get("path"), str):
            continue
        _ev_path = ckpt_dir / _ev["path"]
        try:
            if not _ev_path.is_file():
                continue
            if _sha256_file_streamed(_ev_path) != _ev.get("sha256"):
                continue
        except OSError:
            continue
        best = {
            "evidence_log": str(_ev_path) if _ev_path else None,
            "evidence_log_sha256": (_ev or {}).get("sha256")
                                   if isinstance(_ev, dict) else None,
            "rung": rung,
            "rung_index": ladder_index(rung),
            "il_path": str(il_path.resolve()),
            "checkpoint_sha256": actual,
            "checkpoint_bytes": il_path.stat().st_size,
            "manifest": str(man_path),
            "written_timestamp": manifest.get("written_timestamp"),
        }
    return best


def resume_status_counts(raw: str) -> Optional[Dict[str, int]]:
    """proved/unproven AT THE CHECKPOINT, read from a resumed run's own log.

    A resumed script's FIRST pass is `equiv_status` on the design it just read
    back, so the FIRST `N are proven and M are unproven` line in the log is the
    checkpoint's position. Returns None — never a fabricated zero — unless that
    line demonstrably precedes the first induction pass, because a log in which
    it does not is a log where the read-back did not happen and the only line
    present is the FINAL status.
    """
    if not raw:
        return None
    first = _FINAL_RE.search(raw)
    if not first:
        return None
    induct = re.search(r"(?i)Executing\s+EQUIV_INDUCT\s+pass", raw)
    if induct is not None and induct.start() < first.start():
        return None
    return {"proved": int(first.group(1)), "unproven": int(first.group(2))}


def final_status_counts(raw: str) -> Optional[Dict[str, int]]:
    """proved/unproven as the LAST `equiv_status` in `raw` reported them.

    The LAST, for the same reason `parse_equiv_output` reads the last one: a
    recipe that prints `equiv_status` more than once — every resumed leg does,
    once at the read-back and once at the end — has to be read at the state it
    FINISHED in, not the one it started from.

    Returns None, never a fabricated zero, when the text carries no status line
    at all: a leg that was killed before its closing `equiv_status` did not
    measure a position, and "could not read it" is not "read it and it was
    empty".
    """
    finals = list(_FINAL_RE.finditer(raw or ""))
    if not finals:
        return None
    return {"proved": int(finals[-1].group(1)),
            "unproven": int(finals[-1].group(2))}


def leg_peak_rss_kib(telemetry_path: Optional[Path],
                     attempt_number: int) -> Optional[int]:
    """The MAX rss the supervisor sampled during ONE ladder leg.

    This is the per-rung figure vibe-ic#2194 turns on. With one rung per
    process the ladder's peak is the MAX of these; with the whole ladder in one
    process there is a single leg and the figure is their ACCUMULATION, which
    is the defect. The supervisor already tags every sample with the attempt it
    was taken under, and a leg is one attempt, so this needs no new instrument.

    None means NOT MEASURED — no sidecar, or a `ps` with no rss support (the
    supervisor flags that itself as `resource_probe_degraded`), or a leg
    shorter than the sampling interval. It is never replaced by a 0, which a
    reader would take for "measured, and it was empty".
    """
    if telemetry_path is None:
        return None
    try:
        doc = json.loads(Path(telemetry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    peaks = [int(sample["rss_kib"])
             for sample in (doc.get("samples") or [])
             if isinstance(sample, dict)
             and sample.get("attempt") == attempt_number
             and isinstance(sample.get("rss_kib"), int)]
    return max(peaks) if peaks else None


#: Yosys's OWN closing line, one per process: `End of script. Logfile hash:
#: …, time: …, MEM: 166.80 MB peak`. It is the tool's `ru_maxrss` for THAT
#: process, so it is an exact peak rather than a poll, and it is present for a
#: rung that lasted 0.15 s exactly as for one that lasted an hour.
_YOSYS_PEAK_MEM_RE = re.compile(
    r"End of script\..*?MEM:\s*([0-9]+(?:\.[0-9]+)?)\s*MB peak")


def yosys_self_reported_peak_kib(raw: Optional[str]) -> Optional[int]:
    """The peak Yosys itself reports for ONE leg, in KiB. None = NOT MEASURED.

    WHY THIS EXISTS, AND WHAT IT REPLACES AS THE PRIMARY SOURCE (vibe-ic#2194).
    `leg_peak_rss_kib` reads the supervisor's samples, and the supervisor polls
    every `DEFAULT_POLL_S` (30 s). A poll is not a peak. MEASURED on a 1153-point
    miter, per-rung arm, this file's own instrument against Yosys's:

        rung                 supervisor        Yosys's own
        equiv_simple_full    165100 KiB        154.53 MB
        equiv_induct_seq4     64832 KiB        166.80 MB   <- 2.6x UNDERSTATED
        equiv_induct_seq16    53016 KiB         45.55 MB
        equiv_induct_seq64    53412 KiB         46.00 MB

    The seq4 row is the defect: one sample landed while that process was small,
    and a sample was then published in a field named `peak`. That is a number
    that reads as measured and is not the quantity it names — and #2194's whole
    acceptance is "the ladder's peak is the MAX of its rungs", which cannot be
    read off an instrument that can miss a rung's maximum entirely. The same
    poll also reports NOTHING for a rung shorter than its interval, which is why
    c071f6253 could only record `legs 2-4 NOT_MEASURED — each ran in under 1 s`
    and had to land `Refs #2194` rather than close it.

    Yosys states the figure itself, in the evidence every run already keeps, and
    nothing read it. `MB` here is `ru_maxrss / 1024` on Linux, so KiB is the
    figure times 1024 — CROSS-CHECKED against the supervisor on the single-
    process arm of the same design, where the poll did catch the maximum:
    211.43 MB -> 216504 KiB against the supervisor's 222940 KiB for the whole
    process TREE, agreeing to 3%.

    The LAST match, not the first: a leg's output is that one process's log, but
    a resumed leg's evidence can carry the earlier leg's tail, and the closing
    line is the one that belongs to the process that just ended.
    """
    if not raw:
        return None
    finals = _YOSYS_PEAK_MEM_RE.findall(raw)
    if not finals:
        return None
    try:
        return int(round(float(finals[-1]) * 1024))
    except (TypeError, ValueError):
        return None


def leg_peak_rss(sampled: Optional[int],
                 self_reported: Optional[int]) -> Tuple[Optional[int], Optional[str]]:
    """(peak_kib, source) for ONE leg from the sources that exist.

    Both are LOWER BOUNDS on the true peak — the supervisor can poll past a
    maximum, and Yosys's figure covers the Yosys process alone while the
    supervisor covers the whole stamped tree — so the larger is the better
    estimate and taking it can never overstate beyond what one of them measured.
    Neither present is NOT_MEASURED: None, never 0.
    """
    present = [(v, n) for v, n in ((sampled, "supervisor samples"),
                                   (self_reported, "yosys end-of-script"))
               if isinstance(v, int)]
    if not present:
        return None, None
    best = max(present)[0]
    return best, "+".join(n for _, n in present)


def proof_state_carry(legs: List[Dict]) -> Dict:
    """Did the PROVED SET survive each process boundary? (vibe-ic#2194)

    A restart from a checkpoint that had lost what was already proved would
    silently re-prove it and LOOK EXACTLY LIKE PROGRESS — same passes, same
    log shape, more wall clock. So this is MEASURED on every run instead of
    assumed: leg k+1 reads its own position back out of its LEADING
    `equiv_status` (`proved_at_entry`), and that must equal what leg k's
    CLOSING `equiv_status` reported (`proved_at_exit`).

    `carried` is True only when every boundary was measured AND agreed, False
    as soon as one measured boundary disagrees, and None — NOT_MEASURED, never
    a default True — when nothing disagreed but a boundary could not be read.
    """
    boundaries = []
    for prev, cur in zip(legs, legs[1:]):
        exit_p = prev.get("proved_at_exit")
        entry_p = cur.get("proved_at_entry")
        boundaries.append({
            "from_rung": prev.get("rung"), "to_rung": cur.get("rung"),
            "proved_at_exit": exit_p, "proved_at_entry": entry_p,
            "carried": (None if exit_p is None or entry_p is None
                        else exit_p == entry_p),
        })
    verdicts = [b["carried"] for b in boundaries]
    if any(v is False for v in verdicts):
        carried = False
    elif verdicts and all(v is True for v in verdicts):
        carried = True
    else:
        carried = None
    return {
        "boundaries": boundaries,
        "boundaries_measured": sum(1 for v in verdicts if v is not None),
        "boundaries_total": len(boundaries),
        "carried": carried,
    }


def recover_orphan_checkpoints(ckpt_dir: Path, key: str,
                               base_script_sha256: str, reports_dir: Path,
                               **manifest_fields: Any) -> List[str]:
    """Promote `.part` files a PREVIOUS invocation wrote but never published.

    WHY THIS IS NOT OPTIONAL. Promotion normally happens on this program's own
    return path, so every stop that ROUTES THROUGH IT — the progress watchdog,
    a container-side kill, `subprocess.TimeoutExpired` — publishes its
    checkpoints. A stop that does NOT (the runner's outer subprocess budget
    killing `lec_run.py` itself, an OOM, a reboot) leaves complete `.part`
    files that nothing would ever promote, and the next invocation's prune
    would DELETE the very work this feature exists to preserve. Measured on
    sha256: two complete 43.8 MB rungs were sitting as `.part` while the run
    was in flight.

    The attestation is the same one promotion always uses, read out of the
    LIVE LOG the previous invocation was tee-ing (`reports/lec.live.*.rpt`,
    plus the published `lec.rpt`), and it is SCOPED to this checkpoint
    directory's name so another attempt's log cannot vouch for these bytes.
    Never raises: recovery is a bonus, and a filesystem that will not give it
    must not fail a proof.
    """
    ckpt_dir = Path(ckpt_dir)
    orphans = [r for r in LEC_CHECKPOINT_RUNGS
               if (ckpt_dir / (r + ".il.part")).is_file()]
    if not orphans:
        return []
    recovered: List[str] = []
    try:
        logs = sorted(Path(reports_dir).glob("lec.live.*.rpt"))
        published = Path(reports_dir) / DEFAULT_RPT_REL.split("/")[-1]
        if published.is_file():
            logs.append(published)
    except OSError:
        return []
    for log in logs:
        if not [r for r in LEC_CHECKPOINT_RUNGS
                if (ckpt_dir / (r + ".il.part")).is_file()]:
            break
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # The log that ATTESTS the orphan is also the evidence that leg
        # produced -- the same file, so the manifest names the one it read.
        got = promote_and_record_checkpoints(
            ckpt_dir, key, base_script_sha256, text,
            **{**manifest_fields, "evidence_log": log})
        for rung in got:
            if rung not in recovered:
                recovered.append(rung)
    return sorted(recovered, key=ladder_index)


def prune_superseded_ladders(ckpt_dir: Path, key: str,
                             base_script_sha256: str) -> List[str]:
    """Remove the rung artefacts of a ladder this identity has MOVED ON from.

    A checkpoint directory is named by `lec_checkpoint_key`, which binds the
    design and the tool but DELIBERATELY NOT the script — so when the emitted
    ladder changes (a plugin release that adds or reorders a rung), the SAME
    directory receives a second ladder's rungs under a new
    `base_script_sha256`. The old ladder's `.il` files can never revalidate
    again (`select_resume_checkpoint` refuses on the ladder mismatch, by name),
    but nothing removed them: a 43.8 MB rung per ladder per design, kept
    forever. A checkpoint directory with no bound is a disk leak.

    Bounded to ONE ladder — the latest one to record a rung here. Only rungs
    whose OWN manifest names THIS key and a DIFFERENT ladder are removed, and
    only the three files this program writes for a rung. A manifest that will
    not parse, one that names another key, and any file this program does not
    write are left exactly where they are: an unreadable manifest is not
    evidence that its .il is dead.

    Returns the file names removed. Never raises — a filesystem that will not
    take a deletion must not fail a proof that already succeeded.
    """
    ckpt_dir = Path(ckpt_dir)
    removed: List[str] = []
    for rung in LEC_CHECKPOINT_RUNGS:
        man_path = ckpt_dir / (rung + ".json")
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        if (manifest.get("schema_version") != LEC_CHECKPOINT_SCHEMA_VERSION
                or manifest.get("checkpoint_key") != key
                or manifest.get("base_script_sha256") == base_script_sha256):
            continue
        for name in (rung + ".il", rung + ".evidence.rpt", rung + ".json"):
            try:
                (ckpt_dir / name).unlink()
                removed.append(name)
            except OSError:
                continue
    return removed


def prune_stale_checkpoint_parts(ckpt_dir: Path) -> List[str]:
    """Remove `<rung>.il.part` leftovers of a run killed mid-write.

    Only files this program itself writes, only in this key's own directory,
    only the `.part` spelling — a promoted `.il` and its manifest are never
    touched here.
    """
    removed: List[str] = []
    for rung in LEC_CHECKPOINT_RUNGS:
        part = Path(ckpt_dir) / (rung + ".il.part")
        try:
            if part.is_file():
                part.unlink()
                removed.append(part.name)
        except OSError:
            continue
    return removed


def _has_fingerprint(value: Any) -> bool:
    """A required artefact is either hash-bound or explicitly not in use."""
    return (isinstance(value, dict)
            and ((isinstance(value.get("sha256"), str)
                  and value["sha256"].startswith("sha256:")
                  and len(value["sha256"]) > len("sha256:"))
                 or value.get("state") in ("absent", "unused")))


def proof_identity_complete(identity: Any) -> bool:
    """Old/partial cache formats are misses, never optimistically upgraded."""
    if not isinstance(identity, dict):
        return False
    if not isinstance(identity.get("recipe_schema_version"), str):
        return False
    if not isinstance(identity.get("top"), str) or not identity["top"]:
        return False
    gold = identity.get("gold_rtl")
    if not isinstance(gold, list) or not gold or not all(
            isinstance(x, dict) and isinstance(x.get("path"), str)
            and _has_fingerprint(x) for x in gold):
        return False
    if not _has_fingerprint(identity.get("gate_netlist")):
        return False
    if not _has_fingerprint(identity.get("equivalence_script")):
        return False
    scan = identity.get("scan")
    if not isinstance(scan, dict) or not all(
            _has_fingerprint(scan.get(k))
            for k in ("metadata", "gate_wrapper", "gold_wrapper")):
        return False
    if not _has_fingerprint(identity.get("liberty")):
        return False
    yosys = identity.get("yosys")
    image = identity.get("container")
    return bool(isinstance(yosys, dict) and yosys.get("version")
                and isinstance(image, dict) and image.get("image_digest"))


def pass_cache_eligible(report: Any) -> bool:
    """Only a completed, non-vacuous proof may seed/reuse the PASS cache."""
    return bool(
        isinstance(report, dict)
        and report.get("verdict") == "PASS"
        and report.get("equivalent") is True
        and isinstance(report.get("compared_points"), int)
        and report["compared_points"] > 0
        and report.get("non_equivalent_points") == 0
        and report.get("unproven_points") == 0
        and not report.get("inconclusive")
        and not report.get("parse_error")
        and not report.get("budget_exhausted")
        and not report.get("progress_stalled"))


def _raw_rpt_matches_pass(report: Dict, raw_rpt: str) -> bool:
    """Require the cached raw Yosys evidence to corroborate the JSON PASS."""
    parsed = parse_equiv_output(raw_rpt)
    return bool(parsed.get("verdict") == "PASS"
                and parsed.get("equivalent") is True
                and parsed.get("success_line") is True
                and parsed.get("proven") == report.get("compared_points")
                and parsed.get("unproven") == 0)


def store_pass_cache(cache_dir: Path, identity: Dict, report: Dict,
                     raw_rpt: str, *,
                     source_proof_timestamp: Optional[str] = None
                     ) -> Optional[Path]:
    """Atomically publish a complete PASS entry; every other state is ignored."""
    cache_dir = Path(cache_dir)
    if (not proof_identity_complete(identity)
            or not pass_cache_eligible(report)
            or not _raw_rpt_matches_pass(report, raw_rpt)):
        return None
    if report.get("proof_identity") != identity:
        return None
    key = lec_cache_key(identity)
    entry_dir = cache_dir / key.split(":", 1)[1]
    report_bytes = (json.dumps(report, indent=2, ensure_ascii=False)
                    + "\n").encode("utf-8")
    rpt_bytes = raw_rpt.encode("utf-8")
    _atomic_write_bytes(entry_dir / "source_report.json", report_bytes)
    _atomic_write_bytes(entry_dir / "source_lec.rpt", rpt_bytes)
    manifest = {
        "schema_version": LEC_PASS_CACHE_SCHEMA_VERSION,
        "cache_key": key,
        "proof_identity": identity,
        "source_proof_timestamp": source_proof_timestamp or _utc_now(),
        "source_report": {
            "path": "source_report.json",
            "sha256": _sha256_bytes(report_bytes),
        },
        "source_rpt": {
            "path": "source_lec.rpt",
            "sha256": _sha256_bytes(rpt_bytes),
        },
    }
    # Manifest last is the commit point. A partial directory cannot hit.
    _atomic_write_json(entry_dir / "entry.json", manifest)
    return entry_dir / "entry.json"


def find_pass_cache(cache_dir: Path, identities: Dict[str, Dict], *,
                    invocation_timestamp: Optional[str] = None
                    ) -> Optional[Dict]:
    """Return a revalidated PASS plus a fresh invocation attestation."""
    cache_dir = Path(cache_dir)
    for key, current_identity in identities.items():
        if key != lec_cache_key(current_identity):
            continue
        if not proof_identity_complete(current_identity):
            continue
        entry_dir = cache_dir / key.split(":", 1)[-1]
        try:
            manifest = json.loads((entry_dir / "entry.json").read_text())
            source_report_meta = manifest["source_report"]
            source_rpt_meta = manifest["source_rpt"]
            if (not isinstance(source_report_meta, dict)
                    or source_report_meta.get("path") != "source_report.json"
                    or not isinstance(source_rpt_meta, dict)
                    or source_rpt_meta.get("path") != "source_lec.rpt"):
                continue
            report_bytes = (entry_dir / "source_report.json").read_bytes()
            rpt_bytes = (entry_dir / "source_lec.rpt").read_bytes()
            source_report = json.loads(report_bytes)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (manifest.get("schema_version") != LEC_PASS_CACHE_SCHEMA_VERSION
                or manifest.get("cache_key") != key
                or manifest.get("proof_identity") != current_identity
                or source_report.get("proof_identity") != current_identity
                or source_report_meta.get("sha256")
                    != _sha256_bytes(report_bytes)
                or source_rpt_meta.get("sha256")
                    != _sha256_bytes(rpt_bytes)
                or not pass_cache_eligible(source_report)
                or not isinstance(manifest.get("source_proof_timestamp"), str)
                or not manifest["source_proof_timestamp"]
                or not _raw_rpt_matches_pass(
                    source_report, rpt_bytes.decode("utf-8", "replace"))):
            continue
        hit = copy.deepcopy(source_report)
        hit["cache_use_attestation"] = {
            "hit": True,
            "cache_key": key,
            "source_report_sha256": _sha256_bytes(report_bytes),
            "source_rpt_sha256": _sha256_bytes(rpt_bytes),
            "source_proof_timestamp": manifest.get("source_proof_timestamp"),
            "invocation_timestamp": invocation_timestamp or _utc_now(),
            "revalidated_identity": copy.deepcopy(current_identity),
        }
        # Internal transport only; main removes it before writing lec.json.
        hit["_cache_source_rpt"] = rpt_bytes.decode("utf-8", "replace")
        return hit
    return None


def lec_stage_from_output(raw: str) -> str:
    """Best-effort live Yosys stage; evidence only, never a verdict input."""
    upper = raw.upper()
    inducts = upper.count("EXECUTING EQUIV_INDUCT PASS")
    if inducts:
        return ("equiv_induct_seq4", "equiv_induct_seq16",
                "equiv_induct_seq64")[min(inducts, 3) - 1]
    simples = upper.count("EXECUTING EQUIV_SIMPLE PASS")
    if simples >= 2:
        return "equiv_simple_full"
    if simples == 1:
        return "equiv_simple_short"
    if "EXECUTING EQUIV_STRUCT PASS" in upper:
        return "equiv_struct"
    if "EXECUTING EQUIV_MAKE PASS" in upper:
        return "equiv_make"
    return "setup"


def lec_proved_points_from_output(raw: str) -> Optional[Dict[str, int]]:
    """The proof's OWN measure of how far it has got: proved / unproven points.

    WHY THIS EXISTS (measured 2026-09-06, an open benchmark IC on 8HD-8). A
    post-layout LEC was killed by a wall-clock ceiling at 7195 s of a 7200 s
    budget. Its telemetry sidecar recorded `status: "hard_ceiling"`,
    `returncode: 124`, and 239 samples whose `cpu_seconds` tracked `elapsed_sec`
    at 99.99 % to the very last look -- so the artefact PROVED the job was
    working at a full core when it died. What the artefact could NOT say is how
    far the proof had got, because nothing in it records a proved-point count:
    `proved`, `unproven`, `points` and `equiv_status` appear nowhere in the
    file. A reader could see that it was busy, never that it was CONVERGING.

    That gap is the difference between "we killed something busy" and "we killed
    something 1374 points into a proof". This parser closes it, and it is
    EVIDENCE ONLY -- it never reaches a verdict. `parse_equiv_output` remains
    the sole authority on PASS/FAIL/INCONCLUSIVE.

    Returns None when the log carries no count yet (the honest answer during
    `equiv_make`), never a fabricated zero. PURE.

    It REUSES the parser's own patterns (`_FINAL_RE`, `_PROVED_SIMPLE_RE`,
    `_INDUCT_FOUND_RE`), which are defined below this function and resolve at
    call time -- deliberately, so this probe sits beside its sibling
    `lec_stage_from_output` and can never drift into a SECOND spelling of how a
    Yosys count is read.
    """
    if not raw:
        return None
    # STRIPPED BEFORE COUNTING. A yosys log can quote source back at you; a
    # commented-out sentence that happens to match one of these lines is not a
    # position this proof reached. All three patterns read the SAME stripped
    # text, so the probe cannot report a `proved` from one text and an
    # `unproven` from another.
    scanned = strip_echoed_hdl_comments(raw)

    # AND THEN ASKED WHETHER THE LINE DENIES ITS OWN NUMBER.
    #
    # Stripping closes `//` comments. It does not close a /* block comment */,
    # and it cannot close an echoed English sentence that is not a comment at
    # all. Anchoring closed `_INDUCT_FOUND_RE`, and anchoring is NOT AVAILABLE
    # to the other two -- MEASURED, not assumed: the real yosys line is
    #     "  Of those cells 798 are proven and 1039 are unproven."
    # which carries leading text, so `(?m)^` would stop matching the very
    # output this probe exists to read. Polarity is what generalises, and
    # `_FINAL_RE` is consulted FIRST and returns immediately, so it is the one
    # that decides.
    #
    # `extra_breaks=("\n",)` because a yosys log is a machine-generated report
    # whose consecutive lines are unrelated RECORDS. `sentence_scope`'s own
    # docstring (vibe-ic#790) records what a caller that does not say so
    # inherits: a denial in a LATER, UNRELATED line retracts this line's
    # number -- quietly, with nothing going red.
    def _asserted(matches):
        """The matches whose own log line does not DENY the number in them."""
        kept = []
        for mo in matches:
            lo, hi = sentence_scope(scanned, mo.start(), mo.end(),
                                    extra_breaks=("\n",))
            if is_denied(scanned[lo:hi]) is None:
                kept.append(mo)
        return kept

    out: Dict[str, int] = {}
    m = _asserted(list(_FINAL_RE.finditer(scanned)))
    if m:
        out["proved"] = int(m[-1].group(1))
        out["unproven"] = int(m[-1].group(2))
        return out
    p = _asserted(list(_PROVED_SIMPLE_RE.finditer(scanned)))
    if p:
        out["proved"] = int(p[-1].group(1))
    u = _asserted(list(_INDUCT_FOUND_RE.finditer(scanned)))
    if u:
        out["unproven"] = int(u[-1].group(1))
    return out or None


_INDUCT_PASS_RE = re.compile(r"(?m)^\d+(?:\.\d+)*\. Executing EQUIV_INDUCT pass\.")
_INDUCT_WORKSET_RE = re.compile(
    r"(?m)^Found (\d+) unproven \$equiv cells in module \S+:$")
_INDUCT_DECISION_RE = re.compile(
    r"(?m)^\s+Trying to prove \$equiv for .+: (success!|failed\.)\s*$")


def induct_decision_progress(raw: str) -> Optional[Dict[str, int]]:
    """How far the LAST `equiv_induct` pass in `raw` has got deciding points.

    `equiv_induct` first builds and solves its whole-design induction model,
    printing nothing countable; when the whole-set step fails it decides the
    points ONE AT A TIME, one line each (`Trying to prove $equiv for <p>:
    success!` / `: failed.`). This reads that phase: the pass's workset (its
    `Found N unproven $equiv cells` line) and the decisions printed so far.

    Returns None before the pass has stated its workset -- no evidence yet, and
    never a fabricated zero. `equiv_simple`'s `...:ezsat` lines are not
    decisions of this pass and are not counted. Evidence only; the verdict is
    `parse_equiv_output`'s. PURE."""
    import instrument_calibration
    instrument_calibration.assert_calibrated(
        "lec_run::induct_decision_progress")
    if not raw:
        return None
    # A Yosys error can echo HDL source into the live log.  This progress
    # reader is evidence-only, but its result controls the projection probe;
    # quoted comments must therefore not manufacture a workset or decisions.
    scanned = strip_echoed_hdl_comments(raw)
    starts = list(_INDUCT_PASS_RE.finditer(scanned))
    if not starts:
        return None
    tail = scanned[starts[-1].end():]
    ws = _INDUCT_WORKSET_RE.search(tail)
    if not ws:
        return None
    decisions = _INDUCT_DECISION_RE.findall(tail[ws.end():])
    proved = sum(1 for d in decisions if d == "success!")
    return {"workset": int(ws.group(1)), "decided": len(decisions),
            "proved": proved, "failed": len(decisions) - proved}


#: The fewest per-point decisions a rate is measured over before a projection
#: may speak. Below it the rate is noise, and the probe says nothing.
PROJECTION_MIN_DECISIONS = 20


def rung_projection_abort_probe(live_log_path: Path, offset: int,
                                budget: "StepBudget", *,
                                clock=time.monotonic):
    """The `abort_probe` a LEC rung runs under (FX_AES_LEC_SCALE).

    THE STEP BUDGET STILL STOPS NOTHING BY ITSELF (#2051, R-0915-48): a proof
    whose rate would finish inside the budget, or one that has decided nothing
    yet, is never touched, however long it runs. What stops a rung is the
    PROOF'S OWN EVIDENCE that it cannot finish in the declared budget: once
    `equiv_induct` is deciding points one at a time, the measured decision
    rate projects the time the remaining workset needs, and when that exceeds
    what is left of the step budget the rung is going nowhere within it. It is
    aborted then -- not at the deadline -- with the numbers, and the ladder
    reports INCONCLUSIVE at its last durable checkpoint.

    MEASURED on opentitan_aes x sky130A (84,623 cells): `equiv_induct -seq 4`
    decided 936 of 3,219 points in ~3,300 s (3.5 s each) after ~4,100 s of
    model building; at that rate the rung needed ~11,000 s more, inside a
    7,200 s declared step budget. The run's outer timeout killed it instead,
    with no verdict and no counts."""
    state: Dict[str, Any] = {"first": None}

    def probe() -> Optional[str]:
        try:
            with open(live_log_path, "rb") as fh:
                fh.seek(offset)
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        try:
            prog = induct_decision_progress(text)
        except Exception:                      # noqa: BLE001 - no evidence
            return None
        if not prog or prog["decided"] <= 0:
            return None
        now = clock()
        if state["first"] is None:
            state["first"] = (now, prog["decided"])
            return None
        t0, d0 = state["first"]
        done = prog["decided"] - d0
        if done < PROJECTION_MIN_DECISIONS or now <= t0:
            return None
        rate = done / (now - t0)
        remaining = prog["workset"] - prog["decided"]
        need_s = remaining / rate
        left_s = budget.remaining_s()
        if need_s <= left_s:
            return None
        return (f"the step budget cannot be met at the proof's own measured "
                f"rate: equiv_induct has decided {prog['decided']} of "
                f"{prog['workset']} points ({prog['proved']} proven, "
                f"{prog['failed']} failed) at {rate:.3f} points/s, so the "
                f"remaining {remaining} need ~{need_s:.0f}s and "
                f"{max(left_s, 0)}s of the {budget.total_s}s step budget is "
                f"left. Those in-rung decisions are not durable (equiv_induct "
                f"keeps them in memory); the proof state reported is the last "
                f"checkpoint's")

    return probe


def attach_telemetry(report: Dict, sidecar: Path, project: Path) -> Dict:
    """Hash-bind the exact telemetry bytes into the final verdict report."""
    try:
        data = Path(sidecar).read_bytes()
        record = json.loads(data)
    except (OSError, ValueError) as exc:
        report["telemetry"] = {
            "available": False,
            "reason": f"telemetry sidecar unavailable: {exc}",
        }
        return report
    try:
        rel = str(Path(sidecar).resolve().relative_to(Path(project).resolve()))
    except ValueError:
        rel = str(Path(sidecar).resolve())
    report["telemetry"] = {
        "available": True,
        "path": rel,
        "sha256": _sha256_bytes(data),
        "record": record,
    }
    return report


#: Statuses the SUPERVISOR writes to say a run was STOPPED rather than finishing.
#: `_docker_watchdog.run_docker_supervised` owns them; nothing else may spell a
#: stop, and nothing else may unspell one.
_SUPERVISOR_STOP_STATUSES = ("hard_ceiling", "progress_stalled")


def _finish_telemetry_sidecar(sidecar: Path, status: str, **extra: Any) -> None:
    """Close the telemetry sidecar for the step.

    A STOP RECORDED BY THE SUPERVISOR IS NOT OVERWRITTEN. Measured on a real
    production sidecar: a proof SIGKILLed by its container ceiling carried

        telemetry["status"]              = "complete"      <- the field a
                                                              consumer reads
        telemetry["returncode"]          = 124
        telemetry["attempts"][-1].status = "hard_ceiling"  <- the truth, one
                                                              level down

    because `run_docker_supervised` had written `hard_ceiling` and this function
    then wrote `complete` over it at step end. Two writers of one field with two
    vocabularies — "the tool exited naturally" and "the step is done" — and the
    later one won. The kill survived only in the nested attempt record, which is
    written before the overwrite and which no consumer looks at first.

    The supervisor is the authority on HOW A RUN ENDED, so a recorded stop now
    stands. `step_status` carries what this function would have written, so the
    step-completion fact is not lost — it is just no longer allowed to
    impersonate the run's outcome. Every other status (`complete`, `cache_hit`,
    `tool_unavailable`) is written exactly as before, and a sidecar that carries
    no supervisor stop is byte-identical to the previous behaviour.
    """
    try:
        doc = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {"schema_version": LEC_TELEMETRY_SCHEMA_VERSION,
               "samples": [], "attempts": []}
    _recorded = str(doc.get("status") or "")
    if _recorded in _SUPERVISOR_STOP_STATUSES:
        doc["step_status"] = status
    else:
        doc["status"] = status
    doc["finished_timestamp"] = _utc_now()
    doc.update(extra)
    _atomic_write_json(Path(sidecar), doc)

# ---------------------------------------------------------------------------
# Yosys equiv_status output parser (PURE — the tests call this directly).
#
# Ported verbatim in spirit from mcp-eda/src/index.js yosys_equiv parsing.
# Every regex below has been validated against real Yosys 0.66 output for
# BOTH the clean-PASS case (generic $_-primitive netlist) and the
# SAT-model-limited case (sky130_fd_sc_hd-mapped netlist).
# ---------------------------------------------------------------------------

# Final summary from `equiv_status` (present when the run completes):
#   "  Of those cells 71 are proven and 0 are unproven."
_FINAL_RE = re.compile(r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven")

# Direct total — equiv_simple ENTRY line:
#   "Found 71 unproven $equiv cells (71 groups) in equiv:"
_EQUIV_SIMPLE_ENTRY_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:")

# Direct total — final equiv_status header / older Yosys total line:
#   "Found 71 $equiv cells in equiv:"   (NB: no `unproven` infix)
_OLD_TOTAL_RE = re.compile(r"Found\s+(\d+)\s+\$equiv\s+cells")

# Fallback proven — equiv_simple's proved-count line:
#   "Proved 35 previously unproven $equiv cells."
_PROVED_SIMPLE_RE = re.compile(
    r"Proved\s+(\d+)\s+previously\s+unproven\s+\$equiv\s+cells")

# Forward-compat proven/total — a hypothetical newer "Proved M/N" shape.
_SIMPLE_SLASH_RE = re.compile(
    r"equiv_simple[^\n]*Proved\s+(\d+)/(\d+)\s+\$equiv\s+cells")

# Fallback unproven — equiv_induct residual line, anchored on `in module
# equiv:` so it does NOT collide with the equiv_simple entry line above:
#   "Found 35 unproven $equiv cells in module equiv:"
#
# ANCHORED TO THE START OF A LINE (`(?m)^[ \t]*`). yosys prints this line at
# column 0 — verified over every fixture in this suite and over four real logs
# on 8HD-9 (sha256, an 8x8 MAC, a re-encoded FSM), none of which carries a
# non-whitespace prefix — while a Verilog line the tool ECHOES into its log
# carries whatever prefixed it in the source. Without the anchor, a design
# containing the comment
#     // Found 999 unproven $equiv cells in module equiv:
# echoed by yosys in an error would be read as this run's residual count, and
# `parse_equiv_output` uses this same pattern as its unproven FALLBACK when no
# equiv_status line exists — so the spoof would reach a verdict, not just the
# evidence. The anchor costs nothing (every real match is already at line
# start) and closes that.
_INDUCT_FOUND_RE = re.compile(
    r"(?m)^[ \t]*Found\s+(\d+)\s+unproven\s+\$equiv\s+cells"
    r"\s+in\s+module\s+equiv\s*:")

#: A Verilog LINE COMMENT that a tool echoed into its own log. Anchored at the
#: start of a line on purpose: an absolute path (`/foss/pdks/...`) and a `//`
#: inside a sentence are NOT comments here and must survive. Measured on a real
#: 2.23 MB sha256 LEC log: 18,472 lines in, 18,472 out, `/foss/pdks` intact,
#: 11.5 ms per call.
_HDL_LINE_COMMENT_RE = re.compile(r"(?m)^[ \t]*//.*$")


def strip_echoed_hdl_comments(text: str) -> str:
    """Drop HDL line comments a tool echoed into its log, before counting.

    The counting patterns below are matched against TOOL OUTPUT, and tool
    output can contain SOURCE that the tool quoted back. A commented-out line
    is not something the run did; reading one as a proved-point count states a
    position the proof never reached. PURE.
    """
    return _HDL_LINE_COMMENT_RE.sub("", text or "")

# SAT-model abort (chip-AGNOSTIC): the honest capability-gap signal.
#   "ERROR: No SAT model available for cell _204__gate (sky130_fd_sc_hd__lpflow_isobufsrc_1)."
_SAT_ABORT_RE = re.compile(
    r"No SAT model available for cell\s+(\S+)\s+\((\S+?)\)")

# Best-effort per-instance unproven cell list.
_UNPROVEN_LIST_RE = re.compile(r"Unproven\s+\$equiv\s+cells:\s*([^\n]+)")

# SECONDARY SOURCE for the same list (vibe-ic#2182). `_UNPROVEN_LIST_RE` reads
# the closing `equiv_status` summary -- which a run that never REACHES
# `equiv_status` does not print. Both blocked benchmark ICs measured on
# 2026-09-07 are exactly that shape: opentitan_aes stopped inside
# `equiv_induct -seq 64` (rc=137) with `unproven_points: 3`, and sha256 was
# still inside the ladder with 34 -- and BOTH published `unproven_cells: []`
# while their own raw log named every one of those cells, at column 2, in the
# `equiv_induct` workset block:
#
#     Proof for induction step failed. Trying to prove individual $equiv from workset.
#       Trying to prove $equiv for \u_dut...u_reg_status_key_init.clean_d: failed.
#
# A count with no names is what forced a human to read a 10 MB log to learn
# three identifiers the program already had in hand. So: when the primary
# summary line is ABSENT, read the names from the LAST workset block instead --
# last, for the same reason `_INDUCT_FOUND_RE` takes the last residual line
# (each rung re-reports what is STILL unproven, so the furthest state the run
# reached is the last one it printed). The name may contain spaces
# (`\read_data [0]`), so the pattern anchors on the `: failed.` suffix at
# end-of-line rather than on whitespace. This NEVER overrides the primary
# source and NEVER invents: with neither present the list stays empty, which
# is the honest "could not read it", not a default.
_INDUCT_WORKSET_MARK = ("Proof for induction step failed. "
                        "Trying to prove individual $equiv from workset.")
_INDUCT_WORKSET_FAIL_RE = re.compile(
    r"^[ \t]+Trying to prove \$equiv for (.+?): failed\.[ \t]*$", re.M)


def unproven_cells_from_induct_workset(text: str) -> List[str]:
    """Names of the $equiv cells the LAST induction workset failed to prove.

    Order-preserving and de-duplicated; empty when the log has no workset
    block, which is the same "no names available" the primary source reports.
    """
    text = text or ""
    cut = text.rfind(_INDUCT_WORKSET_MARK)
    scanned = text[cut:] if cut >= 0 else text
    out: List[str] = []
    for m in _INDUCT_WORKSET_FAIL_RE.finditer(scanned):
        name = m.group(1).strip()
        if name and name not in out:
            out.append(name)
    return out

# BUDGET-EXHAUSTED marker (#155 POSITIVE timeout discriminator). run_yosys_equiv
# (below) writes this EXACT string into the raw log ITSELF when the yosys
# subprocess is KILLED by the wall budget — it is NOT tool output a design could
# emit, so it can never be spoofed by a genuine-garbage log. Post-memory_map a
# memory-bearing design is genuinely satgen-modelable, so equiv_induct ATTEMPTS
# the full sequential proof; on a large design (e.g. sha256's memory-inclusive
# miter, or a whole AES cipher whose S-box/GF cones are SAT-intractable) that
# proof can exceed the LEC wall clock, leaving no final equiv_status → the run
# is killed. A killed run produced NO completed comparison, so the cause must be
# NAMED (raise --timeout) instead of read as a mismatch that was never found.
_TIMEOUT_MARKER = "[lec_run] ERROR: yosys equiv exceeded its time budget"
_TIMEOUT_RE = re.compile(re.escape(_TIMEOUT_MARKER))

# A progress-stall kill is a different resource outcome from exhausting the
# caller's total wall budget.  Both mean "the proof did not complete" and both
# must block frontend retries / false non-equivalence, but the report must say
# which one happened.  `_progress_run.RC_STALLED` is deliberately distinct
# from GNU timeout's 124/137, so preserve that distinction all the way to the
# raw evidence instead of collapsing it into a misleading timeout.
_STALL_MARKER = "[lec_run] ERROR: yosys equiv stopped making forward progress"
_STALL_RE = re.compile(re.escape(_STALL_MARKER))
_EXECUTION_STOP_RE = re.compile(
    f"(?:{re.escape(_TIMEOUT_MARKER)}|{re.escape(_STALL_MARKER)})")


def strip_producer_stop_markers(raw: str) -> Tuple[str, int]:
    """Drop the lines carrying THIS producer's own stop markers. (text, count)

    Used only on a PRIOR leg's log when a resumed run carries it forward as
    evidence. Those two markers say how THAT leg ended; carrying them would
    make the current run report a kill it did not suffer -- `budget_exhausted`
    and `progress_stalled` are read off exactly these strings. The fact that a
    prior leg was stopped is not lost: it is recorded in
    `lec_resume.carried_evidence.prior_leg_was_stopped`, which is measured HERE
    and returned as the count. PURE.
    """
    kept, dropped = [], 0
    for line in (raw or "").splitlines(True):
        if _TIMEOUT_MARKER in line or _STALL_MARKER in line:
            dropped += 1
            continue
        kept.append(line)
    return "".join(kept), dropped


def run_was_stopped(raw: str) -> bool:
    """Was this run CUT OFF, or did it finish and decide?

    The two markers `_EXECUTION_STOP_RE` matches are written by THIS PRODUCER's
    own kill paths and by nothing else, so this is an observable about the run
    and never a reading of the tool's prose — which is why it is a predicate
    with a name rather than a `bool(RE.search(...))` spelled at each call site.
    Three places ask this question; they must not be able to answer it
    differently. PURE.
    """
    return bool(_EXECUTION_STOP_RE.search(raw or ""))

# A wall-budget kill reaches run_yosys_equiv by TWO paths that must be treated
# identically:
#   (1) the HOST `subprocess.run(timeout=…)` raises subprocess.TimeoutExpired; or
#   (2) the CONTAINER-side `timeout` that _docker wraps every call in
#       (wrap_with_container_timeout, added to stop the orphaned-tool leak) fires
#       `margin_s` seconds BEFORE the host deadline, so yosys is already dead and
#       `docker exec` returns NORMALLY with GNU-`timeout`'s exit code — the host
#       run never times out and path (1) is structurally UNREACHABLE for the
#       container flow. GNU `timeout` reports 124 when its SIGTERM expiry killed
#       the command, and 137 (128+9) when `--kill-after` had to escalate to
#       SIGKILL (the usual outcome for yosys mid-SAT, which ignores SIGTERM). A
#       container OOM-kill also surfaces as 137 — likewise a resource-exhaustion
#       no-verdict run, not a proven mismatch — so folding it in here is correct.
# Without recognising path (2), a killed-mid-proof run (0 completed comparisons,
# no counterexample) is misread as a hard FAIL (measured on opentitan_aes ×
# sky130A: 27904 $equiv cells, killed at 7200s, booked verdict=FAIL "may
# genuinely differ" — a false non-equivalence that halted the whole flow).
_CONTAINER_TIMEOUT_RCS = (124, 137)
_PROGRESS_STALL_RCS = (_pr.RC_STALLED,)
#: The supervisor's DELIBERATE stop: the caller's own predicate said the job is
#: going nowhere (here: cannot finish in the step budget at its own rate).
#: Read from the supervisor itself, never spelled a second time.
_RC_ABORTED = _pr._wd.RC_ABORTED

# EVIDENCE-BASED timeout split (merge of local FAIL vs origin #155
# SKIPPED-CONDITION). A wall-budget kill (parse_error + _TIMEOUT_RE) is a pure
# resource skip ONLY if the log carries NO recorded non-equivalence. This matches
# the UNMISTAKABLE counterexample / non-equivalence phrases a yosys/SAT run
# prints when it actually PROVED a difference — phrases a pure resource-
# exhaustion log can never contain. PRECISION-first: a miss degrades to the
# visible SKIPPED-CONDITION (never a PASS), a match escalates the timeout to a
# real FAIL. chip-AGNOSTIC — no chip/vendor literal.
_MISMATCH_EVIDENCE_RE = re.compile(
    r"counter-?example"
    r"|non-?equivalent"
    r"|inequivalent"
    r"|not\s+equivalent"
    r"|equivalence\s+(?:check\s+)?failed",
    re.IGNORECASE)

# Canonical Yosys success line (corroboration for the gate's .rpt parse).
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)

# #208 — induction NON-CONVERGENCE signatures. A COMPLETED equiv_make miter can
# leave points `unproven` for two very different reasons:
#   (a) a genuine difference — which yosys backs with a COUNTEREXAMPLE
#       (_MISMATCH_EVIDENCE_RE), OR
#   (b) equiv_induct's SAT induction simply did NOT CONVERGE on a large
#       sequential design — a flat wall that proved NOTHING and recorded NO
#       counterexample. (b) is INCONCLUSIVE, not NOT_EQUIVALENT: non-convergence
#       is not non-equivalence. These match the two flat-wall shapes seen in the
#       wild (chip-AGNOSTIC — pure yosys phrases):
#   * the SAT base case cannot even be established (`Circuit inherently
#     diverges!` — equiv_induct aborts at base-case step k), and
#   * an equiv_induct pass that `Proved 0 previously unproven $equiv cells` — the
#     escalating `-seq 4/16/64` sweep made zero progress.
_INDUCT_DIVERGE_RE = re.compile(r"[Cc]ircuit\s+inherently\s+diverges", re.IGNORECASE)
_PROVED_ZERO_RE = re.compile(
    r"Proved\s+0\s+previously\s+unproven\s+\$equiv\s+cells")


# YOSYS'S OWN INTERNAL COMBINATIONAL CELL VOCABULARY.
#
# This is a CLOSED, TOOL-DEFINED set (yosys's internal cell library: the `$_*_`
# gate-level primitives and the coarse-grain word-level operators), NOT a guess
# about any PDK's cell names. Membership is used ONLY to establish the POSITIVE
# fact "every cell in this miter is combinational". Anything not listed -- a
# PDK Liberty cell, a `$mem`, a flip-flop, a cell type added by a future yosys
# -- makes the answer "unknown", which keeps the PREVIOUS behaviour exactly.
# The asymmetry is deliberate: an omission from this list can only cost us the
# stricter verdict, never grant a softer one.
_YOSYS_COMB_CELL_TYPES = frozenset("""
$_NOT_ $_BUF_ $_AND_ $_NAND_ $_OR_ $_NOR_ $_XOR_ $_XNOR_ $_ANDNOT_ $_ORNOT_
$_MUX_ $_NMUX_ $_MUX4_ $_MUX8_ $_MUX16_ $_AOI3_ $_OAI3_ $_AOI4_ $_OAI4_
$_TBUF_ $not $pos $neg $and $or $xor $xnor $reduce_and $reduce_or $reduce_xor
$reduce_xnor $reduce_bool $logic_not $logic_and $logic_or $shl $shr $sshl
$sshr $shift $shiftx $lt $le $eq $ne $eqx $nex $ge $gt $add $sub $mul $div
$mod $divfloor $modfloor $pow $mux $pmux $bmux $demux $bwmux $tribuf $lut
$sop $macc $macc_v2 $alu $lcu $fa $concat $slice $buf $equiv
""".split())

# A state-bearing miter and a stateless one are different questions, and only
# the first one `equiv_induct` can answer.
# The miter module name `build_equiv_script` always uses.
_MITER_MODULE = "equiv"

# #2050 — THE FSM ENCODING TRANSLATION FILE.
#
# `synth` runs `fsm`, whose `fsm_recode` pass re-assigns the state encoding of
# every FSM it extracts.  `synth -encfile <f>` (passed through to `fsm_recode`)
# writes the old->new table; `equiv_make -encfile <f>` reads it back and builds
# the encoder/decoder that matches the two encodings.  This constant is the
# SINGLE source of truth for the file's name: the producer
# (design_one_shot_runner's two synth call-sites) imports it from here, and
# `fsm_encfile_beside_netlist` below is the consumer.  One definition is what
# stops a producer rename from silently disabling the LEC fix — a missing file
# is not an error anywhere, it just quietly restores the old, name-positional
# matching.
FSM_ENCFILE_NAME = "fsm_encoding.enc"


def fsm_encfile_beside_netlist(gate_netlist: str) -> Optional[str]:
    """Path of a nonempty FSM encoding table beside this gate netlist, or None.

    None is the correct answer for every netlist produced before the synth step
    started writing the file, and for every non-yosys netlist: the caller then
    emits the pre-change recipe byte-for-byte.  An absent table means "no
    translation is known", which is exactly the pre-#2050 situation; what the
    fix removes is the case where a translation EXISTS and was ignored.

    Yosys also creates a zero-byte file when no FSM was recoded. Passing that
    file suppresses splitnets in both recipes even though there is no state
    encoding to protect. If scan insertion scalarized internal buses, their
    vector RTL names then lose every per-bit correspondence. Preserve the
    normal matching recipe for this empty-table case; nonempty tables retain
    the whole-state matching required for recoded FSMs.
    """
    if not gate_netlist:
        return None
    try:
        # NOT `.resolve()`: the string returned here is written verbatim into
        # the Yosys script, which runs inside the container against the SAME
        # path the rest of the script uses for the netlist. Canonicalising
        # would follow host symlinks and could emit a path the container has
        # not mounted, which yosys reports as "Can't open encfile".
        cand = Path(gate_netlist).parent / FSM_ENCFILE_NAME
    except (OSError, ValueError):
        return None
    return str(cand) if cand.is_file() and cand.stat().st_size > 0 else None


def fsm_signal_names(encfile: Optional[str]) -> Optional[List[str]]:
    """Read the whole FSM names that must survive wire splitting (#2209).

    Unknown syntax/names retain the old, unsplit recipe. None is distinct
    from an observed empty encoding file, which declares no recoded FSMs.
    Only literal selection-safe identifiers are accepted: guessing a glob
    for an escaped name could split precisely the state we must preserve.
    """
    if not encfile:
        return None
    try:
        lines = Path(encfile).read_text().splitlines()
    except (OSError, UnicodeError, ValueError):
        return None
    names = set()
    have_fsm = False
    for line in lines:
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] == ".fsm" and len(words) == 3:
            name = words[2].removeprefix("\\")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", name):
                return None
            names.add(name)
            have_fsm = True
        elif (words[0] == ".map" and len(words) == 3 and have_fsm
              and all(re.fullmatch(r"[01xXzZ-]+", w) for w in words[1:])):
            continue
        else:
            return None
    return sorted(names)


def _equiv_splitnets(encfile: Optional[str],
                     names: Optional[List[str]]) -> str:
    if not encfile:
        return "splitnets -ports\n"
    if names is None:
        return ""
    # Keep every recoded FSM whole at the top and under any flatten prefix.
    # All other wires may regain their scalar-name correspondence. Selection
    # changes names only; it neither assumes equality nor removes logic/points.
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", n) for n in names):
        return ""
    exclude = "".join(f" w:{n} %d w:*.{n} %d" for n in sorted(set(names)))
    return f"splitnets -ports w:*{exclude}\nselect *\n"


def scan_fsm_mapping(encfile: Optional[str], gate_netlist: str,
                     top: str, scan_mode: Optional[Dict], *,
                     pre_scan_netlist: Optional[str] = None,
                     liberty_text: str = "",
                     dff_cells: Optional[List[str]] = None) -> Optional[Dict]:
    """Restore producer-recorded FSM words lost to scan scalarization.

    Only the published scan prefix and complete, explicitly declared scalar
    wire sets authorize an alias. No matching by width alone or assumed state
    equality is used. Yosys still proves the encoder/decoder correspondence.
    Unrecognized or incomplete inputs retain the conservative old recipe.
    """
    if not encfile or not scan_mode or fsm_signal_names(encfile) is None:
        return None
    prefix = scan_mode.get("internal_prefix")
    if not isinstance(prefix, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.$]*", prefix):
        return None
    try:
        netlist = Path(gate_netlist).read_text()
        encoding = Path(encfile).read_text()
    except (OSError, UnicodeError, ValueError):
        return None
    # This is the generated post-scan top-level scalar declaration form.
    # Restrict the lookup to the compared module; another module's wires
    # cannot authorize aliases in this one.
    modules = re.findall(r"(?ms)^\s*module\s+(\\?[^\s(]+).*?^\s*endmodule\b",
                         netlist)
    if modules != [top]:
        return None
    declarations = re.findall(r"(?m)^\s*wire\s+\\([^\s;]+)\s*;\s*$",
                              netlist)
    pre_instances = gate_instances = lib_cells = {}
    pre_text = ""
    if pre_scan_netlist and liberty_text and dff_cells:
        try:
            pre_text = Path(pre_scan_netlist).read_text()
        except (OSError, UnicodeError, ValueError):
            return None
        # Reuse the post-layout producer's structural/Liberty parsers. A
        # renamed scan-chain tail can be found at its unchanged FF OUTPUT
        # pin; D inputs are ineligible because scan insertion adds their mux.
        from lec_post_layout_check import _parse_netlist_instances, _parse_liberty_pins
        pre_instances = _parse_netlist_instances(pre_text)
        gate_instances = _parse_netlist_instances(netlist)
        lib_cells = _parse_liberty_pins(liberty_text)
    records = []
    current = None
    for line in encoding.splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] == ".fsm":
            if words[1].removeprefix("\\") != top:
                return None
            current = {"name": words[2].removeprefix("\\"), "maps": []}
            records.append(current)
        elif words[0] == ".map" and current is not None:
            current["maps"].append(words[1:])
        else:
            return None
    aliases = {}
    normalized = []
    for record in records:
        maps = record["maps"]
        if not maps or len({len(x[1]) for x in maps}) != 1:
            return None
        width = len(maps[0][1])
        original = prefix + "." + record["name"]
        # The alias must be NEW. Connecting an already driven word would
        # constrain the DUT, rather than only restoring its missing name.
        if re.search(r"(?m)^\s*(?:wire|reg)\s+(?:\[[^\]]+\]\s+)?\\"
                     + re.escape(original) + r"\s*;", netlist):
            return None
        bits = [f"{original}[{i}]" for i in range(width)]
        observed = [n for n in declarations if n.startswith(original + "[")]
        if len(observed) != len(set(observed)) or set(observed) - set(bits):
            return None
        for i, bit in enumerate(bits):
            if declarations.count(bit) == 1:
                continue
            candidates = []
            source_bit = f"{record['name']}[{i}]"
            for inst, (cell, pins) in pre_instances.items():
                if cell not in (dff_cells or []):
                    continue
                for pin in lib_cells.get(cell, {}).get("outputs", {}):
                    if pins.get(pin) != source_bit:
                        continue
                    after = gate_instances.get(prefix + "." + inst)
                    if not after or after[0] != cell:
                        continue
                    target = after[1].get(pin)
                    if target and declarations.count(target) == 1:
                        candidates.append(target)
            if len(candidates) != 1:
                return None
            bits[i] = candidates[0]
        full = _LEC_WRAP_INST + "." + original
        aliases[full] = [_LEC_WRAP_INST + "." + bit for bit in bits]
        normalized.append(f".fsm {top} {full}\n")
        normalized.extend(f".map {a} {b}\n" for a, b in maps)
    if not aliases:
        return None
    body = "".join(normalized)
    return {"aliases": aliases, "encoding_text": body,
            "encoding_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "source_encoding_sha256": hashlib.sha256(encoding.encode()).hexdigest(),
            "gate_netlist_sha256": hashlib.sha256(netlist.encode()).hexdigest(),
            "pre_scan_netlist_sha256": (hashlib.sha256(pre_text.encode()).hexdigest()
                                         if pre_text else None),
            "liberty_sha256": (hashlib.sha256(liberty_text.encode()).hexdigest()
                                if liberty_text else None)}


_STAT_MODULE_RE = re.compile(r"(?m)^\s*===\s+(\S+)\s+===\s*$")
# yosys prints the per-type histogram as "count", then 2+ spaces, then the
# cell type, indented under the module header; the SUMMARY lines above it
# ("113 cells", "222 wires") use a SINGLE space. Requiring 2+ spaces separates the two without
# keyword-matching, and keeps bare Liberty cell names (which must count as
# UNKNOWN, i.e. fail-open) in the histogram rather than dropping them.
_STAT_CELL_RE = re.compile(r"(?m)^[ \t]+(\d+)[ \t]{2,}(\S+)[ \t]*$")


def miter_is_stateless(text: str):
    """(stateless, evidence) -- True ONLY on positive evidence that the miter
    yosys built contains no state element at all.

    WHY THIS EXISTS -- MEASURED 2026-08-27, on unpatched main 40d0e14c08.
    A `popcount8` gold was synthesised, ONE gate in the netlist was mutated
    (`$_NAND_` -> `$_NOR_`), and `lec_run.py` reported that genuinely
    non-equivalent pair as **INCONCLUSIVE**, not FAIL. The mechanism:

      * the design is purely combinational, so `equiv_simple` correctly left
        the 4 differing output bits unproven;
      * the script then ran `equiv_induct -seq 4/16/64` anyway. On a miter with
        NO state there is nothing to induct over, so every rung necessarily
        printed `Proved 0 previously unproven $equiv cells.`;
      * `induction_did_not_converge` reads exactly that phrase as "a flat
        induction wall", and the classifier re-classes a flat wall from
        NOT_EQUIVALENT to INCONCLUSIVE.

    That re-class is right for a DEEP SEQUENTIAL design, where `-seq 64` really
    can run out of depth. On a stateless design it is unconditional: EVERY real
    combinational mismatch produces that phrase, so the discriminator says "not
    a mismatch" about every mismatch it is shown. A checker that cannot say
    FAIL is not a checker.

    THE OBSERVABLE, not a name guess: this reads the cell histogram YOSYS
    ITSELF printed for the miter module (`stat` after `equiv_make`), and
    returns True only when the histogram was found, counted at least one cell,
    and EVERY type in it is in yosys's own combinational vocabulary. A PDK
    Liberty cell, a `$mem`, a `$_DFF_*`, or any type this list does not know
    yields False -- i.e. the previous behaviour, unchanged. PURE."""
    # ANCHOR ON THE MITER MODULE BY NAME. `build_equiv_script` always builds
    # the miter as `equiv_make gold gate equiv`, so the histogram we need is
    # the one headed `=== equiv ===`. Anchoring matters: `prep` prints its OWN
    # `=== <gold-top> ===` statistics earlier in the same log, and taking
    # merely the LAST section would read the GOLD's cell mix on any log that
    # lacks the miter `stat` -- e.g. a log produced before this pass was added.
    # Requiring the miter's own section makes such a log answer "unknown"
    # (False), which is the previous behaviour, instead of answering from the
    # wrong design.
    mods = [m for m in _STAT_MODULE_RE.finditer(text or "")
            if m.group(1) == _MITER_MODULE]
    if not mods:
        return False, (f"no `stat` cell histogram for the miter module "
                       f"`{_MITER_MODULE}` in the log -- statelessness was "
                       f"not established, so the sequential-depth "
                       f"re-classification keeps its previous behaviour")
    last = mods[-1]
    section = (text or "")[last.end():]
    nxt = _STAT_MODULE_RE.search(section)
    if nxt:
        section = section[:nxt.start()]
    types = {}
    for m in _STAT_CELL_RE.finditer(section):
        cnt, name = int(m.group(1)), m.group(2)
        types[name] = cnt
    if not types:
        return False, ("`stat` reported no cell types for the miter -- "
                       "statelessness was not established")
    unknown = sorted(t for t in types if t not in _YOSYS_COMB_CELL_TYPES)
    if unknown:
        return False, (
            f"the miter contains cell type(s) outside yosys's combinational "
            f"vocabulary ({', '.join(unknown[:6])}) -- it may hold state, so "
            f"induction non-convergence remains a possible explanation")
    return True, (
        f"`stat` shows the miter is built entirely from combinational cells "
        f"({', '.join(sorted(types)[:6])}) -- it holds NO state, so temporal "
        f"induction had nothing to unroll and `Proved 0 previously unproven` "
        f"is the guaranteed output for ANY unproven point, mismatch or not. "
        f"Induction non-convergence cannot explain this result.")


#: EVIDENCE THAT INDUCTION RAN — the pass by name, OR either line only it
#: prints. The name alone is not enough: `_DEPTH_WALL`, this file's oldest
#: hand-written depth fixture, is an EXCERPT of a real induction run that starts
#: below the `Executing EQUIV_INDUCT pass.` header, and a real log that has been
#: tailed or clipped looks the same. `equiv_induct.cc` is the only pass that
#: prints "Proving induction step" or "Proving existence of base case";
#: VERIFIED, not assumed — an `equiv_simple`-only log of this file's own
#: reproducer (LEC_LADDER rungs 1-2, no induction emitted) contains ZERO
#: occurrences of "induct" or "base case", while the same recipe at rung 3
#: contains all three phrases.
_INDUCTION_RAN_RE = re.compile(
    r"equiv_induct"
    r"|Proving\s+induction\s+step"
    r"|Proving\s+existence\s+of\s+base\s+case",
    re.IGNORECASE)


def ladder_reached_induction(text: str) -> bool:
    """Did an `equiv_induct` pass ACTUALLY RUN in this log?

    #2050 FAMILY, SECOND INSTANCE. `equiv_simple` prints the SAME
    `Proved 0 previously unproven $equiv cells.` line `equiv_induct` does, so a
    whole-text search for that phrase cannot tell "induction hit a wall" from
    "induction never ran". `induction_ladder_exhausted` below already knows
    this — its docstring says its scan is scoped past the marker "so
    equiv_simple's OWN proved-count can never trigger it" — but the two
    functions that answer the same question about the same log,
    `induction_did_not_converge` and `induction_wall_kind`, were not scoped, and
    reported a flat INDUCTION wall on a run containing no induction.

    MEASURED on main 800cecb34, pinned image sha256:89a8fd7295…, yosys 0.68+:
    `build_equiv_script(..., ladder_rungs=2)` emits `equiv_simple -short` and
    `equiv_simple` and NOTHING ELSE — `LEC_LADDER`'s induction rungs are 3, 4
    and 5 — and the resulting log contains the string "induct" ZERO times. The
    record nevertheless read "equiv_induct did NOT converge (equiv_induct proved
    0 previously-unproven cells across the escalating -seq sweep)" with
    `induction_wall_kind: "induction_depth"`, and advised closing the remainder
    with a commercial sign-off LEC "which handles deep sequential induction".
    Running ONE more rung proved every remaining point (13/17 -> 17/17).

    This is the #581 defect with a different cause: there the WALL CLOCK stopped
    the proof before induction ran and the record blamed the engine's depth;
    here the RECIPE stops before induction runs and the record blames the
    engine's depth. `ladder_rungs` is #2194's per-rung RESOURCE knob — it exists
    so one yosys process holds one rung's peak memory — so this shape is the
    NORMAL state of every intermediate rung of a per-rung driver run, not a
    corner case.
    """
    return bool(_INDUCTION_RAN_RE.search(text or ""))


def induction_did_not_converge(text: str):
    """(bool, evidence) — True when equiv_induct made NO progress (a flat wall)
    rather than finding a difference. PRECISION-first: the caller MUST also
    confirm NO counterexample (_MISMATCH_EVIDENCE_RE) before re-classing to
    INCONCLUSIVE, because a real non-equivalence also leaves points unproven but
    is witnessed by a counterexample. chip-AGNOSTIC: pure yosys log phrases."""
    if _INDUCT_DIVERGE_RE.search(text):
        return True, ("equiv_induct SAT base case could not be established "
                      "(`Circuit inherently diverges!`)")
    # SCOPED PAST THE MARKER. `equiv_simple` prints this same line, so an
    # unscoped search answers "induction hit a flat wall" about a log in which
    # induction never ran. See `ladder_reached_induction`.
    if (ladder_reached_induction(text)
            and _PROVED_ZERO_RE.search(text)):
        return True, ("equiv_induct proved 0 previously-unproven cells across "
                      "the escalating -seq sweep (a flat induction wall)")
    return False, ""


# #2050 — THE TWO FLAT WALLS ARE NOT THE SAME WALL, AND ONLY ONE OF THEM IS
# ABOUT DEPTH.  `induction_did_not_converge` above answers "did equiv_induct
# make progress?" — one bit, and both of its signatures were then reported with
# the same sentence ("a disclosed sequential-depth capability gap ... close with
# sign-off LEC, which handles deep sequential induction").  Read yosys's own
# `passes/equiv/equiv_induct.cc` and the two signatures are opposite findings:
#
#   * `Proved 0 previously unproven $equiv cells` — the base case HELD, the
#     induction step could not be closed within `-seq N`.  That IS a depth
#     statement: a deeper N, or an engine with stronger induction, can help.
#
#   * `Circuit inherently diverges!` — the BASE CASE went UNSAT.  The base case
#     is `ez->assume(all unproven key points equal at steps 1..k); ez->solve()`.
#     UNSAT means there is NO trace at all in which those points are
#     simultaneously equal for k consecutive cycles.  That is a statement about
#     the MITER, not about depth, and a deeper `-seq` provably cannot help: each
#     rung only ADDS assumed-equal terms, and adding clauses preserves UNSAT.
#     MEASURED on opentitan_aes: `-seq 4`, `-seq 16` and `-seq 64` printed
#     byte-identical output, all three aborting at base-case step 2.
#
# The usual cause is a key point that is not the same signal on the two sides —
# e.g. `synth`'s `fsm_recode` re-encoded an FSM state register and the recipe
# matched the old and new encodings positionally by name.  Prescribing a
# commercial sequential-LEC engine for that would buy nothing: the inconsistency
# is in the miter handed to the engine.
_WALL_MITER_INCONSISTENT = "miter_inconsistent"
_WALL_INDUCTION_DEPTH = "induction_depth"
#: The ladder STOPPED BELOW its induction rungs, so there is no induction
#: result to have a depth opinion about. Remediable HERE — run the rungs — and
#: therefore a different finding from either wall above.
_WALL_LADDER_BELOW_INDUCTION = "ladder_below_induction"


def induction_wall_kind(text: str) -> str:
    """WHICH flat wall the log shows: `miter_inconsistent`, `induction_depth`,
    or "" when neither signature is present. PURE.

    Precedence is deliberate and load-bearing: a run that reached
    `Circuit inherently diverges!` ALSO prints `Proved 0 previously unproven
    $equiv cells` for the same pass (equiv_induct returns without proving
    anything), so the depth signature is present on both shapes and only the
    base-case signature separates them."""
    if _INDUCT_DIVERGE_RE.search(text or ""):
        return _WALL_MITER_INCONSISTENT
    if not _PROVED_ZERO_RE.search(text or ""):
        return ""
    # A DEPTH VERDICT REQUIRES AN INDUCTION PASS TO HAVE HAPPENED. Without one
    # the same `Proved 0` line is equiv_simple's, and the honest answer names
    # the truncated ladder rather than the engine.
    return (_WALL_INDUCTION_DEPTH if ladder_reached_induction(text or "")
            else _WALL_LADDER_BELOW_INDUCTION)


# #778 / round-2 subservient×sky130A — the escalating `-seq 4/16/64` induction
# ladder can run OUT of depth on a deep bit-serial datapath (SERV accumulates
# its memory ADDRESS bit-serially, threading bufreg→bufreg2→arbiter→mux far past
# a single 32-cycle period) while its DEEPEST rung is STILL proving new cells.
# MEASURED (subservient×sky130A, 3544 points): equiv_simple proved 3369, then
# equiv_induct proved 35 (-seq 4), 22 (-seq 16), 27 (-seq 64) — a strictly
# positive, still-descending tail — leaving 91 unproven with ZERO counterexample
# (all on `o_wb_mem_adr`/`arbiter.o_wb_mem_adr`). That is "converging but
# ladder-exhausted", NOT a flat wall (`Proved 0`, handled above) and NOT a proven
# difference (a counterexample, handled by _MISMATCH_EVIDENCE_RE). It is the SAME
# disclosed sequential-depth capability gap as `induction_did_not_converge`, so
# it must ALSO reclassify to INCONCLUSIVE, never a false NOT_EQUIVALENT.
_EQUIV_INDUCT_MARKER_RE = re.compile(r"equiv_induct", re.IGNORECASE)


def induction_ladder_exhausted(text: str):
    """(bool, evidence) — True when the equiv_INDUCT ladder made POSITIVE but
    INCOMPLETE progress: at least one induct rung proved >0 previously-unproven
    cells, yet points remain unproven at equiv_status. This is the -seq depth
    budget running out on a deep sequential design, NOT a proven difference
    (witnessed by a counterexample) and NOT a flat wall (`Proved 0`). PRECISION-
    first / §4.05 NO-LEAK: the caller MUST also confirm NO counterexample AND
    unproven>0 before re-classing to INCONCLUSIVE. The `Proved N` scan is scoped
    to the region AFTER the first equiv_induct marker so equiv_simple's OWN
    proved-count can never trigger it — a genuine mismatch (MISMATCH_OUTPUT:
    equiv_simple proves 33, equiv_induct then proves 0 and leaves 7 unproven)
    has NO post-induct `Proved N>0` line and correctly stays FAIL. chip-AGNOSTIC:
    pure yosys log phrases, no chip/vendor literal."""
    m = _EQUIV_INDUCT_MARKER_RE.search(text)
    if not m:
        return False, ""
    induct_region = text[m.start():]
    proved = [int(n) for n in _PROVED_SIMPLE_RE.findall(induct_region)]
    total = sum(n for n in proved if n > 0)
    if total > 0:
        return True, (
            f"equiv_induct proved {total} previously-unproven cell(s) across "
            "the escalating -seq sweep but the ladder was exhausted before full "
            "convergence — a bounded sequential-depth induction gap, not a flat "
            "wall and not a counterexample")
    return False, ""

def ladder_stopped_below_induction(text: str):
    """(bool, evidence) — points are open and the ladder never REACHED
    induction, so nothing has yet been asked of the prover that could close
    them.

    This must re-class to INCONCLUSIVE for exactly the reason #581's
    wall-clock branch does: the remainder was NEVER ATTEMPTED, so nothing about
    it was learned, and a FAIL here would be a fabricated non-equivalence.
    MEASURED: the design that produced this shape is EQUIVALENT — one further
    rung proves all 17 of 17 points.

    But it is a DIFFERENT finding from a capability gap and it carries a
    different remedy, which is the whole reason it is separated: the fix is to
    RUN THE INDUCTION RUNGS, here, for free. Advising a commercial sign-off LEC
    "which handles deep sequential induction" for a ladder that stopped two
    rungs short sends the reader to buy a tool for work this one has not been
    asked to do yet.

    PRECISION-first, identically to its siblings: the caller confirms NO
    counterexample and a state-bearing miter first, so a real mismatch (which
    prints a counterexample) and a stateless miter (where induction could not
    have helped anyway) both keep their blocking FAIL.
    """
    if ladder_reached_induction(text):
        return False, ""
    if not _PROVED_ZERO_RE.search(text or ""):
        return False, ""
    return True, (
        "the proof ladder STOPPED BELOW its induction rungs — no equiv_induct "
        "pass appears in this log at all, so the `Proved 0 previously unproven` "
        "line is equiv_simple's own and says nothing about sequential depth")


# Frontend-ABORT signatures — a read_verilog / read_slang failure that prevented
# ANY equivalence miter from being built (0 compared points). DISTINCT from a
# genuine mismatch (a miter DID run and left points unproven). A zero-miter abort
# is not classifiable as PASS or FAIL, so it re-classifies to INCONCLUSIVE rather
# than a false FAIL that cascade-marks downstream steps MISSING.
# SCOPE (v1.4.33): this signature now decides ONLY the VERDICT classification.
# WHICH FRONTEND reads the gold is decided by `should_retry_gold_with_slang`,
# which keys on the OBSERVABLE "no miter was built" rather than on the tool's
# error wording — an allow-list of phrasings silently skipped the capable
# frontend whenever a new abort was worded differently (how ibex was missed).
# TWO families, BOTH resolved by slang:
#   (A) PARSE / lex aborts — the built-in reader can't tokenise the SV closure
#       (package import before the ANSI port list, typedefs, unsupported syntax).
#   (B) ELABORATION aborts — the built-in reader PARSES but can't ELABORATE a
#       VALID SV-2017 construct that slang resolves. The canonical case is an SV
#       package/enum constant used as a parameter value, which yosys's built-in
#       const-evaluator mis-reports as non-constant (ibex, rv-ibex2 run:
#       "chip_top.sv:85: ERROR: Parameter u_ibex_core.RV32M with non-constant
#       value!"). Without (B) the retry never fired on ibex-class designs → a
#       false compared_points=0 FAIL cascading 24 steps.
# §4.05 NO-LEAK: widening the matcher widens what TRIGGERS a retry, never what
# PASSES. A genuine non-constant-param DESIGN bug is rejected by slang TOO; a
# slang-also-fails run STAYS FAIL (finalize_after_slang_retry never excuses it);
# and a miter that runs and leaves points unequal still FAILs. The retry only
# changes WHICH frontend reads the gold, never the equivalence verdict.
_FRONTEND_PARSE_ABORT_RE = re.compile(
    # (A) parse / lex aborts
    r"syntax\s+error"
    r"|unexpected\s+TOK_\w+"
    r"|TOK_PACKAGE|TOK_TYPEDEF"
    r"|unsupported\s+SystemVerilog"
    r"|can'?t\s+open\s+input\s+file"
    r"|unable\s+to\s+open"
    r"|no\s+such\s+file"
    r"|cannot\s+(?:find|open)\s+(?:file|module)"
    r"|failed\s+to\s+parse"
    # (B) elaboration aborts that slang resolves (SV package/enum-as-param-value)
    r"|Parameter\s+\S+\s+with\s+non-constant\s+value"
    r"|non-constant\s+value"
    r"|is\s+not\s+a\s+constant\b"
    r"|failed\s+to\s+evaluate",
    re.IGNORECASE)


def is_frontend_parse_abort(text: str) -> bool:
    """True iff a Yosys log carries a FRONTEND abort signature — a
    read_verilog/read_slang PARSE or ELABORATION failure that built no miter.
    PURE. Consulted ONLY when parse_error is True (0 miter), so it can only fire
    the slang retry / INCONCLUSIVE re-class on a zero-miter run — never on a real
    mismatch whose miter ran.

    v1.4.x — RETAINED for the slang-RETRY trigger and for the reason string, but
    NO LONGER the verdict classifier. INCONCLUSIVE-vs-FAIL on a zero-miter run is
    now decided by :func:`frontend_aborted_before_elaboration`, an observation of
    HOW FAR the run got rather than of how the tool phrased its abort."""
    return bool(_FRONTEND_PARSE_ABORT_RE.search(text or ""))


# HARD-MACRO STAGING GAP (#192) — yosys `hierarchy -check` aborts when the
# netlist instantiates a module whose definition was not read on that side:
#   ERROR: Module `\fakeram45_2048x39' referenced in module `\top' in cell
#          `\u_sram' is not part of the design.
# This is netgen-STABLE yosys wording (the `hierarchy` pass emits it verbatim
# for any unresolved instance). It aborts BEFORE `equiv_make`, so 0 points are
# ever compared — distinct from a genuine mismatch, whose miter DID run. The
# captured group is the unresolved (macro) module name, with any leading Verilog
# escape backslash stripped. chip/PDK-AGNOSTIC: keys on the yosys message shape,
# never on a design/macro literal.
_UNDEF_MODULE_RE = re.compile(
    r"Module\s+[`'\"]?\\?([A-Za-z_$][\w$]*)['`\"]?\s+referenced\s+in\s+module\b"
    r"[^\n]*?\bis\s+not\s+part\s+of\s+the\s+design",
    re.IGNORECASE)


def undefined_macro_modules(text: str) -> List[str]:
    """Sorted, de-duplicated module names the equiv run referenced but could
    not resolve — a hard macro (or any submodule) instantiated in the netlist
    whose definition was not staged, so `hierarchy -check` aborted before any
    miter was built. PURE.

    Consulted ONLY when parse_error is True (0 miter), so it can re-classify a
    zero-miter run to INCONCLUSIVE but can NEVER touch a run whose miter
    actually compared points — a real mismatch still FAILs."""
    return sorted({m.group(1) for m in _UNDEF_MODULE_RE.finditer(text or "")})


# ---------------------------------------------------------------------------
# STAGE-PROGRESS OBSERVABLE (v1.4.x) — how far did the yosys run actually get?
#
# THE RESIDUAL HALF OF THE ea13744db BUG. Frontend SELECTION moved to the
# observable there, but the VERDICT classification — INCONCLUSIVE vs FAIL on a
# zero-miter run — still keyed on `_FRONTEND_PARSE_ABORT_RE`. A reworded abort
# restores the false FAIL, which cascade-marks 24 downstream steps MISSING.
#
# The observable: yosys NUMBERS and ANNOUNCES every pass it dispatches
# ("1. Executing Verilog-2005 frontend: …", "2. Executing HIERARCHY pass …").
# Verified live on the vibeic-eda image:
#   read ok + hierarchy ok      -> passes = [Verilog-2005 frontend, HIERARCHY]
#   frontend abort (modern SV)  -> passes = [Verilog-2005 frontend]         <-- stopped AT the read
#   post-frontend failure       -> passes = [Verilog-2005 frontend, HIERARCHY]
#   yosys never ran / crashed   -> passes = []
# So "only frontend passes executed" is POSITIVE evidence that the read is where
# it stopped — i.e. no elaborated design was ever produced — whatever the tool
# said. Pass-class names ("… frontend") are yosys's own command-inventory
# naming, which is API-stable, unlike error phrasing which is not.
_YOSYS_PASS_RE = re.compile(r"^\s*[\d.]+\.\s+Executing\s+(.+?)\s*$", re.MULTILINE)
# A yosys READ pass announces itself as an "<X> frontend" (Verilog-2005 / SLANG /
# Liberty / RTLIL / BLIF). Every design-BUILDING pass announces as "<NAME> pass",
# and writers as "<NAME> backend".
#
# ANCHORED to where yosys structurally writes the class token, in two rounds of
# peer review with the sibling LVS wording fix.
#
# ROUND 1 (their finding): the captured pass name INCLUDES the pass ARGUMENTS —
# real yosys prints "Verilog-2005 frontend: /tmp/frontend/rtl/m.v" — so a bare
# \bfrontend\b also fires on a PATH containing that word. Misfires in the
# DANGEROUS direction: a design-BUILDING pass wrongly counted as a read pass
# empties the non-frontend list and buys the LENIENT verdict (INCONCLUSIVE).
#
# ROUND 2 (their sharpened threat model): requiring `frontend` to be followed by
# `:` / `.` / end was still forgeable, because those separators occur INSIDE
# arguments too — "SOMEPASS pass (reading /work/frontend.)" and
# "… (reading /work/frontend: x)" both satisfied it. Their sharper framing is the
# right one and generalises past LVS: THE DESIGN AND THE ENVIRONMENT NAME THEIR
# OWN THINGS, so any structural token matched against a region that contains
# paths / net names / cell names is a token those inputs can FORGE. (In netgen's
# case a SystemVerilog escaped identifier legally contains SPACES, so a net can
# spell a verdict phrase exactly.)
#
# So the class token is now read ONLY from the CLASS DESCRIPTOR — the text before
# the first argument separator (`:` for a frontend's file, `(` for a pass's
# description) — which is the one region yosys writes and the inputs cannot
# reach. Verified against real output: reads are "<X> frontend: <path>" or
# "<X> frontend."; builders are "<NAME> pass (<desc>)" or "<NAME> pass."; writers
# are "<X> backend.".
_YOSYS_PASS_ARG_SEP_RE = re.compile(r"[:(]")
_YOSYS_FRONTEND_CLASS_RE = re.compile(r"\bfrontend$", re.IGNORECASE)


def _yosys_pass_is_frontend(pass_name: str) -> bool:
    """True iff this yosys pass announcement is a READ (frontend) pass.

    Reads the class token from the DESCRIPTOR only, never from the arguments —
    see the note above. Fail-safe direction: anything unrecognised is treated as
    NOT a frontend pass, which pushes the verdict toward the BLOCKING outcome."""
    descriptor = _YOSYS_PASS_ARG_SEP_RE.split(pass_name or "", 1)[0]
    return bool(_YOSYS_FRONTEND_CLASS_RE.search(descriptor.strip().rstrip(".")))


def yosys_executed_passes(text: str) -> List[str]:
    """Ordered list of the yosys passes that ACTUALLY executed in this log.

    PURE. The primitive behind the stage-progress observable; exposed so a test
    can pin the parse against real transcripts."""
    return [m.group(1) for m in _YOSYS_PASS_RE.finditer(text or "")]


def frontend_aborted_before_elaboration(text: str) -> Tuple[bool, str]:
    """OBSERVABLE: did the run stop AT the frontend, producing no elaborated
    design? Returns (aborted_at_frontend, evidence).

    True requires POSITIVE evidence on BOTH counts:
      1. at least one pass executed AND it was a READ/frontend pass — so yosys
         genuinely ran and genuinely reached the read; and
      2. NO non-frontend pass ever executed — so the design was never built.

    This deliberately preserves the asymmetry the earlier fix imposed. A yosys /
    docker CRASH with no frontend evidence yields NO executed passes -> False ->
    the caller keeps the HARD FAIL. A run that got PAST the read and died later
    has a non-frontend pass in the list -> False -> HARD FAIL. Only the narrow
    "reached the read, never got past it" shape re-classifies to INCONCLUSIVE.

    §4.05 — INCONCLUSIVE is the LESS blocking outcome (a FAIL cascade-marks 24
    downstream steps MISSING), so widening it is the direction that could hide a
    genuine failure. That is exactly why this requires positive stage evidence
    rather than merely the ABSENCE of a recognised phrase. Neither outcome is
    ever a PASS: a miter that runs and leaves points unequal still FAILs."""
    passes = yosys_executed_passes(text)
    if not passes:
        return False, ("no yosys pass executed at all — the tool never reached "
                       "a frontend (crash / container / invocation failure); "
                       "there is no evidence of a frontend abort")
    non_frontend = [p for p in passes if not _yosys_pass_is_frontend(p)]
    if non_frontend:
        return False, (
            f"the run got PAST the read — {len(passes)} pass(es) executed and "
            f"{non_frontend[0]!r} ran after the frontend, so a design WAS "
            f"elaborated; whatever failed later is not a frontend abort")
    return True, (
        f"only frontend/read pass(es) executed ({', '.join(passes[:3])}"
        f"{'…' if len(passes) > 3 else ''}) and no design-building pass ever "
        f"ran — the read is where it stopped, so no elaborated design was "
        f"produced")


# SV-2017 gold signature — DESIGN properties the yosys built-in reader cannot
# reliably elaborate: a `package`/`interface` declaration, a package import, a
# package-scope reference (`pkg::CONST`, the ibex `ibex_pkg::RV32MFast`-as-param
# case), or a `typedef`. Used ONLY to EXPLAIN which frontend was chosen — never
# as the sole trigger, and never keyed on a chip name, a path, or an IC class.
_SV2017_GOLD_RE = re.compile(
    r"(?m)^\s*(?:package|interface)\s+\w+"
    r"|^\s*import\s+\w+\s*::"
    r"|^\s*typedef\b"
    r"|(?<![\w.])\w+\s*::\s*\w+")


def gold_requires_sv2017(gold_files: List[str]) -> bool:
    """True iff the gold RTL uses SV-2017 constructs beyond the yosys built-in
    reader's subset (package / interface / import / package-scope ref / typedef).
    PURE, filesystem-only, DESIGN-property driven."""
    for f in gold_files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _SV2017_GOLD_RE.search(text):
            return True
    return False


# A WALL-BUDGET KILL IS NOT A FRONTEND FAILURE.
#
# MEASURED 2026-08-27 (VerilogEval-Human Prob030_popcount255, a 255-bit popcount
# whose gold is PURELY COMBINATIONAL): `yosys -s reports/lec_equiv.ys` ground at
# 99.9% CPU for the full 7195s container budget inside `equiv_simple`, was
# SIGTERMed, and left `parse_error=True` (no equiv_status, so nothing parsed).
# `should_retry_gold_with_slang` keys on exactly that observable - "the built-in
# gold read produced NO equivalence miter at all" - and so read the budget kill
# as a GOLD-READ failure and re-ran the WHOLE proof under `read_slang` with the
# SAME 7195s budget. Observed directly on the live sweep: yosys pid A went
# <defunct> at the deadline, reports/lec_equiv.ys was rewritten with
# `read_slang` 20s later, and a fresh yosys pid B started on it. NOTHING was
# written to reports/lec.json or reports/lec.rpt at the deadline - not a FAIL,
# not a SKIPPED-CONDITION, nothing - because the report is only written after
# the whole retry ladder finishes. With the -DSYNTHESIS rung as well, the same
# undecidable proof can consume THREE full budgets (~6h) before the honest
# "I could not decide this within the resources given" reaches disk.
#
# The retry rule was missing one conjunct: "no miter was built" must exclude
# "we never found out, because the clock killed it". Those are different facts.
# The gold read DEMONSTRABLY SUCCEEDED here - yosys reached `equiv_simple`,
# which is downstream of both reads - so a different FRONTEND cannot change the
# outcome; only a larger budget or a cheaper proof strategy could, and neither
# is what the retry does.
#
# `_EXECUTION_STOP_RE` matches ONLY markers written by this program's own
# budget-kill and progress-stall paths; neither is tool output a design could
# emit.  This discriminator therefore cannot fire on a naturally completed
# run.
#
# DIRECTION OF RISK: declining the retry can only make the recorded outcome
# LESS conclusive, never more. It cannot manufacture a PASS (only a completed
# `equiv_status` with 0 unproven does that, and a killed run has no
# equiv_status), and it cannot hide a mismatch (a recorded counterexample keeps
# its FAIL through `_MISMATCH_EVIDENCE_RE` in the SAME branch). What it removes
# is one way to spend hours and record nothing. chip/PDK/tool-AGNOSTIC: keys
# only on this program's own marker.
def budget_kill_blocks_frontend_retry(gold_log: str) -> Tuple[bool, str]:
    """(blocked, evidence) - True iff OUR supervisor cut <gold_log> short,
    which makes a gold-FRONTEND retry incapable of changing the answer.

    PURE. Returns False (retry stays available) for every log that does not
    carry a producer-owned execution-stop marker, so no run that ends on its
    own is moved."""
    if not _EXECUTION_STOP_RE.search(gold_log or ""):
        return False, ""
    stopped_by = ("the no-forward-progress watchdog"
                  if _STALL_RE.search(gold_log or "") else
                  "the wall budget (wall-clock)")
    return True, (
        f"the gold read was NOT the failure - yosys was stopped mid-proof by "
        f"{stopped_by} (this program's own execution-stop marker is in the "
        "log), so no equiv_status was reached. Re-reading the gold with "
        "a different frontend cannot make an undecided SAT proof converge; it "
        "only repeats the same undecided proof and delays the honest record. "
        "Investigate the stalled process or raise --timeout / "
        "VIBEIC_LEC_YOSYS_TIMEOUT_S as applicable, or close the remainder "
        "with sign-off LEC.")


def should_retry_gold_with_slang(parsed: Dict, gold_log: str,
                                 requires_sv2017: bool) -> "tuple[bool, str]":
    """Decide whether to re-read the GOLD with `read_slang`. Returns (retry, why).

    THE RULE (general, design-driven): retry whenever the built-in gold read
    produced NO equivalence miter at all — i.e. `parse_error`, meaning yosys
    printed no proven/unproven/total counts and no SAT-model abort, so ZERO
    points were compared. A zero-miter run carries no equivalence evidence in
    either direction, and `read_slang` is the most capable SV-2017 frontend
    available (the same one `synth` falls back to), so it has not yet been given
    a chance to decide the question.

    WHY NOT the old rule: the retry used to fire only when the yosys log matched
    `_FRONTEND_PARSE_ABORT_RE` — a hard-coded allow-list of error PHRASINGS.
    Any zero-miter abort worded differently silently skipped the capable
    frontend and fell through to a FALSE FAIL (this is exactly how ibex's
    "Parameter ... with non-constant value" elaboration abort was missed until
    the phrase was hand-added). Keying on the OBSERVABLE (no miter was built)
    instead of on the tool's wording removes the whole class of misses.

    §4.05 NO-LEAK — widening the TRIGGER cannot widen what PASSES:
      * `parse_error` is False the moment a miter actually ran, so a genuine
        mismatch (miter ran, points left unproven) can NEVER reach this retry.
      * If slang also builds no miter, `finalize_after_slang_retry` keeps the
        verdict at FAIL — no free non-blocking pass.
      * The VERDICT classification (INCONCLUSIVE vs FAIL) still uses the narrow
        `is_frontend_parse_abort` signature, deliberately NOT widened here: a
        yosys/docker crash with no frontend-abort evidence stays a hard FAIL.
    The `why` string is recorded in reports/lec.json so the fallback and its
    justification are explicit and auditable.
    """
    if not parsed.get("parse_error"):
        return False, ""
    # A WALL-BUDGET KILL IS NOT A GOLD-READ FAILURE (measured 2026-08-27).
    # `parse_error` means "no miter counts were parsed", and a run KILLED at its
    # deadline mid-`equiv_induct` produces exactly that - with no equiv_status
    # line - even though the gold read SUCCEEDED and the proof was running. This
    # retry exists for a gold read that FAILED; firing it on a killed one asks a
    # different frontend to make a combinatorially explosive proof cheap, which
    # it cannot, and costs another full budget to find out (Prob030_popcount255:
    # 7195s ground, killed, then re-read with read_slang and started over).
    #
    # ASSEMBLY v1.11.95 - TWO BRANCHES IMPLEMENTED THIS SAME GUARD, and only one
    # copy may survive. The predicate is IDENTICAL: budget_kill_blocks_frontend_
    # retry's whole test is the producer-owned execution-stop marker, written
    # ONLY by the kill paths in `run_yosys_equiv`, so its presence is
    # unambiguous evidence that the proof did not complete. The named function
    # is kept because it also carries the evidence string into reports/lec.json
    # and is the form under test
    # (test_lec_bounded_proof.py::test_budget_killed_log_blocks_the_retry). A
    # second inline `_TIMEOUT_RE.search` here would be an unreachable duplicate
    # of one decision, not a second guard.
    #
    # 4.05 NO-LEAK: this only ever turns a retry OFF - it can never widen what
    # PASSES, and it leaves the timeout VERDICT classification untouched. The
    # genuine gold-read failures this retry was written for carry no such
    # marker, so that recovery is unaffected. Declining here is what lets the
    # SKIPPED-CONDITION verdict the classifier ALREADY computes actually reach
    # reports/lec.json.
    _budget_blocked, _budget_ev = budget_kill_blocks_frontend_retry(gold_log)
    if _budget_blocked:
        return False, _budget_ev
    # AND THE NOT-BLOCKED ANSWER IS RECORDED TOO (#313 §6). "the budget-kill
    # check ran and did not block" and "the budget-kill check never ran" are
    # different facts about a run, and until this line the log could not tell
    # them apart — the decline was audible and the non-decline was silent,
    # which is the asymmetry `silent_decline_audit` exists to remove. It names
    # `_budget_blocked` so the predicate's own answer is in the record, not
    # merely its consequence.
    print(f"[lec_run] gold-frontend retry: budget-kill check consulted, "
          f"_budget_blocked={_budget_blocked!r} — not declined here.",
          file=sys.stderr)
    if is_frontend_parse_abort(gold_log):
        return True, ("built-in read_verilog -sv aborted with a frontend "
                      "parse/elaboration signature and built no miter")
    if requires_sv2017:
        return True, ("built-in read_verilog -sv built no miter and the gold "
                      "RTL uses SV-2017 constructs (package / interface / "
                      "import / package-scope ref / typedef) outside its "
                      "supported subset")
    return True, ("built-in read_verilog -sv built no miter (0 compared "
                  "points, no equivalence evidence) — the capable SV-2017 "
                  "frontend has not been tried yet")


def finalize_after_slang_retry(parsed: Dict, slang_retry_failed: bool) -> Dict:
    """Downgrade a provisional INCONCLUSIVE verdict to FAIL when the read_slang
    gold-read retry was attempted and slang ALSO could not build a miter.

    §4.05 NO-LEAK: INCONCLUSIVE (a non-blocking SKIPPED-CONDITION) is only
    justified when the capable SV-2017 frontend was NOT tried (e.g. slang
    unavailable). Once slang — the most capable frontend — has ALSO failed to
    elaborate the gold, the design is not excused as a built-in-reader tool gap;
    a genuine elaboration error must NOT get a free non-blocking pass. PURE; a
    no-op when slang was not attempted or slang succeeded.

    EXCEPTION — the #192 hard-macro staging gap is NOT a gold-frontend failure.
    That INCONCLUSIVE is raised when the GATE side's `hierarchy -check` aborts
    because the netlist instantiates a hard macro whose definition was never
    staged into the miter. The gold RTL elaborated fine; no frontend, however
    capable, can supply a module that is not there, so "slang also failed" is
    not evidence about this design at all. Downgrading it re-introduces exactly
    the harm #192 removed — a comparison that never started, booked as a proven
    non-equivalence — and worse, the downgrade's own text tells the operator to
    "fix the elaboration error", pointing at RTL that is provably fine.

    Measured 2026-07-22 on a design carrying a `pdk_local` SRAM macro: `lec.json`
    came out `verdict=FAIL`, `compared_points=0`, explanation "Neither
    read_verilog -sv nor the read_slang SV-2017 frontend could elaborate the
    gold", while that same JSON carried
    `undefined_macro_modules: ["<the macro>"]` and `lec.rpt` ended on the
    gate-side line `ERROR: Module '\\<macro>' referenced in module '\\<top>' in
    cell '\\<inst>' is not part of the design.` — after the gold had already run
    58 passes. The classification was right and the finalizer overwrote it.

    Keyed on the recorded `undefined_macro_modules`, so it is chip-, macro- and
    PDK-AGNOSTIC, and it cannot excuse a real gold elaboration failure (which
    records no undefined macro)."""
    if not slang_retry_failed or parsed.get("verdict") != "INCONCLUSIVE":
        return parsed
    if parsed.get("undefined_macro_modules"):
        # Gate-side hard-macro staging gap — nothing to do with the gold
        # frontend. Keep the #192 INCONCLUSIVE and its remediation.
        return parsed
    out = dict(parsed)
    out["verdict"] = "FAIL"
    out["equivalent"] = False
    out["verdict_explanation"] = (
        "Neither read_verilog -sv nor the read_slang SV-2017 frontend could "
        "elaborate the gold to build an equivalence miter (0 compared points). "
        "With the capable frontend ALSO failing, this is not excused as a "
        "built-in-reader tool gap → reported as FAIL (fix the elaboration "
        "error). §4.05: a slang-also-fails run never becomes a non-blocking "
        "INCONCLUSIVE.")
    return out


def parse_equiv_output(text: str, *,
                       ladder_complete: Optional[bool] = None) -> Dict:
    """Parse raw Yosys equiv_status stdout into a structured verdict.

    Returns a dict with:
        proven, unproven, total            : Optional[int]
        sat_model_unsupported_cells        : List[{"cell", "cell_type"}]
        unproven_cells                     : List[str]
        success_line                       : bool
        parse_error                        : bool
        equivalent                         : bool
        verdict                            : "PASS"|"SKIPPED-CONDITION"|"FAIL"
        verdict_explanation                : str

    Never fabricates: when nothing is parseable, parse_error is True and the
    counts stay None (never the ambiguous -1 sentinel).
    """
    text = text or ""
    _stop_kind = ("the no-forward-progress watchdog"
                  if _STALL_RE.search(text) else "the wall-clock budget")

    # THE LAST `equiv_status`, NOT THE FIRST. `_OLD_TOTAL_RE` below already
    # argues this in its own comment -- "a recipe that calls it more than once
    # must be read at the state it finished in" -- and `lec_proved_points_from
    # _output` already takes `[-1]`. This reader was the one that did not, and
    # while every recipe emitted exactly one `equiv_status` the two spellings
    # coincided and nothing could tell them apart.
    #
    # A RESUMED recipe emits TWO: one on the design it just read back (which
    # STATES the position it resumed at) and the closing one. Read first-match,
    # the verdict would publish the counts the run STARTED from as the counts
    # it FINISHED with, and every point the resumed rungs proved would be
    # invisible.
    _finals = list(_FINAL_RE.finditer(text))
    final = _finals[-1] if _finals else None
    proven: Optional[int] = int(final.group(1)) if final else None
    unproven: Optional[int] = int(final.group(2)) if final else None
    total: Optional[int] = None

    # PRECEDENCE, and it is not cosmetic. `equiv_status` prints the CENSUS of
    # every $equiv point in the miter ("Found N $equiv cells in equiv:"); the
    # equiv_simple ENTRY line prints only the points still UNPROVEN when that
    # pass started. The two coincide exactly when nothing was proven before
    # equiv_simple ran -- which is the common small case, and is why reading
    # the entry line as a total survived this long. As soon as any earlier
    # pass discharges a point the entry line is SMALLER than the population,
    # and booking it as `miter_points` publishes a denominator narrower than
    # the proof actually covered, which makes every proven/total ratio derived
    # from this report look better than the run earned.
    #
    # MEASURED (opentitan_aes x chip_top, v1.17.22 canonical LEC run): the log
    # carried `Found 3396 unproven $equiv cells (3396 groups) in equiv:` and,
    # from equiv_status, `Found 4072 $equiv cells in equiv:` / `Of those cells
    # 830 are proven and 3242 are unproven.` The report published
    # miter_points=3396 against proven=830 + unproven=3242 = 4072 -- a
    # decomposition that does not add up, and a ratio of 24.4% where the run
    # earned 20.4%.
    #
    # LAST match, not the first: equiv_status is the final pass, and a recipe
    # that calls it more than once must be read at the state it finished in.
    _census = _OLD_TOTAL_RE.findall(text)
    if _census:
        total = int(_census[-1])
    if total is None:
        m = _EQUIV_SIMPLE_ENTRY_RE.search(text)
        if m:
            total = int(m.group(1))

    if proven is None:
        # CUMULATIVE, not the first pass. Each proof pass reports the cells IT
        # discharged, and the sets are disjoint, so the run's proven count is
        # the SUM over every pass — `search` returned only the first one.
        #
        # MEASURED on sha256 x sky130A (v1.15.44, RTL vs post-DFT scan
        # netlist): the ladder logged `Proved 1`, `Proved 0`, `Proved 1834`,
        # `Proved 0` and was then killed by its wall budget with no final
        # `equiv_status` to short-circuit on. The report recorded
        # `compared_points=1` and explained "1/1838 proven" for a run that had
        # proven 1835 of 1838 — three orders of magnitude off, and it read as
        # "the proof never started" instead of "the proof left three points".
        _proved_all = [int(n) for n in _PROVED_SIMPLE_RE.findall(text)]
        if _proved_all:
            proven = sum(_proved_all)
    if proven is None or total is None:
        m = _SIMPLE_SLASH_RE.search(text)
        if m:
            if proven is None:
                proven = int(m.group(1))
            if total is None:
                total = int(m.group(2))

    if unproven is None:
        # The LAST residual line, not the first: each induction rung re-reports
        # what is STILL unproven, so the furthest state the run reached is the
        # last one it printed. On the same measured run the first line said
        # 1837 and the last said 3.
        _resid = _INDUCT_FOUND_RE.findall(text)
        if _resid:
            unproven = int(_resid[-1])

    # Reconstruct the missing piece from the other two when possible.
    if total is None and proven is not None and unproven is not None:
        total = proven + unproven
    if total is not None and proven is not None and unproven is None:
        unproven = total - proven
    if total is not None and unproven is not None and proven is None:
        proven = total - unproven

    # A decomposition that does not add up is a bug in THIS parser, not a
    # property of the design, and it must never be published as if it were a
    # census. `proven` and `unproven` are both read from the same
    # `equiv_status` summary line, so their sum is the population that pass
    # actually saw; if `total` came from a different line and disagrees, the
    # sum is the one to trust. Widen only -- never narrow a denominator here.
    if (total is not None and proven is not None and unproven is not None
            and proven + unproven > total):
        total = proven + unproven

    sat_aborts: List[Dict[str, str]] = [
        {"cell": mm.group(1), "cell_type": mm.group(2)}
        for mm in _SAT_ABORT_RE.finditer(text)
    ]

    ml = _UNPROVEN_LIST_RE.search(text)
    if ml:
        unproven_cells = [t for t in re.split(r"[,\s]+", ml.group(1)) if t][:50]
    elif unproven == 0:
        # The closing `equiv_status` says nothing is unproven. The workset's
        # "failed" lines then belong to an attempt a later extension closed
        # (subservient's PASS listed the five cells `-seq 16` went on to prove).
        unproven_cells = []
    else:
        # #2182 -- the run never reached `equiv_status`; the workset block is
        # the only place the names survive. Same 50-name cap as the primary.
        unproven_cells = unproven_cells_from_induct_workset(text)[:50]

    success_line = bool(_SUCCESS_RE.search(text))

    parse_error = proven is None and unproven is None and total is None \
        and not sat_aborts

    matched = (
        not parse_error
        and unproven == 0
        and (proven or 0) > 0
        and not sat_aborts
    )

    _fe_aborted, _fe_evidence = frontend_aborted_before_elaboration(text)
    _undef_macros = undefined_macro_modules(text)
    if parse_error and _undef_macros:
        # HARD-MACRO STAGING GAP (#192). The netlist instantiates a module whose
        # definition was not staged on this side, so `hierarchy -check` aborted
        # BEFORE equiv_make and 0 points were compared. A killed-before-it-ran
        # comparison is NOT a proven non-equivalence — yet booking it as FAIL
        # (which is what the generic parse_error branch below does) reports a
        # comparison that never started as if equivalence had been tested and
        # failed. That is the exact harm in #192. Classify INCONCLUSIVE: a
        # disclosed staging gap, non-blocking, never a vacuous PASS.
        #
        # We deliberately do NOT auto-stage the macro into the miter and
        # re-compare. In-container negative controls proved that naive symmetric
        # staging (the full behavioural model on both sides) AND a `-lib`
        # blackbox BOTH produce a FALSE PASS on a memory macro — even for a
        # genuine logic bug in the netlist that FEEDS the macro — because yosys
        # equiv's name-based net matching mis-handles the hierarchical macro I/O
        # (the blackbox loses its port directions; the full model name-aliases
        # the macro output net to a top port). A false LEC PASS ships a broken
        # netlist as verified, which is strictly worse than the false FAIL this
        # fix removes. Sound hard-macro equivalence needs a blackbox
        # assume-guarantee this recipe cannot guarantee → close with sign-off
        # LEC (Conformal/VC LEC), which does.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            "LEC built NO equivalence miter — the netlist instantiates hard "
            f"macro/submodule(s) {_undef_macros} whose definition was not "
            "staged, so `hierarchy -check` aborted before equiv_make and 0 "
            "points were compared. NOT a proven non-equivalence (no miter ran) "
            "→ INCONCLUSIVE, never a hard FAIL that cascade-marks downstream "
            "steps MISSING and never a vacuous PASS. Close with sign-off LEC "
            "(Conformal/VC LEC), which handles hard macros with a sound "
            "blackbox assume-guarantee. See reports/lec.rpt for the hierarchy "
            "error.")
    elif parse_error and _fe_aborted:
        # OBSERVABLE (v1.4.x): the run REACHED the read and never got past it,
        # so no elaborated design was ever produced and NO miter was built → 0
        # compared points. Not classifiable as PASS or FAIL → INCONCLUSIVE.
        # Decided by stage progress, NOT by how the frontend phrased its abort —
        # a reworded abort used to restore the false FAIL that cascade-marks 24
        # downstream steps MISSING.
        # §4.05: this requires POSITIVE stage evidence, so a crash with no
        # frontend evidence, and a run that died AFTER elaborating, both stay
        # HARD FAIL below. A genuine miter that runs and leaves unproven points
        # still FAILs; only the zero-miter stopped-at-the-read shape re-classes.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            "Yosys built NO equivalence miter — the run stopped AT the frontend "
            "so no elaborated design was ever produced, leaving 0 compared "
            f"points. Observable: {_fe_evidence}. Not classifiable as PASS or "
            "FAIL → INCONCLUSIVE (the static/functional sign-off is not decided "
            "here; re-run with the slang frontend or fix the read error). See "
            "reports/lec.rpt for the frontend error.")
    elif parse_error and _EXECUTION_STOP_RE.search(text):
        # MERGE (#155 origin SKIPPED-CONDITION vs local FAIL) — EVIDENCE-BASED
        # SPLIT: the miter was still running when the wall budget expired, leaving
        # no equiv_status (parse_error) but the self-written timeout marker.
        # Classify by the ACTUAL EVIDENCE in the log, not a binary policy:
        #   * if the LEC actually RECORDED a mismatch / counterexample before it
        #     was killed → a proven non-equivalence is a real FAIL regardless of
        #     the timeout (a mismatch found is a mismatch found);
        #   * otherwise (pure resource/time exhaustion, 0 points decided) →
        #     SKIPPED-CONDITION: a DISCLOSED budget/capability gap (the SAME
        #     family as the $mem_v2 SAT-model skip below), NOT a proven mismatch
        #     — so origin #155 holds: a slow-but-not-disproven proof (e.g.
        #     sha256's >1200s memory-inclusive miter) is NOT spuriously FAILed.
        # It is STILL a visible non-PASS (equivalent:false, verdict != PASS),
        # never a silent free pass — so local's "a resource limit is never a free
        # pass" ALSO holds: a real regression cannot hide behind it.
        # §4.05: the mismatch discriminator is PRECISION-first — it fires only on
        # an unmistakable non-equivalence phrase a pure-timeout log cannot carry,
        # so the DANGEROUS direction (a spurious FAIL on a slow proof) cannot
        # occur; a missed mismatch degrades to the visible SKIPPED-CONDITION.
        equivalent = False
        if _MISMATCH_EVIDENCE_RE.search(text):
            verdict = "FAIL"
            verdict_explanation = (
                f"Yosys equiv was stopped by {_stop_kind} before completion, "
                "but the log "
                "RECORDED a "
                "mismatch / counterexample before it was killed — a proven "
                "non-equivalence is a real FAIL regardless of the timeout. See "
                "reports/lec.rpt for the recorded counterexample.")
        else:
            verdict = "SKIPPED-CONDITION"
            verdict_explanation = (
                f"Yosys equiv was stopped by {_stop_kind} before equiv_status "
                "could "
                "report — 0 points compared and NO mismatch was recorded, so "
                "there is no equivalence evidence in either direction. This is a "
                "DISCLOSED budget/capability gap (the same family as the $mem_v2 "
                "SAT-model skip), NOT a proven mismatch: raise --timeout or close "
                "the remainder with sign-off LEC (Conformal/VC LEC). It stays a "
                "visible non-PASS (equivalent:false) — never a silent free pass a "
                "regression could hide behind.")
    elif parse_error:
        # HARD FAIL, deliberately NOT re-classified: there is no positive
        # evidence the FRONTEND is where this stopped. Either yosys never ran
        # (crash / container failure) or it elaborated a design and died later —
        # both are real failures, and INCONCLUSIVE (the less blocking outcome)
        # must never be reachable without stage evidence. The observable that
        # ruled it out is recorded so the distinction is auditable.
        equivalent = False
        verdict = "FAIL"
        verdict_explanation = (
            "Yosys produced no parseable equivalence result — the equiv "
            "check did not reach a verdict (see reports/lec.rpt for the raw "
            f"tool log). NOT re-classified as INCONCLUSIVE because {_fe_evidence}"
            " — a run with no frontend-abort evidence stays a blocking FAIL.")
    elif (_EXECUTION_STOP_RE.search(text)
          and proven is None and unproven is None
          and not _MISMATCH_EVIDENCE_RE.search(text)):
        # ORGANIC v1462 (ibex/CPU-class) — a wall-clock TIMEOUT killed the run
        # BEFORE any completed equiv_status verdict: NO `N are proven and M are
        # unproven` line was ever emitted (proven AND unproven both unknown),
        # only the INITIAL `$equiv` cell TOTAL leaked into the parse (so
        # parse_error is False and the parse_error+timeout branch above was
        # skipped — that is the bug this branch fixes). yosys was killed
        # mid-equiv_simple, so ZERO points were decided in EITHER direction and
        # NO counterexample was recorded. This is the SAME zero-completed-
        # comparison class as the frontend parse-abort (INCONCLUSIVE), NOT a
        # proven mismatch — blocking the whole flow on it is a false FAIL that
        # cascade-marks downstream steps MISSING.
        #
        # §4.05 PRECISION-first / NO-LEAK: this fires ONLY when NEITHER a proven
        # NOR an unproven count exists (no completed comparison) AND no
        # counterexample phrase is present. A COMPLETED miter that left points
        # unproven (e.g. sha256: `952 are proven and 1034 are unproven` — both
        # parsed) has proven!=None and NEVER reaches here → it stays a real FAIL
        # (the tested `miter ran, unproven>0 = FAIL` doctrine is untouched). A
        # timeout that DID record `_MISMATCH_EVIDENCE_RE` escalates to the
        # blocking FAIL below. Never a PASS — equivalent stays False.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            f"Yosys equiv was stopped by {_stop_kind} BEFORE any "
            "completed equiv_status verdict — no `N proven / M unproven` line "
            "was emitted (only the initial $equiv cell total was seen) and NO "
            "counterexample was recorded, so 0 points were decided in either "
            "direction. A budget-exhausted proof is NOT a proven "
            "non-equivalence → INCONCLUSIVE (a disclosed budget gap: raise "
            "--timeout or close with sign-off LEC). It stays a visible non-PASS "
            "(equivalent:false), never a silent free pass a regression could "
            "hide behind.")
    elif matched:
        equivalent = True
        verdict = "PASS"
        verdict_explanation = (
            f"all {proven}/{proven} $equiv cells proven; RTL and gate "
            "netlist structurally equivalent"
            + (" (Yosys: Equivalence successfully proven!)"
               if success_line else ""))
    elif sat_aborts:
        equivalent = False
        verdict = "SKIPPED-CONDITION"
        types = sorted({c["cell_type"] for c in sat_aborts})
        verdict_explanation = (
            f"Yosys proved {proven if proven is not None else '?'}/"
            f"{total if total is not None else '?'} structural equivalence; "
            f"{len(sat_aborts)} cell(s) lacked a SAT model in equiv_induct "
            f"(custom-PDK Liberty primitives without Yosys built-in "
            f"semantics: {', '.join(types[:6])}). This is a disclosed tool "
            "capability-gap, NOT a proven mismatch — sign-off LEC "
            "(Conformal/VC LEC) required to close the remainder.")
    else:
        # A COMPLETED miter left points unproven. #208 — distinguish a genuine
        # difference (witnessed by a COUNTEREXAMPLE) from equiv_induct simply
        # NOT CONVERGING (a flat wall that proved nothing and recorded no
        # counterexample). The latter is INCONCLUSIVE, not NOT_EQUIVALENT: a
        # non-convergent induction is not evidence of non-equivalence.
        # §4.05 PRECISION-first / NO-LEAK: the re-class fires ONLY when there is
        # (i) positive non-convergence evidence AND (ii) NO counterexample. A
        # real mismatch prints a counterexample → _MISMATCH_EVIDENCE_RE matches
        # → stays the blocking FAIL below; a miter that leaves points unproven
        # WITHOUT the flat-wall signature also stays FAIL. Never a PASS.
        _noconv, _noconv_ev = induction_did_not_converge(text)
        _has_ctrex = bool(_MISMATCH_EVIDENCE_RE.search(text))
        # A STATELESS MITER CANNOT HAVE AN INDUCTION-DEPTH PROBLEM. See
        # miter_is_stateless: on a combinational miter every rung of the
        # `-seq` ladder is guaranteed to print `Proved 0 previously unproven`
        # for any point equiv_simple left open, so the flat-wall signature
        # fires on EVERY real combinational mismatch and laundered it into a
        # non-blocking INCONCLUSIVE. Requiring positive evidence that the
        # miter holds state is what lets the FAIL survive. Fail-CLOSED: when
        # statelessness cannot be established, `_stateless` is False and this
        # line is a no-op -- every sequential design keeps today's verdict.
        _stateless, _stateless_ev = miter_is_stateless(text)
        if _stateless:
            _noconv = False
            _noconv_ev = _stateless_ev
        # #778 — a `-seq` ladder that ran out of depth WHILE STILL PROVING new
        # cells on its deepest rung (converging, not a flat wall) is the same
        # disclosed sequential-depth capability gap. Only consulted when there is
        # neither a flat wall nor a counterexample, so it can never soften a real
        # mismatch (which prints a counterexample → stays the blocking FAIL).
        if not _noconv and not _has_ctrex and not _stateless:
            _noconv, _noconv_ev = induction_ladder_exhausted(text)
        # AND THE LADDER THAT NEVER GOT THERE. Same guards, same reason, and
        # last in the chain so it can only ever describe a log the two above
        # have already declined: no flat wall (there was no induction to be
        # flat), no positive induct progress (likewise), no counterexample, and
        # a miter that holds state.
        _below_induction = False
        if not _noconv and not _has_ctrex and not _stateless:
            _below_induction, _below_ev = ladder_stopped_below_induction(text)
            if _below_induction:
                _noconv, _noconv_ev = True, _below_ev
        # A WALL-CLOCK KILL THAT MADE PARTIAL PROGRESS.
        #
        # The three budget guards above all have a precondition this shape
        # fails, so it fell through to the blocking FAIL below:
        #   * the `parse_error + _EXECUTION_STOP_RE` branch needs NOTHING parsed;
        #   * the `proven is None and unproven is None` branch needs NEITHER
        #     count parsed;
        #   * `induction_did_not_converge` needs `Proved 0` or `Circuit
        #     inherently diverges`, and `induction_ladder_exhausted` needs an
        #     `equiv_induct` marker — NEITHER exists when the clock kills the
        #     run during equiv_simple, before equiv_induct ever starts.
        #
        # So a run killed mid-`equiv_simple` AFTER it proved some cells parses
        # as `proven=N>0`, `unproven=total-N>0`, no flat wall, no ladder, no
        # counterexample — and was reported as
        #     "N/T proven, U unproven — the RTL and gate netlist MAY GENUINELY
        #      DIFFER at these points."
        # from a log whose last line is this program's OWN
        # producer-owned execution-stop marker. That is the exact harm the module docstring says
        # this file exists to prevent: "a killed run produced NO evidence —
        # indistinguishable at the gate from a real mismatch", to be "NAMED
        # (raise --timeout) instead of read as a mismatch that was never
        # found."
        #
        # THE PRECISE DISTINCTION — a MEASURED unproven count vs an INFERRED
        # one. This is the line the existing doctrine already draws, which the
        # budget branches simply never consulted:
        #
        #   * `equiv_status` emitted "Of those cells N are proven and M are
        #     unproven" (_FINAL_RE). Those M points WERE attempted and left
        #     unproven — a real per-point verdict. A timeout marker arriving
        #     afterwards (e.g. rc=137 re-attaching it) cannot retract it, and
        #     it must STAY FAIL. Asserted by
        #     `test_lec_run.test_container_timeout_rc_with_recorded_mismatch_still_fails`
        #     and `test_v1462_lvs_lec_manifest_capture
        #      .test_timeout_with_partial_completed_verdict_still_fails`.
        #
        #   * NO `_FINAL_RE` line: `unproven` was not measured at all, it was
        #     RECONSTRUCTED by `total - proven` further up. Those points were
        #     never attempted — the clock killed the run first. Reporting them
        #     as points where the designs "may genuinely differ" states a
        #     comparison that never happened.
        #
        # So the re-class fires only on (timeout marker) AND (no completed
        # equiv_status) AND (no counterexample). §4.05 PRECISION-first /
        # NO-LEAK: each of the three conjuncts removes a way this could soften
        # a real result, and `_EXECUTION_STOP_RE` is written only by this
        # producer's kill paths, so a naturally completed run is untouched.
        _execution_stopped = bool(_EXECUTION_STOP_RE.search(text))
        # A COUNT FROM AN UNFINISHED LADDER IS A POSITION, NOT A VERDICT
        # (vibe-ic#2194). The rule above is exactly right while ONE process
        # runs the whole ladder: there is then a single `equiv_status`, at the
        # very end, so a `_FINAL_RE` line existing IS the ladder having
        # finished. Once each rung runs in its OWN process every leg prints an
        # `equiv_status` — a leading one at its read-back and a closing one of
        # its own — so a `_FINAL_RE` line can belong to a leg the ladder never
        # climbed past. Reading THAT as "attempted and left unproven" would
        # report a ladder cut off at -seq 16 as a design that "may genuinely
        # differ", on points that -seq 64 was still going to discharge. That is
        # the #2182 mislabel, arriving by a new road.
        #
        # `ladder_complete` is therefore a fact the TEXT CANNOT CARRY, supplied
        # by the driver that knows it. None — every caller that predates this,
        # and the single-process path, where the old equivalence still holds —
        # leaves the conjunct exactly as it was. Only an explicit False, which
        # only the per-rung driver passes and only when it stopped early, can
        # move a verdict, and it moves it towards NOT MEASURED, never towards
        # a PASS: `_has_ctrex` and `_noconv` remain separate conjuncts, so a
        # recorded counterexample still keeps its FAIL.
        _measured_verdict = (bool(_FINAL_RE.search(text))
                             and ladder_complete is not False)
        if _execution_stopped and not _measured_verdict and not _has_ctrex \
                and not _noconv:
            _noconv = True
            _noconv_ev = (
                f"{_stop_kind} stopped yosys mid-proof, before "
                "equiv_induct ran — the unproven remainder was never "
                "attempted, not refuted")
        # NO-COMPLETED-COMPARISON KILL (measured: opentitan_aes × sky130A).
        # A miter WAS built — `not parse_error`, so `total` is known — but
        # NEITHER a proven NOR an unproven count was ever recorded: equiv_make
        # ran and then NO equiv_simple / equiv_induct / equiv_status verdict
        # reached the log, and NO counterexample was seen. A COMPLETED equiv
        # pass ALWAYS emits at least one count — equiv_status' "N proven / M
        # unproven" (_FINAL_RE), equiv_simple's "Proved N previously unproven"
        # (_PROVED_SIMPLE_RE, N may be 0), or equiv_induct's "Found N unproven
        # … in module equiv" (_INDUCT_FOUND_RE) — so `proven is None AND
        # unproven is None` means the proof was CUT OFF before any point was
        # decided: an external kill / crash / container interruption that did
        # NOT route through an execution-stop marker path
        # (_EXECUTION_STOP_RE absent, so _execution_stopped above did not
        # fire). Zero decided points + zero
        # counterexamples = no equivalence evidence in EITHER direction — the
        # exact no-evidence state this module's docstring exists to keep OUT of
        # a false NOT_EQUIVALENT ("a killed run produced NO evidence —
        # indistinguishable at the gate from a real mismatch"). §4.05 NO-LEAK:
        # a real mismatch carries a counterexample (_has_ctrex) OR a completed
        # status with unproven>0 (proven parsed), so it can NEVER reach here —
        # this softens ONLY a run that decided nothing. INCONCLUSIVE, never
        # FAIL, never PASS. MEASURED WITNESS: opentitan_aes's Step-13 lec.rpt
        # ended mid-`equiv_simple` (only ~1720/31850 cells attempted, no
        # equiv_status, no "Proved N", no marker) and was booked FAIL "may
        # genuinely differ" — a fabricated non-equivalence that blocked 24
        # downstream steps.
        _no_completed_comparison = (proven is None and unproven is None)
        if _no_completed_comparison and not _has_ctrex and not _noconv:
            _noconv = True
            _noconv_ev = (
                "equiv_make built the miter but NO equiv_simple/induct/status "
                "verdict was ever recorded (no proven and no unproven count) "
                "and no counterexample was seen — the proof was cut off before "
                "any point was decided (an interrupted/killed/crashed run "
                "outside the wall-budget marker path)")
        if _no_completed_comparison and _noconv and not _has_ctrex:
            # The miter was built but the proof was cut off before ANY point was
            # decided. Distinct wording from the convergence-wall case below:
            # equiv_induct never even ran here, so "did NOT converge" would be
            # inaccurate — the run recorded NO verdict at all.
            equivalent = False
            verdict = "INCONCLUSIVE"
            verdict_explanation = (
                f"A {total if total is not None else '?'}-point equivalence "
                "miter was built, but the proof recorded NO decided points "
                f"({_noconv_ev}) and NO counterexample "
                "(non_equivalent_points=0). A run that decided nothing is NOT "
                "evidence of non-equivalence: a real difference produces a "
                "counterexample or a completed equiv_status with unproven>0. "
                "→ INCONCLUSIVE (a killed/interrupted run outside the "
                "wall-budget marker path), never a false NOT_EQUIVALENT. Re-run "
                "uninterrupted (raise --timeout) or close with sign-off LEC "
                "(Conformal/VC LEC). Visible non-PASS (equivalent:false) — "
                "never a vacuous PASS a regression could hide behind.")
        elif _noconv and not _has_ctrex and (unproven or 0) > 0:
            equivalent = False
            verdict = "INCONCLUSIVE"
            # A TIMEOUT IS A BUDGET OUTCOME, NOT A CAPABILITY GAP — vibe-ic#581,
            # and this branch was asserting the opposite on a real run.
            #
            # MEASURED 2026-09-06 on an open benchmark IC (reports/lec.json,
            # captured read-only): a proof holding a full core for the whole
            # budget was killed at 7195.77 s of 7200 s with
            # `killed_by_budget: true`, and this branch booked it
            # "1060/2130 proven, 1070 unproven — but equiv_induct did NOT
            # converge (THE WALL-CLOCK BUDGET STOPPED YOSYS MID-PROOF, before
            # equiv_induct ran) ... → INCONCLUSIVE (A DISCLOSED
            # SEQUENTIAL-DEPTH CAPABILITY GAP) ... Close the remainder with
            # sign-off LEC, which handles deep sequential induction."
            #
            # THE RECORD CONTRADICTED ITSELF IN ONE SENTENCE. Its own evidence
            # string said the clock stopped the proof; the label beside it
            # blamed the engine's depth, and the remedy it recommended was a
            # commercial tool. equiv_induct had not failed to converge — by the
            # same sentence's admission it had NOT YET RUN.
            #
            # So the label now follows the evidence. `_execution_stopped` is
            # already computed above from `_EXECUTION_STOP_RE`, which only this
            # producer's kill paths write, and `_stop_kind` already says WHICH
            # kill it was. A run that was STOPPED gets the stopped wording; a
            # run that genuinely walked the induction ladder to exhaustion keeps
            # the capability-gap wording, because for that run it is TRUE.
            if ladder_complete is False and not _execution_stopped:
                verdict_explanation = (
                    f"{proven}/{total} proven, {unproven} unproven — "
                    "the proof ladder did not finish. A completed earlier "
                    "rung is partial evidence, not an exhausted engine "
                    "ladder or proof of a mismatch. No counterexample was "
                    "recorded. Equivalence remains INCONCLUSIVE.")
            elif _below_induction and not _execution_stopped:
                verdict_explanation = (
                    f"{proven if proven is not None else 0}/"
                    f"{total if total is not None else '?'} proven, "
                    f"{unproven if unproven is not None else '?'} unproven — "
                    f"and the proof ladder STOPPED BELOW ITS INDUCTION RUNGS "
                    f"({_noconv_ev}), with NO counterexample recorded "
                    "(non_equivalent_points=0). This is NOT a statement about "
                    "the engine's sequential depth and NOT a capability gap: "
                    "equiv_induct was never asked, so nothing about the "
                    "remainder was learned. → INCONCLUSIVE (the recipe stopped "
                    "short), never a false NOT_EQUIVALENT. THE REMEDY IS HERE, "
                    "NOT IN A COMMERCIAL TOOL: run the induction rungs "
                    "(`equiv_induct -seq 4/16/64`, LEC_LADDER rungs 3-5; raise "
                    "`ladder_rungs`, or let the per-rung driver continue to the "
                    "next rung). Visible non-PASS (equivalent:false) — never a "
                    "vacuous PASS a regression could hide behind.")
            elif _execution_stopped:
                verdict_explanation = (
                    f"{proven if proven is not None else 0}/"
                    f"{total if total is not None else '?'} proven, "
                    f"{unproven if unproven is not None else '?'} unproven — "
                    f"and the proof was STOPPED before it could finish "
                    f"({_noconv_ev}), with NO counterexample recorded "
                    "(non_equivalent_points=0). This is NOT a statement about "
                    "the engine's sequential depth and NOT a capability gap: "
                    "the remainder was never attempted, so nothing about it was "
                    "learned. → INCONCLUSIVE (the run was cut off), never a "
                    "false NOT_EQUIVALENT. The remedy is to let the proof RUN "
                    "— it was making forward progress when it was stopped; "
                    "reach for sign-off LEC only if it is allowed to finish and "
                    "then genuinely does not converge. Visible non-PASS "
                    "(equivalent:false) — never a vacuous PASS a regression "
                    "could hide behind.")
            else:
                verdict_explanation = (
                    f"{proven if proven is not None else 0}/"
                    f"{total if total is not None else '?'} proven, "
                    f"{unproven if unproven is not None else '?'} unproven — but "
                    "equiv_induct did NOT converge "
                    f"({_noconv_ev}) and NO counterexample was recorded "
                    "(non_equivalent_points=0). Non-convergence is NOT "
                    "non-equivalence: a real difference produces a counterexample. "
                    "→ INCONCLUSIVE (a disclosed sequential-depth capability gap), "
                    "never a false NOT_EQUIVALENT. Close the remainder with sign-off "
                    "LEC (Conformal/VC LEC), which handles deep sequential "
                    "induction. Visible non-PASS (equivalent:false) — never a "
                    "vacuous PASS a regression could hide behind.")
        else:
            equivalent = False
            verdict = "FAIL"
            verdict_explanation = (
                f"{proven if proven is not None else 0}/"
                f"{total if total is not None else '?'} proven, "
                f"{unproven if unproven is not None else '?'} unproven — the RTL "
                "and gate netlist may genuinely differ at these points."
                + (" A counterexample was recorded in the tool log."
                   if _has_ctrex else ""))

    return {
        "proven": proven,
        "unproven": unproven,
        "total": total,
        "sat_model_unsupported_cells": sat_aborts,
        "unproven_cells": unproven_cells,
        "success_line": success_line,
        "parse_error": parse_error,
        "equivalent": equivalent,
        "verdict": verdict,
        "verdict_explanation": verdict_explanation,
        # #2050: WHICH flat wall, when there is one — `miter_inconsistent`
        # (equiv_induct's base case went UNSAT: the key-point set the recipe
        # handed the engine cannot all hold at once) vs `induction_depth`
        # (the base case held; the induction step did not close within -seq).
        # "" when neither signature is in the log. The gate needs the two
        # apart because only the second one is a depth gap that a stronger
        # sequential engine could close.
        "induction_wall_kind": induction_wall_kind(text),
        # #192: hard macro(s) the run could not resolve (empty unless a
        # `hierarchy -check` abort on an unstaged module drove the INCONCLUSIVE
        # classification above).
        "undefined_macro_modules": _undef_macros,
    }


def build_report(parsed: Dict, top: str, gate_netlist: str,
                 liberty: Optional[str],
                 liberty_source: Optional[str] = None) -> Dict:
    """Shape a parse result into the reports/lec.json schema the gate reads."""
    proven = parsed["proven"]
    unproven = parsed["unproven"]
    return {
        "equivalent": parsed["equivalent"],
        # proven $equiv cell count — >0 required for a non-vacuous PASS.
        "compared_points": proven if proven is not None else 0,
        # The SIZE of the proof obligation, i.e. how many $equiv points
        # equiv_make built. `parse_equiv_output` has always measured this (it
        # is the `total` it uses to reconstruct the other two counts) and
        # build_report has always dropped it, so an INCONCLUSIVE lec.json said
        # `compared_points: 0` and gave a reader NO way to tell "the budget
        # nearly covered it, raise --timeout" from "this miter is orders of
        # magnitude beyond any budget on this machine". Those call for opposite
        # actions. None only when no total was parseable (never fabricated).
        "miter_points": parsed.get("total"),
        # Yosys equiv_status does not emit a distinct proven-non-equivalent
        # count; a genuine difference surfaces as `unproven`, so this stays 0.
        "non_equivalent_points": 0,
        "unproven_points": unproven if unproven is not None else 0,
        "gold": f"{top} (RTL)",
        "gate": f"{Path(gate_netlist).name} (synth)",
        "tool": "yosys equiv_make+equiv_simple+equiv_induct",
        "verdict": parsed["verdict"],
        # A frontend parse-abort built no miter → INCONCLUSIVE (0 compared
        # points); the downstream gate treats this as a non-blocking
        # SKIPPED-CONDITION, never a hard FAIL nor a vacuous PASS.
        "inconclusive": parsed["verdict"] == "INCONCLUSIVE",
        # #208: True when the INCONCLUSIVE was reached by a COMPLETED miter that
        # left points unproven because equiv_induct did not converge (a flat
        # wall, no counterexample) — as opposed to the #192 zero-miter aborts.
        # Auditable so a reviewer sees this is a sequential-depth gap, not a
        # proven non-equivalence.
        "non_convergence": (parsed["verdict"] == "INCONCLUSIVE"
                            and (unproven or 0) > 0),
        # #192: names the unstaged hard macro(s) when a `hierarchy -check` abort
        # drove INCONCLUSIVE; empty on every other outcome. Auditable so a
        # reviewer sees WHY no miter was built.
        "undefined_macro_modules": parsed.get("undefined_macro_modules", []),
        "sat_model_unsupported_cells": parsed["sat_model_unsupported_cells"],
        "unproven_cells": parsed["unproven_cells"],
        "verdict_explanation": parsed["verdict_explanation"],
        # #2050 — carried through so the gate can name the RIGHT cause. See
        # `induction_wall_kind`. "" on every log with no flat-wall signature,
        # which is every PASS and every counterexample FAIL, so no existing
        # verdict moves.
        "induction_wall_kind": parsed.get("induction_wall_kind", ""),
        "liberty": liberty,
        # WHICH of the four resolution paths produced that library. Recorded so
        # a reader never has to infer it: "default" means the built-in constant,
        # which belongs to one PDK and is wrong for every other one.
        "liberty_source": liberty_source,
        "program": PROGRAM,
    }


# ---------------------------------------------------------------------------
# Container plumbing (patterned on the shared long-tool docker watchdog).
# ---------------------------------------------------------------------------
def _docker_exec_raw(container: str, cmd: str, timeout: int = 120):
    """Short, unsupervised docker/host exec used only by watchdog probes.

    `_docker_watchdog.run_docker_supervised` injects this callback for its
    identity, CPU and reap probes.  Those commands are short and bounded; they
    must not recursively enter the long-tool supervisor they are measuring.
    """
    argv = (["bash", "-lc", cmd] if container in ("", "host") else
            _ce.docker_exec_argv(container, "bash", "-lc", cmd))
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return 124, out, err + f"\nprobe timeout after {timeout}s"
    except OSError as exc:
        return 127, "", f"COMMAND_NOT_FOUND: {exc}"


def _dw_mod():
    """The container watchdog module, or None. One import shape for every
    caller in this file."""
    try:
        import _docker_watchdog as _dw
        return _dw
    except Exception:  # nosec — never let hardening break the call
        return None


def _docker(container: str, cmd: str, timeout: int = 120,
            marker: Optional[str] = None, *,
            log_path: Optional[Path] = None,
            telemetry_path: Optional[Path] = None,
            telemetry_context: Optional[Dict] = None,
            abort_probe=None):
    """Run `cmd` in the container under a bounded budget.

    The command carries its OWN container-side deadline a few seconds before
    host's.  A marked long tool additionally uses the shared container-aware
    progress watchdog: it observes the stamped in-container process tree's CPU,
    not merely the nearly-idle host `docker exec` client.  That distinction is
    load-bearing for quiet Yosys SAT passes.  The former host-only progress
    monitor killed two healthy RTLLM LEC jobs after its nested silence window
    while each Yosys process was still advancing at one full core; the 7195 s
    container timeout then survived as an orphan.

    The shared watchdog owns both sides of the contract: progress comes from
    the real container tree, and a stall/ceiling reaps exactly the stamped tree
    before releasing the host client.  `timeout` remains the TOTAL LEC attempt
    budget, not a fresh retry budget.  Unmarked short probes retain the prior
    lightweight path.  chip/tool/design-AGNOSTIC.
    """
    try:
        import _docker_watchdog as _dw
    except Exception:  # nosec — never let hardening break the call
        _dw = None

    if marker and _dw is not None:
        rc, out, err = _dw.run_docker_supervised(
            container, cmd, marker,
            docker_exec_raw=_docker_exec_raw,
            log_path=log_path,
            telemetry_path=telemetry_path,
            telemetry_stage_probe=lec_stage_from_output,
            # HOW FAR THE PROOF GOT, into the sidecar. Measured 2026-09-06 on a
            # real ceiling kill: the sidecar recorded status "hard_ceiling",
            # rc 124, and 239 samples whose cpu_seconds tracked elapsed at
            # 99.99 % to the last look -- so it proved the job was WORKING and
            # could not say it was CONVERGING, because no proved-point count
            # was anywhere in the file. Evidence only; never a verdict input.
            telemetry_metric_probe=lec_proved_points_from_output,
            telemetry_context=telemetry_context,
            # The caller's domain predicate (`rung_projection_abort_probe`):
            # the proof's own evidence, never the clock, may end a rung.
            abort_probe=abort_probe,
            # THE ATTEMPT BUDGET IS NOT A CEILING, and handing it to
            # `hard_ceiling_s` was a wall-clock deadline wearing the watchdog's
            # clothes. `_watchdog` says what that parameter is for in one line:
            # "a pathological-infinite-loop backstop ONLY ... NOT the primary
            # control". Pinned to the budget it also became the container-side
            # GNU `timeout` (`wrap_with_container_timeout`), so a Yosys proof
            # that was emitting output and holding a full core was SIGKILLed at
            # budget-5s with no verdict -- and the flow then recorded a design
            # it never compared. MEASURED 2026-09-06 on an open benchmark IC: a
            # post-layout LEC at 5360 s of a 7195 s budget, 1374 points proved,
            # 0 failed, 99.9 % CPU, still advancing.
            #
            # WHAT STILL BOUNDS THE STEP. `timeout` keeps its ORIGINAL job --
            # `StepBudget.next_attempt_budget()` returns 0 once the step
            # deadline has passed and the next attempt is NOT LAUNCHED. That is
            # the anti-re-arm property the budget was written for on
            # 2026-08-27 (three attempts x 7200 s against a nominal "7200 s
            # budget"), and it is a decision taken BETWEEN attempts, so it
            # stops nothing that is running. A RUNNING attempt is now bounded
            # by FORWARD PROGRESS alone: still moving -> runs to completion,
            # however long that legitimately takes; stopped moving -> killed
            # and recorded as STALLED (`_STALL_MARKER`, rc RC_STALLED), which
            # this file already keeps distinct from `_TIMEOUT_MARKER`.
            #
            # A BIGGER NUMBER WOULD BE THE SAME DEFECT WITH A LATER DATE, so
            # there is no number here at all: the ceiling falls back to the
            # primitive's own pathological backstop, exactly as
            # `design_one_shot_runner._run` already does after the same repair.
        )
        return subprocess.CompletedProcess(
            (["bash", "-lc", cmd] if container in ("", "host") else
             _ce.docker_exec_argv(container, "bash", "-lc", cmd)),
            rc, out, err)

    if _dw is not None:
        cmd = _dw.wrap_with_container_timeout(cmd, timeout)
    return _pr.run(
        (["bash", "-lc", cmd] if container in ("", "host") else
         _ce.docker_exec_argv(container, "bash", "-lc", cmd)),
        capture_output=True, text=True)


def _docker_exec3(container: str, cmd: str):
    """`(rc, out, err)` docker-exec adapter matching the `exec_fn` contract of
    synth_frontend.resolve_slang_load_prefix (used to probe the slang load
    prefix for the gold-read slang fallback). Never raises — returns a non-zero
    rc + empty streams on failure so the caller keeps the fork-safe default."""
    try:
        r = _docker(container, cmd, timeout=60)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def _container_available(container: str) -> bool:
    """Can this process run anything in `container`?

    `ContainerImageMismatch` IS DELIBERATELY NOT CAUGHT HERE (vibe-ic#2173).
    It is not an availability answer: the container is right there, yosys is
    right there, and what was refused is the RIGHT to use bytes this repo does
    not pin. Answering `False` would report it as the "container not available
    — runner should disclosed-skip" case one line below, which is a capability
    gap this flow deliberately carries and a completely different sentence.
    `main`'s door guard below catches it and reports the refusal in its own
    tier; `entry` is the backstop for the container touches further down.
    """
    try:
        return _docker(container, "true", timeout=30).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _container_file_exists(container: str, path: str) -> bool:
    try:
        r = _docker(container, f"test -f {shlex.quote(path)}", timeout=30)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _container_dir_writable(container: str, path: str) -> Tuple[bool, str]:
    """Can the TOOL write into this directory? Measured, never assumed.

    `write_rtlil` to a path the container cannot write is a HARD yosys ERROR
    that aborts the whole script (measured in-container: rc 1, "Can't open
    output file ... for writing"). A checkpoint is an optimisation, so it must
    never be able to fail a proof that would otherwise have succeeded — the
    directives are therefore emitted ONLY after a real write has been observed
    to land and read back. A failed probe DISABLES checkpointing loudly and
    leaves the recipe byte-identical to the un-checkpointed one.
    """
    token = secrets.token_hex(8)
    probe = str(Path(path) / (".lec_ckpt_probe." + token))
    q = shlex.quote(probe)
    rc, out, err = _docker_exec_raw(
        container,
        f"printf %s {shlex.quote(token)} > {q} && cat {q} && rm -f {q}",
        timeout=60)
    if rc == 0 and token in _strip_login_banner(out or ""):
        return True, ""
    detail = (_strip_login_banner(err or "").strip()
              or _strip_login_banner(out or "").strip() or f"rc={rc}")
    return False, (f"the container cannot write into {path} ({detail}) — "
                   "checkpointing disabled for this run; the recipe is the "
                   "un-checkpointed one")


def _container_file_sha256(container: str, path: str) -> Optional[str]:
    """Hash a container-only input; absence disables cache, never the proof.

    THE BANNER IS NOT THE OUTPUT (measured 2026-09-06 on 8HD-9, image 0.3.46).
    The EDA image's login profile prints `[INFO] Final PATH variable: ...`
    lines on stdout before the command runs, so the FIRST token of `out` is
    `[INFO]`, never the digest -- `sha256sum` exited 0 and its digest was three
    lines down. The 64-hex match then failed, this returned None, the Liberty
    fingerprint was recorded as `{"state": "unreadable"}`, `_has_fingerprint`
    said no, `proof_identity_complete` said no, and the LEC PASS CACHE WAS
    SILENTLY OFF for every design whose Liberty lives in the container -- which
    is every Liberty-mapped LEC on this fleet. Measured on a real run: the
    report said `cache: {enabled: false, reason: "one or more required proof
    fingerprints unavailable"}` while `sha256sum` had in fact succeeded.

    `_strip_login_banner` is the file's OWN remedy for this exact banner and
    `_yosys_version` beside it already applies it; only this reader did not.
    Nothing else changes: a genuinely absent or unreadable file still yields
    None, and None still disables reuse rather than blocking a fresh proof.
    """
    rc, out, _ = _docker_exec_raw(
        container, f"sha256sum -- {shlex.quote(path)} 2>/dev/null", timeout=60)
    token = _strip_login_banner(out or "").strip().split()
    if rc == 0 and token and re.fullmatch(r"[0-9a-fA-F]{64}", token[0]):
        return "sha256:" + token[0].lower()
    return None


def _yosys_version(container: str) -> Optional[str]:
    rc, out, _ = _docker_exec_raw(container, "yosys -V 2>/dev/null", timeout=60)
    value = _strip_login_banner(out or "").strip().splitlines()
    return value[-1].strip() if rc == 0 and value else None


def _container_image_digest(container: str) -> Optional[str]:
    if container in ("", "host"):
        return None
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.Image}}", container],
            capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    digest = (r.stdout or "").strip()
    return digest if r.returncode == 0 and digest else None


def _path_fingerprint(path: Optional[str], project: Path, *,
                      absent_state: str = "absent") -> Dict:
    if not path:
        return {"state": absent_state}
    p = Path(path).resolve()
    try:
        label = str(p.relative_to(project.resolve()))
    except ValueError:
        label = str(p)
    try:
        return {"path": label, "sha256": _sha256_file(p)}
    except OSError:
        return {"path": label, "state": "unreadable"}


def build_proof_identity(*, project: Path, gold_files: List[str],
                         gate_netlist: str, script: str, top: str,
                         scan_meta: Optional[str], gate_wrapper: str,
                         gold_wrapper: str, liberty: Optional[str],
                         liberty_sha256: Optional[str], yosys_version: Optional[str],
                         image_digest: Optional[str]) -> Dict:
    """Build the exact semantic/tool identity a cached proof attests to."""
    liberty_id = ({"path": liberty, "sha256": liberty_sha256}
                  if liberty and liberty_sha256
                  else ({"state": "unused"} if not liberty
                        else {"path": liberty, "state": "unreadable"}))
    return {
        "recipe_schema_version": LEC_RECIPE_SCHEMA_VERSION,
        # List order is intentionally preserved: frontend compilation order is
        # semantic for macros/packages, so sorting here would weaken the key.
        "gold_rtl": [_path_fingerprint(p, project) for p in gold_files],
        "gate_netlist": _path_fingerprint(gate_netlist, project),
        "equivalence_script": {"sha256": _sha256_bytes(script.encode("utf-8"))},
        "top": top,
        "scan": {
            "metadata": _path_fingerprint(scan_meta, project),
            "gate_wrapper": _path_fingerprint(gate_wrapper, project),
            "gold_wrapper": _path_fingerprint(gold_wrapper, project),
        },
        "liberty": liberty_id,
        "yosys": {"version": yosys_version},
        "container": {"image_digest": image_digest},
    }




def _strip_login_banner(text: str) -> str:
    """Drop the container login-profile `[INFO] ...` banner lines that
    `bash -lc` prints before the actual tool output (they are PATH/PYTHONPATH
    noise, not Yosys output). chip-AGNOSTIC."""
    return "\n".join(
        ln for ln in (text or "").splitlines()
        if not ln.lstrip().startswith("[INFO]"))


# A Yosys pre-techmap netlist instantiates its cells as ESCAPED internal-
# primitive identifiers (`\$_DFF_P_`, `\$_NAND_`, `\$_NOT_`, …). Detect that
# vocabulary structurally so the gate-read recipe can switch to `-icells`
# (which re-binds those names to real internal cells instead of aborting
# `hierarchy -check` on an "undefined module `\$_DFF_P_'"). Anchored on the
# backslash-escaped `\$_` prefix (tool-defined, NOT a chip/PDK literal) so it
# never matches an RTL wire named `$foo` or a Liberty cell `sky130_fd_sc_hd__*`.
_GENERIC_PRIM_RE = re.compile(r"\\\$_[A-Z]")


def _netlist_uses_generic_primitives(path: str) -> bool:
    """True iff <path> is a generic Yosys `$_`-primitive (pre-techmap) netlist —
    i.e. it instantiates escaped internal-gate identifiers like `\\$_DFF_P_`.
    chip/PDK-AGNOSTIC: keys only on the Yosys-defined `\\$_` prefix."""
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return False
    return bool(_GENERIC_PRIM_RE.search(text))


# ---------------------------------------------------------------------------
# FUNCTIONAL-MODE (scan-aware) COMPARISON
# ---------------------------------------------------------------------------
# When the gate netlist is a REAL scan-inserted implementation netlist (see
# programs/fault_scan_chain_insert.py), it carries five DFT ports the RTL gold
# does not have — `sin`, `shift`, `test`, `tck` (inputs) and `sout` (output) —
# and its internal wires all carry the prefix `fault chain`'s resynthesis put
# on them.  Two things then break, and BOTH are name/interface problems, not
# equivalence problems:
#
#   1. `equiv_make` HARD-ERRORS on a gate port with no gold counterpart:
#        ERROR: Can't match gate port `test_gate' to a gold port.
#      MEASURED.  So the DFT ports must be REMOVED, not merely constrained;
#      a yosys `connect -set test 1'b0` tie-off leaves them in the port list.
#   2. `equiv_make` matches gold/gate wires BY NAME.  A uniform prefix on one
#      side destroys every internal correspondence and leaves only the output
#      port, which drops the miter from 97 compared points to 1 and sends
#      `equiv_induct` into a non-converging wall.  MEASURED: 63 proven with the
#      prefix mirrored, vs 1 unproven point without.
#
# The fix is a one-level wrapper on EACH side, with the gold wrapper's instance
# name chosen (an escaped identifier containing a dot) so the two `flatten`
# prefixes come out byte-identical:
#
#   gate:  rename <top> <top>__scan
#          module <top>(<rtl ports>)  { <top>__scan \_LECWRAP (…, .sin(1'b0),
#              .shift(1'b0), .test(1'b0), .tck(1'b0), .sout()) }
#   gold:  rename <top> <top>__rtl
#          module <top>(<rtl ports>)  { <top>__rtl \_LECWRAP.<prefix> (…) }
#
# WHAT THIS IS NOT.  It does not compare a different netlist: the file read on
# the gate side is the post-DFT netlist itself, and the wrapper only ties the
# DFT controls to their functional-mode values and drops the scan output.  The
# tie-off VALUES are load-bearing and proven so by controls: tying `test` to 1
# instead of 0 leaves 0 of 63 points proven, tying `shift` to 1 leaves 32
# unproven, and a one-gate `nor2_1`→`nand2_1` corruption of the scan netlist
# leaves 1 unproven.  All three FAIL, so the comparison cannot be vacuous.
#
# EVERY NAME HERE IS KNOWN, NOT SNIFFED.  The four tie-off ports and `sout` are
# `fault chain` OPTION names the scan producer passes; the internal prefix is
# MEASURED from the artefact by `fault_scan_chain_insert.measure_internal_prefix`
# and travels in `reports/phase2/dft/scan_chain.json`.  When the prefix cannot
# be measured the wrapper is still emitted WITHOUT it (the DFT ports still have
# to go) and the compared-point count simply drops — recorded in the report as
# `scan_functional_mode.internal_prefix: null`, never silently.

_LEC_WRAP_INST = "_LECWRAP"


def scan_mode_from_meta(meta: Optional[Dict]) -> Optional[Dict]:
    """Normalise `reports/phase2/dft/scan_chain.json` into the wrapper inputs.

    Returns None when the metadata does not describe a published scan netlist —
    an unpublished or failed chain must never trigger functional-mode wrapping,
    because then the gate netlist has no DFT ports and the wrapper would be a
    pure fabrication.  PURE.
    """
    if not isinstance(meta, dict):
        return None
    if not meta.get("published"):
        return None
    tie = meta.get("functional_mode_tieoff")
    sout = meta.get("scan_out_port")
    if not isinstance(tie, dict) or not tie or not isinstance(sout, str):
        return None
    prefix = meta.get("internal_wire_prefix")
    return {
        "tieoff": {str(k): int(v) for k, v in tie.items()},
        "scan_out_port": sout,
        "internal_prefix": prefix if isinstance(prefix, str) and prefix
                           else None,
    }


def build_scan_wrappers(top: str, rtl_ports: List[Tuple[str, str, str]],
                        scan_mode: Dict) -> Tuple[str, str]:
    """(gate_wrapper_verilog, gold_wrapper_verilog).  PURE.

    `rtl_ports` is the gold top's port list as `(direction, range, name)`
    triples — taken from the RTL, so the wrapper's interface IS the RTL's
    interface by construction and cannot drift from it.
    """
    decls = "\n".join(f"  {d} {r}{n};".replace("  ", " ").rstrip()
                      for d, r, n in rtl_ports)
    names = ", ".join(n for _, _, n in rtl_ports)
    conns = ", ".join(f".{n}({n})" for _, _, n in rtl_ports)
    tie = ", ".join(f".{p}(1'b{v})"
                    for p, v in sorted(scan_mode["tieoff"].items()))
    header = (f"/* GENERATED by lec_run.build_scan_wrappers — functional-mode\n"
              f"   comparison of the post-DFT scan netlist.  Do not edit. */\n")
    gate = (f"{header}"
            f"module {top}({names});\n{decls}\n"
            f"  {top}__scan \\{_LEC_WRAP_INST} (\n"
            f"    {conns},\n"
            f"    {tie}, .{scan_mode['scan_out_port']}());\n"
            f"endmodule\n")
    # The gold instance name reproduces the gate's FULL flatten prefix —
    # `<wrapper instance>.<fault-chain prefix>` — as one escaped identifier.
    pref = scan_mode.get("internal_prefix")
    gold_inst = f"{_LEC_WRAP_INST}.{pref}" if pref else _LEC_WRAP_INST
    gold = (f"{header}"
            f"module {top}({names});\n{decls}\n"
            f"  {top}__rtl \\{gold_inst} ({conns});\n"
            f"endmodule\n")
    return gate, gold


#: R-0915-97 — EQUIV_MAKE PAIRS BY NAME, AND A MAPPED MEMORY HAS TWO NAMES.
#:
#: MEASURED, sha256 x sky130A, lane icsha2, run17's own RTL+netlist pair. The
#: gold side runs `memory_map`, which splits each memory into WORDS and names
#: them `\h_reg[0]` .. `\h_reg[7]`, `\w_reg[0]` .. `\w_reg[15]`. The GATE
#: netlist carries the same storage as ONE WIDE VECTOR under the memory's base
#: name -- `wire [255:0] \h_reg[0]` (netlist.v:32063) and
#: `wire [511:0] \w_reg[0]` (:32105). So `h_reg[1..7]` and `w_reg[1..15]` exist
#: on the gold side and NOWHERE on the gate side: 672 bits of state that
#: `equiv_make` leaves unpaired, i.e. FREE and unrelated on the two sides.
#:
#: Nothing downstream of them can ever be proven -- `e_s_reg <= h_reg[4]` is a
#: comparison between a gold word and a gate wire that is not the same signal --
#: and that is exactly the 481 unproven points run17 reported: `dig_reg` 224,
#: `hh/g/f/d/c/b_reg` 32 each, `e_s_reg` 32, `delta_reg` 32, `e_reg` 1. It is
#: NOT a logic difference and NOT induction weakness: four ladder arms
#: (`equiv_struct -icells`, `opt_dff -sat` on both sides, a carry-save
#: cut-point, `-seq 66/80`) each stopped at 501-1000 unproven, and 0
#: counterexamples were ever found.
#:
#: WITH THE WORDS ALIASED the SAME pair proves in 75 s: "Proved 1570 previously
#: unproven $equiv cells ... 2209 are proven and 0 are unproven. Equivalence
#: successfully proven!" -- reproduced in the pinned image on 8HD-6.
#:
#: DERIVED, NEVER A DESIGN LITERAL. The word NAMES come from the gold side's own
#: post-`memory_map` wire list, and the total width from the gate netlist's own
#: declaration; the word width is their quotient. A gate that already carries
#: per-word names gets NOTHING emitted, and a gold word with no gate bits to
#: alias is a FINDING, not a silent skip -- aliasing a word that does not exist
#: would manufacture agreement, which is the one thing this must never do.
_MEM_WORD_RE = re.compile(r"^\\?(?P<base>[A-Za-z_][\w$.]*)\[(?P<idx>\d+)\]$")
_GATE_WIDE_RE = re.compile(
    r"^\s*wire\s*\[\s*(?P<hi>\d+)\s*:\s*0\s*\]\s*\\(?P<name>\S+)\s*;",
    re.M)


def gold_memory_words(select_list_text: str) -> Dict[str, List[int]]:
    """`base -> sorted word indices`, from yosys `select -list w:*` output. PURE.

    A family is only a memory word set when it has TWO OR MORE indices: a
    one-element `x[0]` is an ordinary indexed wire and aliasing it would be a
    rename with no referent.
    """
    fam: Dict[str, List[int]] = {}
    for raw in (select_list_text or "").splitlines():
        tok = raw.strip().split()
        if not tok:
            continue
        name = tok[-1].split("/")[-1]
        m = _MEM_WORD_RE.match(name)
        if m:
            fam.setdefault(m.group("base"), []).append(int(m.group("idx")))
    return {b: sorted(set(v)) for b, v in fam.items() if len(set(v)) > 1}


def gate_wide_vectors(netlist_text: str) -> Dict[str, int]:
    """`\name -> width`, for every wide `wire [hi:0] \name ;` in the gate. PURE."""
    return {m.group("name"): int(m.group("hi")) + 1
            for m in _GATE_WIDE_RE.finditer(netlist_text or "")}


def memory_word_alias_plan(gold_words: Dict[str, List[int]],
                           gate_wide: Dict[str, int]
                           ) -> Tuple[List[Dict[str, object]], List[str]]:
    """`(plan, findings)` — which memories need per-word aliases on the gate. PURE.

    A memory is in the plan only when the gate carries ONE wide vector named
    `<base>[0]` whose width is an exact multiple of the gold word count. Every
    refusal is a FINDING that the caller publishes; none of them is silent.
    """
    plan: List[Dict[str, object]] = []
    findings: List[str] = []
    for base in sorted(gold_words):
        idx = gold_words[base]
        wide_name = f"{base}[0]"
        total = gate_wide.get(wide_name)
        if total is None:
            continue                      # gate already per-word, or no such net
        if any(f"{base}[{k}]" in gate_wide for k in idx[1:]):
            continue                      # gate ALREADY carries per-word names
        if idx != list(range(len(idx))):
            findings.append(
                f"LEC_MEMORY_WORDS_NOT_CONTIGUOUS: gold memory {base!r} has word "
                f"indices {idx}, which are not 0..{len(idx) - 1}; no alias was "
                f"emitted and the unpaired words stay unpaired")
            continue
        if total % len(idx):
            findings.append(
                f"LEC_MEMORY_WIDTH_MISMATCH: gate {wide_name!r} is {total} bits "
                f"and gold splits {base!r} into {len(idx)} words, which does not "
                f"divide; no alias was emitted")
            continue
        width = total // len(idx)
        plan.append({"base": base, "words": len(idx), "width": width,
                     "total": total})
    return plan, findings


def memory_word_alias_tcl(plan: List[Dict[str, object]], top: str = "") -> str:
    """The gate-side alias block for `plan`. PURE; empty string for an empty plan.

    `rename` moves the wide vector out of the way FIRST, so the per-word `x[0]`
    the gold side expects is free to be created; every word is then a slice of
    the renamed vector, so the alias adds no state and can only ever express the
    identity the gate netlist already holds.
    """
    if not plan:
        return ""
    # `rename`/`add -wire`/`connect` name objects INSIDE a module, so the block
    # runs in the module's own scope. Without the `cd` yosys answers
    # "ERROR: Object `\\m[0]' not found!" — measured on the 4x8 fixture.
    out = ["# R-0915-97 — per-word aliases for memories `memory_map` split on "
           "the gold side and the gate carries as one wide vector."]
    if top:
        out.append(f"cd {top}")
    for mem in plan:
        base, n, w = mem["base"], int(mem["words"]), int(mem["width"])
        out.append(f"rename \\{base}[0] \\{base}__lecwide")
        for k in range(n):
            out.append(f"add -wire \\{base}[{k}] {w}")
            out.append(f"connect -set \\{base}[{k}] "
                       f"\\{base}__lecwide[{w * k + w - 1}:{w * k}]")
    if top:
        out.append("cd ..")
    return "\n".join(out) + "\n"


#: R-0915-97(2) — OPT_DFF MOVES A PUBLIC `*_d` NAME OFF THE FLOP'S REAL D.
#:
#: MEASURED on opentitan_aes (lane icaes). Synthesis folds a flop's feedback
#: leaf into an enable and SAYS SO in its own log:
#:     Adding EN signal on ... clean_q ... (D = \clean_d, Q = \clean_q)
#: The PUBLIC `*_d` name is left on the enable-folded mux output -- the netlist
#: literally carries `assign new_d = clean_d` -- and the flop's true D becomes an
#: anonymous net. `equiv_make` pairs by NAME, so gold's `clean_d` is paired
#: against a wire that computes a DIFFERENT function, and no proof can close it:
#: 38/1 unproven as-is, 38/38 proven with those names blacklisted.
#:
#: NOTHING IS WAIVED. The REGISTER (`clean_q`) is compared either way; what is
#: dropped is a comparison between two internal nets that synthesis renamed
#: apart. The blacklist is derived from the synth log of the SAME netlist, so it
#: can only ever name signals this synthesis run itself reported folding, and it
#: never contains a Q name.
_EN_FOLD_RE = re.compile(
    r"Adding (?:EN|SRST|ARST) signal on [^\n]*?\(D = \\(?P<d>[^,)]+),"
    r"\s*Q = \\(?P<q>[^,)]+)\)")


def enable_folded_pairs(log_text):
    """`[{d, q, line}]` for every EN/SRST/ARST fold the synth log reports. PURE."""
    out = []
    for line in (log_text or "").splitlines():
        m = _EN_FOLD_RE.search(line)
        if m:
            out.append({"d": m.group("d").strip(), "q": m.group("q").strip(),
                        "line": line.strip()})
    return out


def blacklist_candidates(log_text, unproven, proven):
    """Pass-2 blacklist: the EVIDENCE-GATED subset. PURE, sorted by name.

    BLANKET BLACKLISTING IS WRONG AND THE FULL DESIGN SAYS SO. MEASURED on
    opentitan_aes: blacklisting ALL 158 folded D names gave 3717 proven / 293
    UNPROVEN against 4025 / 3 for the flow's own script -- removing those pairs
    removed the intermediate CUT POINTS the induction relies on. So a name is a
    candidate only when (a) it is UNPROVEN in pass 1, (b) it is the D of a
    folding line in the SAME netlist's synth log, and (c) that line's Q is among
    pass 1's PROVEN cells. (c) is what makes this evidence rather than a waiver:
    the REGISTER is proven and only the internal net synthesis renamed apart is
    dropped. A `*_d` whose Q is ALSO unproven is a real divergence and stays red.

    Returns the full record per name -- the D, its Q and the synth-log line --
    because the report publishes the evidence, not just the decision.
    """
    un, pr = set(unproven or ()), set(proven or ())
    seen, out = set(), []
    for rec in enable_folded_pairs(log_text):
        if rec["d"] in un and rec["q"] in pr and rec["d"] not in seen:
            seen.add(rec["d"])
            out.append(rec)
    return sorted(out, key=lambda r: r["d"])



#: R-0915-97(3) — A HELPER WITH TESTS IS NOT A FIX UNTIL THE RUNNER RUNS IT.
#: The two derivations below are what turn `memory_word_alias_plan` and
#: `blacklist_candidates` from definitions into behaviour: the first derives
#: gold's post-`memory_map` word set BY RUNNING YOSYS on the gold, the way
#: `paired.ys` did by hand; the second reads pass 1's own unproven list.
_MEM_PROBE_TEE = "lec_gold_mem_words.txt"
#: The probe is `prep + memory_map` on the GOLD alone — seconds, not a proof.
_MEM_PROBE_TIMEOUT_S = 900


def memory_probe_script(gold_read_cmd: str, top: str, tee_path: str) -> str:
    """The pre-pass that asks GOLD what `memory_map` named its words. PURE.

    Identical prologue to the proof's own gold side up to `memory_map`, so the
    word set it reports is the word set the proof will carry, not an
    approximation of it.
    """
    return (f"{gold_read_cmd}\n"
            f"prep -top {top}\n"
            f"memory_map\n"
            f"tee -q -o {tee_path} select -list w:*\n")


def blacklist_second_pass_plan(raw: str, synth_log_text: str
                               ) -> List[Dict[str, str]]:
    """Pass 2's candidate list from pass 1's OWN output. PURE.

    `equiv_status` prints a line per UNPROVEN point and nothing per proven one,
    so "proven" is derived as "the Q of a fold line that is NOT in the unproven
    list". A `*_d` whose Q is also unproven is a real divergence and is never a
    candidate. Empty list means NO second pass at all.
    """
    un = set(unproven_names(raw))
    folds = enable_folded_pairs(synth_log_text)
    proven = {r["q"] for r in folds if r["q"] not in un}
    return blacklist_candidates(synth_log_text, un, proven)


def unproven_names(raw: str) -> List[str]:
    r"""The gold-side names of pass 1's unproven `$equiv` cells. PURE.

    `equiv_status` prints one `Unproven $equiv <cell>: \<x>_gold \<x>_gate`
    line per unproven point and nothing per PROVEN point, so this list is the
    only per-name evidence the tool gives — which is why the caller derives
    "proven" as "compared and NOT in this list".
    """
    out: List[str] = []
    for line in (raw or "").splitlines():
        if "Unproven $equiv" not in line:
            continue
        tok = line.split()
        if len(tok) >= 2 and tok[-2].endswith("_gold"):
            out.append(tok[-2].lstrip("\\")[: -len("_gold")])
    return sorted(set(out))


def build_equiv_script(gold_files: List[str], gate_netlist: str, top: str,
                       liberty: Optional[str],
                       blackbox_v: Optional[List[str]] = None,
                       gate_is_generic: bool = False,
                       gold_frontend: str = "verilog",
                       slang_prefix: str = "",
                       gold_defines: str = "-DSIMULATION -DYOSYS",
                       scan_mode: Optional[Dict] = None,
                       memory_word_aliases: Optional[List[Dict[str, object]]] = None,
                       equiv_blacklist_path: str = "",
                       gate_wrapper_v: str = "",
                       gold_wrapper_v: str = "",
                       fsm_encfile: Optional[str] = None,
                       fsm_preserve_signals: Optional[List[str]] = None,
                       scan_fsm_restore: Optional[Dict] = None,
                       checkpoint_dir: Optional[str] = None,
                       resume_from: Optional[Dict] = None,
                       ladder_rungs: Optional[int] = None) -> str:
    """Build the Yosys RTL(gold)≡synth-netlist(gate) equiv script.

    `checkpoint_dir` — emit an RTLIL CHECKPOINT after every ladder rung, into
    that directory, each followed by a `log` sentinel that attests the write
    finished. With `checkpoint_dir=None` AND `resume_from=None` the emitted
    text is BYTE-IDENTICAL to the recipe before checkpoints existed, which is
    what makes the no-checkpoint path a control rather than a claim.

    `resume_from` — a validated checkpoint record from
    `select_resume_checkpoint`. The whole front half (both source reads,
    `equiv_make`, `equiv_struct`) is REPLACED by a `read_rtlil` of that
    checkpoint, and only the rungs AFTER it are emitted. The two read-only
    observables the parser depends on are preserved deliberately: `stat` (the
    miter cell histogram `miter_is_stateless` reads) and the closing
    `equiv_status`. A leading `equiv_status` is added so the resumed run's own
    log STATES the position it resumed at instead of the caller remembering it.

    v1.3.85 — APPROACH C (satgen-modelable BOTH sides). Step-13 compares an RTL
    gold against a Liberty-mapped synth gate — two DIFFERENT cell vocabularies,
    so `equiv_simple` cannot structural-match and EVERY point falls to the
    `equiv_induct` SAT engine. The prior recipes handed those points a Liberty
    cell the SAT engine cannot model:
      * `read_liberty -lib <lib>` (the delegated post-layout gate==gate recipe)
        imports the cells as BLACKBOXES with no logic → satgen aborts
        "ERROR: No SAT model available for cell _197__gate (NAND2D1)".
      * `-icells` + flatten aborted `hierarchy` on the Liberty-blackbox flop.
    The fix: on the GATE side read the Liberty WITHOUT `-lib` and with
    `-ignore_miss_func`, which EXPANDS every combinational cell's `function`
    and every `ff`/`latch` group into Yosys internal primitives
    (`NAND2D1` → `$_AND_`+`$_NOT_`; `DFFHQD1` → `$_DFF_P_`), then `flatten`
    inlines them so the netlist is pure `$_`-primitive logic the SAT engine CAN
    model. The GOLD stays RTL (coarse `$`-cells, already satgen-modelable).
    `-ignore_miss_func` degrades HONESTLY: a cell with no `function` (e.g. a
    clock-gating latch `TLATNCAD*`) stays a blackbox, and if the design uses one
    `equiv_induct` still emits "No SAT model …" → SKIPPED-CONDITION, never a
    fake pass.  Measured on a commercial-PDK spm: 65/65 $equiv cells proven, 0 unproven,
    "Equivalence successfully proven!"; a one-gate NAND2D1→NOR2D1 corruption of
    the netlist leaves 2 unproven → the gate FAILs (false-clean-PROOF). The
    induction escalates 4→16→64 frames so a pipelined design proves at the depth
    matching its latency (spm needs frame 2). chip-/PDK-AGNOSTIC.

    `liberty` may be None (a generic `$_`-primitive netlist needs no Liberty; it
    is already satgen-modelable). `blackbox_v` — PDK physical-only cell Verilog
    (fill/tap/decap) read `-lib` so those inert cells become empty blackboxes;
    empty for a pre-PnR synth netlist (those cells are inserted later).

    `gate_is_generic=True` — the gate is a pre-techmap Yosys netlist whose cells
    are escaped internal primitives (`\\$_DFF_P_`, `\\$_NAND_`, …). Read it with
    `read_verilog -icells` and NO Liberty: `-icells` re-binds those escaped names
    to real internal cells so `hierarchy -check` RESOLVES them (a plain
    `read_verilog` treats `\\$_DFF_P_` as an undefined user module and ABORTS
    before `equiv_make` → 0 $equiv points → a false compared_points=0 FAIL). The
    resulting `$_`-primitive gate is already satgen-modelable, so equiv proceeds
    normally. chip/PDK-AGNOSTIC — no Liberty vocabulary is involved.

    #155 — a `memory_map` PASS runs on EACH side after `prep` / `hierarchy`
    (which have already run `proc; memory_collect`, so any memory is a packed
    `$mem`/`$mem_v2` cell) and BEFORE `flatten`, legalizing the memory to
    flops + address-decode gates that equiv_induct's satgen CAN model. Without
    it a memory-bearing gold aborts `equiv_induct` with `No SAT model available
    for cell … ($mem_v2)` → an honest SKIPPED-CONDITION that never actually
    compared the design. This is plain stock-yosys 1042b3f55 (no fork flag, no
    capability probe — the `memory_map` command has shipped for years). ORDER
    IS LOAD-BEARING: it must run PRE-flatten (a `memory_map` placed AFTER
    `flatten`/`splitnets` leaves every $equiv point unproven — verified 0/8 vs
    136/0 in-container), and each side must legalize its own module BEFORE
    `equiv_make` merges them. NO-LEAK: on a design with NO memory `memory_map`
    is a no-op, so a non-memory LEC verdict is byte-unchanged; a memory-bearing
    EQUIVALENT design now PROVES ("Equivalence successfully proven!"), and a
    broken one stays unproven → FAIL (sound negative)."""
    from lec_observable_cone import observable_matchpoint_names
    _observable_names = observable_matchpoint_names(top)
    gold_read = " ".join(gold_files)
    bb = "".join(f"read_verilog -lib {q}\n" for q in (blackbox_v or []))
    # Empty except on the Liberty-expanded gate (see LIBERTY_PIN_ATTR).
    hide_cell_pins = ""
    if gate_is_generic:
        # Pre-techmap `$_`-primitive gate: -icells re-binds the escaped names so
        # `hierarchy -check` resolves them (no Liberty; already satgen-modelable).
        gate_read = f"{bb}read_verilog -icells {gate_netlist}\n"
    elif liberty:
        # Expand Liberty cells to $_ primitives (functions + ff/latch groups),
        # skipping any cell with no function (stays blackbox → honest SAT gap).
        # The gold is stashed at this point, so the design is EMPTY and every
        # wire `w:*` selects belongs to a Liberty cell module; `flatten` copies
        # the tag onto each wire it creates from one, and those wires are then
        # hidden. See LIBERTY_PIN_ATTR for why.
        gate_read = (f"read_liberty -ignore_miss_func {liberty}\n"
                     f"setattr -set {LIBERTY_PIN_ATTR} 1 w:*\n"
                     f"{bb}read_verilog {gate_netlist}\n")
        hide_cell_pins = f"rename -hide a:{LIBERTY_PIN_ATTR}\n"
    else:
        gate_read = f"{bb}read_verilog -sv {gate_netlist}\n"
    # GOLD frontend: default is yosys's built-in `read_verilog -sv` (SV subset).
    # On a real SV CPU/SoC gold (package-scope refs like `pkg::`, unpacked-array
    # ports) that reader parse-ABORTS → 0 miter → a FALSE FAIL. `gold_frontend=
    # "slang"` reads the gold with `read_slang` — the SAME full SV-2017 frontend
    # the synth step auto-falls-back to (synth_frontend.decide_synth_frontend) —
    # so a design that SYNTHESISES cleanly is also LEC-comparable. On a non-fork
    # image `read_slang` needs `plugin -i slang` first (slang_prefix carries it);
    # the vibeic-eda fork ships it built-in (slang_prefix == "").
    # The slang read must MIRROR the synth invocation's DEFINE SET, not just
    # read_slang alone (rv-aes): synth reads `-DSIMULATION -DYOSYS` primary and
    # retries `-DSYNTHESIS -DYOSYS` when a sim-only construct ($urandom /
    # std::randomize / $value$plusargs in a dead `ifdef SIMULATION arm) breaks
    # the build. `gold_defines` carries whichever set main() is on, so the gold
    # elaborates the same arm synth built the gate from (else the miter aborts
    # on $urandom). Default is the synth PRIMARY set; main() flips it to
    # -DSYNTHESIS on the same sim-only-construct signature synth uses.
    if gold_frontend == "slang":
        _plugin_line = ("plugin -i slang\n"
                        if "plugin" in (slang_prefix or "") else "")
        # --single-unit: read ALL gold files as ONE compilation unit, so a
        # macro defined in an early file is visible to every later file. This
        # MIRRORS the shared preprocessor scope of the successive
        # `read_verilog` calls synth uses. Without it slang makes each CLI file
        # its own unit, and a design whose modules rely on a cross-file
        # `` `define `` (the ordinary Verilog header idiom) aborts with
        # "unknown macro or compiler directive" — a read abort, hence 0
        # compared points. `_resolve_gold_files` guarantees the macro headers
        # are concatenated first, which single-unit reads REQUIRE.
        gold_read_cmd = (f"{_plugin_line}read_slang --single-unit {gold_read} "
                         f"--top {top} {gold_defines}")
    else:
        gold_read_cmd = f"read_verilog -sv {gold_read}"
    # FUNCTIONAL-MODE WRAPPING (scan netlists only).  Both halves are emitted
    # together or not at all: a gold wrapper without a gate wrapper would
    # compare the RTL against nothing, and a gate wrapper without a gold one
    # would leave the prefixes unmirrored.  When `scan_mode` is None every
    # string below is empty and the script is BYTE-IDENTICAL to the pre-change
    # one — a non-scan design's verdict cannot move.
    gold_rename = gold_wrap_read = ""
    gate_rename = gate_wrap_read = ""
    if scan_mode and gate_wrapper_v and gold_wrapper_v:
        gold_rename = f"rename {top} {top}__rtl\n"
        gold_wrap_read = f"read_verilog -sv {gold_wrapper_v}\n"
        gate_rename = f"rename {top} {top}__scan\n"
        gate_wrap_read = f"read_verilog -sv {gate_wrapper_v}\n"
    # RESUME FIRST, and deliberately BEFORE the FSM-encoding block below: a
    # resumed run does not BUILD a miter, it reads one back, so nothing the
    # encfile path sets up applies to it. Keeping this return above that block
    # leaves BOTH paths byte-identical to what each was before this rebase.
    if resume_from is not None:
        # RESUME. The proven-marking is carried IN the RTLIL (yosys rewires a
        # proven $equiv cell's \\B to its \\A), so reading the checkpoint back
        # restores the proof position itself — not a note about it.
        return (
            f"read_rtlil {shlex.quote(str(resume_from['il_path']))}\n"
            # `stat` is the observable `miter_is_stateless` reads; without it a
            # resumed run's parse would differ from a from-zero run's for a
            # reason that has nothing to do with the design.
            f"stat\n"
            # SAY WHERE WE RESUMED, in the run's own log.
            f"equiv_status\n"
            + _emit_ladder(checkpoint_dir,
                           start_index=int(resume_from["rung_index"]) + 1,
                           rungs=ladder_rungs)
            + "equiv_status\n"
        )

    # FSM RE-ENCODING (#2050) — `synth` runs `fsm`, whose `fsm_recode` pass
    # RE-ASSIGNS the state encoding of every FSM it extracts. The gate then
    # holds the SAME state register under the SAME hierarchical name with a
    # DIFFERENT code and usually a DIFFERENT WIDTH (measured on opentitan_aes:
    # 19 of 19 extracted FSMs recoded to one-hot; e.g. a 3-bit sparse
    # `...u_prim_alert_sender.state_q` became a 7-bit one-hot register).
    # `equiv_make` matches key points BY NAME and has its own guard for this:
    # it SKIPS a signal whose gold and gate widths differ (equiv_make.cc,
    # `if (... gold_wire->width != gate_wire->width) continue;`).
    #
    # `splitnets -ports` DEFEATS that guard. Contrary to what its name
    # suggests, `-ports` means "internal signals AND ports" (internal-only is
    # the default), so it bit-blasts the state register on BOTH sides FIRST.
    # equiv_make then no longer sees one 3-bit wire against one 7-bit wire; it
    # sees `state_q[0..2]` on each side and matches them POSITIONALLY. Those
    # pairs are not the same signal. Forcing them equal makes the miter's
    # key-point set INCONSISTENT, and `equiv_induct`'s base case — which asks
    # whether ALL unproven key points CAN be simultaneously equal for k
    # consecutive cycles — goes UNSAT and prints `Circuit inherently
    # diverges!`. One poisoned pair aborts the induction for the WHOLE design:
    # measured on opentitan_aes, 3242 points across every block were left
    # unproven by 3 recoded registers in one alert sender.
    #
    # The remedy is yosys's own, and it needs BOTH ends: `synth -encfile <f>`
    # (passed to `fsm_recode` via `fsm`) WRITES the old->new encoding table,
    # and `equiv_make -encfile <f>` READS it and builds the encoder/decoder
    # that matches the two encodings correctly. MEASURED: adding `-encfile` to
    # synth leaves the netlist BYTE-IDENTICAL (same sha256 on opentitan_aes and
    # on the fsmtop reproducer) — it only records the translation.
    #
    # The encfile is keyed on WHOLE signal names. Keep those words intact;
    # other vectors may need splitting to match scalarized scan data wires.
    # Missing/unsupported encoding metadata retains the old unsplit recipe.
    #
    # NO-LEAK: with `fsm_encfile=None` — every caller until the synth step
    # starts writing one — both strings below are the pre-change literals and
    # the script is BYTE-IDENTICAL, so no design's verdict can move.
    # #2209: scan insertion can spell every data vector as escaped scalar
    # wires. Suppressing ALL splitting then loses the data correspondences.
    # Preserve the encoding table's FSM words, including hierarchical copies,
    # while normalizing the remaining names on BOTH sides. Unknown encoding
    # metadata keeps #2050's conservative unsplit behavior.
    _splitnets = _equiv_splitnets(fsm_encfile, fsm_preserve_signals)
    _encopt = f" -encfile {fsm_encfile}" if fsm_encfile else ""
    # R-0915-97(2) — names `opt_dff` moved off the flop's real D. Appended, not
    # substituted: a design with no enable folding gets no option at all and its
    # emitted script is byte-identical to today's.
    _blopt = f" -blacklist {equiv_blacklist_path}" if equiv_blacklist_path else ""
    # R-0915-97 — the gate-side per-word memory aliases, same shape and same
    # seam as the scan-FSM restore below: `add -wire` + `connect`, emitted into
    # the gate design before `design -stash gate`. Empty when the caller found
    # nothing to alias, so a design with no mapped memory is byte-unchanged.
    _mem_alias = memory_word_alias_tcl(list(memory_word_aliases or []), top)
    _restore_words = _mem_alias
    if scan_fsm_restore:
        _encopt = f" -encfile {scan_fsm_restore['encoding_path']}"
        _restore_words += ("# scan FSM encoding sha256: "
                           + scan_fsm_restore["encoding_sha256"] + "\n")
        for name, bits in sorted(scan_fsm_restore["aliases"].items()):
            _restore_words += f"add -wire \\{name} {len(bits)}\n"
            # connect uses SigSpec's comma-list grammar, not Verilog braces.
            vector = ",".join("\\" + bit for bit in reversed(bits))
            _restore_words += f"connect -nomap -nounset -set \\{name} {vector}\n"
    return (
        # --- gold = RTL, kept as generic satgen-modelable Yosys cells ---
        f"{gold_read_cmd}\n"
        # Scan functional-mode only: rename the RTL top out of the way and read
        # the wrapper that re-declares `{top}` with the RTL's own port list, so
        # `prep -top {top}` elaborates the wrapper and `flatten` stamps the
        # gate's prefix onto every gold wire.  Empty otherwise.
        f"{gold_rename}"
        f"{gold_wrap_read}"
        f"prep -top {top}\n"
        # #155: legalize any $mem/$mem_v2 (packed by prep's memory_collect) to
        # flops+decode BEFORE flatten so equiv_induct's satgen can model it;
        # PRE-flatten placement is load-bearing (0/8 vs 136/0). No-op when the
        # design has no memory. Plain stock-yosys command — no fork flag/probe.
        f"memory_map\n"
        f"flatten\n"
        # ASYNC-FF LEGALIZATION: an async-reset/-set FF (SV `always @(posedge clk
        # or negedge rst_n)`) maps to `$_DFF_PN0_`/`$_DFFSR_*`, which
        # equiv_induct's SAT engine cannot model — it aborts "No SAT model
        # available for async FF cell … ($_DFF_PN0_). Consider running
        # `async2sync` or `clk2fflogic` first." (observed on ibex, rv-ibex2).
        # async2sync converts the async control into synchronous D-input logic the
        # SAT engine CAN model. Applied UNIFORMLY on BOTH sides and AFTER flatten,
        # regardless of which frontend read the gold — so the read_slang gold-read
        # retry path (SV-package designs like ibex, which are exactly the async-
        # reset CPUs) is covered too. SOUND: it is an identical modeling transform
        # on gold and gate, so an equivalent design stays equivalent and a real
        # reset-behaviour difference still surfaces as unproven. No-op on a design
        # with no async FF (spm 65/65 unchanged). Verified in-container: an
        # async-reset DFF pair stops at the async-FF SAT abort WITHOUT this and
        # proves "4/4, Equivalence successfully proven!" WITH it.
        f"async2sync\n"
        f"opt_clean\n"
        f"{_splitnets}"
        f"{_observable_names}"
        f"design -stash gold\n"
        # --- gate = synth netlist; Liberty cells EXPANDED to $_ logic then
        #     flattened in so the SAT engine can model every point ---
        f"{gate_read}"
        # Scan functional-mode only: rename the scan netlist's top out of the
        # way and read the wrapper that ties `shift`/`test`/`sin`/`tck` to their
        # functional-mode values and leaves `sout` dangling, so the gate's port
        # set matches the gold's and `equiv_make` does not abort.  Empty
        # otherwise.
        f"{gate_rename}"
        f"{gate_wrap_read}"
        f"hierarchy -check -top {top}\n"
        # #155: same memory legalization on the gate side, in case the gate
        # netlist still carries a $mem*/$mem_v2 cell (no-op otherwise).
        f"memory_map\n"
        f"flatten\n"
        f"{hide_cell_pins}"
        f"async2sync\n"   # async-FF legalization (see the gold side) — both sides
        f"opt_clean\n"
        f"{_restore_words}"
        f"{_splitnets}"
        f"{_observable_names}"
        f"design -stash gate\n"
        f"design -copy-from gold -as gold {top}\n"
        f"design -copy-from gate -as gate {top}\n"
        f"equiv_make{_encopt}{_blopt} gold gate {_MITER_MODULE}\n"
        f"hierarchy -top {_MITER_MODULE}\n"
        # READ-ONLY report pass. It prints the miter's cell histogram, which is
        # the OBSERVABLE `miter_is_stateless` reads to decide whether temporal
        # induction could have had anything to unroll. Without it the parser
        # has to guess, and the guess it used to make was "assume a flat
        # induction wall explains this", which turned every combinational
        # mismatch into a non-blocking INCONCLUSIVE. `stat` mutates no design
        # and costs no solver time.
        # THE SHARED PROOF TAIL. `stat`, the SAT-free `equiv_struct`
        # pre-reduction, the rung ladder and the closing `equiv_status` are
        # emitted by `equiv_proof_tail` — the ONE function every LEC path in
        # this plugin (pre-layout here, post-layout in
        # `lec_post_layout_check.build_yosys_equiv_script`) derives its SAT
        # strategy from. It returns exactly the lines this call site used to
        # spell inline, so the pre-layout script is byte-identical.
        + equiv_proof_tail(checkpoint_dir=checkpoint_dir, start_index=0,
                           rungs=ladder_rungs)
    )


# ---------------------------------------------------------------------------
# THE ONE PROOF TAIL, SHARED BY EVERY LEC PATH (vibe-ic#2151)
# ---------------------------------------------------------------------------
# WHY THIS FUNCTION EXISTS. Until v1.18.98 this plugin ran TWO LEC recipes:
# `build_equiv_script` above (pre-layout, RTL vs synth netlist) and a SECOND,
# INDEPENDENT copy in `lec_post_layout_check.build_yosys_equiv_script`
# (post-layout, reference netlist vs routed netlist). The v1.18.0 LEC-recipe
# fix — `stat` + the SAT-free `equiv_struct` pre-reduction ahead of any SAT
# spend, and the `equiv_simple -short` first rung — landed in THIS file only.
# The post-layout copy kept the pre-v1.18.0 strategy (`equiv_simple` straight
# into `equiv_induct -seq 4/16/64`), so the fix never reached the step that
# proves the ROUTED netlist. MEASURED on the sha256 post-route netlist
# (8HD-8, rbsha2's own run): the post-layout first pass spent 43289.65 s —
# 99% of it in 3x `equiv_induct`, 17.7 GB peak — to arrive at 134 unproven,
# because every structurally-identical cone was handed to the SAT engine
# instead of being collapsed by `equiv_struct` first.
#
# WHAT IT GUARANTEES. One function emits the strategy, so a future rung, a
# future pre-reduction or a future budget marker cannot land on one path and
# miss the other. `test_lec_one_recipe.py` pins that both builders derive
# from this function and that the pre-layout text did not move.
#
# `seq_depths=None` -> the shipped `LEC_LADDER` verbatim (the pre-layout
# caller). The explicit default depth list uses that same recipe. A custom
# ascending depth list retains short/full simple followed by one induction
# per requested depth; that is the post-layout caller's
# already-documented `--seq-depths` knob, and with its default (4, 16, 64) the
# emitted text is IDENTICAL to the ladder. Deeper induction is sound (it only
# proves more), so a caller-chosen depth cannot weaken the proof.
def equiv_proof_tail(seq_depths: Optional[List[int]] = None, *,
                     checkpoint_dir: Optional[str] = None,
                     start_index: int = 0,
                     rungs: Optional[int] = None,
                     induction: bool = True) -> str:
    """The SAT strategy every LEC path shares: `stat`, `equiv_struct`, the
    rung ladder, `equiv_status`.

    Returns the exact lines `build_equiv_script` used to spell inline, which
    is what makes this a shared definition rather than a re-implementation.
    """
    if not induction:
        # THE SCREEN (vibe-ic#2151). Rung 0 only: the SAT-free structural
        # pre-reduction plus the cheap cone proof, and NO induction. It is not
        # a verdict — `equiv_induct` is where a sequentially-equivalent design
        # is proven — it is the cheapest complete enumeration of the points
        # that survive `equiv_simple`, which is the input the pin-permutation
        # classifier needs. Nothing downstream may treat a screen's UNPROVEN
        # as an answer about the design.
        if checkpoint_dir is not None:
            raise ValueError("equiv_proof_tail: a screen writes no checkpoint")
        if rungs is not None:
            raise ValueError("equiv_proof_tail: a screen has no rung ladder "
                             "to bound")
        commands = dict(LEC_LADDER)
        ladder = (commands["equiv_simple_short"]
                  + commands["equiv_simple_full"])
    elif seq_depths is None:
        ladder = _emit_ladder(checkpoint_dir, start_index=start_index,
                              rungs=rungs)
    else:
        # Ascending, de-duplicated, positive — each rung only re-attempts the
        # cells still unproven, so shallow-first keeps the common case cheap.
        depths = sorted({int(d) for d in seq_depths if int(d) > 0})
        if rungs is not None:
            # `rungs` indexes LEC_LADDER, which a caller-chosen depth list is
            # not. Refusing loudly beats silently bounding the wrong ladder.
            raise ValueError("equiv_proof_tail: rungs is supported only for "
                             "the shipped ladder (seq_depths=None)")
        if checkpoint_dir is not None:
            # Checkpoints are keyed on LEC_LADDER's rung NAMES; a caller-chosen
            # depth has no name in that vocabulary. Refusing loudly beats
            # writing a checkpoint no resume could ever select.
            raise ValueError("equiv_proof_tail: checkpoint_dir is supported "
                             "only for the shipped ladder (seq_depths=None)")
        commands = dict(LEC_LADDER)
        simple = (commands["equiv_simple_short"]
                  + commands["equiv_simple_full"])
        # The explicit default used by post-layout is the same recipe. A
        # custom depth list retains its requested schedule; it must not gain
        # an unrequested depth-16 attempt.
        ladder = ("".join(command for _, command in LEC_LADDER)
                  if depths == [4, 16, 64] else simple + "".join(
                      f"equiv_induct -seq {d}\n" for d in depths))
        if not depths:
            ladder = simple + "equiv_induct\n"
    return (
        # READ-ONLY report pass. It prints the miter's cell histogram, which is
        # the OBSERVABLE `miter_is_stateless` reads to decide whether temporal
        # induction could have had anything to unroll. Without it the parser
        # has to guess, and the guess it used to make was "assume a flat
        # induction wall explains this", which turned every combinational
        # mismatch into a non-blocking INCONCLUSIVE. `stat` mutates no design
        # and costs no solver time.
        "stat\n"
        # SAT-FREE structural pre-reduction BEFORE any SAT is spent.
        # equiv_struct merges the $equiv key-points whose driving cones are
        # structurally identical across gold and gate (the majority of a
        # name-mapped miter) by structural hashing alone — no solver call. This
        # is SOUND: it only collapses provably-identical structure, so it can
        # NEVER launder a real mismatch into a proof (a genuinely different
        # cone survives to equiv_simple/equiv_induct below). Without it,
        # equiv_simple SAT-hammers EVERY key-point including the trivially
        # identical ones, so a large design (measured: a 31 850-point AES
        # miter) exhausts the wall clock mid-equiv_simple and yields a false
        # INCONCLUSIVE. equiv_struct AUGMENTS, never REPLACES, the SAT stages
        # that follow — it only shrinks the set they must decide (measured
        # 31 850 -> 3 333, a 10x cut). This is the same pre-pass yosys's own
        # `equiv_opt` runs. chip/PDK-AGNOSTIC.
        "equiv_struct\n"
        # Cheap bounded cone proof first. This can discharge local points
        # quickly, but is never treated as a complete result: every survivor
        # still flows into the full simple pass and the induction ladder.
        # Soundness therefore remains exactly the full recipe's.
        + ladder
        + "equiv_status\n"
    )


def _emit_ladder(checkpoint_dir: Optional[str], start_index: int,
                 rungs: Optional[int] = None) -> str:
    """The rungs from `start_index` on, each followed by its checkpoint.

    With `checkpoint_dir` None this returns exactly the five command lines the
    recipe has always ended with, so the no-checkpoint script is a control and
    not a re-implementation of one.

    `rungs` — emit AT MOST this many rungs (vibe-ic#2194). None means "every
    rung from `start_index` to the top", which is what every caller before
    #2194 asked for and what the un-checkpointed control still asks for, so
    that text does not move. `rungs=1` is what the per-rung driver uses: ONE
    rung per yosys PROCESS, so the ladder's peak memory bounds by its WORST
    SINGLE RUNG instead of accumulating all four in one address space.
    """
    out = []
    stop = (len(LEC_LADDER) if rungs is None
            else min(len(LEC_LADDER), max(0, start_index) + max(0, int(rungs))))
    for idx in range(max(0, start_index), stop):
        rung, commands = LEC_LADDER[idx]
        out.append(commands)
        if checkpoint_dir:
            # `.part` first, PROMOTED by the host only for the rungs the
            # sentinel below attests. A write killed halfway therefore leaves a
            # `.part` nobody will ever read, never a truncated `<rung>.il` a
            # later run would try to resume from.
            out.append("write_rtlil "
                       + shlex.quote(str(Path(checkpoint_dir)
                                         / (rung + ".il.part"))) + "\n")
            # A yosys `log` command: it prints its argument verbatim at
            # column 0 AFTER the backend pass above has returned.
            out.append("log " + LEC_CHECKPOINT_SENTINEL + " "
                       + Path(checkpoint_dir).name + ":" + rung + "\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# WHICH RESOURCE ACTUALLY RAN OUT (vibe-ic#2182)
# ---------------------------------------------------------------------------
# THE DEFECT THIS EXISTS TO PREVENT, measured 2026-09-07 on opentitan_aes:
#
#     lec_equivalence_check.json   exhausted_resource: "wall_clock_seconds"
#     docker inspect …             State.OOMKilled = true
#     /sys/fs/cgroup/memory.events oom_kill 1   (memory.max = 51539607552)
#
# The proof was KILLED FOR MEMORY at a 48 GiB cgroup limit, and the step
# reported that it had run out of TIME. `exhausted_resource` was assigned the
# literal "wall_clock_seconds" whenever the ADMISSION budget was spent, and
# never asked what stopped the process. Every reader of that field — human or
# machine — is sent to the wrong repair: raise the budget, which cannot help a
# proof that never reached a deadline, and which this repo has already ruled is
# not a fix (#2177). The label cost a whole lane its framing.
#
# rc=137 CANNOT settle it on its own: `_CONTAINER_TIMEOUT_RCS` folds GNU
# `timeout`'s `--kill-after` SIGKILL escalation and a cgroup OOM kill into the
# same number, and the code says so itself. So ASK THE MEMORY CONTROLLER. The
# kernel keeps an exact count of OOM kills per cgroup; sampling it either side
# of an attempt turns "it was killed, we don't know why" into a measurement,
# and when the counter cannot be read the honest answer is NOT_MEASURED with
# the reason named — never a default, and never the old literal.
EXHAUSTED_WALL_CLOCK = "wall_clock_seconds"
EXHAUSTED_MEMORY = "memory_bytes"
EXHAUSTED_NOT_MEASURED = "not_measured"

# cgroup v2 first (what this fleet runs), then the v1 layout. Both are plain
# reads of a kernel-maintained counter -- no tool, no parsing of tool output.
_OOM_PROBE_CMD = (
    "cat /sys/fs/cgroup/memory.events 2>/dev/null "
    "|| cat /sys/fs/cgroup/memory/memory.oom_control 2>/dev/null")
_MEMORY_MAX_PROBE_CMD = (
    "cat /sys/fs/cgroup/memory.max 2>/dev/null "
    "|| cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null")
_OOM_KILL_RE = re.compile(r"^oom_kill\s+(\d+)\s*$", re.M)


def parse_oom_kill_count(text: str) -> Optional[int]:
    """The `oom_kill` counter out of a cgroup `memory.events` / `oom_control`.

    None when the text carries no such line — which is "could not read it",
    not "it was zero". PURE.
    """
    m = _OOM_KILL_RE.search(text or "")
    return int(m.group(1)) if m else None


def parse_memory_max_bytes(text: str) -> Optional[int]:
    """The cgroup memory ceiling in bytes, or None for `max` / unreadable.

    cgroup v2 writes the literal `max` when there is NO limit, and v1 writes a
    sentinel so large it means the same thing. Both become None: a ceiling that
    does not exist cannot be the resource that ran out. PURE.
    """
    t = (text or "").strip().split("\n")[0].strip()
    if not t or t == "max":
        return None
    try:
        v = int(t)
    except ValueError:
        return None
    # v1's "no limit" sentinel is PAGE_COUNTER_MAX * PAGE_SIZE; anything within
    # a factor of a machine's addressable memory of that is not a real cap.
    return v if 0 < v < (1 << 62) else None


def probe_cgroup_memory(container: str, exec_raw=None) -> Dict:
    """Sample the container cgroup's OOM counter and ceiling.

    Returns ``{"oom_kills": int|None, "memory_max_bytes": int|None}``. A probe
    that cannot run leaves BOTH None, which the classifier reads as
    NOT_MEASURED rather than as an absence of OOM.
    """
    runner = exec_raw or _docker_exec_raw
    out: Dict[str, Optional[int]] = {"oom_kills": None,
                                     "memory_max_bytes": None}
    try:
        rc, so, _ = runner(container, _OOM_PROBE_CMD, 30)
        if rc == 0:
            out["oom_kills"] = parse_oom_kill_count(so)
        rc, so, _ = runner(container, _MEMORY_MAX_PROBE_CMD, 30)
        if rc == 0:
            out["memory_max_bytes"] = parse_memory_max_bytes(so)
    except Exception:                                   # noqa: BLE001
        # A probe is EVIDENCE-GATHERING, never a gate. If it explodes the run
        # still has a verdict to publish; it simply says NOT_MEASURED.
        pass
    return out


def classify_exhausted_resource(*, budget_exhausted: bool, stopped: bool,
                                returncode: Optional[int] = None,
                                oom_kill_delta: Optional[int] = None,
                                memory_max_bytes: Optional[int] = None
                                ) -> Tuple[Optional[str], str]:
    """Name the resource that ACTUALLY ran out, and the evidence for it. PURE.

    Order is deliberate: what KILLED the process outranks what the admission
    budget did, because a proof that was killed never reached the deadline.
    """
    if oom_kill_delta is not None and oom_kill_delta > 0:
        cap = (f", cgroup memory.max = {memory_max_bytes} bytes"
               if memory_max_bytes else ", cgroup had no memory ceiling set")
        return (EXHAUSTED_MEMORY,
                f"the container cgroup's oom_kill counter rose by "
                f"{oom_kill_delta} during this attempt{cap}")
    # Admission exhaustion prevents another attempt; it did not stop this one.
    if not stopped:
        return (None, "")
    if returncode == 124:
        # GNU `timeout`'s SIGTERM expiry is unambiguous: the clock ended it.
        return (EXHAUSTED_WALL_CLOCK,
                "the container-side backstop expired (rc=124, SIGTERM)")
    if returncode == 137:
        if oom_kill_delta == 0:
            return (EXHAUSTED_WALL_CLOCK,
                    "rc=137 (SIGKILL) with the cgroup oom_kill counter "
                    "UNCHANGED, so the kill came from the container-side "
                    "backstop's --kill-after escalation and not from the "
                    "memory controller")
        return (EXHAUSTED_NOT_MEASURED,
                "rc=137 (SIGKILL) is the container-side backstop's "
                "--kill-after escalation AND a cgroup OOM kill; the cgroup "
                "oom_kill counter could not be read, so which resource ran "
                "out was not measured")
    if stopped:
        return (EXHAUSTED_NOT_MEASURED,
                f"this attempt was stopped (rc={returncode}) and no probe "
                "identified the resource")
    return (None, "")


# ---------------------------------------------------------------------------
# STEP WALL BUDGET — measured ONCE, from the FIRST attempt, across ALL retries.
# ---------------------------------------------------------------------------
# THE DEFECT THIS EXISTS TO PREVENT (measured 2026-08-27 on the VerilogEval-Human
# sweep `_vehuman_clean156`, problem `Prob030_popcount255` — a 255-bit popcount
# whose `equiv_induct` is combinatorially explosive):
#
#   Every attempt used to be handed the SAME constant `args.timeout`. The gold
#   read ground for the full 7195s budget, was killed, and the slang gold-read
#   retry started the SAME problem over with a FRESH full 7195s. A deadline that
#   a retry re-arms is not a deadline: the real bound was `timeout x attempts`
#   (three straight-line attempts x 7200s = SIX HOURS against a nominal "7200s
#   budget"), and NOTHING measured total elapsed. A 156-problem sweep whose
#   MEDIAN problem takes ~30s sat on ONE problem for 131 minutes with a 0-byte
#   dispatch log — from outside, indistinguishable from a sweep making progress.
#
# THE RULE: the budget is a DEADLINE, established before the first attempt. Each
# attempt gets what is LEFT of it, never a fresh copy. When nothing meaningful
# is left the next attempt is NOT LAUNCHED, and the step records how many
# attempts it made and how long they took — so an exhausted proof is visibly
# different from a finished one.
#
# Injectable clock so the ceiling is testable without spending it.
_MIN_ATTEMPT_BUDGET_S = 30


class StepBudget:
    """TOTAL wall-clock budget for one LEC step, shared by every attempt.

    `next_attempt_budget()` returns the REMAINING seconds, or 0 once less than
    `floor_s` is left. 0 means "do not launch" — never "launch with no limit".
    A retry can only ever SHRINK what is left, so the total time this step can
    consume is bounded by `total_s` no matter how many attempts the retry logic
    decides to make.
    """

    def __init__(self, total_s: int, floor_s: int = _MIN_ATTEMPT_BUDGET_S,
                 clock=time.monotonic) -> None:
        self.total_s = int(total_s)
        self.floor_s = int(floor_s)
        self._clock = clock
        self._t0 = clock()
        self.attempts: List[Dict] = []

    def elapsed_s(self) -> float:
        return self._clock() - self._t0

    def remaining_s(self) -> int:
        return int(round(self.total_s - self.elapsed_s()))

    def next_attempt_budget(self) -> int:
        """Seconds the NEXT attempt may run. 0 = the step budget is spent.

        The FIRST attempt always receives the whole budget. The floor exists to
        refuse a POINTLESS RETRY on a nearly-spent budget; it must never turn a
        small operator-configured `--timeout` into "do not run at all", which
        would convert a tight budget into a step that produces no evidence.
        """
        left = self.remaining_s()
        if not self.attempts:
            return max(left, 1)
        return left if left >= self.floor_s else 0

    def exhausted(self) -> bool:
        return self.next_attempt_budget() == 0

    def record(self, frontend: str, defines: str, budget_s: int,
               elapsed_s: float, launched: bool, timed_out: bool,
               kill_cause: Optional[Dict] = None) -> None:
        """Record an attempt that WAS launched.

        `kill_cause` — what `run_yosys_equiv` OBSERVED about this attempt's
        ending (#2182): its return code and the cgroup OOM-counter delta across
        it. Absent on every caller predating the probe, in which case the
        classifier says NOT_MEASURED for an ambiguous rc rather than guessing.
        """
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "gold_frontend": frontend,
            "gold_defines": defines,
            "budget_sec": budget_s,
            "elapsed_sec": round(elapsed_s, 2),
            "launched": launched,
            "killed_by_budget": timed_out,
            "kill_cause": dict(kill_cause) if kill_cause else None,
        })

    def skipped(self, frontend: str, defines: str, why: str) -> None:
        """Record a retry the budget REFUSED to launch."""
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "gold_frontend": frontend,
            "gold_defines": defines,
            "budget_sec": 0,
            "elapsed_sec": 0.0,
            "launched": False,
            "killed_by_budget": False,
            "not_launched_reason": why,
        })

    def count_launched(self) -> int:
        return sum(1 for a in self.attempts if a["launched"])


def annotate_step_budget(report: Dict, budget: "StepBudget", *,
                         stopped: Optional[bool] = None,
                         ladder_complete: Optional[bool] = None) -> Dict:
    """Record WHAT was attempted, WHICH resource ran out, and HOW MANY attempts
    were made onto the verdict the parser already produced.

    `stopped` — was THIS run cut off by one of this producer's own stop markers
    (`_TIMEOUT_MARKER` / `_STALL_MARKER`)? That, and NOT the verdict word, is
    what separates "the clock ended it" from "it finished and decided". When it
    is None the attempt record's `killed_by_budget` is used, which is what
    every caller predating this parameter effectively asked for.

    ADDITIVE ONLY — it never touches `verdict` or `equivalent`. A budget-killed
    proof already classifies as a DISCLOSED non-PASS (`SKIPPED-CONDITION`, or
    `INCONCLUSIVE` on the zero-completed-comparison path); neither is a PASS and
    neither is a FAIL, which is the honest outcome for a proof that did not
    finish. What was MISSING was the EVIDENCE of how much was spent and how
    often it was retried — the absence that made a re-armed deadline look
    exactly like progress from outside.
    """
    launched = [a for a in budget.attempts if a["launched"]]
    report["lec_attempts"] = len(launched)
    report["lec_attempts_detail"] = list(budget.attempts)
    report["step_budget_sec"] = budget.total_s
    report["step_elapsed_sec"] = round(budget.elapsed_s(), 2)
    report["step_budget_exhausted"] = budget.exhausted()
    # WHICH RESOURCE ACTUALLY RAN OUT (#2182). This used to be the literal
    # "wall_clock_seconds" whenever the admission budget was spent, which
    # reported TIME for a proof the kernel had killed for MEMORY. It is now
    # derived from what the attempt's own ending was observed to be, and says
    # `not_measured` -- with the reason -- when nothing could settle it.
    _stopped_now = (
        bool(stopped) if stopped is not None
        else any(a.get("killed_by_budget") for a in budget.attempts
                 if a.get("launched")))
    _cause = next((a.get("kill_cause") for a in reversed(budget.attempts)
                   if a.get("launched") and a.get("kill_cause")), None) or {}
    _resource, _evidence = classify_exhausted_resource(
        budget_exhausted=budget.exhausted(),
        stopped=_stopped_now,
        returncode=_cause.get("returncode"),
        oom_kill_delta=_cause.get("oom_kill_delta"),
        memory_max_bytes=_cause.get("memory_max_bytes"))
    report["exhausted_resource"] = _resource
    report["exhausted_resource_evidence"] = _evidence or None
    # A legacy killed_by_budget flag records a stop, not its cause: the old
    # timeout return-code set also includes OOM/SIGKILL. Without kill_cause,
    # keep the classifier's NOT_MEASURED rather than inventing clock evidence.
    # THE FIELD THAT SAYS WHICH OF THE TWO IT WAS. `step_budget_exhausted`
    # answers "is the ADMISSION budget spent" and stays exactly what it was --
    # true of a proof that legitimately ran long and then DECIDED as much as of
    # one the clock cut off. A machine reader had no field that separated them,
    # which is how a completed, engine-limited proof was consumed as a timeout.
    report["step_budget_stopped_this_proof"] = (
        bool(stopped) if stopped is not None
        else any(a.get("killed_by_budget") for a in budget.attempts
                 if a.get("launched")))
    if budget.exhausted():
        # THE BUDGET NO LONGER STOPS A RUNNING PROOF, so "exhausted" no longer
        # implies "produced nothing". It governs ATTEMPT ADMISSION: past the
        # deadline no FURTHER attempt is launched. A proof that legitimately ran
        # long and then DECIDED is the case this branch could not previously
        # reach, and appending "neither proven equivalent nor proven different"
        # to a PASS would be a contradiction inside one report -- introduced by
        # the very change that made the long run possible.
        #
        # The machine-readable fields above are unchanged and still true (the
        # budget IS spent). Only the sentence splits, and only on whether the
        # producer actually reached a verdict.
        # WHICH TEST DECIDES THIS, and why it is not the verdict word.
        #
        # MEASURED (opentitan_aes x sky130A with the ceiling removed, and
        # reproduced on 8HD-9 on a 9-point miter with a 1s ADMISSION budget):
        # the proof ran to completion through `equiv_induct -seq 64` -- rc 0,
        # `killed_by_budget: false`, a closing `equiv_status`, 830 of 4072
        # points proven, ZERO counterexamples, cause "SAT base case could not
        # be established" -- and lec.json still said
        #
        #     "no attempt reached a verdict. The resource that ran out is
        #      WALL-CLOCK TIME ... Raise --timeout"
        #
        # because the branch keyed on `verdict in ("PASS", "FAIL")`.
        # INCONCLUSIVE is a DECIDED state -- it is the third of the three, and
        # it is the one nearly every large sequential design lands on -- so the
        # test excluded exactly the population it most needed to describe, and
        # told its readers to buy time that could not have helped: raising
        # --timeout cannot establish a base case the engine says diverges.
        #
        # A run that WAS stopped still gets the clock sentence, because for
        # that run it is TRUE. The observable is this producer's OWN stop
        # marker, never the verdict word.
        _stopped = (bool(stopped) if stopped is not None
                    else any(a.get("killed_by_budget") for a in launched))
        _decided = not _stopped
        if _decided and ladder_complete is False:
            report["verdict_explanation"] = (
                (report.get("verdict_explanation") or "").rstrip()
                + " STEP BUDGET: a later proof rung was not admitted after "
                  "the admission budget was spent. The completed rung and "
                  "its checkpoint retain partial proof evidence; the ladder "
                  "did not finish. No running attempt was killed. Resume "
                  "from the verified checkpoint with a justified strategy; "
                  "this is not evidence that the full engine ladder failed.")
        elif _decided:
            _tail = (
                f" STEP BUDGET: the {budget.total_s}s admission budget was "
                f"spent ({len(launched)} attempt(s), "
                f"{report['step_elapsed_sec']}s elapsed), so no FURTHER "
                "attempt would have been launched. It did not stop this one "
                "-- the budget bounds attempts, not runtime -- and the "
                "verdict above is the proof's own.")
            # NAME THE COUNTS AND WHOSE LIMIT IT WAS, but only on positive
            # evidence that a miter was built and a status was reached: a
            # frontend abort is also "not stopped", and claiming a ladder ran
            # for it would be the same class of unearned sentence in the other
            # direction.
            _miter = report.get("miter_points")
            _proven = report.get("compared_points")
            _unproven = report.get("unproven_points")
            if (str(report.get("verdict", "")).strip().upper()
                    not in ("PASS", "FAIL")
                    and isinstance(_miter, int) and _miter > 0
                    and isinstance(_proven, int) and isinstance(_unproven, int)
                    and (_proven + _unproven) > 0):
                _tail += (
                    f" This run REACHED its {report.get('verdict')} on the "
                    f"tool's own evidence -- the ladder ran to a closing "
                    f"equiv_status over {_miter} point(s): {_proven} proven, "
                    f"{_unproven} unproven, "
                    f"{report.get('non_equivalent_points')} counterexample(s). "
                    "The limit it hit is the ENGINE's, named in the verdict "
                    "above; WALL-CLOCK TIME is not the resource that ran out "
                    "and raising --timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S cannot "
                    "move it.")
            report["verdict_explanation"] = (
                (report.get("verdict_explanation") or "").rstrip() + _tail)
        else:
            report["verdict_explanation"] = (
                (report.get("verdict_explanation") or "").rstrip()
                + f" STEP BUDGET: exhausted the TOTAL {budget.total_s}s "
                  f"admission budget for this step after {len(launched)} "
                  f"attempt(s), {report['step_elapsed_sec']}s elapsed, and no "
                  "attempt reached a verdict. The resource that ran out is "
                  "WALL-CLOCK TIME, not equivalence evidence: the designs are "
                  "neither proven equivalent nor proven different. Raise "
                  "--timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S, or close the "
                  "remainder with sign-off LEC.")
    return report


def run_yosys_equiv(container: str, ys_path_in_container: str,
                    timeout: int = DEFAULT_YOSYS_TIMEOUT_S,
                    workdir: Optional[str] = None, *,
                    live_log_path: Optional[Path] = None,
                    telemetry_path: Optional[Path] = None,
                    telemetry_context: Optional[Dict] = None,
                    kill_cause: Optional[Dict] = None,
                    abort_probe=None):
    """Run `yosys -s <ys>` in the container. Returns (launched, raw_output).

    `abort_probe` — the rung's own convergence predicate
    (`rung_projection_abort_probe`), handed to the supervisor. An abort is
    recorded on the step-budget stop path (`_TIMEOUT_MARKER`, read as a
    disclosed no-verdict with the proof state reached), with its reason.

    `kill_cause` — an OUT parameter (#2182). When a dict is passed it is filled
    with what this attempt's ending was OBSERVED to be: the return code, and
    the container cgroup's `oom_kill` counter sampled BEFORE and AFTER, so a
    memory kill can be told apart from the wall-clock backstop that shares its
    rc. A delta, not an absolute, because the counter is cumulative over the
    container's whole life and other jobs share it. Nothing here can change the
    verdict; it only lets the report name the right resource.

    launched=False means Docker/Yosys could not run at all (the caller then
    returns 1 for a disclosed-skip). launched=True means Yosys emitted output
    (any outcome), which the parser then classifies.

    `workdir` runs the gold+gate read from a chosen directory. This is the
    plugin's own `cwd=design_dir` rule (the one `benchmark_score_cwd_guard.py`
    enforces for testbench runs) applied to the LEC read, and it is REQUIRED
    for correctness rather than convenience: a design's memory-initialisation
    and include references (`$readmemh`/`$readmemb`/`` `include ``) are
    ORDINARILY written as RELATIVE paths, and the synthesis that produced the
    gate netlist resolved them because it ran beside the resources the runner
    staged for it. Reading the gold from a DIFFERENT directory makes those same
    relative paths unresolvable, which aborts the gold elaboration and yields a
    zero-point miter — reported downstream as a non-equivalence verdict about a
    design that was never compared. Passing None preserves the previous
    behaviour exactly."""
    cmd = f"yosys -s {shlex.quote(ys_path_in_container)} 2>&1"
    if live_log_path is not None:
        # pipefail preserves Yosys's status while tee makes the proof visible
        # during long quiet-ish passes. The path is per invocation, so two LEC
        # jobs never append into one another's evidence.
        cmd = ("set -o pipefail; " + cmd + " | tee -a "
               + shlex.quote(str(Path(live_log_path).resolve())))
    if workdir:
        cmd = f"cd {shlex.quote(workdir)} && " + cmd
    # R-0915-48 — the opt-in backstop, armed ONLY when asked for. See
    # `_env_lec_hard_bound_s` for why this is not the default and must not
    # become one.
    _hard_bound_s = _env_lec_hard_bound_s()
    if _hard_bound_s is not None and _dw_mod() is not None:
        cmd = _dw_mod().wrap_with_container_timeout(cmd, _hard_bound_s)
        _note_bound = (f"[lec_run] equiv proof carries an OPT-IN container "
                       f"backstop at {_hard_bound_s}s "
                       f"(VIBEIC_LEC_YOSYS_TIMEOUT_S)")
    else:
        _note_bound = ("[lec_run] equiv proof is UNBOUNDED: "
                       "VIBEIC_LEC_YOSYS_TIMEOUT_S is unset, so this leg runs "
                       "to completion however long it takes, which is the "
                       "2026-09-06 behaviour and not an oversight")
    print(_note_bound, file=sys.stderr)
    # BEFORE-sample. Taken even when the attempt goes on to succeed: a probe
    # that only runs on failure cannot produce a delta, and a delta is the only
    # form of this counter that says anything about THIS attempt.
    _mem_before = (probe_cgroup_memory(container)
                   if kill_cause is not None else
                   {"oom_kills": None, "memory_max_bytes": None})
    if kill_cause is not None:
        kill_cause.update(oom_kills_before=_mem_before["oom_kills"],
                          memory_max_bytes=_mem_before["memory_max_bytes"],
                          oom_kill_delta=None, returncode=None)

    def _sample_after(rc: Optional[int]) -> None:
        if kill_cause is None:
            return
        kill_cause["returncode"] = rc
        after = probe_cgroup_memory(container)
        kill_cause["oom_kills_after"] = after["oom_kills"]
        if after["memory_max_bytes"] is not None:
            kill_cause["memory_max_bytes"] = after["memory_max_bytes"]
        before = _mem_before["oom_kills"]
        # BOTH ends must have been read for a delta to mean anything. "Could
        # not read it" is not "it was zero".
        kill_cause["oom_kill_delta"] = (
            after["oom_kills"] - before
            if after["oom_kills"] is not None and before is not None else None)

    try:
        _extra = {}
        if live_log_path is not None or telemetry_path is not None:
            _extra.update(log_path=live_log_path,
                          telemetry_path=telemetry_path,
                          telemetry_context=telemetry_context)
        if abort_probe is not None:
            _extra["abort_probe"] = abort_probe
        r = _docker(
            container, cmd, timeout=timeout,
            # Present in `yosys -s <path>` and therefore usable during the
            # tiny pre-stamp race; after the stamp lands, supervision is by
            # exact (pid, /proc starttime) identity and its descendants.
            marker=ys_path_in_container, **_extra)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        # The HOST deadline fired: unambiguously the clock, and recorded as
        # such so the classifier never has to fall back to NOT_MEASURED here.
        _sample_after(124)
        return (bool(_strip_login_banner(out).strip()),
                _strip_login_banner(out)
                + f"\n{_TIMEOUT_MARKER} after {timeout}s")
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"[lec_run] ERROR: could not exec yosys: {exc}"

    _sample_after(getattr(r, "returncode", None))
    out = _strip_login_banner(r.stdout or "")
    # Launched iff we saw genuine Yosys output (banner or an equiv/error line);
    # a docker-daemon / no-such-container failure yields no Yosys banner.
    launched = ("Yosys" in out or "$equiv" in out
                or "No SAT model" in out or "ERROR:" in out)
    # CONTAINER-side budget kill (path (2), see _CONTAINER_TIMEOUT_RCS): the
    # `timeout` _docker wraps the call in fires before the host deadline, so we
    # arrive here NORMALLY with GNU-`timeout`'s exit code instead of via
    # subprocess.TimeoutExpired above. Re-attach the SAME marker the host path
    # writes, so the parser's budget-exhaustion branch (INCONCLUSIVE /
    # SKIPPED-CONDITION) fires instead of misreading a killed-mid-proof run as a
    # hard FAIL. This is a no-verdict signal ONLY: a COMPLETED miter (proven /
    # unproven parsed) or a recorded counterexample never reaches that branch —
    # both keep their real FAIL — so this can neither fabricate a PASS nor hide a
    # real mismatch (proven on opentitan_aes × sky130A and covered by the tests).
    if launched and getattr(r, "returncode", 0) in _CONTAINER_TIMEOUT_RCS:
        # THE DURATION WAS NEVER MEASURED, so it is no longer stated. `timeout`
        # is the step's ATTEMPT-ADMISSION budget and no kind of deadline, so
        # "after {timeout}s" would name a wall this run did not hit. And rc 137
        # is AMBIGUOUS by construction -- the comment on
        # `_CONTAINER_TIMEOUT_RCS` says so itself: it is GNU `timeout`'s SIGKILL
        # escalation AND a container OOM-kill. An OOM at ten minutes used to be
        # recorded as "exceeded its time budget after 7200s"; with the ceiling
        # back at the pathological backstop the same sentence would read
        # 86400s, which is the same lie with a bigger number.
        #
        # The MARKER itself is kept verbatim: `_TIMEOUT_RE`,
        # `_EXECUTION_STOP_RE` and `budget_kill_blocks_frontend_retry` key on
        # it, and renaming it is a separate change with its own blast radius.
        # Only the fabricated duration goes, replaced by the observable rc.
        out = out.rstrip("\n") + (
            "\n" + _TIMEOUT_MARKER
            + f" (rc={getattr(r, 'returncode', 0)}: the container-side "
            f"backstop, or an OOM kill -- rc 137 does not distinguish them). "
            f"No equivalence verdict was reached. The {timeout}s step budget "
            f"governs ATTEMPT ADMISSION, not runtime, so no wall-clock "
            f"duration is claimed here.")
    elif launched and getattr(r, "returncode", 0) == _RC_ABORTED:
        # THE RUNG'S OWN EVIDENCE ENDED IT (`rung_projection_abort_probe`): it
        # was deciding points, at a rate that cannot finish inside the step
        # budget. Recorded on the budget-stop path, never as a result.
        _why = next((ln.split("WATCHDOG_ABORTED:", 1)[1].strip()
                     for ln in (getattr(r, "stderr", "") or "").splitlines()
                     if "WATCHDOG_ABORTED:" in ln),
                    "the rung's convergence predicate stopped it")
        out = out.rstrip("\n") + (
            "\n" + _TIMEOUT_MARKER + f" (projected, not elapsed): {_why}")
    elif launched and getattr(r, "returncode", 0) in _PROGRESS_STALL_RCS:
        # SAY HOW FAR IT GOT. "It stopped making forward progress" is a claim a
        # reader cannot size without the proof's own count -- a job stopped at 0
        # points and one stopped at 1374 of 1760 are different findings and the
        # remedy differs too. Read from THIS run's log, so it is a measurement
        # and not a default; absent when the log carries no count yet.
        _pts = lec_proved_points_from_output(out)
        out = out.rstrip("\n") + f"\n{_STALL_MARKER}" + (
            f" — last measured position: {_pts.get('proved')} proved"
            + (f", {_pts.get('unproven')} still unproven" 
               if _pts.get("unproven") is not None else "")
            if _pts else " — no proved-point count had been emitted yet")
    return launched, out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# Corner preference when several Liberty files exist: the TYPICAL/NOMINAL
# corner carries the functional cell models used for equivalence. We only pick
# WHICH existing Liberty to read — we never guess a cell model.
_LIB_CORNER_RANK = ("typ", "_tt_", "tt_", "typical", "nom", "_nn_", "nn_")


def _discover_project_liberty(project: Path) -> Optional[Path]:
    """Find the design's OWN PDK Liberty inside the project tree (PURE).

    The Step-13 runner passes no --liberty, so without this the producer falls
    back to the sky130 DEFAULT_LIBERTY — useless for a commercial-PDK design
    whose cells (e.g. commercial-PDK NAND2D1 / DFFHQD1) are only SAT-modelable from ITS
    own Liberty. Searches the canonical Vibe-IC PDK location
    (`input/pdk/liberty/*.lib`) first, then a bounded `input/**.lib` fallback,
    and prefers the typical/nominal corner. Returns None if the project ships no
    Liberty (the caller then keeps the CLI/default). Filesystem-only — no
    container, no design-specific assumption."""
    candidates: List[Path] = []
    prime = project / "input" / "pdk" / "liberty"
    if prime.is_dir():
        candidates = sorted(prime.glob("*.lib"))
    if not candidates:
        inp = project / "input"
        if inp.is_dir():
            candidates = sorted(inp.rglob("*.lib"))
    if not candidates:
        return None

    def _rank(p: Path) -> int:
        name = p.name.lower()
        for i, tag in enumerate(_LIB_CORNER_RANK):
            if tag in name:
                return i
        return len(_LIB_CORNER_RANK)

    candidates.sort(key=lambda p: (_rank(p), str(p)))
    return candidates[0]


# The Liberty a mapping tool RECORDS having loaded. `read_liberty <path>` is
# OpenSTA/Yosys script syntax and `-liberty <path>` is the yosys `abc`/`dfflibmap`
# flag; both are TOOL syntax, not a design, PDK or vendor literal. Whatever path
# the run happened to record is the path that comes back.
_LIBERTY_IN_EVIDENCE_RE = re.compile(
    r"(?:read_liberty|-liberty)[ \t=]+(/\S+?\.lib)\b")

# Where a run records the mapping it performed, in the order a Step-13 caller
# can rely on them existing. Kept to the synthesis stage: the netlist under test
# is the one synthesis produced, so the library synthesis mapped it against is
# the only one an equivalence check may legitimately read.
_SYNTH_EVIDENCE_RELS = (
    "phase2/stage2/synth",
    "phase2/stage1/synth",
    "reports/phase2/synth",
)


def _discover_run_liberty(project: Path) -> Optional[str]:
    """The Liberty THIS RUN's own synthesis loaded, read off its own evidence.

    WHY THIS EXISTS, MEASURED. `_discover_project_liberty` searches the PROJECT
    for a staged Liberty. That is the right answer for a design that VENDORS its
    PDK under `input/pdk/`. It returns None for a design whose PDK is MOUNTED in
    the container — which is this flow's normal shape — and the caller then fell
    back to the sky130 `DEFAULT_LIBERTY` on a design that is not sky130. Yosys
    then cannot resolve the gate netlist's cells, `hierarchy -check` aborts
    before `equiv_make`, and the run records INCONCLUSIVE over ZERO compared
    points while blaming an unstaged hard macro. The cell was never a macro; it
    was an ordinary standard cell, defined in the Liberty the run itself used.

    Correct BY CONSTRUCTION rather than by preference: a gate netlist is only
    meaningful against the library it was MAPPED to, and the run says which that
    was. No PDK name, no corner name, no vendor string is consulted — the
    returned path is whatever the run recorded.

    PURE and filesystem-only: no container, no network. Returns None when the
    run recorded nothing, so the caller's existing order is unchanged."""
    for rel in _SYNTH_EVIDENCE_RELS:
        d = project / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.log")) + sorted(d.glob("*.ys")) \
                + sorted(d.glob("*.tcl")) + sorted(d.glob("*.json")):
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            hits = _LIBERTY_IN_EVIDENCE_RE.findall(text)
            if hits:
                # Last write wins: a script that reads several corners maps
                # against the one it mapped with last.
                return hits[-1]
    return None


def _bound_synthesis_liberty(project: Path) -> Optional[str]:
    """Map the current tool handoff's selected cell library through its mounts.

    The handoff already binds the declared PDK, current RTL/netlist and resolved
    configuration. Its hashed PDK-root record names the host bytes behind the
    tool's guest path; no legacy log search or PDK/corner guess participates.
    """
    import synth_handoff_netlist_check as handoff
    import librelane_contract as LC
    from pdk_revision_resolve import Fs

    bound = handoff.bound_handoff(project)
    if bound is None:
        return None
    try:
        if bound['verdict'] != 'PASS':
            raise ValueError('; '.join(bound['findings']))
        binding = json.loads((project / 'phase2/stage2/synth/synth_inputs.json').read_text())['librelane_synthesis']
        folder = project / binding['folder']
        cfg = json.loads((folder / 'config.json').read_text())
        receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
        root_path = folder / 'pdk_root.json'
        if receipt['sha256'].get('pdk_root.json') != LC.digest(root_path):
            raise ValueError('synthesis PDK mounts changed or were not recorded')
        roots = json.loads(root_path.read_text())
        guest_root = Path(roots['cli_pdk_root'])
        if not guest_root.is_absolute() or str(guest_root) != cfg['PDK_ROOT']:
            raise ValueError('synthesis PDK root disagrees with resolved config')
        # CELL_LIBS is LibreLane's resolved production field; LIB remains
        # supported for existing step configurations that retain that name.
        groups = cfg.get('CELL_LIBS', cfg.get('LIB'))
        if not isinstance(groups, dict) or not groups:
            raise ValueError('current synthesis declares no cell library')
        libraries = set()
        for values in groups.values():
            if not isinstance(values, list) or not values or any(
                    not isinstance(v, str) or not v for v in values):
                raise ValueError('current synthesis cell-library paths are malformed')
            libraries.update(values)
        if len(libraries) != 1:
            raise ValueError('current synthesis cell library is ambiguous')
        library = Path(next(iter(libraries)))
        pdk, _ = LC.phase2_pdk(project, selected=cfg.get('PDK'))
        pdk_guest = guest_root / pdk
        if not library.is_absolute() or '..' in library.parts:
            raise ValueError('cell library path is not absolute or contains traversal')
        mounts = [(Path(host), Path(guest)) for host, guest in roots['mounts_under_it']]
        for host, guest in mounts:
            if not host.is_absolute() or not guest.is_absolute():
                raise ValueError('synthesis PDK mount is not absolute')
        fs = Fs(None)
        def mapped_path(path):
            candidates = []
            for host, guest in mounts:
                if not path.is_relative_to(guest):
                    continue
                resolved = fs.realpath(str(host / path.relative_to(guest)))
                if not resolved:
                    raise ValueError('selected synthesis PDK path is missing')
                target = Path(resolved)
                if not target.is_relative_to(host.resolve()):
                    raise ValueError('selected synthesis PDK path escapes its mount')
                candidates.append(target)
            if len(candidates) != 1:
                raise ValueError('selected synthesis PDK path has missing or ambiguous mounts')
            return candidates[0]
        selected = mapped_path(pdk_guest)
        target = mapped_path(library)
        if not selected.is_dir() or not target.is_file():
            raise ValueError('selected synthesis PDK or cell library is missing')
        if not target.is_relative_to(selected):
            raise ValueError('cell library is outside the resolved selected PDK')
        recorded = receipt['input']['config_files'].get(str(library))
        current = LC.config_file_hashes({'cell_library': str(library)}, mounts)
        if not recorded or current.get(str(library)) != recorded:
            raise ValueError('selected synthesis cell library hash is missing or changed')
        return str(target)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, LC.Refusal) as exc:
        raise ValueError(f'LL_LEC_LIB_UNBOUND: {exc}') from exc


def resolve_liberty(project: Path, cli_liberty: Optional[str],
                    container_has) -> "Tuple[Optional[str], str]":
    """`(liberty, source)` — the Liberty this LEC will read, and WHY (PURE).

    DEGRADE LOUDLY: the source is returned, recorded in `reports/lec.json` as
    `liberty_source`, and printed, so a reader never has to infer which of four
    paths produced the library a verdict was computed over.

        cli          the caller passed --liberty and it is visible
        staged       the design vendored one under input/pdk/
        run_synth    the run's own synthesis recorded loading it
        default      the built-in constant, which belongs to ONE PDK and is
                     therefore wrong for every other one

    A current LibreLane handoff owns the mapping and refuses conflicting or
    invisible choices. Without that contract, the existing cli > staged >
    recorded synthesis > default order remains. `container_has` is a predicate
    so visibility remains testable without a container."""
    bound_liberty = _bound_synthesis_liberty(project)
    if bound_liberty is not None:
        if cli_liberty and cli_liberty != DEFAULT_LIBERTY and Path(cli_liberty).resolve() != Path(bound_liberty):
            raise ValueError('LL_LEC_LIB_CONFLICT: --liberty differs from current synthesis mapping')
        if not container_has(bound_liberty):
            raise ValueError('LL_LEC_LIB_INVISIBLE: selected synthesis library is not visible to the proof tool')
        return bound_liberty, 'run_synth'
    if cli_liberty and cli_liberty != DEFAULT_LIBERTY and container_has(cli_liberty):
        return cli_liberty, "cli"
    staged = _discover_project_liberty(project)
    if staged is not None and (cli_liberty == DEFAULT_LIBERTY
                               or not cli_liberty
                               or not container_has(cli_liberty)):
        return str(staged), "staged"
    if cli_liberty and cli_liberty != DEFAULT_LIBERTY:
        return cli_liberty, "cli"
    from_run = _discover_run_liberty(project)
    # A recorded path that is not VISIBLE where yosys will run is not an answer.
    # Without this guard, a run whose synthesis evidence names a library the
    # container cannot open would end up with no Liberty at all, where today it
    # would at least have had the constant — a corner this fix must not make
    # worse. Checked here so the caller's existing "not found in-container" WARN
    # keeps meaning what it meant.
    if from_run is not None and container_has(from_run):
        return from_run, "run_synth"
    return cli_liberty, "default"


def _resolve_gold_files(gold_dir: Path) -> List[str]:
    """The .v/.sv gold sources to read, as absolute paths.

    Alphabetically sorted, then TWO chip-AGNOSTIC corrections that make the
    gold read match what phase-2 synth already does (see `_rtl_include_hub`):

    1. INCLUDE-HUB AGGREGATORS ARE DROPPED. A file that `` `include ``s a
       sibling which is ALSO staged standalone defines every included module
       twice, so the read ABORTS and the miter is built from 0 points. Phase-2
       synth's selector has excluded these since #614; the gold read did not,
       so a design that SYNTHESISED cleanly could still produce a zero-point
       LEC. (That zero-point run is already reported honestly as INCONCLUSIVE
       by #192's stage-progress observable rather than a false
       NOT_EQUIVALENT — this change is what turns the honest non-result into
       an actual comparison.)

    2. PURE MACRO HEADERS ARE MOVED FIRST, because the slang gold read is a
       SINGLE compilation unit (`--single-unit`) that concatenates the files in
       CLI order. Alphabetical order resolves cross-file `` `define ``s only by
       luck of filename.

    Both are no-ops on a gold dir with no aggregator and no macro header."""
    if not gold_dir.is_dir():
        return []
    files = sorted(
        p for p in gold_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".v", ".sv"))
    files = _macro_headers_first(_drop_include_hubs(files))
    return [str(p.resolve()) for p in files]


_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_]\w*)")


# The wrappers' interface is taken from the SCAN NETLIST's own module header,
# minus the DFT ports — never re-parsed out of the RTL.  Two reasons:
#   * the netlist header is generated Verilog-2005 (`module m(a, b); input a;
#     output [3:0] b;`), which parses unambiguously, whereas the RTL may be
#     ANSI or non-ANSI SystemVerilog with parameters and typedefs;
#   * `fault chain` only ADDS ports, so "scan netlist ports minus the DFT
#     ports" IS the RTL's port list.  If it ever were not, `equiv_make` aborts
#     loudly on the mismatch — the failure mode is a visible error, not a
#     quietly wrong comparison.
_NL_MODULE_HDR_RE = re.compile(
    r"^\s*module\s+(?P<name>\\?[\w$]+)\s*\((?P<ports>[^)]*)\)\s*;",
    re.M)
_NL_PORT_DECL_RE = re.compile(
    r"^\s*(?P<dir>input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?"
    r"(?P<range>\[[^\]]*\]\s*)?(?P<name>\\?[\w$]+)\s*;",
    re.M)


def netlist_top_ports(netlist_text: str, top: str,
                      exclude: Optional[List[str]] = None
                      ) -> List[Tuple[str, str, str]]:
    """`[(direction, range_or_empty, name)]` for module `top`, in header order.

    `exclude` drops named ports (the DFT ports) from the result.  Returns []
    when the module header cannot be found — the caller must then NOT wrap,
    rather than wrap against a guessed interface.  PURE.
    """
    drop = set(exclude or ())
    body = None
    for m in _NL_MODULE_HDR_RE.finditer(netlist_text or ""):
        if m.group("name").lstrip("\\") == top:
            body = (m.group("ports"), netlist_text[m.end():])
            break
    if body is None:
        return []
    order = [p.strip().lstrip("\\") for p in body[0].split(",") if p.strip()]
    decls: Dict[str, Tuple[str, str]] = {}
    for d in _NL_PORT_DECL_RE.finditer(body[1]):
        nm = d.group("name").lstrip("\\")
        if nm in decls:
            continue
        decls[nm] = (d.group("dir"), (d.group("range") or "").strip())
    out: List[Tuple[str, str, str]] = []
    for nm in order:
        if nm in drop or nm not in decls:
            continue
        direction, rng = decls[nm]
        out.append((direction, f"{rng} " if rng else "", nm))
    return out


def _gold_modules(gold_files: List[str]) -> "tuple[set, set]":
    """(declared_modules, instantiated_module_names) across the gold RTL.

    A module is a ROOT if it is declared but never instantiated by another —
    the natural top. Instantiation is detected conservatively as
    `D [#(...)] <inst> (`, which a `module D (` declaration never matches."""
    decls: set = set()
    parts: List[str] = []
    for f in gold_files:
        try:
            t = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        parts.append(t)
        decls.update(_MODULE_DECL_RE.findall(t))
    corpus = "\n".join(parts)
    insts: set = set()
    for d in decls:
        if re.search(r"(?<![\w.])" + re.escape(d)
                     + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(", corpus):
            insts.add(d)
    return decls, insts


_MODULE_BODY_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)\b(.*?)\bendmodule\b",
                             re.S)


def _gold_child_map(gold_files: List[str], decls: set) -> "dict":
    """{module: set(modules it instantiates)} across the gold RTL.

    Same conservative instantiation shape `_gold_modules` uses, but scoped to
    each module BODY so the hierarchy — not just the flat instantiated set —
    is available."""
    children: dict = {}
    for f in gold_files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _MODULE_BODY_RE.finditer(text):
            name, body = m.group(1), m.group(2)
            kids = children.setdefault(name, set())
            for d in decls:
                if d == name:
                    continue
                if re.search(r"(?<![\w.])" + re.escape(d)
                             + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(",
                             body):
                    kids.add(d)
    return children


def _descendants(children: dict, root: str) -> set:
    """Every module reachable BELOW `root` in the gold hierarchy."""
    seen: set = set()
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _gate_modules(gate_netlist: Optional[str]) -> "tuple[set, set]":
    """(declared_modules, instantiated_module_names) in the GATE netlist.

    The exact mirror of `_gold_modules` for the other side of the comparison.
    An equivalence miter needs the top to exist on BOTH sides; a gate netlist
    is usually flattened to a single root, so its declared set is small and
    decisive."""
    if not gate_netlist:
        return set(), set()
    try:
        text = Path(gate_netlist).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set(), set()
    decls: set = set(_MODULE_DECL_RE.findall(text))
    insts: set = set()
    for d in decls:
        if re.search(r"(?<![\w.])" + re.escape(d)
                     + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(", text):
            insts.add(d)
    return decls, insts


def _top_is_comparable(gold_files: List[str], gate_netlist: Optional[str],
                       top: str) -> bool:
    """Is `top` declared on BOTH sides, so a miter can actually be built?

    This is the PROPERTY the top guard exists to defend. A side whose module
    set cannot be read at all (empty) is not evidence of absence and does not
    veto — only a side that demonstrably declares other modules does."""
    gold_decls, _ = _gold_modules(gold_files)
    gate_decls, _ = _gate_modules(gate_netlist)
    if gold_decls and top not in gold_decls:
        return False
    if gate_decls and top not in gate_decls:
        return False
    return True


def _resolve_gold_top(gold_files: List[str], top: str,
                      gate_netlist: Optional[str] = None) -> "tuple[str, str]":
    """Ensure the LEC top is a module that actually exists on BOTH sides.

    A wrong top (e.g. the default 'chip_top' on a standalone 'spm' design) makes
    Yosys build 0 $equiv cells → a MISLEADING 'may genuinely differ' FAIL that
    proved nothing. If `top` is not declared, auto-correct to the sole ROOT
    module; if the choice is ambiguous, return top unchanged with a diagnostic
    note so the caller can emit an honest 'top not found' verdict instead of a
    fake mismatch. Returns (resolved_top, note).

    THE GATE SIDE COUNTS TOO. Checking only the gold made "the top exists in
    the RTL" a PROXY for the property above, and the two come apart on any
    design whose RTL declares more than one root — e.g. an RTL set carrying
    both an ASIC top and a board/FPGA top, where synthesis builds the gate from
    one of them. The gold then declares the caller's top, this guard passes it
    through, and `hierarchy -check -top <top>` aborts on a gate netlist that
    has no such module: zero compared points, reported as a verdict about the
    design. A gate netlist we cannot read yields an empty set and vetoes
    nothing, so a design that resolves today cannot be moved by this."""
    decls, insts = _gold_modules(gold_files)
    resolved, note = top, ""
    if decls and top not in decls:
        roots = sorted(m for m in decls if m not in insts)
        if len(roots) != 1:
            return top, (f"gold top '{top}' not found in RTL modules "
                         f"{sorted(decls)[:8]} and no unique root — cannot "
                         "select a top")
        resolved = roots[0]
        note = (f"gold top '{top}' not found in RTL; auto-corrected to sole "
                f"root module '{roots[0]}'")

    gate_decls, gate_insts = _gate_modules(gate_netlist)
    if gate_decls and resolved not in gate_decls:
        # The candidate must be the gate netlist's SOLE ROOT (what the gate
        # actually IS) and must be DECLARED BY THE GOLD (so there is something
        # to compare it against). An unreadable gold is never enough on its own
        # to let the gate pick a top, and an ambiguous or empty intersection
        # returns a note so the caller emits an honest SKIPPED-CONDITION —
        # never a fabricated mismatch and never a fabricated agreement.
        shared = (decls & gate_decls) if decls else set()
        cands = sorted(m for m in shared if m not in gate_insts)
        if len(cands) == 1:
            # NO-LEAK BAR: never silently substitute a PROPER PART of the
            # design the caller asked about. A candidate that is a DESCENDANT
            # of the requested top would shrink the comparison's scope while
            # still reporting a verdict in the caller's name — the exact
            # proxy-for-the-property shape this fix exists to remove. A
            # SIBLING top (an RTL set carrying an ASIC top and a board top,
            # each instantiating the same blocks) is a naming mismatch and is
            # the case worth correcting; a descendant is a scope reduction and
            # is refused.
            below = _descendants(_gold_child_map(gold_files, decls), resolved) \
                if decls else set()
            if cands[0] in below:
                return resolved, (
                    f"the gate netlist holds '{cands[0]}', which is a SUBMODULE "
                    f"of the requested top '{resolved}' — refusing to compare a "
                    "proper part of the design under the top's name")
            return cands[0], (
                f"top '{resolved}' is declared by the RTL but is not a module "
                f"of the gate netlist {sorted(gate_decls)[:8]}; auto-corrected "
                f"to '{cands[0]}', the gate's sole root and a sibling top the "
                "RTL also declares")
        return resolved, (
            f"top '{resolved}' is not a module of the gate netlist "
            f"{sorted(gate_decls)[:8]} and no unique comparable top exists "
            "— cannot select a top")
    return resolved, note


def _drop_started_artefacts(*paths) -> List[str]:
    """Remove the files `main` had already created, and name what it removed.

    A run the environment refused wrote nothing about the design, so it must
    leave nothing that looks like the beginning of one: an operator who finds
    a live log and a telemetry sidecar with no report cannot tell a refused run
    from a killed one. Best-effort by design — a file that cannot be removed is
    not worth failing a refusal over, and the returned list says which ones
    actually went.
    """
    dropped: List[str] = []
    for pth in paths:
        try:
            if pth is not None and Path(pth).is_file():
                Path(pth).unlink()
                dropped.append(str(pth))
        except OSError:
            pass
    return dropped


def _report_env_refusal(exc: BaseException, dropped: List[str]) -> int:
    """The ONE place this program says "the environment refused me".

    vibe-ic#2173. `ContainerImageMismatch` is a `RuntimeError` and MEASURED
    2026-09-07 on 8HD-6 against `a1f3685837ca` NOTHING on this path caught it:
    `lec_run <project> --top top --container vibeic-eda` against a container
    whose digest is not the pin exited 1 with a traceback ending in
    `_container_exec.ContainerImageMismatch`, wrote no `reports/lec.json`, and
    left `reports/lec.live.*.rpt` + `reports/lec.telemetry.*.json` behind. The
    one line naming BOTH digests -- the only line a reader can act on --
    reached the exit code as a bare 1 and the run record nowhere at all.

    So it is reported as a REFUSAL and not as any of the things it is not: not
    the "container not available -- runner should disclosed-skip" case (yosys
    is there and is usable; the RIGHT to use it is what was refused), not a
    verdict about the design, and not the tool's own rc.
    """
    print(f"{_ce.IMAGE_REFUSAL_MARK}{exc}", file=sys.stderr)
    print(f"[lec_run] ENV_REFUSED: no equivalence was attempted and NO "
          f"reports/lec.json was written: this is NOT a statement about the "
          f"design, and NOT a missing toolchain — the container holds the "
          f"wrong bytes."
          + (f" Started artefacts removed: {dropped}." if dropped else ""),
          file=sys.stderr)
    return _ce.EX_ENV_REFUSED


def entry(argv: Optional[List[str]] = None) -> int:
    """`main`, with the environment refusal lifted out of the body.

    THE BACKSTOP, and it is a WRAPPER rather than a rename. `main` keeps its
    name and its whole body because three shipped guards read that body --
    `inspect.getsource(lec_run.main)` in `test_lec_proof_checkpoint_resume`
    among them -- and moving it under another name is a rename those guards
    cannot follow: MEASURED here, it turned
    `test_recovery_runs_before_the_prune_in_main` red for a reason that had
    nothing to do with checkpoint recovery.

    The door guard inside `main` (`_container_available`) is where a mismatch
    is reached on every ordinary run, and it cleans up the two files `main` has
    already opened. This wrapper is the backstop for the container touches
    further down: a refusal from ANY of them is still a refusal, and this
    program must never hand one to a caller as a traceback again.
    """
    try:
        return main(argv)
    except _ce.ContainerImageMismatch as exc:
        return _report_env_refusal(exc, [])


def _positive_completed_rung_cap(value: str) -> int:
    """Argparse type for the opt-in completed-rung policy.

    This is intentionally a count of *completed checkpointed rungs*, not a
    wall-clock deadline.  A live proof is allowed to finish its current rung;
    only the next rung is refused at a durable, independently re-hashable
    checkpoint boundary.
    """
    try:
        cap = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "max completed rungs must be a positive integer") from exc
    if cap < 1:
        raise argparse.ArgumentTypeError(
            "max completed rungs must be at least 1")
    return cap


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 13 LEC PRODUCER — real Yosys RTL≡gate equivalence "
                    "check → reports/lec.json (+ lec.rpt).")
    ap.add_argument("project_dir", help="Project directory")
    ap.add_argument("--gold-rtl-dir", default="phase2/stage1/rtl",
                    help="Dir of RTL .v/.sv (the gold), relative to project")
    ap.add_argument("--gate-netlist", default="phase2/stage2/synth/netlist.v",
                    help="Synth netlist (the gate), relative to project")
    ap.add_argument("--top", required=True, help="Top module name")
    ap.add_argument("--container", default=DEFAULT_CONTAINER,
                    help="Docker container running yosys (default vibeic-eda)")
    ap.add_argument("--liberty", default=DEFAULT_LIBERTY,
                    help="Absolute .lib path INSIDE the container")
    ap.add_argument("--timeout", type=int, default=DEFAULT_YOSYS_TIMEOUT_S,
                    help="One TOTAL LEC step wall-clock budget in seconds, "
                         "shared by all frontend/define retries "
                         f"(default {DEFAULT_YOSYS_TIMEOUT_S})")
    ap.add_argument("--max-completed-rungs", type=_positive_completed_rung_cap,
                    default=None,
                    help="OPT-IN: stop only BETWEEN complete, log-attested "
                         "checkpoint rungs after this many new rungs in this "
                         "invocation, then emit an INCONCLUSIVE receipt. "
                         "This is a deterministic work counter, not a "
                         "wall-clock kill; default is unbounded.")
    ap.add_argument("--json", default=DEFAULT_JSON_REL,
                    help="Output JSON path, relative to project")
    ap.add_argument("--scan-meta", default=None,
                    help="Path (project-relative) to the scan-chain metadata "
                         "written by fault_scan_chain_insert.py "
                         "(reports/phase2/dft/scan_chain.json).  When it is "
                         "present AND declares a PUBLISHED scan netlist, the "
                         "gate is compared in FUNCTIONAL MODE: the DFT control "
                         "ports are tied to their functional values, the scan "
                         "output is dropped, and the gold is given the gate's "
                         "own internal-wire prefix so equiv_make can still "
                         "match points by name.  Absent or unpublished → the "
                         "script is byte-identical to the non-scan one.")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[lec_run] ERROR: not a directory: {project}", file=sys.stderr)
        return 1

    json_out = project / args.json
    rpt_out = project / DEFAULT_RPT_REL
    json_out.parent.mkdir(parents=True, exist_ok=True)
    rpt_out.parent.mkdir(parents=True, exist_ok=True)
    invocation_timestamp = _utc_now()
    invocation_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                     + "-" + secrets.token_hex(6))
    live_log_path = rpt_out.parent / f"lec.live.{invocation_id}.rpt"
    telemetry_path = rpt_out.parent / f"lec.telemetry.{invocation_id}.json"
    _atomic_write_bytes(live_log_path, b"")
    _atomic_write_json(telemetry_path, {
        "schema_version": LEC_TELEMETRY_SCHEMA_VERSION,
        "invocation_id": invocation_id,
        "invocation_timestamp": invocation_timestamp,
        "status": "setup",
        "samples": [],
        "attempts": [],
    })

    gold_dir = project / args.gold_rtl_dir
    gate_netlist = project / args.gate_netlist

    gold_files = _resolve_gold_files(gold_dir)
    if not gold_files:
        print(f"[lec_run] ERROR: no .v/.sv gold RTL under {gold_dir}",
              file=sys.stderr)
        return 1
    if not gate_netlist.is_file():
        print(f"[lec_run] ERROR: gate netlist not found: {gate_netlist}",
              file=sys.stderr)
        return 1

    container = "host" if _ce.local_exec_mode(PROGRAM) else args.container
    try:
        _reachable = _container_available(container)
    except _ce.ContainerImageMismatch as exc:
        # THE DOOR GUARD. Caught HERE and not only in `entry` because the two
        # files above are already on disk: a refused run must take them back
        # with it, or a reader finds the opening of a run that never happened.
        return _report_env_refusal(
            exc, _drop_started_artefacts(live_log_path, telemetry_path))
    if not _reachable:
        print(f"[lec_run] ERROR: container '{container}' not available "
              "(docker/yosys cannot run) — runner should disclosed-skip.",
              file=sys.stderr)
        return 1

    # Verify the Liberty file exists in-container; omit it if absent (generic
    # $_-primitive netlists need no Liberty; Liberty-mapped netlists will then
    # honestly hit unmodelable cells → SKIPPED-CONDITION, never a fake pass).
    # Prefer the PROJECT's own PDK Liberty over the (single-PDK) CLI default:
    # the runner passes no --liberty, and a design's cells are only
    # SAT-modelable from ITS Liberty. When the design VENDORS none — a PDK
    # mounted in the container is the flow's normal shape — fall to the Liberty
    # THIS RUN's own synthesis recorded loading, because a gate netlist is only
    # meaningful against the library it was mapped to. The built-in constant is
    # the last resort and is named as such in the record.
    try:
        liberty, liberty_source = resolve_liberty(
            project, args.liberty,
            lambda pth: _container_file_exists(container, pth))
    except ValueError as exc:
        # Replace any old PASS before returning: the current declared mapping
        # was refused and no proof was attempted against a substitute library.
        parsed = {'proven': 0, 'unproven': 0, 'total': 0, 'equivalent': False,
                  'verdict': 'INCONCLUSIVE', 'verdict_explanation': str(exc),
                  'sat_model_unsupported_cells': [], 'unproven_cells': [],
                  'undefined_macro_modules': []}
        report = build_report(parsed, args.top, str(gate_netlist.resolve()), None, 'refused')
        _atomic_write_bytes(rpt_out, (str(exc) + '\nLEC not run: library mapping refused.\n').encode())
        _finish_telemetry_sidecar(telemetry_path, 'not_run', verdict='INCONCLUSIVE',
                                equivalent=False, current_pass='setup')
        _atomic_write_json(json_out, attach_telemetry(report, telemetry_path, project))
        print(f'[lec_run] {exc}', file=sys.stderr)
        return 2
    if liberty_source in ("staged", "run_synth"):
        print(f"[lec_run] Liberty resolved from {liberty_source}: {liberty}",
              file=sys.stderr)
    elif liberty_source == "default":
        print(f"[lec_run] WARN: falling back to the built-in default Liberty "
              f"{liberty} — this design staged none and its own synthesis "
              f"recorded none. If the gate netlist was mapped against a "
              f"different library, `hierarchy -check` will abort and this run "
              f"will report INCONCLUSIVE over 0 compared points.",
              file=sys.stderr)
    liberty_present = bool(liberty) and _container_file_exists(container, liberty)
    if liberty and not liberty_present:
        print(f"[lec_run] WARN: Liberty not found in-container: {liberty} "
              "— proceeding without it.", file=sys.stderr)
        liberty = None

    # Defense-in-depth: make sure the top actually exists on BOTH sides. A
    # wrong top (default 'chip_top' on a standalone 'spm') builds 0 $equiv cells
    # → a MISLEADING 'may genuinely differ' FAIL that proved nothing. Auto-correct
    # to the sole root, or emit an honest 'top not found' SKIPPED-CONDITION.
    # The GATE netlist is consulted as well: a top the gold declares but the
    # gate does not is exactly as un-comparable as one the gold lacks, and
    # aborts `hierarchy -check` before a single $equiv point is built.
    _gate_for_top = str(gate_netlist.resolve()) if gate_netlist else None
    resolved_top, top_note = _resolve_gold_top(gold_files, args.top,
                                               _gate_for_top)
    if top_note:
        print(f"[lec_run] {top_note}", file=sys.stderr)
    if not _top_is_comparable(gold_files, _gate_for_top, resolved_top):
        top_note = top_note or (
            f"top '{resolved_top}' is not declared on both the RTL and the "
            "gate netlist, so no equivalence miter can be built")
        parsed = {
            "proven": None, "unproven": None, "total": None,
            "sat_model_unsupported_cells": [], "unproven_cells": [],
            "success_line": False, "parse_error": False, "equivalent": False,
            "verdict": "SKIPPED-CONDITION",
            "verdict_explanation": (
                top_note + " — LEC not run (no fabricated mismatch). Pass a "
                "valid --top or resolve the RTL top."),
        }
        report = build_report(parsed, args.top, str(gate_netlist.resolve()),
                              liberty, liberty_source)
        rpt_out.write_text(
            f"[lec_run] {top_note}\nLEC not run; honest SKIPPED-CONDITION.\n",
            encoding="utf-8")
        _finish_telemetry_sidecar(
            telemetry_path, "not_run", verdict=report["verdict"],
            equivalent=report["equivalent"], current_pass="setup")
        report = attach_telemetry(report, telemetry_path, project)
        _atomic_write_json(json_out, report)
        print(f"[lec_run] SKIPPED-CONDITION → {json_out}")
        return 0

    gate_abs = str(gate_netlist.resolve())

    # ORGANIC-20260801 — an instantiated hard-macro (SRAM/IP) whose model is
    # STAGED under input/pdk_local (L8) is UNDEFINED in rtl/, so the GOLD read
    # aborts `unknown module <macro>` (0 compared points → false FAIL) and the
    # synth GATE netlist instantiates it without a module decl. Blackbox the
    # macro on BOTH sides — prepend a `(* blackbox *)` stub to the gold read
    # AND pass it as `blackbox_v` for the gate read — so the miter proves the
    # surrounding logic under an assume-guarantee on identical macro
    # interfaces. No-op when the design stages no hard-macro (byte-identical).
    macro_blackbox_v: List[str] = []
    for _m in _hms.staged_hardmacro_models(project, gold_files):
        if _m["v"] is not None:
            _stub = _hms.emit_blackbox_stub(
                _m["v"], _m["name"], rpt_out.parent / "lec_hardmacro_bb")
            macro_blackbox_v.append(str(_stub.resolve()))
    if macro_blackbox_v:
        gold_files = macro_blackbox_v + gold_files
        print(f"[lec_run] staged hard-macro blackbox: "
              f"{[Path(s).name for s in macro_blackbox_v]}", file=sys.stderr)

    # A pre-techmap generic `$_`-primitive netlist must be read with `-icells`
    # and NO Liberty, else `hierarchy -check` aborts on an undefined `\$_DFF_P_`
    # module before any $equiv point is built (compared_points=0 false-FAIL).
    gate_is_generic = _netlist_uses_generic_primitives(gate_abs)
    if gate_is_generic:
        liberty = None
        print("[lec_run] gate is a generic $_-primitive netlist → "
              "read_verilog -icells (no Liberty).", file=sys.stderr)
    # Write the .ys into the (bind-mounted) project reports dir so the
    # container sees it at the same absolute path (same assumption that lets
    # yosys read the RTL/netlist by their host absolute paths).
    ys_host = rpt_out.parent / "lec_equiv.ys"
    ys_in_container = str(ys_host.resolve())
    # CWD: read the gold from the GATE NETLIST'S OWN DIRECTORY — the directory
    # the flow stages the gate's companion resources into (memory-init images,
    # `include headers). A design's `$readmemh`/`$readmemb`/`` `include ``
    # arguments are ordinarily written as RELATIVE paths, so a read performed
    # from anywhere else cannot resolve them; the gold elaboration then aborts
    # and the miter is empty, which is reported downstream as a non-equivalence
    # verdict about a design that was never compared. This is the plugin's own
    # `cwd=design_dir` rule (the one `benchmark_score_cwd_guard.py` enforces for
    # testbench runs) applied to the LEC read. Falls back to the gold RTL dir,
    # then to None (the previous behaviour) when neither directory exists, so
    # no design that resolves today can be moved by this.
    equiv_workdir: Optional[str] = None
    for _cand in (Path(gate_abs).parent,
                  Path(gold_files[0]).parent if gold_files else None):
        if _cand is not None and _cand.is_dir():
            equiv_workdir = str(_cand.resolve())
            break
    if equiv_workdir:
        print(f"[lec_run] gold+gate read cwd = {equiv_workdir} "
              "(mirrors the synth cwd so relative $readmemh/`include resolve)",
              file=sys.stderr)
    gold_frontend = "verilog"
    gold_defines = "-DSIMULATION -DYOSYS"   # synth PRIMARY define set (mirrored)

    # --- functional-mode (scan) comparison ---------------------------------
    # Only fires when the caller NAMED a scan-chain metadata file AND that file
    # declares a published scan netlist AND the gate netlist really carries the
    # DFT ports it describes.  Any one of those missing → no wrapping at all,
    # and the emitted script is byte-identical to the pre-change one.  Each
    # decision is recorded in `scan_functional_mode` in the report, so a reader
    # can see WHY the comparison was or was not functional-mode constrained.
    scan_mode: Optional[Dict] = None
    scan_record: Dict = {"requested": bool(args.scan_meta), "applied": False,
                         "reason": "no --scan-meta given"}
    gate_wrapper_v = gold_wrapper_v = ""
    scan_meta_abs = ""
    if args.scan_meta:
        meta_path = project / args.scan_meta
        scan_meta_abs = str(meta_path.resolve())
        try:
            _meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _meta, scan_record["reason"] = None, (
                f"scan metadata unreadable ({meta_path}): {exc}")
        _sm = scan_mode_from_meta(_meta)
        if _meta is not None and _sm is None:
            scan_record["reason"] = (
                "scan metadata does not declare a PUBLISHED scan netlist with "
                "a functional-mode tie-off — not wrapping (a wrapper over a "
                "netlist with no DFT ports would be a fabrication)")
        if _sm is not None:
            _nl_text = Path(gate_abs).read_text(encoding="utf-8",
                                                errors="ignore")
            _dft = sorted({*_sm["tieoff"], _sm["scan_out_port"]})
            _all_ports = netlist_top_ports(_nl_text, resolved_top)
            _have = {n for _, _, n in _all_ports}
            _absent = [p for p in _dft if p not in _have]
            _rtl_ports = netlist_top_ports(_nl_text, resolved_top,
                                           exclude=_dft)
            if not _all_ports:
                scan_record["reason"] = (
                    f"could not read module {resolved_top}'s port list out of "
                    f"the gate netlist — not wrapping against a guessed "
                    f"interface")
            elif _absent:
                # The gate is NOT the scan netlist the metadata describes.
                # Wrapping anyway would tie off ports that do not exist and the
                # comparison would say nothing about the real artefact.
                scan_record["reason"] = (
                    f"gate netlist {Path(gate_abs).name} does not carry the "
                    f"DFT port(s) {_absent} the scan metadata declares — the "
                    f"gate is not the scan netlist, so functional-mode "
                    f"constraints are NOT applied")
            else:
                gate_src, gold_src = build_scan_wrappers(
                    resolved_top, _rtl_ports, _sm)
                gate_w = rpt_out.parent / "lec_scan_gate_wrapper.v"
                gold_w = rpt_out.parent / "lec_scan_gold_wrapper.v"
                gate_w.write_text(gate_src, encoding="utf-8")
                gold_w.write_text(gold_src, encoding="utf-8")
                gate_wrapper_v = str(gate_w.resolve())
                gold_wrapper_v = str(gold_w.resolve())
                scan_mode = _sm
                scan_record = {
                    "requested": True, "applied": True,
                    "reason": "gate carries the declared DFT ports",
                    "tieoff": _sm["tieoff"],
                    "scan_out_port_dangling": _sm["scan_out_port"],
                    "internal_prefix": _sm["internal_prefix"],
                    "compared_interface_ports": [n for _, _, n in _rtl_ports],
                    "gate_wrapper": str(gate_w.relative_to(project)),
                    "gold_wrapper": str(gold_w.relative_to(project)),
                }
                print(f"[lec_run] functional-mode scan comparison: tie "
                      f"{_sm['tieoff']}, drop '{_sm['scan_out_port']}', "
                      f"gold prefix {_sm['internal_prefix']!r}",
                      file=sys.stderr)
    if scan_record.get("requested") and not scan_record.get("applied"):
        print(f"[lec_run] scan functional-mode NOT applied: "
              f"{scan_record['reason']}", file=sys.stderr)

    # Cache identity includes tool/runtime bytes as well as design bytes. A
    # failed fingerprint probe disables reuse but does not block a fresh proof.
    runtime_yosys_version = _yosys_version(container)
    runtime_image_digest = _container_image_digest(container)
    runtime_liberty_sha256 = (
        _container_file_sha256(container, liberty) if liberty else None)
    cache_dir = project / DEFAULT_CACHE_REL
    cache_hit_report: Optional[Dict] = None
    final_proof_identity: Optional[Dict] = None

    # --- proof checkpointing ------------------------------------------------
    # Decided ONCE per invocation, and only ever by a measurement: the host has
    # to be able to make the directory and the CONTAINER has to be able to
    # write into it. Anything else disables checkpointing with a stated reason
    # and leaves the emitted recipe byte-identical to the one before this
    # existed. Degrade loudly, never silently.
    checkpoint_root = project / DEFAULT_CHECKPOINT_REL
    checkpoint_enabled = True
    checkpoint_disabled_reason: Optional[str] = None
    try:
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        checkpoint_enabled = False
        checkpoint_disabled_reason = (
            f"could not create {checkpoint_root}: {exc}")
    if checkpoint_enabled:
        _ok, _why = _container_dir_writable(
            container, str(checkpoint_root.resolve()))
        if not _ok:
            checkpoint_enabled, checkpoint_disabled_reason = False, _why
    if not checkpoint_enabled:
        print(f"[lec_run] WARN: proof checkpointing OFF — "
              f"{checkpoint_disabled_reason}", file=sys.stderr)
    if args.max_completed_rungs is not None and not checkpoint_enabled:
        # The counter has no honest boundary without a re-hashable completed
        # checkpoint.  Refuse before launching Yosys rather than degrade into
        # the old one-process/unbounded path while still claiming the cap.
        _receipt = rpt_out.parent / (
            f"{CONTROLLED_LIMIT_RECEIPT_PREFIX}.{invocation_id}.json")
        _doc = {
            "schema_version": CONTROLLED_LIMIT_RECEIPT_SCHEMA_VERSION,
            "invocation_id": invocation_id,
            "verdict": "INCONCLUSIVE",
            "equivalent": False,
            "policy": {"enabled": True,
                       "max_completed_rungs": args.max_completed_rungs},
            "reason": "REFUSED_NO_CHECKPOINT_BOUNDARY",
            "checkpoint_reason": checkpoint_disabled_reason,
            "statement": (
                "No LEC rung was launched: an opt-in completed-rung policy "
                "requires a writable, verifiable checkpoint boundary."),
        }
        _atomic_write_json(_receipt, _doc)
        _atomic_write_json(json_out, {
            "verdict": "INCONCLUSIVE",
            "equivalent": False,
            "verdict_explanation": _doc["statement"],
            "bounded_rung_policy": _doc["policy"],
            "controlled_limit_receipt": str(_receipt.relative_to(project)),
        })
        print("[lec_run] REFUSED: --max-completed-rungs requires a "
              "writable checkpoint boundary", file=sys.stderr)
        return 2
    resume_record: Dict[str, Any] = {
        "enabled": checkpoint_enabled,
        "reason": checkpoint_disabled_reason,
        "schema_version": LEC_CHECKPOINT_SCHEMA_VERSION,
        "directory": None,
        "checkpoint_key": None,
        "base_script_sha256": None,
        "resumed": False,
        "resumed_from": None,
        "rungs_recorded_this_run": [],
        "rungs_recovered_from_a_killed_run": [],
        "rungs_available": [],
        "state": "DISABLED" if not checkpoint_enabled else "NO_CHECKPOINT",
        "resumable_from_rung": None,
        "state_label": None,
        "statement": None,
    }

    # THE PER-RUNG TABLE (vibe-ic#2194), published on every run so the ceiling
    # property is a standing measurement and not a one-off in a lane's notes.
    ladder_record: Dict[str, Any] = {
        "schema_version": LEC_LADDER_SCHEMA_VERSION,
        "rungs": list(LEC_CHECKPOINT_RUNGS),
        "per_rung_processes": None,
        "legs": [],
        "stopped_because": None,
        "peak_rss_kib": None,
        "peak_rss_kib_source": None,
        "sum_of_rung_peaks_kib": None,
        "proof_state_carry": None,
    }
    # This is deliberately separate from StepBudget.  StepBudget records a
    # caller's elapsed-time admission budget but, by current doctrine, does
    # not kill a progressing proof.  The optional cap below is a deterministic
    # count of COMPLETE rungs and can therefore stop only where the checkpoint
    # protocol has already made the state durable and independently verifiable.
    bounded_rung_policy: Dict[str, Any] = {
        "schema_version": "vibeic.lec.completed-rung-cap.v1",
        "enabled": args.max_completed_rungs is not None,
        "max_completed_rungs": args.max_completed_rungs,
        "completed_rungs_this_invocation": 0,
        "limit_reached": False,
        "stopped_before_rung": None,
        "reason": (None if args.max_completed_rungs is not None
                   else "not requested"),
    }
    controlled_rung_limit_hit = False

    proof_execution: Dict[str, Any] = {
        "schema_version": LEC_PROOF_EXECUTION_SCHEMA_VERSION,
        "path": None,
        "canonical_recipe_sha256": None,
        "equivalence_script_sha256_executed": None,
        "evidence_legs": [],
    }

    def _telemetry_finish(status: str, **extra: Any) -> None:
        _finish_telemetry_sidecar(telemetry_path, status, **extra)

    _scan_fsm_restore = scan_fsm_mapping(
        fsm_encfile_beside_netlist(gate_abs), gate_abs, resolved_top, scan_mode)
    if _scan_fsm_restore is None and scan_mode and isinstance(_meta, dict) and liberty:
        _pre_rel = _meta.get("fault_input_netlist") or _meta.get("input_netlist")
        if isinstance(_pre_rel, str):
            _lib_rc, _lib_text, _lib_err = _docker_exec_raw(
                container, "cat " + shlex.quote(liberty))
            if _lib_rc == 0:
                _scan_fsm_restore = scan_fsm_mapping(
                    fsm_encfile_beside_netlist(gate_abs), gate_abs,
                    resolved_top, scan_mode,
                    pre_scan_netlist=str(project / _pre_rel),
                    liberty_text=_lib_text,
                    dff_cells=str(_meta.get("dff_cells", "")).split(","))
    if _scan_fsm_restore:
        _scan_enc_path = project / "reports" / "lec_scan_fsm_encoding.enc"
        _scan_enc_path.write_text(_scan_fsm_restore["encoding_text"])
        _scan_fsm_restore["encoding_path"] = str(_scan_enc_path)
        scan_record["fsm_correspondence"] = _scan_fsm_restore

    # R-0915-97(3) — what the alias pre-pass found, published in lec.json.
    mem_alias_record: List[Dict[str, object]] = []
    mem_alias_findings: List[str] = []
    blacklist_record: List[Dict[str, str]] = []
    blacklist_pass: Dict[str, Any] = {}
    _mem_plan_cache: Dict[str, Tuple[List[Dict[str, object]], List[str]]] = {}

    # THE ALIAS PLAN, DERIVED BY RUNNING YOSYS, CACHED PER FRONTEND. Lazily on
    # the first script emission so it is derived with the SAME gold prologue the
    # proof will use: the probe script IS that prologue, cut at
    # `design -stash gold`, plus a `tee` of the mapped word list. No second
    # spelling of the gold recipe can drift from the first.
    def _memory_alias_plan(frontend: str, slang_prefix: str, defines: str
                           ) -> Tuple[List[Dict[str, object]], List[str]]:
        key = f"{frontend}|{slang_prefix}|{defines}"
        if key in _mem_plan_cache:
            return _mem_plan_cache[key]
        plan: List[Dict[str, object]] = []
        findings: List[str] = []
        try:
            wide = gate_wide_vectors(Path(gate_abs).read_text(errors="replace"))
            if wide:
                base = build_equiv_script(
                    gold_files, gate_abs, resolved_top, liberty,
                    blackbox_v=macro_blackbox_v or None,
                    gate_is_generic=gate_is_generic, gold_frontend=frontend,
                    slang_prefix=slang_prefix, gold_defines=defines,
                    scan_mode=scan_mode, gate_wrapper_v=gate_wrapper_v,
                    gold_wrapper_v=gold_wrapper_v)
                prologue = base.split("design -stash gold")[0]
                tee = rpt_out.parent / _MEM_PROBE_TEE
                probe = rpt_out.parent / "lec_mem_probe.ys"
                probe.write_text(prologue
                                 + f"tee -q -o {tee} select -list w:*\n",
                                 encoding="utf-8")
                launched, _raw = run_yosys_equiv(
                    container, str(probe.resolve()),
                    timeout=_MEM_PROBE_TIMEOUT_S, workdir=equiv_workdir)
                if launched and tee.is_file():
                    plan, findings = memory_word_alias_plan(
                        gold_memory_words(tee.read_text(errors="replace")),
                        wide)
        except OSError as exc:                                 # noqa: BLE001
            findings = [f"LEC_MEMORY_PROBE_UNREADABLE: {exc}"]
        _mem_plan_cache[key] = (plan, findings)
        for f in findings:
            if f not in mem_alias_findings:
                mem_alias_findings.append(f)
        if plan and not mem_alias_record:
            mem_alias_record.extend(plan)
        return plan, findings

    def _make_script(frontend: str, slang_prefix: str, defines: str, *,
                     checkpoint_dir: Optional[str] = None,
                     resume_from: Optional[Dict] = None,
                     ladder_rungs: Optional[int] = None,
                     equiv_blacklist_path: str = "") -> str:
        _plan, _ = _memory_alias_plan(frontend, slang_prefix, defines)
        return build_equiv_script(
            gold_files, gate_abs, resolved_top, liberty,
            memory_word_aliases=_plan,
            equiv_blacklist_path=equiv_blacklist_path,
            blackbox_v=macro_blackbox_v or None,
            gate_is_generic=gate_is_generic,
            gold_frontend=frontend, slang_prefix=slang_prefix,
            gold_defines=defines, scan_mode=scan_mode,
            gate_wrapper_v=gate_wrapper_v,
            gold_wrapper_v=gold_wrapper_v,
            # #2050 — the FSM encoding table synth wrote beside THIS netlist,
            # or None when there is none (every netlist produced before the
            # synth step started writing it), in which case the recipe below
            # is byte-identical to the pre-change one. It flows through
            # `_identity_for` -> script_sha256, so a run WITH a translation and
            # a run WITHOUT one can never share a PASS-cache entry.
            fsm_encfile=fsm_encfile_beside_netlist(gate_abs),
            fsm_preserve_signals=fsm_signal_names(
                fsm_encfile_beside_netlist(gate_abs)),
            scan_fsm_restore=_scan_fsm_restore,
            checkpoint_dir=checkpoint_dir, resume_from=resume_from,
            ladder_rungs=ladder_rungs)

    def _identity_for(script: str, frontend: str, defines: str,
                      slang_prefix: str) -> Dict:
        identity = build_proof_identity(
            project=project, gold_files=gold_files, gate_netlist=gate_abs,
            script=script, top=resolved_top,
            scan_meta=scan_meta_abs or None,
            gate_wrapper=gate_wrapper_v, gold_wrapper=gold_wrapper_v,
            liberty=liberty, liberty_sha256=runtime_liberty_sha256,
            yosys_version=runtime_yosys_version,
            image_digest=runtime_image_digest)
        # These are already transitively covered by script_sha256, but naming
        # them makes the attestation reviewable without reverse-engineering .ys.
        identity["gold_frontend"] = frontend
        identity["gold_defines"] = defines if frontend == "slang" else None
        identity["slang_load_prefix"] = slang_prefix if frontend == "slang" else None
        return identity

    def _canonical_script_for(frontend: str, slang_prefix: str,
                              defines: str) -> Tuple[str, Optional[str],
                                                     Optional[Path]]:
        """(the FROM-ZERO script actually run, checkpoint key, directory).

        NOT circular even though the script has to contain the checkpoint
        paths: `lec_checkpoint_key` ignores `equivalence_script` by
        construction, so the key can be computed from a script that does not
        yet know where the checkpoints go.

        The PREFLIGHT cache lookup and `_run` both call this, so the identity
        the cache is SEARCHED under is the identity a from-zero run would
        STORE under. Letting those two drift is how a cache stops hitting
        without anything reporting that it stopped.
        """
        base = _make_script(frontend, slang_prefix, defines)
        if not checkpoint_enabled:
            return base, None, None
        key = lec_checkpoint_key(
            _identity_for(base, frontend, defines, slang_prefix))
        cdir = checkpoint_dir_for(project, key)
        return (_make_script(frontend, slang_prefix, defines,
                             checkpoint_dir=str(cdir)), key, cdir)

    # Preflight every recipe the deterministic retry ladder could select. This
    # is what lets a second invocation reuse a prior slang PASS without first
    # rerunning—and failing—the built-in Verilog frontend. Both valid slang
    # load forms are generated locally; no Yosys capability probe is needed.
    _candidate_identities: Dict[str, Dict] = {}
    for _fe, _prefix, _defs in (
            ("verilog", "", "-DSIMULATION -DYOSYS"),
            ("slang", "", "-DSIMULATION -DYOSYS"),
            ("slang", "plugin -i slang", "-DSIMULATION -DYOSYS"),
            ("slang", "", "-DSYNTHESIS -DYOSYS"),
            ("slang", "plugin -i slang", "-DSYNTHESIS -DYOSYS")):
        _candidate_script, _, _ = _canonical_script_for(_fe, _prefix, _defs)
        _candidate_identity = _identity_for(
            _candidate_script, _fe, _defs, _prefix)
        if proof_identity_complete(_candidate_identity):
            _candidate_identities[lec_cache_key(_candidate_identity)] = \
                _candidate_identity
    if _candidate_identities:
        cache_hit_report = find_pass_cache(
            cache_dir, _candidate_identities,
            invocation_timestamp=invocation_timestamp)
        if cache_hit_report is not None:
            final_proof_identity = cache_hit_report[
                "cache_use_attestation"]["revalidated_identity"]
            _telemetry_finish(
                "cache_hit",
                cache_key=cache_hit_report["cache_use_attestation"]["cache_key"],
                current_pass="cache_hit",
                revalidated_identity=final_proof_identity)
            print("[lec_run] exact PASS cache HIT "
                  f"{cache_hit_report['cache_use_attestation']['cache_key']} "
                  "— Yosys not launched; source proof and current identity "
                  "revalidated.", file=sys.stderr)

    def _run(frontend: str, slang_prefix: str = "",
             defines: str = "-DSIMULATION -DYOSYS"):
        nonlocal cache_hit_report, final_proof_identity, controlled_rung_limit_hit
        # THE FROM-ZERO SCRIPT FIRST, always — it is what the checkpoint key
        # and the manifest's `base_script_sha256` are computed from, so a
        # resumed run and a from-zero run agree on WHICH ladder wrote a file.
        canonical_script, ckpt_key, ckpt_dir = _canonical_script_for(
            frontend, slang_prefix, defines)
        # RECORDED, not re-derived later. The report needs the SAME
        # `base_script_sha256` this attempt used; re-deriving it after the run
        # would have to reconstruct the frontend, the define set AND the slang
        # load prefix the attempt chose, and a single wrong guess reports zero
        # available checkpoints for a ladder that wrote four.
        resume_record["base_script_sha256"] = _sha256_bytes(
            canonical_script.encode("utf-8"))
        resume_from: Optional[Dict] = None
        if checkpoint_enabled and ckpt_dir is not None and ckpt_key is not None:
            resume_record["checkpoint_key"] = ckpt_key
            try:
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                resume_record["directory"] = str(
                    ckpt_dir.relative_to(project))
            except (OSError, ValueError):
                resume_record["directory"] = str(ckpt_dir)
            # RECOVER BEFORE PRUNING. The prune deletes `.part` leftovers; a
            # complete one belonging to a run that was killed before it could
            # publish is recoverable, and deleting it first would destroy
            # exactly the work this feature exists to keep.
            _recovered = recover_orphan_checkpoints(
                ckpt_dir, ckpt_key,
                _sha256_bytes(canonical_script.encode("utf-8")),
                rpt_out.parent,
                yosys_version=runtime_yosys_version,
                image_digest=runtime_image_digest,
                invocation_id=invocation_id, evidence_log=live_log_path)
            if _recovered:
                resume_record["rungs_recovered_from_a_killed_run"] = _recovered
                print("[lec_run] recovered checkpoint(s) a previous killed "
                      f"invocation never published: {_recovered}",
                      file=sys.stderr)
            prune_stale_checkpoint_parts(ckpt_dir)
            resume_from = select_resume_checkpoint(
                ckpt_dir, ckpt_key,
                _sha256_bytes(canonical_script.encode("utf-8")))
        # ONE RUNG PER PROCESS whenever there is a checkpoint to restart from
        # (vibe-ic#2194). `_per_rung` is the SAME condition the promote/resume
        # block below already keys on. With checkpointing OFF there is nothing
        # to restart from, so the ladder stays in ONE process and the emitted
        # recipe is byte-identical to the pre-#2194 one — that path remains a
        # control rather than a second implementation.
        _per_rung = (checkpoint_enabled and ckpt_dir is not None
                     and ckpt_key is not None)
        # THE ENTRY STATE — what a PREVIOUS INVOCATION left behind, as distinct
        # from the checkpoints this invocation is about to write for itself.
        # Every field that has always meant "did this invocation resume" stays
        # bound to this, so a from-zero run does not begin reporting
        # `resumed: true` merely because its own rung 2 reads its own rung 1.
        _entry_resume_from = resume_from
        if resume_from is not None:
            script = _make_script(frontend, slang_prefix, defines,
                                  checkpoint_dir=str(ckpt_dir),
                                  resume_from=resume_from,
                                  ladder_rungs=1 if _per_rung else None)
        elif _per_rung:
            script = _make_script(frontend, slang_prefix, defines,
                                  checkpoint_dir=str(ckpt_dir), ladder_rungs=1)
        else:
            script = canonical_script
        # THE PROOF IDENTITY IS THE RECIPE, NOT THE PATH TAKEN THROUGH IT.
        # `canonical_script` — the FROM-ZERO ladder — is what the identity is
        # built from on every run, resumed or not, so a PASS reached by
        # resuming is stored under exactly the key a from-zero run would search.
        #
        # WHY THIS IS NOT A LIE ABOUT WHAT RAN. A resumed script is not an
        # independent recipe: `_make_script(..., resume_from=...)` derives it
        # MECHANICALLY from this same canonical ladder plus one checkpoint, and
        # that checkpoint was already refused unless its manifest names this
        # canonical ladder (`base_script_sha256`), its .il re-hashes to the
        # recorded digest, and its carried evidence re-hashes too. The bytes
        # that were actually executed, and both evidence legs, are recorded in
        # `proof_execution` below and in `lec_resume` — named, hash-bound, and
        # reviewable — they are simply not part of the KEY.
        #
        # WHAT KEYING ON THE RESUMED SCRIPT COST. Every resume produced its own
        # key, so a PASS reached at invocation 2 was stored where no later
        # invocation looks: invocation 3 selects the now-FURTHEST rung, resumes
        # from a different position, misses, and re-proves; only invocation 4,
        # resuming from the same rung as 3, finds 3's entry. Convergence at
        # four invocations for a design that was proven at two.
        final_proof_identity = _identity_for(
            canonical_script, frontend, defines, slang_prefix)
        proof_execution["path"] = ("resumed" if resume_from is not None
                                   else "from-zero")
        proof_execution["canonical_recipe_sha256"] = _sha256_bytes(
            canonical_script.encode("utf-8"))
        proof_execution["equivalence_script_sha256_executed"] = _sha256_bytes(
            script.encode("utf-8"))
        if resume_from is not None:
            proof_execution["resumed_from"] = {
                "rung": resume_from["rung"],
                "rung_index": resume_from["rung_index"],
                "checkpoint_sha256": resume_from["checkpoint_sha256"],
                "checkpoint_bytes": resume_from["checkpoint_bytes"],
            }
        if proof_identity_complete(final_proof_identity):
            _key = lec_cache_key(final_proof_identity)
            _hit = find_pass_cache(
                cache_dir, {_key: final_proof_identity},
                invocation_timestamp=invocation_timestamp)
            if _hit is not None:
                cache_hit_report = _hit
                _telemetry_finish(
                    "cache_hit", cache_key=_key, current_pass="cache_hit",
                    revalidated_identity=final_proof_identity)
                print(f"[lec_run] exact PASS cache HIT {_key} — Yosys not "
                      "launched; source proof and current identity revalidated.",
                      file=sys.stderr)
                return True, _hit.get("_cache_source_rpt", "")
        # ANNOUNCED HERE, NOT WHERE THE CHECKPOINT WAS SELECTED. Selecting one
        # is not resuming from it: the PASS-cache lookup above returns first on
        # a hit and launches no yosys at all, and the line used to be printed
        # before that check -- so an invocation that resumed NOTHING said
        # "RESUMING the proof at rung equiv_induct_seq64" on stderr while
        # lec.json correctly recorded `resumed: false`. Measured on a real PASS
        # design, invocations 4 and 5. An operator reads the stderr.
        if _entry_resume_from is not None:
            print(f"[lec_run] RESUMING the proof at rung "
                  f"{_entry_resume_from['rung']} "
                  f"(index {_entry_resume_from['rung_index']}) "
                  f"from {_entry_resume_from['checkpoint_sha256']} "
                  f"({_entry_resume_from['checkpoint_bytes']} bytes) — the "
                  "rungs before it are NOT re-proved.", file=sys.stderr)
        # ------------------------------------------------------------------
        # THE RUNG LOOP — ONE RUNG PER PROCESS (vibe-ic#2194)
        # ------------------------------------------------------------------
        # THE DEFECT. `_emit_ladder` emitted EVERY remaining rung into ONE
        # script, so ONE yosys process ran the whole ladder and its peak memory
        # was the ACCUMULATION of all four rungs rather than the worst of them.
        # MEASURED on opentitan_aes: an OOM kill at a 48 GiB cgroup cap
        # (`OOMKilled=true`, `memory.events oom_kill 1`), while the very rung
        # that died reaches the SAME 57873326 clauses and 22024817 variables at
        # 16.3 GB with `oom_kill 0` when it is the only rung in the process. So
        # 48 GiB was never that rung's footprint.
        #
        # WHY A BIGGER CEILING IS NOT THE REPAIR. It buys exactly one more rung
        # and then dies again — a limit moved to fit the job it just failed,
        # the same shape as a 600 s bound on a 983 s gate (#2177). A ladder
        # whose memory grows with the NUMBER OF RUNGS can only be sized for a
        # machine, and then only until the next design.
        #
        # THE REPAIR. Each rung runs in a FRESH process, resuming from the
        # previous rung's checkpoint, so peak bounds by the WORST SINGLE RUNG
        # and scales with the design instead of with the host.
        #
        # THE PROOF STATE TRAVELS IN THE CHECKPOINT, not beside it: yosys marks
        # a `$equiv` point proven by REWIRING that cell's \\B to its \\A, which
        # is ordinary RTLIL, so `write_rtlil`/`read_rtlil` round-trips the
        # proven SET across a process boundary. That is not assumed here —
        # `proved_at_entry` below measures it at every boundary, because a
        # restart that had silently lost the proven set would redo the work and
        # look exactly like progress.
        ladder_legs: List[Dict[str, Any]] = []
        _leg_raws: List[str] = []
        _all_recorded: List[str] = []
        _launched = False
        _ladder_stop: Optional[str] = None
        #: TERMINAL vs UNFINISHED (#2232 follow-on). A no-progress stop is not
        #: an interruption: the rung RAN, reached its own closing `equiv_status`
        #: and reported that it moved nothing, so that count IS the ladder's
        #: verdict-grade state. `complete: False` means something else entirely —
        #: "this is a POSITION, not a verdict" — and a downstream reader appends
        #: "the admission budget was spent" to it, which on a flat wall is simply
        #: untrue. The two stops are told apart here rather than sharing a flag.
        _stopped_on_no_progress = False
        while True:
            _start_index = (0 if resume_from is None
                            else int(resume_from["rung_index"]) + 1)
            _at_top = _start_index >= len(LEC_LADDER)
            if _at_top and ladder_legs:
                _ladder_stop = _LADDER_COMPLETE
                break
            # A bounded policy is checked only BEFORE a NEW rung.  The
            # read-back-only final leg remains allowed: it consumes no rung and
            # is the sole producer of a terminal PASS/FAIL.  Conversely, a
            # completed rung followed by a cap is explicitly not a PASS just
            # because its local `equiv_status` happened to sound optimistic.
            if (not _at_top and args.max_completed_rungs is not None
                    and bounded_rung_policy[
                        "completed_rungs_this_invocation"]
                    >= args.max_completed_rungs):
                controlled_rung_limit_hit = True
                bounded_rung_policy.update({
                    "limit_reached": True,
                    "stopped_before_rung": LEC_LADDER[_start_index][0],
                    "reason": (
                        "completed-rung cap reached at a log-attested "
                        "checkpoint boundary; no later rung was launched"),
                })
                _ladder_stop = (
                    "controlled completed-rung cap reached before rung "
                    f"{LEC_LADDER[_start_index][0]}; the prior checkpoint is "
                    "durable, but no terminal equivalence verdict was run")
                break
            # `_at_top` with NO legs yet: a PREVIOUS invocation already
            # checkpointed every rung. One leg still has to run — it reads the
            # position back and STATES it — or this invocation launches nothing
            # and reaches no verdict at all, where the single-process ladder
            # would have returned the completed proof. The entry script built
            # above is already the right one: bounded from a start index past
            # the top rung, it emits `read_rtlil`, `stat` and `equiv_status`
            # and no rung.
            _rung_name = None if _at_top else LEC_LADDER[_start_index][0]
            if ladder_legs:
                # Leg 1's script was built above (it is the one the identity
                # and the PASS-cache lookup were computed from); every later
                # leg is derived here from the checkpoint the previous one left.
                script = _make_script(frontend, slang_prefix, defines,
                                      checkpoint_dir=str(ckpt_dir),
                                      resume_from=resume_from, ladder_rungs=1)
            ys_host.write_text(script, encoding="utf-8")
            # THE TOTAL, NOT A FRESH COPY. Handing `args.timeout` here is the
            # defect measured on 2026-08-27: it re-armed the deadline on every
            # attempt. Every attempt — and every RUNG — draws from the SAME
            # StepBudget deadline, so splitting the ladder across four
            # processes cannot buy it four budgets.
            _attempt_budget = budget.next_attempt_budget()
            if _attempt_budget <= 0:
                budget.skipped(frontend, defines,
                               "the step budget was spent before rung "
                               f"{_rung_name} could be launched")
                _ladder_stop = ("the step budget was spent before rung "
                                f"{_rung_name} could be launched")
                break
            _attempt_no = len(budget.attempts) + 1
            _started = budget.elapsed_s()
            # PER LEG, not per invocation: each rung's process has its own kill
            # cause, so "which rung was killed and why" survives the split.
            _kill_cause: Dict = {}
            # The rung's OWN convergence predicate, reading only this leg's
            # part of the live log (FX_AES_LEC_SCALE): the step budget ends a
            # rung only on the proof's evidence that it cannot finish in it.
            _leg_offset = (live_log_path.stat().st_size
                           if live_log_path is not None
                           and live_log_path.is_file() else 0)
            _leg_probe = (rung_projection_abort_probe(
                              live_log_path, _leg_offset, budget)
                          if live_log_path is not None else None)
            _leg_launched, _leg_raw = run_yosys_equiv(
                container, ys_in_container,
                kill_cause=_kill_cause,
                abort_probe=_leg_probe,
                timeout=_attempt_budget,
                workdir=equiv_workdir,
                live_log_path=live_log_path,
                telemetry_path=telemetry_path,
                telemetry_context={
                    "schema_version": LEC_TELEMETRY_SCHEMA_VERSION,
                    "invocation_id": invocation_id,
                    "invocation_timestamp": invocation_timestamp,
                    "attempt": _attempt_no,
                    "ladder_leg": len(ladder_legs) + 1,
                    "rung": _rung_name,
                    "frontend": frontend,
                    "defines": defines,
                })
            budget.record(frontend, defines, _attempt_budget,
                          budget.elapsed_s() - _started, _leg_launched,
                          bool(_TIMEOUT_RE.search(_leg_raw)),
                          kill_cause=_kill_cause)
            _launched = _launched or _leg_launched
            _leg_raws.append(_leg_raw)
            # ENTRY counts come from THIS leg's own LEADING `equiv_status` (the
            # read-back position); EXIT counts from its closing one. Comparing
            # leg k+1's entry against leg k's exit is what demonstrates that
            # the PROOF STATE, and not merely the netlist, crossed the process
            # boundary.
            _entry_counts = (resume_status_counts(_leg_raw)
                             if resume_from is not None else None)
            _exit_counts = final_status_counts(_leg_raw)
            _peak_sampled = leg_peak_rss_kib(telemetry_path, _attempt_no)
            _peak_self = yosys_self_reported_peak_kib(_leg_raw)
            _peak_kib, _peak_src = leg_peak_rss(_peak_sampled, _peak_self)
            _leg: Dict[str, Any] = {
                "leg": len(ladder_legs) + 1,
                "rung": _rung_name,
                "rung_index": None if _at_top else _start_index,
                "position_read_back_only": _at_top,
                "attempt": _attempt_no,
                "rungs_in_this_process": (
                    0 if _at_top else
                    (1 if _per_rung else len(LEC_LADDER) - _start_index)),
                "resumed_from_rung": (resume_from or {}).get("rung"),
                "script_sha256": _sha256_bytes(script.encode("utf-8")),
                "budget_sec": _attempt_budget,
                "elapsed_sec": round(budget.elapsed_s() - _started, 2),
                "launched": _leg_launched,
                "proved_at_entry": (_entry_counts or {}).get("proved"),
                "unproven_at_entry": (_entry_counts or {}).get("unproven"),
                "proved_at_exit": (_exit_counts or {}).get("proved"),
                "unproven_at_exit": (_exit_counts or {}).get("unproven"),
                # TWO INSTRUMENTS, BOTH RECORDED, the better one published
                # (vibe-ic#2194). The supervisor's poll is kept because it sees
                # the whole process tree; Yosys's own closing figure is kept
                # because it is an exact peak and exists for every leg however
                # short. Neither is allowed to become a 0.
                "peak_rss_kib_sampled": _peak_sampled,
                "peak_rss_kib_self_reported": _peak_self,
                "peak_rss_kib": _peak_kib,
                "peak_rss_kib_source": _peak_src,
                "stopped": run_was_stopped(_leg_raw),
                "checkpoint_recorded": [],
            }
            if _per_rung:
                _recorded = promote_and_record_checkpoints(
                    ckpt_dir, ckpt_key,
                    _sha256_bytes(canonical_script.encode("utf-8")), _leg_raw,
                    yosys_version=runtime_yosys_version,
                    image_digest=runtime_image_digest,
                    invocation_id=invocation_id,
                    resumed_from_rung=(resume_from or {}).get("rung"),
                    evidence_log=live_log_path)
                _leg["checkpoint_recorded"] = _recorded
                for _r in _recorded:
                    if _r not in _all_recorded:
                        _all_recorded.append(_r)
                # PRUNE ONLY ONCE THIS LADDER HAS LANDED SOMETHING. Superseding
                # is a statement that a NEWER ladder now owns this directory,
                # and the evidence for that statement is a rung this ladder
                # recorded. Doing it before the run (at selection time) would
                # let an attempt that dies in its first pass delete a complete
                # ladder and leave nothing in its place.
                if _recorded:
                    _pruned = prune_superseded_ladders(
                        ckpt_dir, ckpt_key,
                        _sha256_bytes(canonical_script.encode("utf-8")))
                    if _pruned:
                        resume_record["superseded_ladder_files_removed"] = _pruned
                        print("[lec_run] pruned a superseded ladder's "
                              f"checkpoints in {ckpt_dir.name}: {_pruned}",
                              file=sys.stderr)
            ladder_legs.append(_leg)
            # Count ONLY the rung that actually completed and whose log
            # attested checkpoint was promoted.  A stopped leg, a partial
            # `.part`, a top read-back, or a synthetic report never consumes a
            # unit of this deterministic policy.
            if (_per_rung and not _at_top and _rung_name in _recorded):
                bounded_rung_policy["completed_rungs_this_invocation"] += 1
            if _at_top:
                _ladder_stop = _LADDER_COMPLETE
                break
            # A LEG THAT WAS CUT OFF ENDS THE LADDER. `run_was_stopped` is this
            # producer's OWN predicate for "cut off, as opposed to finished and
            # decided" — three places already ask it and its docstring says
            # they must not be able to answer differently, so this is its
            # fourth caller and not a fourth spelling. Climbing on in a fresh
            # process after a stop is precisely how a restart would HIDE a real
            # exhaustion: the stop would scroll past, a later rung would write
            # a checkpoint, and the run would look like it had simply gone
            # further. It stops, and it says which rung it stopped on.
            if run_was_stopped(_leg_raw):
                _ladder_stop = (
                    f"the leg running rung {_rung_name} was CUT OFF (this "
                    "producer's own stop marker), so the ladder stopped there "
                    "and nothing beyond it was attempted")
                break
            if not _per_rung:
                _ladder_stop = ("checkpointing is unavailable, so the whole "
                                "ladder ran in one process")
                break
            # FORWARD PROGRESS, OR STOP AND SAY SO. The next leg may only start
            # ABOVE the rung this one was asked to climb. A rung that genuinely
            # exceeds the ceiling writes no checkpoint, so the furthest valid
            # one does not move, and the ladder STOPS here with its reason
            # recorded — it is never re-attempted in a loop, and the verdict
            # stays whatever this leg's own log earned (a killed leg carries
            # its stop marker into the parse below and classifies as a
            # disclosed non-PASS). A restart must not be able to hide a real
            # exhaustion.
            resume_from = select_resume_checkpoint(
                ckpt_dir, ckpt_key,
                _sha256_bytes(canonical_script.encode("utf-8")))
            _next_index = (0 if resume_from is None
                           else int(resume_from["rung_index"]) + 1)
            if _next_index <= _start_index:
                _ladder_stop = (
                    f"rung {_rung_name} recorded no checkpoint, so the ladder "
                    "stopped there; the verdict below is what that leg's own "
                    "log earned and nothing was re-attempted")
                break
            # A RUNG THAT PROVED NOTHING DOES NOT AUTHORISE A DEEPER ONE
            # (vibe-ic#2232). MEASURED on ic/sha256: the rung that does the
            # work took 700.6 s and the ladder then spent 7.5 h and counting on
            # rungs that moved nothing, each authorised by `budget_sec 86400`.
            # Its own log said so twice before the third rung started:
            #     Proved 0 previously unproven $equiv cells.
            #       Of those cells 1611 are proven and 2 are unproven.
            # Deepening `-seq` is only worth a rung when the previous rung
            # actually proved something. A stalled rung completes NORMALLY, so
            # it writes its checkpoint and every stop condition above it is
            # satisfied — which is why the ladder climbed on.
            #
            # LAST OF THE STOP CONDITIONS, DELIBERATELY. A rung that exceeds the
            # ceiling dies with NO checkpoint, and in the silent-OOM shape its
            # counts are still readable and equal — so an earlier placement
            # RELABELLED a real exhaustion as a benign no-progress stop and
            # took `test_a_rung_that_exceeds_the_ceiling_still_fails_honestly
            # [True-no checkpoint]` down with it. Exhaustion keeps its own
            # reason; this only speaks when the rung genuinely FINISHED.
            #
            # THE COUNTS WERE ALREADY BEING MEASURED HERE; they were simply
            # never compared. Both ends must have been READ: a count of None is
            # NOT_MEASURED, and reading an absence as "nothing moved" would
            # invent a stop out of an unread state, which is the same error as
            # inventing a pass out of one. So the guard fires only on four
            # measured numbers.
            #
            # This decides WHERE THE LADDER STOPS, never what the verdict is:
            # the residual is still parsed from the legs' own logs below, and a
            # stopped ladder reports `complete: False`.
            _pe = (_entry_counts or {}).get("proved")
            _px = (_exit_counts or {}).get("proved")
            _ue = (_entry_counts or {}).get("unproven")
            _ux = (_exit_counts or {}).get("unproven")
            # AND THERE MUST BE SOMETHING LEFT TO PROVE (#2232 follow-on).
            # A ladder that has already proven EVERYTHING enters its next rung
            # with 0 unproven and leaves with 0 unproven, so the four counts
            # are equal for the one reason that is not a stall: there was
            # nothing for the rung to move. Reading that as "proved nothing"
            # stopped a COMPLETE proof one rung early and published it as
            # `complete: False` — a finished equivalence reported as a wall.
            # MEASURED against this file's own suite on live main: a fully
            # proven ladder stopped at `equiv_induct_seq4` with "the 0 unproven
            # point(s) are reported as the residual", and
            # `lec_ladder.complete` came back False.
            #
            # The residual is what the stop is ABOUT — the reason string says
            # "a residual it has already declared it cannot move" — so a stop
            # with no residual is not this condition. Requiring `_ux > 0` says
            # that in the predicate instead of only in the prose. It NARROWS
            # the stop; no rung that genuinely stalled with work outstanding
            # escapes it, which `test_a_rung_that_proved_nothing_new_does_not_
            # earn_the_next_one` and the FIRST-rung test both still pin.
            # Splitting the two simple commands adds a process boundary, not
            # a new reason to stop.  Historically their combined rung could
            # make zero progress before an induction rung made progress, so a
            # plateau here must still be allowed to reach induction.
            # The early joint attempt precedes the full simple fallback.
            # Its plateau cannot establish that a later, different proof
            # strategy will make no progress, so it does not cut that tail.
            if (_rung_name not in {"equiv_simple_short", "equiv_simple_full",
                                  "equiv_induct_joint_seq16"}
                    and None not in (_pe, _px, _ue, _ux)
                    and _px == _pe and _ux == _ue and _ux > 0):
                # THE THREE THINGS A STOP OWES ITS READER: which rung, and
                # the two counts the decision was made from, each spelled so a
                # reader (and a test) can find it without re-deriving it from
                # prose. A stop that says only "proved nothing" reads
                # downstream exactly like a ladder that finished.
                _ladder_stop = (
                    f"rung {_rung_name} proved nothing — {_pe} proven at "
                    f"entry, {_ux} still unproven at exit: it entered with "
                    f"{_pe} proven / {_ue} unproven and left with the same "
                    f"counts, so the ladder stopped there rather than "
                    f"authorising a deeper induction rung against a residual "
                    f"it has already declared it cannot move; the {_ux} "
                    f"unproven point(s) are reported as the residual")
                _stopped_on_no_progress = True
                break
        # THE WHOLE LADDER'S OUTPUT, IN ORDER. `parse_equiv_output` already
        # reads the LAST `equiv_status` (it was made resume-aware for exactly
        # this reason), so a concatenation of the legs is read at the state the
        # ladder finished in, not the state its first leg started from.
        _raw = "".join(_leg_raws)
        # R-0915-97(3) — PASS 2, EVIDENCE-GATED, AND ONLY WHEN THERE IS
        # EVIDENCE. Pass 1 has just finished; its unproven list is the only
        # per-name evidence yosys gives, so "proven" is derived as "compared and
        # NOT in that list". A candidate needs its Q proven, so a real
        # divergence (Q unproven too) can never be blacklisted. An empty
        # candidate set means NO second pass and today's behaviour exactly.
        _bl_cands = []
        _synth_log = project / "phase2" / "stage2" / "synth" / "yosys.log"
        if _leg_raws and _synth_log.is_file():
            try:
                _bl_cands = blacklist_second_pass_plan(
                    _raw, _synth_log.read_text(errors="replace"))
            except OSError:
                _bl_cands = []
        if _bl_cands:
            _bl_path = rpt_out.parent / "lec_blacklist.txt"
            _bl_path.write_text("\n".join(c["d"] for c in _bl_cands) + "\n",
                                encoding="utf-8")
            _bl_ys = rpt_out.parent / "lec_equiv_blacklist.ys"
            _bl_ys.write_text(
                _make_script(frontend, slang_prefix, defines,
                             equiv_blacklist_path=str(_bl_path.resolve())),
                encoding="utf-8")
            _bl_launched, _bl_raw = run_yosys_equiv(
                container, str(_bl_ys.resolve()),
                timeout=max(1, budget.next_attempt_budget()),
                workdir=equiv_workdir)
            _p1 = final_status_counts(_raw) or {}
            _p2 = final_status_counts(_bl_raw) or {}
            for c in _bl_cands:
                blacklist_record.append({
                    "name": c["d"], "proven_q": c["q"],
                    "synth_log_line": c["line"]})
            _bl_pass = {
                "blacklisted": [c["d"] for c in _bl_cands],
                "pass1_proved": _p1.get("proved"),
                "pass1_unproven": _p1.get("unproven"),
                "pass2_proved": _p2.get("proved"),
                "pass2_unproven": _p2.get("unproven"),
                "script": str(_bl_ys), "launched": _bl_launched,
            }
            # THE SECOND PASS ONLY REPLACES THE FIRST WHEN IT PROVED MORE. The
            # blanket-blacklist measurement (3717/293 against 4025/3) is why:
            # removing cut points can LOSE proofs, and a pass that loses them
            # must not become the verdict.
            if (_bl_launched and _p2.get("proved") is not None
                    and _p1.get("proved") is not None
                    and _p2["proved"] >= _p1["proved"]):
                _raw = _raw + _bl_raw
                _bl_pass["adopted"] = True
            else:
                _bl_pass["adopted"] = False
            blacklist_pass.update(_bl_pass)
        if _per_rung:
            resume_record["rungs_recorded_this_run"] = _all_recorded
        resume_record["resumed"] = _entry_resume_from is not None
        if _entry_resume_from is not None:
            _first_leg = ladder_legs[0] if ladder_legs else {}
            resume_record["resumed_from"] = {
                "rung": _entry_resume_from["rung"],
                "rung_index": _entry_resume_from["rung_index"],
                "checkpoint_sha256": _entry_resume_from["checkpoint_sha256"],
                "checkpoint_bytes": _entry_resume_from["checkpoint_bytes"],
                "checkpoint_written_timestamp":
                    _entry_resume_from.get("written_timestamp"),
                "evidence_log": _entry_resume_from.get("evidence_log"),
                "evidence_log_sha256":
                    _entry_resume_from.get("evidence_log_sha256"),
                # MEASURED from this run's OWN leading equiv_status, not
                # remembered from the run that wrote the checkpoint. None is
                # NOT_MEASURED and is never replaced by a zero.
                "proved_at_checkpoint": _first_leg.get("proved_at_entry"),
                "unproven_at_checkpoint": _first_leg.get("unproven_at_entry"),
                "counts_measured": _first_leg.get("proved_at_entry") is not None,
            }
        # EVERY SCRIPT THAT ACTUALLY RAN. `equivalence_script_sha256_executed`
        # above names the FIRST leg's bytes — which is the whole of what ran on
        # the single-process path, and the entry of what ran on the per-rung
        # one. The rest are named here rather than left unstated.
        proof_execution["ladder_leg_script_sha256s"] = [
            lg["script_sha256"] for lg in ladder_legs]
        _rung_peaks = [lg["peak_rss_kib"] for lg in ladder_legs
                       if lg.get("peak_rss_kib") is not None]
        ladder_record.update({
            "per_rung_processes": _per_rung,
            "legs": ladder_legs,
            "processes_launched": sum(1 for lg in ladder_legs if lg["launched"]),
            "stopped_because": _ladder_stop,
            "stopped_on_no_progress": _stopped_on_no_progress,
            # THE CEILING PROPERTY, stated as a number a reader can check: with
            # one rung per process the ladder's peak is the MAX of the rungs;
            # the SUM is published beside it because that is what the peak used
            # to be, and their difference is the defect this closed.
            "peak_rss_kib": max(_rung_peaks) if _rung_peaks else None,
            "sum_of_rung_peaks_kib": sum(_rung_peaks) if _rung_peaks else None,
            "peak_rss_kib_source": ("max over per-rung processes" if _per_rung
                                    else "one process ran every rung"),
            "proof_state_carry": proof_state_carry(ladder_legs),
            "processes": len(ladder_legs),
            # Did the ladder climb EVERY rung? None on the single-process path,
            # where the parser's own rule already answers it correctly and this
            # must not disturb it.
            "complete": ((_ladder_stop == _LADDER_COMPLETE
                          or _stopped_on_no_progress)
                         if _per_rung else None),
        })
        # BOTH LEGS, HASH-BOUND. A resumed PASS is stored under the same key a
        # from-zero PASS would use, so the entry has to carry the evidence for
        # the whole proof and not just for the half this process ran. The
        # carried leg is the checkpoint's own copy (revalidated at selection);
        # this leg is the log this invocation produced. Named and hashed here,
        # so a reader of the cached report can re-check either one.
        _legs: List[Dict[str, Any]] = []
        # THE ENTRY CHECKPOINT, not the one the rung loop last advanced to.
        # `resume_from` is rebound on every leg, so reading it here would name
        # the checkpoint this invocation ENDED on and call it the evidence it
        # CARRIED IN — which is the opposite of what a carried leg is.
        if (_entry_resume_from is not None
                and _entry_resume_from.get("evidence_log")):
            _legs.append({
                "leg": "carried",
                "path": Path(_entry_resume_from["evidence_log"]).name,
                "sha256": _entry_resume_from.get("evidence_log_sha256"),
                "through_rung": _entry_resume_from["rung"],
            })
        try:
            if live_log_path is not None and Path(live_log_path).is_file():
                _legs.append({
                    "leg": "this_invocation",
                    "path": Path(live_log_path).name,
                    "sha256": _sha256_file_streamed(Path(live_log_path)),
                    "bytes": Path(live_log_path).stat().st_size,
                })
            else:
                # NOT_MEASURED, never a fabricated entry: the leg ran, and the
                # log this process was tee-ing is simply not readable here.
                _legs.append({"leg": "this_invocation", "state": "unreadable"})
        except OSError as _exc:
            _legs.append({"leg": "this_invocation", "state": "unreadable",
                          "error": str(_exc)})
        proof_execution["evidence_legs"] = _legs
        return _launched, _raw

    # The deadline is established HERE, once, before the first attempt.
    budget = StepBudget(args.timeout)
    t0 = time.time()
    if cache_hit_report is not None:
        launched = True
        raw = cache_hit_report.get("_cache_source_rpt", "")
    else:
        launched, raw = _run("verilog")

    # SLANG GOLD-READ FALLBACK: the built-in `read_verilog -sv` gold read ABORTED
    # (no miter built) on an SV closure the reader can't PARSE (package-scope
    # refs, unpacked-array ports) OR can't ELABORATE (an SV package/enum constant
    # used as a parameter value → the built-in const-evaluator's "non-constant
    # value" abort; ibex). Retry the gold with `read_slang` — a COMPLETE MIRROR
    # of the synth frontend: the SAME SV-2017 reader AND the SAME define-set
    # progression (rv-aes). synth reads `-DSIMULATION -DYOSYS` primary and, on a
    # sim-only-construct failure ($urandom / std::randomize / $value$plusargs in
    # a dead `ifdef SIMULATION arm), retries `-DSYNTHESIS -DYOSYS` (the
    # synthesizable `else — the arm the gate was actually built from). Mirror
    # that two-pass so the gold matches the gate. Only retry on a genuine
    # zero-miter abort; if slang ALSO fails (under BOTH define sets), record it
    # so the verdict is finalized to FAIL (never a non-blocking pass for a design
    # the capable frontend also can't build).
    slang_retry_failed = False
    gold_frontend_reason = ""
    if launched:
        _p1 = parse_equiv_output(
            raw, ladder_complete=ladder_record.get("complete"))
        _retry_gold, gold_frontend_reason = should_retry_gold_with_slang(
            _p1, raw, gold_requires_sv2017(gold_files))
        if _retry_gold and budget.next_attempt_budget() == 0:
            # THE CEILING IS THE TOTAL: a retry that would re-arm a spent budget
            # is not launched at all. Only the RETRY is refused — the verdict
            # stays whatever the evidence already supports.
            budget.skipped("slang", gold_defines,
                           "step wall budget exhausted before the gold-read "
                           "retry")
            print("[lec_run] gold-frontend retry NOT launched: the step's "
                  f"total {budget.total_s}s wall budget is spent "
                  f"({round(budget.elapsed_s(), 2)}s elapsed). A retry must "
                  "not re-arm a deadline.", file=sys.stderr)
            _retry_gold = False
        if _retry_gold:
            try:
                from synth_frontend import resolve_slang_load_prefix
                slang_prefix = resolve_slang_load_prefix(container, _docker_exec3)
            except Exception:
                slang_prefix = ""  # fork-safe default: read_slang built-in
            print(f"[lec_run] FALLBACK gold frontend verilog → slang: "
                  f"{gold_frontend_reason}. Retrying the gold read with "
                  "read_slang (SV-2017 frontend, -DSIMULATION define set).",
                  file=sys.stderr)
            launched2, raw2 = _run("slang", slang_prefix, gold_defines)
            if launched2:
                _p2 = parse_equiv_output(
                    raw2, ladder_complete=ladder_record.get("complete"))
                raw = raw2
                gold_frontend = "slang"
                if not _p2["parse_error"]:
                    print("[lec_run] read_slang gold read built a miter "
                          "(SV-2017 frontend).", file=sys.stderr)
                else:
                    # DEFINE-SET MIRROR (synth #668): did slang die on a sim-only
                    # construct ($urandom etc.) in the dead `ifdef SIMULATION arm?
                    # Retry under -DSYNTHESIS (the synthesizable else — how synth
                    # built the gate), reusing the SAME decision the synth path
                    # uses (synth_frontend_should_retry_under_synthesis).
                    _retry = False
                    try:
                        from synth_frontend import \
                            synth_frontend_should_retry_under_synthesis
                        from synth_frontend import read_text_blob
                        # v1.4.x OBSERVABLE-OVER-WORDING: the OBSERVABLE is that
                        # the slang gold read built no miter (_p2 parse_error —
                        # the `else` we are in); the DESIGN PROPERTY (does the
                        # gold source branch on the define set) comes from the
                        # gold RTL itself, not from slang's phrasing.
                        _retry, _reason = \
                            synth_frontend_should_retry_under_synthesis(
                                raw2,
                                rtl_text_blob=read_text_blob(gold_files),
                                produced_output=False)
                    except Exception:
                        _retry = False
                    # TWO INDEPENDENT DECLINES, both kept, in this order.
                    # (1) A wall-budget kill on the slang rung is not a
                    # define-set problem either (same measurement and reasoning
                    # as budget_kill_blocks_frontend_retry). Without this the
                    # THIRD rung spends a third full budget on the same
                    # undecided proof before anything is recorded. `_b3` is read
                    # again below, so this must run first.
                    _b3, _b3_ev = budget_kill_blocks_frontend_retry(raw2)
                    if _b3:
                        _retry = False
                        gold_frontend_reason = _b3_ev
                        print("[lec_run] -DSYNTHESIS gold retry DECLINED: "
                              + _b3_ev, file=sys.stderr)
                    else:
                        # The same asymmetry as the call site in
                        # `should_retry_gold_with_slang` above: without this
                        # branch a reader cannot tell a check that RAN and
                        # passed from one that was never reached, and the third
                        # rung then spends a full budget with nothing in the
                        # log to say why it was allowed to.
                        print(f"[lec_run] -DSYNTHESIS gold retry: budget-kill "
                              f"check consulted, _b3={_b3!r} — not declined "
                              f"here.", file=sys.stderr)
                    # (2) A DIFFERENT condition: the rung was not killed, but
                    # the step's TOTAL wall budget is already spent, so a retry
                    # would have to re-arm a deadline. Budget accounting, not a
                    # kill marker - neither test implies the other, so neither
                    # may replace the other.
                    if _retry and budget.next_attempt_budget() == 0:
                        budget.skipped(
                            "slang", "-DSYNTHESIS -DYOSYS",
                            "step wall budget exhausted before the define-set "
                            "retry")
                        print("[lec_run] -DSYNTHESIS retry NOT launched: the "
                              f"step's total {budget.total_s}s wall budget is "
                              "spent. A retry must not re-arm a deadline.",
                              file=sys.stderr)
                        _retry = False
                    if _retry:
                        gold_defines = "-DSYNTHESIS -DYOSYS"
                        print("[lec_run] read_slang -DSIMULATION died on a "
                              "sim-only construct → retrying -DSYNTHESIS (mirror "
                              "synth #668).", file=sys.stderr)
                        launched3, raw3 = _run("slang", slang_prefix, gold_defines)
                        if launched3:
                            _p3 = parse_equiv_output(
                                raw3,
                                ladder_complete=ladder_record.get("complete"))
                            raw = raw3
                            if _p3["parse_error"]:
                                slang_retry_failed = True
                        else:
                            slang_retry_failed = True
                    else:
                        # slang failed for a non-define reason → no free pass.
                        slang_retry_failed = not _b3
                    if slang_retry_failed:
                        print("[lec_run] read_slang could not build the gold "
                              "miter under either define set → verdict finalized "
                              "to FAIL (no free pass).", file=sys.stderr)
    elapsed = round(time.time() - t0, 2)

    # THE EVIDENCE FOR A RESUMED PROOF IS BOTH LEGS. The rungs below the
    # checkpoint ran in a PREVIOUS invocation, so this run's log cannot contain
    # them -- and `parse_equiv_output` reads exactly that missing evidence to
    # tell "the induction did not converge, and it recorded no counterexample"
    # (INCONCLUSIVE) from "the designs may genuinely differ" (FAIL). MEASURED on
    # sha256 before this: from-zero INCONCLUSIVE, resumed FAIL, same 798/1039
    # counts, same design. The prior leg's own stop markers are stripped --
    # they say how THAT leg ended -- and the count of them is recorded.
    _carried_text, _carried_stops = "", 0
    _carried = (resume_record.get("resumed_from") or {}).get("evidence_log") \
        if resume_record.get("resumed") else None
    if _carried:
        try:
            _carried_text, _carried_stops = strip_producer_stop_markers(
                Path(_carried).read_text(encoding="utf-8", errors="replace"))
        except OSError as _exc:
            # NOT_MEASURED, and it must not become a different verdict: the
            # selector already refused any checkpoint whose evidence would not
            # revalidate, so reaching here means it vanished between then and
            # now. Say so; do not silently classify on half a proof.
            _carried_text, _carried_stops = "", 0
            resume_record["carried_evidence_error"] = str(_exc)
            print(f"[lec_run] WARN: carried evidence unreadable: {_exc}",
                  file=sys.stderr)
    if _carried_text:
        resume_record["carried_evidence"] = {
            "log": Path(_carried).name,
            "sha256": (resume_record.get("resumed_from") or {}).get(
                "evidence_log_sha256"),
            "bytes": len(_carried_text.encode("utf-8")),
            "prior_leg_stop_markers_stripped": _carried_stops,
            "prior_leg_was_stopped": _carried_stops > 0,
        }
        raw = _carried_text.rstrip("\n") + "\n" + raw

    # Always persist the raw tool log for transparency / gate corroboration.
    # On a cache hit this is the byte-revalidated source report, while the new
    # invocation attestation lives in lec.json and its unique telemetry file.
    # For a resumed run this is BOTH legs, in order, which is the proof.
    _atomic_write_bytes(rpt_out, raw.encode("utf-8"))

    # WAS THIS RUN STOPPED? Asked ONCE, of this run's own log, through the
    # predicate that owns the question. Spelled inline as
    # `bool(_EXECUTION_STOP_RE.search(raw))` the match sat inside the expression
    # assigned to `report`, which makes `report` a match-derived name for every
    # later reader of it — `prose_polarity_consulted_check` reported exactly
    # that, correctly, about the shape. One predicate, asked once, also cannot
    # answer differently at the two call sites below.
    stopped_this_run = run_was_stopped(raw)

    if not launched:
        print(f"[lec_run] ERROR: yosys did not run in '{container}' "
              "— runner should disclosed-skip. Raw log at reports/lec.rpt.",
              file=sys.stderr)
        # Still emit a truthful diagnostic JSON (equivalent:false, no fake data).
        diag = build_report(
            {"proven": None, "unproven": None, "total": None,
             "sat_model_unsupported_cells": [], "unproven_cells": [],
             "success_line": False, "parse_error": True, "equivalent": False,
             "verdict": "FAIL",
             "verdict_explanation": (
                 "Yosys/Docker could not run — no equivalence evidence "
                 "produced. See reports/lec.rpt.")},
            resolved_top, gate_abs, liberty, liberty_source)
        diag = annotate_step_budget(diag, budget, stopped=stopped_this_run)
        diag["lec_resume"] = resume_record
        diag["lec_ladder"] = ladder_record
        _telemetry_finish("tool_unavailable", verdict=diag["verdict"],
                          equivalent=False,
                          current_pass=lec_stage_from_output(raw))
        diag = attach_telemetry(diag, telemetry_path, project)
        _atomic_write_json(json_out, diag)
        return 1

    parsed = parse_equiv_output(
        raw, ladder_complete=ladder_record.get("complete"))
    if controlled_rung_limit_hit:
        # The cap is an operator-requested admission boundary, not equivalence
        # evidence.  Even if a local rung's `equiv_status` printed a happy
        # phrase, later required rungs were deliberately not launched, so the
        # only honest terminal result is INCONCLUSIVE.  Keep measured point
        # counts and parser diagnostics intact; override only the conclusion.
        parsed = dict(parsed)
        parsed["verdict"] = "INCONCLUSIVE"
        parsed["equivalent"] = False
        parsed["verdict_explanation"] = (
            "Controlled completed-rung limit reached after "
            f"{bounded_rung_policy['completed_rungs_this_invocation']} "
            "log-attested checkpointed rung(s); no later rung was launched. "
            "The proof is resumable where the receipt names it, but the "
            "designs are neither proven equivalent nor proven different.")
    if cache_hit_report is not None:
        report = copy.deepcopy(cache_hit_report)
        report.pop("_cache_source_rpt", None)
        report["elapsed_sec"] = elapsed
        report["execution_mode"] = "exact-pass-cache-hit"
        report["lec_attempts"] = 0
        report["lec_attempts_detail"] = []
        report["step_budget_sec"] = args.timeout
        report["step_elapsed_sec"] = round(budget.elapsed_s(), 2)
        report["step_budget_exhausted"] = False
        report["exhausted_resource"] = None
        report["step_budget_stopped_this_proof"] = False
    else:
        # §4.05 NO-LEAK: if the slang retry was attempted and slang ALSO failed
        # to build a miter, downgrade provisional INCONCLUSIVE to FAIL — a
        # design the capable frontend cannot elaborate is not a free pass.
        parsed = finalize_after_slang_retry(parsed, slang_retry_failed)
        report = build_report(parsed, resolved_top, gate_abs, liberty,
                              liberty_source)
        report["elapsed_sec"] = elapsed
        # WHAT was attempted, WHICH resource ran out, HOW MANY attempts.
        # `stopped` is MEASURED from this run's own log -- the producer writes
        # those two markers itself and nothing else can -- so the budget
        # sentence follows the evidence rather than the verdict word.
        report = annotate_step_budget(
            report, budget, stopped=stopped_this_run,
            ladder_complete=ladder_record.get("complete"))
        report["gold_rtl_files"] = [Path(f).name for f in gold_files]
        report["gold_frontend"] = gold_frontend
        report["gold_defines"] = (
            gold_defines if gold_frontend == "slang" else None)
        report["gold_frontend_reason"] = gold_frontend_reason or None
        report["execution_mode"] = "fresh-yosys-proof"
    # THE BOUND AND WHETHER IT WAS HIT. Without these a reader of lec.json
    # cannot tell a proof that DECIDED nothing from a proof that was never
    # given enough resources to decide anything -- the exact confusion that
    # made a 2h grind indistinguishable from a hang. `yosys_budget_s` is the
    # bound the CALLER set (--timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S);
    # `budget_exhausted` is True only when THIS program's own budget-kill
    # marker is in the log; `proof_stages_attempted` names the yosys passes
    # that actually ran, so "what was attempted" is evidence, not a guess.
    report["yosys_budget_s"] = args.timeout
    report["budget_exhausted"] = bool(_TIMEOUT_RE.search(raw))
    report["progress_stalled"] = bool(_STALL_RE.search(raw))
    report["proof_stages_attempted"] = yosys_executed_passes(raw)[:40]
    report["parse_error"] = bool(parsed.get("parse_error"))
    # WHAT WAS CONSTRAINED, ALWAYS. Recorded on every run — including the runs
    # where nothing was constrained, with the reason — so a PASS on a scan
    # netlist can never be read without seeing the mode it was proven in, and a
    # scan netlist compared WITHOUT the constraints is visible as such rather
    # than looking like an ordinary comparison.
    report["scan_functional_mode"] = scan_record
    report["bounded_rung_policy"] = bounded_rung_policy
    # WHERE THIS PROOF CAN BE PICKED UP FROM. Without this a reader of a
    # stalled or budget-stopped lec.json cannot tell that the work the run DID
    # do is on disk and where — which is why every restart used to re-prove
    # from zero and nothing in the artefact said it had to.
    if cache_hit_report is not None:
        resume_record["state"] = "CACHE_HIT_NOTHING_RESUMED"
        resume_record["statement"] = (
            "an exact PASS cache entry revalidated, so yosys was never "
            "launched: a checkpoint may have been SELECTED while building the "
            "identity, but none was read and none was written by this run")
    elif checkpoint_enabled and resume_record.get("checkpoint_key"):
        _cdir = project / DEFAULT_CHECKPOINT_REL / \
            str(resume_record["checkpoint_key"]).split(":", 1)[-1]
        resume_record["rungs_available"] = list_checkpoint_rungs_declared(
            _cdir, resume_record["checkpoint_key"],
            resume_record.get("base_script_sha256") or "")
        _furthest = (resume_record["rungs_available"][-1]
                     if resume_record["rungs_available"] else None)
        _complete = bool(report.get("verdict") == "PASS"
                         or (ladder_record.get("complete") is not False
                             and not report.get("budget_exhausted")
                             and not report.get("progress_stalled")
                             and not report.get("parse_error")))
        if _complete:
            resume_record["state"] = "COMPLETE"
            resume_record["state_label"] = report.get("verdict")
            resume_record["statement"] = (
                "the proof ran to a completed equiv_status; the checkpoints "
                f"on disk ({resume_record['rungs_available']}) are evidence, "
                "not work to be finished")
        elif _furthest is not None:
            resume_record["state"] = "RESUMABLE"
            resume_record["resumable_from_rung"] = _furthest
            resume_record["state_label"] = (
                f"{report.get('verdict')}-resumable-from-rung-"
                f"{ladder_index(_furthest)}")
            resume_record["statement"] = (
                f"the proof did NOT complete ({report.get('verdict')}) and a "
                f"revalidatable checkpoint stands at rung {_furthest} "
                f"(index {ladder_index(_furthest)}): a re-invocation on these "
                "exact inputs resumes THERE and does not re-prove the rungs "
                "before it. This is not a pass and it never seeds the PASS "
                "cache.")
        else:
            resume_record["state"] = "NO_CHECKPOINT"
            resume_record["state_label"] = report.get("verdict")
            resume_record["statement"] = (
                "the proof did not complete and no rung finished, so there is "
                "nothing to resume from — a restart starts over, and that is "
                "a measured fact about this run rather than a default")
    report["lec_resume"] = resume_record
    # R-0915-97(3) — the alias pre-pass and the blacklist second pass, in the
    # report, by name. A finding is a FINDING (it names the memory and why no
    # alias was emitted), and every blacklisted name carries its synth-log line
    # and its proven Q, which is the evidence that it is not a waiver.
    if mem_alias_record:
        report["lec_memory_word_aliases"] = list(mem_alias_record)
    if mem_alias_findings:
        report.setdefault("findings", []).extend(mem_alias_findings)
        report["lec_memory_alias_findings"] = list(mem_alias_findings)
    if blacklist_record:
        report["lec_enable_fold_blacklist"] = list(blacklist_record)
    if blacklist_pass:
        report["lec_blacklist_pass"] = dict(blacklist_pass)
    # THE PER-RUNG TABLE (vibe-ic#2194): which rung ran in which process, what
    # each one peaked at, and whether the proved set survived every boundary.
    report["lec_ladder"] = ladder_record
    # WHAT RAN, beside WHAT WAS PROVED. `proof_identity` is the recipe — the
    # key a PASS is cached under, identical for a from-zero and a resumed run
    # of the same design — so the bytes this invocation actually executed and
    # the evidence legs it read are recorded here, where a reader can check
    # them and no cache lookup depends on them.
    if cache_hit_report is not None:
        # A CACHE HIT RAN NOTHING, so it has no execution record of its own —
        # and overwriting the source proof's with this invocation's empty one
        # would publish an all-None record as if it were a measurement. The
        # cached report's `proof_execution` describes the run that produced the
        # proof and is KEPT; what this invocation did is stated beside it.
        _src = report.get("proof_execution")
        report["proof_execution"] = {
            "schema_version": LEC_PROOF_EXECUTION_SCHEMA_VERSION,
            "path": "cache-hit",
            "yosys_launched": False,
            "source_proof_execution": (
                _src if isinstance(_src, dict)
                else {"state": "not recorded by the run that produced this "
                                "cache entry"}),
            "statement": (
                "this invocation launched no yosys; `source_proof_execution` "
                "is the record of the run that produced the cached proof"),
        }
    else:
        report["proof_execution"] = proof_execution
    # A per-invocation receipt prevents a later normal run from silently
    # overwriting the finding that this particular invocation stopped by its
    # requested resource counter.  It is written atomically, and the main
    # report names its exact path.  No receipt is emitted on the default path.
    if controlled_rung_limit_hit:
        controlled_receipt = rpt_out.parent / (
            f"{CONTROLLED_LIMIT_RECEIPT_PREFIX}.{invocation_id}.json")
        controlled_doc = {
            "schema_version": CONTROLLED_LIMIT_RECEIPT_SCHEMA_VERSION,
            "invocation_id": invocation_id,
            "verdict": "INCONCLUSIVE",
            "equivalent": False,
            "policy": bounded_rung_policy,
            "stopped_because": ladder_record.get("stopped_because"),
            "checkpoint": {
                "state": resume_record.get("state"),
                "resumable_from_rung": resume_record.get("resumable_from_rung"),
                "rungs_available": resume_record.get("rungs_available"),
                "checkpoint_key": resume_record.get("checkpoint_key"),
            },
            "measured_counts": {
                "compared_points": report.get("compared_points"),
                "unproven_points": report.get("unproven_points"),
                "non_equivalent_points": report.get("non_equivalent_points"),
            },
            "statement": (
                "A deterministic completed-rung policy stopped this "
                "invocation between complete checkpoints. This receipt is not "
                "a PASS or FAIL and cannot seed the PASS cache."),
        }
        _atomic_write_json(controlled_receipt, controlled_doc)
        try:
            report["controlled_limit_receipt"] = str(
                controlled_receipt.relative_to(project))
        except ValueError:
            report["controlled_limit_receipt"] = str(controlled_receipt)
    else:
        report["controlled_limit_receipt"] = None
    if final_proof_identity is not None:
        report["proof_identity"] = final_proof_identity
    if cache_hit_report is None:
        if (final_proof_identity is not None
                and proof_identity_complete(final_proof_identity)):
            report["cache"] = {
                "enabled": True, "hit": False,
                "cache_key": lec_cache_key(final_proof_identity),
                "directory": DEFAULT_CACHE_REL,
            }
        else:
            report["cache"] = {
                "enabled": False, "hit": False,
                "reason": "one or more required proof fingerprints unavailable",
                "directory": DEFAULT_CACHE_REL,
            }
    else:
        report["cache"] = {
            "enabled": True, "hit": True,
            "cache_key": report["cache_use_attestation"]["cache_key"],
            "directory": DEFAULT_CACHE_REL,
        }

    _telemetry_finish(
        "cache_hit" if cache_hit_report is not None else "complete",
        verdict=report.get("verdict"), equivalent=report.get("equivalent"),
        current_pass=("cache_hit" if cache_hit_report is not None
                      else lec_stage_from_output(raw)),
        # THE RESUME FACT, in the sidecar as well as the report: the sidecar is
        # what a supervisor writes and a monitor reads while the step is still
        # running, and it is the artefact that recorded a ceiling kill without
        # ever saying how far the proof had got.
        resumed_from=resume_record.get("resumed_from"),
        carried_evidence=resume_record.get("carried_evidence"),
        checkpoint_key=resume_record.get("checkpoint_key"),
        checkpoint_state=resume_record.get("state"),
        rungs_recorded=resume_record.get("rungs_recorded_this_run"))
    report = attach_telemetry(report, telemetry_path, project)
    _atomic_write_json(json_out, report)

    if (cache_hit_report is None and final_proof_identity is not None
            and pass_cache_eligible(report)):
        report["source_proof_timestamp"] = _utc_now()
        # Re-write once so the source report and the user-visible report are
        # exactly the same bytes before hashing them into the cache manifest.
        _atomic_write_json(json_out, report)
        store_pass_cache(
            cache_dir, final_proof_identity, report, raw,
            source_proof_timestamp=report["source_proof_timestamp"])

    print(json.dumps({
        "verdict": report["verdict"],
        "equivalent": report["equivalent"],
        "compared_points": report["compared_points"],
        "unproven_points": report["unproven_points"],
        "sat_model_unsupported_cells":
            len(report["sat_model_unsupported_cells"]),
        "json": str(json_out),
        "rpt": str(rpt_out),
    }, indent=2, ensure_ascii=False))

    # PRODUCER contract: 0 whenever a truthful verdict was written (PASS,
    # SKIPPED-CONDITION, INCONCLUSIVE, or an evidence-backed FAIL). 1 only when
    # Yosys ran but produced no parseable evidence AND it is not a frontend
    # parse-abort (INCONCLUSIVE) nor a disclosed wall-budget skip
    # (SKIPPED-CONDITION) — both are truthful, visible-non-PASS verdicts, not
    # tool failures. An evidence-backed timeout FAIL keeps parse_error+FAIL → 1.
    return 1 if (parsed["parse_error"]
                 and parsed["verdict"] not in ("INCONCLUSIVE",
                                               "SKIPPED-CONDITION")) else 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(entry))
