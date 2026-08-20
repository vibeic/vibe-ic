#!/usr/bin/env python3
"""The ONE answer to "are these bytes the bytes THIS RUN produced?".

WHY THIS MODULE EXISTS
======================
`adversarial_agent` (#1119) executes two shape-preserving attacks against the
sign-off gates:

    A3_CROSS_DESIGN   copy design B's same-named reports into design A's cell
    A2_STALE_REPLAY   copy an EARLIER run of the SAME design's reports in

Measured on the published corpus, with the gates' own CLIs, thirteen
(attack, gate) pairs produced a green from evidence that was not theirs:
six gates under A3, six under A2, and one under A1 (destructive overwrite).
The reason is uniform and it is not a parsing bug — every one of those gates
reads a report, parses it correctly, finds a clean verdict, and says PASS.
The report is simply not this run's, and NOTHING IN THE GATE ASKED.

    A gate that cannot tell WHOSE report it read is signing a statement
    about a design it never examined.

The one gate that survived A3 (`--mode sta`) did NOT survive it by checking
anything: the donor's timing reports happened to carry a real violation, so a
CONTENT check caught what an IDENTITY check would have caught for the right
reason. A donor that was merely clean would have forged that green too. So
there was no run-identity defence anywhere in the flow, and "six of seven"
overstated the one that was there.

WHAT A RUN ALREADY RECORDS — TWO REGISTERS, BOTH ALREADY WRITTEN
================================================================
Nothing here asks a producer for new information. Both registers exist, are
published, and already cover the sign-off reports:

    provenance.jsonl            `outputs: {relpath: "sha256:<hex>"}` per
                                tool invocation (`provenance_logger`)
    steps/**/STEP_RECORD.json   `declared_outputs: [{rel, sha256, ...}]` per
                                flow step (`step_write_ledger`)

Measured over every cell in the published corpus that carries either register
(22 cells, `provenance.jsonl` and/or `steps/`):

    ledger entries 362   present 200   bytes AGREE 200   DISAGREE 0

Zero disagreements anywhere. A check that fires only on DISAGREEMENT therefore
costs nothing on an honest tree, which is criterion 2 of
`skills/flow-change-acceptance` and the reason this is safe to make BLOCKING.

THE THREE STATES, AND WHY UNRECORDED IS NOT A FAILURE
=====================================================
    BOUND       a register names this relpath and the bytes on disk are one of
                the values it recorded. The evidence is this run's.
    MISMATCH    a register names this relpath and the bytes are NONE of the
                recorded values. Somebody replaced the evidence after the run
                recorded it. This is the finding.
    UNRECORDED  no register names this relpath. NOTHING IS CLAIMED. A local
                run, an imported tree, or a step whose producer does not
                record its outputs all land here, and turning that into a
                failure would redden legitimately-complete designs — the
                false-positive machine `flow-change-acceptance` §2 forbids.

`UNRECORDED` is DISCLOSED, never silent: :meth:`Assessment.disclosure` names
the count and :meth:`Assessment.summary` carries it into the gate's own JSON,
so a reader can see exactly how much of a verdict rests on bound evidence and
how much rests on bytes nobody vouched for. A gate that quietly found no
register would be indistinguishable from a gate that checked and was happy —
the `unmeasured-reads-as-a-measured-zero` shape this repo keeps paying for.

A RELPATH MAY CARRY MORE THAN ONE RECORDED HASH, LEGITIMATELY
=============================================================
A run that writes the same path twice records it twice with different hashes
(measured: one multicorner timing report is declared by two invocations of the
same tool, setup and hold, with different bytes). So the ledger maps a relpath
to a SET, and BOUND means "the bytes match SOMETHING this run recorded". Any
stricter rule would have to decide which record is final, which the registers
do not state, and would fire on honest trees. Paths with more than one
recorded value are counted in the summary as `ambiguous` rather than being
silently collapsed.

ENFORCEMENT: this module decides nothing on its own. It reports states. Each
call site declares what a MISMATCH does there, from a MEASUREMENT rather than
an intention — and the answer is not uniform: `flow_gate_enforcement_audit`
classifies `sta_report_check` and `em_report_check` ENFORCED and the other five
sign-off wrappers, plus `erc_density_check`, AUDIT_ONLY. A MISMATCH always
turns the gate's own verdict red and its exit code 1; for five of seven that is
recorded and the run continues. Both call sites say which they are.

chip-AGNOSTIC: no design, PDK, vendor or cell literal appears here or can. The
only inputs are relative paths, sha256 digests and the two register formats.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

#: The registers, spelled as the producers spell them.
PROVENANCE_NAME = "provenance.jsonl"
STEP_RECORD_GLOB = "steps/**/STEP_RECORD.json"

BOUND = "BOUND"
MISMATCH = "MISMATCH"
UNRECORDED = "UNRECORDED"
UNREADABLE = "UNREADABLE"

#: The finding rule name a call site raises on a MISMATCH. One spelling, so a
#: reader grepping for the defect finds every gate that can report it.
RULE = "EVIDENCE_NOT_FROM_THIS_RUN"


def _sha256_of(path: Path) -> Optional[str]:
    """The file's digest, or None when it cannot be read.

    NEVER raises. An unreadable report is already a finding in every mode that
    consumes one; manufacturing a binding failure out of it would attribute a
    permissions error or a dangling symlink to forgery.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except (OSError, ValueError):
        return None
    return h.hexdigest()


def _digest(value: object) -> Optional[str]:
    """`"sha256:<hex>"` and a bare `<hex>` are the same statement."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.lower().startswith("sha256:"):
        v = v[len("sha256:"):]
    v = v.strip()
    if len(v) == 64 and all(c in "0123456789abcdefABCDEF" for c in v):
        return v.lower()
    return None


@dataclass
class Ledger:
    """What this run recorded producing. `entries[relpath] -> {sha256, ...}`."""
    entries: Dict[str, Set[str]] = field(default_factory=dict)
    #: Register FILES actually read, project-relative. Empty means no register
    #: exists, which is a disclosure and not a verdict.
    registers: List[str] = field(default_factory=list)
    #: Register files that exist but could not be parsed. Counted, never
    #: silently skipped: an unreadable register is "I could not look".
    unreadable_registers: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.entries)

    @property
    def ambiguous(self) -> List[str]:
        return sorted(k for k, v in self.entries.items() if len(v) > 1)


def load_ledger(project_dir: Path) -> Ledger:
    """Read both registers. Never raises; a broken register is recorded."""
    project_dir = Path(project_dir)
    led = Ledger()

    prov = project_dir / PROVENANCE_NAME
    if prov.is_file():
        ok = False
        try:
            text = prov.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = None
        if text is None:
            led.unreadable_registers.append(PROVENANCE_NAME)
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    # ONE bad line is not a bad register — the file is
                    # append-only and a run killed mid-append leaves a partial
                    # final line. Skipping it loses that line's coverage, which
                    # degrades to UNRECORDED, never to a false MISMATCH.
                    continue
                if not isinstance(rec, dict):
                    continue
                ok = True
                for rel, val in (rec.get("outputs") or {}).items():
                    d = _digest(val)
                    if isinstance(rel, str) and d:
                        led.entries.setdefault(_norm(rel), set()).add(d)
            if ok:
                led.registers.append(PROVENANCE_NAME)
            else:
                led.unreadable_registers.append(PROVENANCE_NAME)

    for sr in sorted(project_dir.glob(STEP_RECORD_GLOB)):
        rel_name = _rel(sr, project_dir)
        try:
            doc = json.loads(sr.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            led.unreadable_registers.append(rel_name)
            continue
        if not isinstance(doc, dict):
            led.unreadable_registers.append(rel_name)
            continue
        led.registers.append(rel_name)
        for out in doc.get("declared_outputs") or []:
            if not isinstance(out, dict):
                continue
            rel, d = out.get("rel"), _digest(out.get("sha256"))
            if isinstance(rel, str) and d:
                led.entries.setdefault(_norm(rel), set()).add(d)
    return led


def _norm(rel: str) -> str:
    return str(Path(rel).as_posix()).lstrip("./")


def _rel(path: Path, project_dir: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(project_dir).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


@dataclass
class Binding:
    """One consumed artefact's state."""
    rel: str
    state: str
    actual: Optional[str] = None
    recorded: Tuple[str, ...] = ()

    @property
    def is_mismatch(self) -> bool:
        return self.state == MISMATCH

    def message(self) -> str:
        return (
            f"{self.rel} is not the artefact this run recorded producing: the "
            f"run's own ledger declares sha256 "
            f"{', '.join(s[:16] for s in self.recorded)} for that path and the "
            f"bytes on disk hash to {(self.actual or 'unreadable')[:16]}. A "
            f"sign-off gate must not certify a design from evidence that "
            f"belongs to a different run.")


@dataclass
class Assessment:
    bindings: List[Binding] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)

    @property
    def mismatched(self) -> List[Binding]:
        return [b for b in self.bindings if b.state == MISMATCH]

    @property
    def bound(self) -> List[Binding]:
        return [b for b in self.bindings if b.state == BOUND]

    @property
    def unrecorded(self) -> List[Binding]:
        return [b for b in self.bindings if b.state == UNRECORDED]

    def summary(self) -> Dict[str, object]:
        """The disclosure, in the shape a gate's JSON verdict carries."""
        return {
            "registers_read": len(self.ledger.registers),
            "registers_unreadable": len(self.ledger.unreadable_registers),
            "ledger_entries": len(self.ledger.entries),
            "consumed": len(self.bindings),
            "bound": len(self.bound),
            "unrecorded": len(self.unrecorded),
            "unreadable": len([b for b in self.bindings
                               if b.state == UNREADABLE]),
            "mismatched": len(self.mismatched),
            "mismatched_paths": [b.rel for b in self.mismatched],
            "ambiguous_ledger_paths": len(self.ledger.ambiguous),
        }

    def disclosure(self) -> str:
        """Why this assessment claims what it claims — ALWAYS emitted.

        Including when it claims nothing. "no register was found" and "every
        artefact checked out" must never be spelled the same way.
        """
        s = self.summary()
        if not self.ledger.registers:
            base = ("no run-evidence register was found (neither "
                    f"{PROVENANCE_NAME} nor {STEP_RECORD_GLOB}), so NOTHING "
                    "was verified about which run produced the artefacts this "
                    "verdict rests on")
        else:
            base = (f"{s['bound']} of {s['consumed']} consumed artefact(s) "
                    f"match the bytes this run recorded producing; "
                    f"{s['unrecorded']} are named by no register and are "
                    f"therefore UNVERIFIED, not verified-clean")
        if self.ledger.unreadable_registers:
            base += (f"; {len(self.ledger.unreadable_registers)} register "
                     f"file(s) exist but could not be parsed")
        return base


def assess(project_dir: Path, consumed: Iterable[Path],
           ledger: Optional[Ledger] = None) -> Assessment:
    """Classify every consumed artefact against the run's own ledger."""
    project_dir = Path(project_dir)
    led = ledger if ledger is not None else load_ledger(project_dir)
    out = Assessment(ledger=led)
    seen: Set[str] = set()
    for p in consumed:
        p = Path(p)
        rel = _norm(_rel(p, project_dir))
        if rel in seen:
            continue
        seen.add(rel)
        recorded = led.entries.get(rel)
        if not recorded:
            out.bindings.append(Binding(rel, UNRECORDED))
            continue
        actual = _sha256_of(p)
        if actual is None:
            out.bindings.append(Binding(rel, UNREADABLE,
                                        recorded=tuple(sorted(recorded))))
            continue
        state = BOUND if actual in recorded else MISMATCH
        out.bindings.append(Binding(rel, state, actual,
                                    tuple(sorted(recorded))))
    out.bindings.sort(key=lambda b: b.rel)
    return out
