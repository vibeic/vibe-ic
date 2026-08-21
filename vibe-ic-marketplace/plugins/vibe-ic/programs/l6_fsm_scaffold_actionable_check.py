#!/usr/bin/env python3
"""l6_fsm_scaffold_actionable_check.py — SEMANTIC layer gate for L6.

ENFORCEMENT: advisory — on both axes, TODAY, and the section below headed
"BLOCKS (exit 1)" is about a THIRD axis that is unchanged. Reconciled here
because until vibe-ic#1035 this file argued at length for blocking while the
flow wired it advisory, and nothing in the tree connected the two claims:

  * VERDICT SEVERITY — rc 1, unchanged. A finding here is a FAIL, not a
    warning. That is what "BLOCKS (exit 1)" below argues for, and the argument
    stands on its own terms: both readers of L6 degrade silently in the PASS
    direction, so a finding here becomes a manufactured PASS four steps later.
  * FLOW SLOT — `advisory_program_exit_zero`, by MEASUREMENT and not by
    preference. Re-measured on 2ec8fc2f with `tools/d9_corpus_baseline.py
    --only l6_fsm_scaffold_actionable_check`: 41 of 107 published roots red,
    0 CLEAN, 66 NO-INPUT, identical to the Phase-0 baseline at 93bfcf95f. Every
    one of the 41 is a TRUE finding, and that is exactly why blocking would be
    wrong: across all 107 published `L6_CONTROL_LOGIC.json`, 36 carry
    `fsm_states` and exactly ONE (espi) carries a single transition, because
    the prose-walker `l6_fsm_prose_walker_v1_6_484` emits `transitions: []`
    every time it runs. Blocking would fail 41 published roots for one broken
    extractor. The defect is in the PRODUCER, not in 41 designs.
  * CAN IT STOP THE STEP — no. No runner spawns this gate inline, so its
    verdict reaches step 1 only when `flow_compliance_check` evaluates the
    clause. This is the axis `flow_gate_enforcement_audit` measures and the one
    the `ENFORCEMENT:` token above names.

PROMOTION CONDITION, stated so this is a re-measurement and not a judgement
call: repair the L6 transition extractor, then re-run the command above. When
the red count is driven by designs rather than by the walker, this declaration
becomes `blocking` and the flow row becomes `program_exit_zero`.

THE CONSUMER MODEL, STATED FIRST BECAUSE PART A DEPENDS ON IT (#509)
=====================================================================
``phase2_scaffold_gen`` is an ORACLE, not a flow step. No runner and no
step of ``flow/phase1_phase2_phase3.yaml`` calls it, at any version; Phase
2 authors RTL through ``design_one_shot_runner.step_rtl_gen``. What the
module is, is an EXECUTABLE SPECIFICATION of what a conforming Phase 2
must be able to produce from L6, and Part A below drives it as such.

Every Part-A sentence is therefore COUNTERFACTUAL by construction: it says
what a conforming phase 2 WOULD be handed, not what phase 2 does receive.
That is a complete justification — the contract is what is being enforced,
and an L6 that cannot yield a scaffoldable FSM is underspecified whether or
not any program consumes it — and it is the only honest one. A blocking
gate whose stated reason does not happen is a gate nobody can evaluate.
See ``phase2_scaffold_gen``'s own docstring for the measurement.

BLOCKS (exit 1). Why a finding here is a FAIL and not a warning
===============================================================
A claim about this program's VERDICT SEVERITY only. It is NOT a claim about
the flow slot — that is decided, and measured, in the `ENFORCEMENT:` block at
the top of this docstring, which records why the row is advisory today and what
would promote it. Read on its original terms the argument below is unaffected:

Both readers of L6 degrade SILENTLY and in the PASS direction:

  * ``phase2_scaffold_gen.emit_fsm_v()`` — the scaffold contract's
    reference implementation — emits a syntactically valid Verilog
    module from whatever L6 gives it. Zero states → a file stamped
    "intentionally empty". One state → a module whose only behaviour is
    ``state <= S_<the one state>`` on reset, with the transition body
    left as a ``// TODO`` comment. Both compile. An L6 that yields
    either is indistinguishable, to every presence-shaped check, from
    one that yields a healthy scaffold.
  * ``l11_sequence_covers_l6_reject_rules_check`` contains the literal
    branch ``if not kws: # generic rule — accept any silent sequence``.
    A reject rule whose condition yields no keyword therefore does not
    fail the coverage gate — it makes the coverage gate *vacuous* for
    that rule, so ONE unrelated silent sequence "covers" every such
    rule and the gate reports PASS.

A gate whose failure mode is a manufactured PASS four steps downstream
cannot be reported as a warning. FAIL is rc 1.

The contract this gate enforces
===============================
    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an ACTIONABLE FORM — not when a token appears
    somewhere.

Part A — the FSM skeleton (previously ungated)
----------------------------------------------
``phase2_scaffold_gen.derive_fsm_states(l6)`` is the *only* path the
scaffold contract defines from L6 into a ``<top>_fsm.v``. It reads
``fsm_states`` / ``fsm_hints*`` — not ``states`` — so an L6 that puts its
state list under a key the emitter does not read yields an EMPTY FSM
while every token-presence check sees a populated layer. This gate calls
the emitter's own derivation function, so it measures exactly what a
conforming phase 2 would be handed rather than restating the rule.

Triggered only by L6's OWN self-declaration that the input contains an
FSM (``no_fsm_in_input`` / ``no_fsm_states_in_input`` both false, or a
non-empty state list). A design that honestly records "there is no FSM
in my input" is not penalised. Requirements when triggered:

  A1  ``derive_fsm_states()`` must yield >= 2 states. One state is not
      a state machine: ``emit_fsm_v`` would give it a 1-bit ``state``
      register that can never change value.
  A2  the layer must carry at least one transition — per-state
      ``transitions[]`` or a top-level ``fsm_transitions``/
      ``transitions`` list. ``emit_fsm_v``'s body is literally
      ``// TODO — transition logic per L6.fsm_transitions``; with zero
      transitions there is nothing a conforming phase 2 could scaffold
      from.
  A3  every transition target must name a state that exists in the
      derived state set. A dangling target is a scaffold that cannot
      be built. Derived purely from L6's own contents.

Part B — reject_rules actionability
------------------------------------
Triggered only when L6 declares ``reject_rules[]``. The requirement is
DERIVED by importing the consumer's own extractor,
``l11_sequence_covers_l6_reject_rules_check._rule_keywords()`` — this
gate does not restate the keyword vocabulary, so it stays correct when
that table grows.

  B1  every rule needs an identity (``name``/``rule_id``/``id``) and a
      non-empty ``condition``.
  B2  the consumer's extractor must return >= 1 keyword for the rule
      AND at least one returned keyword must occur at a TOKEN BOUNDARY
      in the rule's own text.

B2's boundary requirement is the interesting half. The consumer matches
by bare substring, so a rule condition that is a raw document scrape can
produce keywords by accident: a condition describing a 39-bit host write
yields the keyword ``9 bit`` — matched inside "39 bit" — and the
coverage gate then demands (or accepts) an L11 sequence about 9-bit
framing for a rule that has nothing to do with it. Requiring the
triggering keyword to sit on a token boundary distinguishes a distilled,
machine-matchable rule from a paragraph that happened to contain the
right letters. Fully general: no vocabulary is hardcoded here, only the
boundary predicate.

Part A is stated in terms of a contract — so it must check the contract
BINDS this design (#504)
====================================================================
Every sentence of Part A is a claim about ``phase2_scaffold_gen.
emit_fsm_v()``: what it writes when handed 0 states, 1 state, no
transitions, a dangling target. For a REUSED-IP design the scaffold
contract does not describe phase 2's obligation at all. The detected
class carries ``rtl_gen: null`` in ``ic_class_registry.json`` and the
design stages its own implementation, so ``design_one_shot_runner``
routes phase 2 through ``reused_ip_rtl_consume`` and phase 2 builds from
the staged files — a conforming phase 2 for such a design is never
obliged to derive a state enum from L6 at all. Part A's requirement then
has nothing to bind, and Phase 1 halts on it.

Note the two are different questions and #509 did not merge them. Part A
is counterfactual for EVERY design, because the oracle runs for none;
what #504 measured is narrower — that for a reused-IP design the
counterfactual itself is vacuous, since the phase 2 the contract
describes is not the phase 2 this design gets. That is what the
disclosure below discloses.

The predicate that knows this is NOT restated here. It is imported from
``_reused_ip_predicate`` — the same module ``flow_compliance_check`` and
``l_doc_structured_field_count_check`` read, so all three gates answer
"is this design's RTL reused IP?" with one implementation instead of the
three-readers/two-copies arrangement #504 measured.

AND IT IS A DISCLOSURE, NOT A PASS. This is the half that matters. What
a reused-IP project carries when Part A defers is an L6 with states, no
transitions, and nothing that checked either — certifying that as
``PASS: FSM is actionable`` would publish a document nobody read as a
verified one. So the deferral has its own verdict tier, following
``si_mcf_sta_check``'s: verdict ``VACUOUS_PASS``, **rc 2**, a
``_gate_denominator.Denominator`` recording ``examined 0`` of
``considered <derived states>`` with a written
``not_applicable_reason`` that names the states found, the transitions
absent, and the consumer that does not run — plus a ``VACUOUS_PASS:``
token on stderr. rc 2 is not rc 0: a genuinely-verified FSM still exits
0, and no reader can confuse the two.

The deferral covers Part A ONLY. Part B's consumer is
``l11_sequence_covers_l6_reject_rules_check``, which runs for every
design whatever authored the RTL, so a reject-rule failure still FAILs
at rc 1 — the disclosure of Part A is printed alongside it.

Nor is either existing escape the answer for such a design: setting
``no_fsm_in_input`` would assert the input documents no FSM when it
documents one, and the ``l6_fsm_scaffold_degraded_intentional`` waiver
asserts an intentional simplification when nothing was simplified. Both
would be false statements. A disclosed skip is the only honest shape.

Fail-safe / no-false-positive design
====================================
* No L6 file → SKIP(2).
* ``ic_class`` in {pure_analog, bare_fpga} → SKIP (no control FSM).
* L6 positively declares no FSM in the input → Part A SKIPs.
* No ``reject_rules[]`` → Part B SKIPs.
* If the consuming programs cannot be imported the gate SKIPs rather
  than guessing at their contract.
* The reused-IP deferral is evaluated ONLY after Part A has already
  produced a failure, so a design whose L6 IS scaffoldable keeps its
  rc-0 PASS. And it is fail-closed in every direction: an unimportable
  predicate module, an unclassifiable design, a class with a
  deterministic ``rtl_gen``, or a project staging no RTL all keep the
  FAIL. A scaffold-generated design is exactly the case Part A is
  correct about, and it still blocks.

Waiver: ``l6_fsm_scaffold_degraded_intentional`` (>=40 chars) in
``<project>/waivers.json``.

Usage:
    python3 l6_fsm_scaffold_actionable_check.py <project_dir> \
        [--json <out.json>]

Exit codes:
    0 = PASS / SKIP-by-class / PASS_WITH_WAIVER
    1 = FAIL (blocks)
    2 = input-missing / not-applicable (skip), and the #504 disclosed
        VACUOUS_PASS — NOT a sign-off, see above
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _gate_denominator as _gd  # noqa: E402
import _path_layout as _pl  # noqa: E402

try:
    import _reused_ip_predicate as _reused_ip  # noqa: E402
except Exception:  # noqa: BLE001 — fail-closed: no module, no deferral
    _reused_ip = None  # type: ignore[assignment]

#: Exit codes. 2 carries BOTH the pre-existing "nothing to check" skip and
#: the #504 disclosed VACUOUS_PASS — neither is a sign-off, and the phase-1
#: runner + `flow_compliance_check._check_program_exit_zero` already treat rc 2
#: as non-blocking-but-labelled, so the tier needs no new plumbing.
RC_PASS = 0
RC_FAIL = 1
RC_VACUOUS = 2

#: One unit of what Part A measures, in this gate's own terms. Named once so
#: the denominator block, the reason prose and any cross-gate disclosure sweep
#: agree by construction rather than by re-typing the string.
DENOM_UNIT = ("L6 FSM state(s) a conforming phase 2 would take into "
              "phase2_scaffold_gen.emit_fsm_v()")

WAIVER_KEY = "l6_fsm_scaffold_degraded_intentional"
WAIVER_MIN_LEN = 40

_SKIP_CLASSES = ("pure_analog", "bare_fpga")

# L6's own positive assertions that the INPUT contains no FSM.
_NO_FSM_KEYS = ("no_fsm_in_input", "no_fsm_states_in_input")

_RULE_ID_KEYS = ("name", "rule_id", "id", "rule", "rule_name")
_RULE_TEXT_KEYS = ("condition", "name", "trigger", "rule", "description")

_TRANSITION_LIST_KEYS = ("fsm_transitions", "transitions", "state_transitions")
_TRANSITION_TARGET_KEYS = ("to", "next", "next_state", "target",
                           "dest", "destination", "to_state")


# ---------------------------------------------------------------------------
# Consumer imports — the contract is derived from the consuming programs.
# ---------------------------------------------------------------------------

def _load_module(fname: str, alias: str):
    p = Path(__file__).resolve().parent / fname
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(alias, p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _load_scaffold_gen():
    """phase2_scaffold_gen — owner of derive_fsm_states()/emit_fsm_v()."""
    try:
        import phase2_scaffold_gen as psg  # type: ignore
        return psg
    except Exception:
        return _load_module("phase2_scaffold_gen.py", "_psg_for_l6_gate")


def _load_l11_gate():
    """The L11/L12 coverage gate — owner of the reject-rule vocabulary."""
    return _load_module(
        "l11_sequence_covers_l6_reject_rules_check.py", "_l11_for_l6_gate")


# ---------------------------------------------------------------------------
# L6 loading / normalisation
# ---------------------------------------------------------------------------

def _find_l6(project: Path) -> Optional[Path]:
    cand = _pl.generated_docs_dir(project) / "L6_CONTROL_LOGIC.json"
    if cand.is_file():
        return cand
    for pat in ("phase1/generated_docs/L6_CONTROL_LOGIC.json",
                "phase1/generated_docs/L6*.json",
                "**/L6_CONTROL_LOGIC.json"):
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _l6_declares_no_fsm(l6: dict) -> bool:
    """L6's own assertion that its INPUT documents contain no FSM.

    Only a POSITIVE True counts. A missing key is not an assertion, so
    a layer that simply omitted the flag is still checked (fail-closed).
    """
    return any(l6.get(k) is True for k in _NO_FSM_KEYS)


def _state_entries(l6: dict) -> List[Any]:
    """Raw state entries from every key derive_fsm_states() consults."""
    psg = _load_scaffold_gen()
    keys = ("fsm_states", "fsm_hints", "fsm_hints_transmitter",
            "fsm_hints_receiver", "fsm_hints_master", "fsm_hints_slave")
    if psg is not None:
        # Prefer the emitter's own key order when it exposes one.
        src = getattr(psg, "_FSM_STATE_KEYS", None)
        if isinstance(src, (list, tuple)) and src:
            keys = tuple(str(k) for k in src)
    out: List[Any] = []
    for k in keys:
        v = l6.get(k)
        if isinstance(v, list):
            out.extend(v)
    return out


# v1.7.74 — for #505. Per-machine view of the derived state set.
#
# `derive_fsm_states()` returns a FLAT union of every state entry in L6,
# which is what phase 2 scaffolds from. But L6 may describe MORE THAN
# ONE machine: a `typedef enum` declares a named, closed set while a
# prose walker infers a state name out of a chapter about a different
# block. Reporting that union as one machine asserts a machine the input
# never declared, and blames the closed enum for a state that is not its
# member. This grouping consumes L6's own attribution — it derives no
# grouping of its own and matches no names.
def _fsm_machines(l6: dict, derived: List[str]) -> List[Dict[str, Any]]:
    """One record per state machine L6 attributes its states to.

    Prefers L6's own `fsm_machines[]`; falls back to the per-state
    `fsm_machine` / `declared_type` attribution; falls back again to a
    single unattributed machine so pre-v1.7.74 layers keep working."""
    machines = l6.get("fsm_machines")
    if isinstance(machines, list) and machines:
        out: List[Dict[str, Any]] = []
        for m in machines:
            if not isinstance(m, dict):
                continue
            out.append({
                "machine_id": str(m.get("machine_id") or "?"),
                "closed": bool(m.get("closed")),
                "declared_type": m.get("declared_type"),
                "source": m.get("source") or "",
                "states": [str(s) for s in (m.get("states") or [])],
            })
        if out:
            return out
    order: List[str] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for st in _state_entries(l6):
        if not isinstance(st, dict):
            continue
        name = str(st.get("name") or st.get("state") or "")
        if not name:
            continue
        declared = st.get("declared_type")
        mid = str(st.get("fsm_machine")
                  or (declared if isinstance(declared, str) and declared
                      else "")
                  or str(st.get("evidence") or "").split(" (")[0]
                  or "?")
        rec = by_id.get(mid)
        if rec is None:
            order.append(mid)
            rec = by_id[mid] = {
                "machine_id": mid,
                "closed": bool(isinstance(declared, str) and declared),
                "declared_type": declared if isinstance(declared, str) else None,
                "source": str(st.get("evidence") or "").split(" (")[0],
                "states": [],
            }
        if name not in rec["states"]:
            rec["states"].append(name)
    if order:
        return [by_id[m] for m in order]
    if derived:
        return [{"machine_id": "?", "closed": False, "declared_type": None,
                 "source": "", "states": list(derived)}]
    return []


def _machine_label(m: Dict[str, Any]) -> str:
    kind = ("closed typedef enum" if m.get("closed")
            else "inferred from documents")
    return (f"{m.get('machine_id')} [{kind}, "
            f"{len(m.get('states') or [])} state(s)]")


def _declared_transitions(l6: dict) -> List[dict]:
    """Every transition L6 declares — per-state or top-level."""
    out: List[dict] = []
    for k in _TRANSITION_LIST_KEYS:
        v = l6.get(k)
        if isinstance(v, list):
            out.extend(e for e in v if isinstance(e, dict))
    for st in _state_entries(l6):
        if not isinstance(st, dict):
            continue
        for k in ("transitions", "next_states", "edges"):
            v = st.get(k)
            if isinstance(v, list):
                for e in v:
                    if isinstance(e, dict):
                        out.append({**e, "_from": st.get("name")
                                    or st.get("state")})
                    elif isinstance(e, str) and e.strip():
                        out.append({"to": e,
                                    "_from": st.get("name")
                                    or st.get("state")})
    return out


def _transition_target(tr: dict) -> str:
    for k in _TRANSITION_TARGET_KEYS:
        v = tr.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _rule_text(rule: dict) -> str:
    return " ".join(
        str(rule.get(k) or "") for k in _RULE_TEXT_KEYS).strip()


def _rule_identity(rule: dict) -> str:
    for k in _RULE_ID_KEYS:
        v = rule.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _kw_on_token_boundary(kw: str, text: str) -> bool:
    """True when `kw` occurs in `text` NOT glued to surrounding
    alphanumerics — i.e. the consumer's substring match on it is a real
    hit rather than an accident inside a longer token."""
    if not kw:
        return False
    return re.search(
        r"(?<![0-9A-Za-z])" + re.escape(kw) + r"(?![0-9A-Za-z])",
        text, re.IGNORECASE) is not None


def _scaffold_consumer_is_bypassed(project: Path) -> bool:
    """True when the scaffold contract does not bind this design's phase 2.

    The whole of Part A is stated in terms of what
    ``phase2_scaffold_gen.emit_fsm_v()`` would emit. When the design is reused
    IP — the detected class carries ``rtl_gen: null`` AND reused RTL is staged
    — ``design_one_shot_runner`` routes phase 2 through
    ``reused_ip_rtl_consume``, so a conforming phase 2 for THIS design derives
    no state enum from L6 and Part A's requirements have no obligation to be
    actionable FOR.

    Delegates to the ONE shared reader (``_reused_ip_predicate``) — no second
    copy of the predicate lives here. Fail-closed: an unimportable module or a
    raising predicate answers False, which keeps the FAIL."""
    if _reused_ip is None:
        return False
    try:
        return bool(
            _reused_ip.detected_class_rtl_gen_null_and_vendor_rtl(project))
    except Exception:  # noqa: BLE001 — a broken probe never relaxes a gate
        return False


def _deferral_reason(derived: List[Any], transitions_declared: int) -> str:
    """The written reason a reader gets INSTEAD of a verdict on Part A.

    It has to say three things or it is worse than the FAIL it replaces: what
    the layer actually carries, what it does not, and why the contract this
    part enforces does not bind this design. Chip-AGNOSTIC — the state names
    are the project's own data, never a literal in this file."""
    names = [str(s) for s in derived]
    shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
    return (
        "phase2_scaffold_gen.emit_fsm_v() — the scaffold-contract oracle every "
        "requirement in this part is stated in terms of — states no obligation "
        "for this project: the detected ic_class carries rtl_gen=null in "
        "ic_class_registry.json and reused RTL is staged, so a conforming "
        "phase 2 takes the reused_ip_rtl_consume path and builds from the "
        "staged implementation rather than deriving a state enum from L6. "
        f"WHAT L6 CARRIES, UNVERIFIED: {len(names)} derived state(s)"
        + (f" [{shown}]" if names else "")
        + f" and {transitions_declared} declared transition(s). NOTHING in "
        "this run compared those states, or the transitions they lack, "
        "against the staged implementation's own FSM. This is a disclosure "
        "that the requirement has no binding contract here — NOT a finding "
        "that the requirement is met, and NOT a sign-off on L6.")


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        r = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(r, str) and len(r.strip()) >= WAIVER_MIN_LEN:
            return True, r.strip()
    return False, ""


# ---------------------------------------------------------------------------
# Core evaluation (importable for tests)
# ---------------------------------------------------------------------------

def evaluate(project: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "gate": "l6_fsm_scaffold_actionable_check",
        "verdict": "SKIP",
        "reason": "",
        "fsm_checked": False,
        "derived_states": [],
        # v1.7.74 — for #505. The derived set broken out per machine, so
        # a reader can tell "these ten are the machine" from "these
        # eleven names were seen somewhere".
        "machines": [],
        "transitions_declared": 0,
        "reject_rules_checked": 0,
        "failures": [],
        "warnings": [],
        # #504 — Part A's consumer model, made explicit in the report rather
        # than assumed. True means phase2_scaffold_gen.emit_fsm_v() really is
        # what builds this design's FSM, so Part A's requirements bind.
        "scaffold_consumer_runs": True,
        "deferred_to_staged_rtl": [],
    }

    l6p = _find_l6(project)
    if l6p is None:
        out["reason"] = "no L6_CONTROL_LOGIC.json"
        return out
    try:
        l6 = json.loads(l6p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        out["verdict"] = "FAIL"
        out["reason"] = f"L6 is not parseable JSON: {exc}"
        out["failures"] = [out["reason"]]
        return out
    if not isinstance(l6, dict):
        out["verdict"] = "FAIL"
        out["reason"] = "L6 top level is not an object"
        out["failures"] = [out["reason"]]
        return out

    # #504 — the two parts are collected SEPARATELY because they have
    # different consumers and therefore different applicability. Part A is
    # about phase2_scaffold_gen.emit_fsm_v(), which a reused-IP design never
    # reaches; Part B is about l11_sequence_covers_l6_reject_rules_check, which
    # runs whatever authored the RTL. Merging them into one list is what made
    # the FSM half unable to state its own consumer model.
    fsm_failures: List[str] = []
    rule_failures: List[str] = []
    warnings: List[str] = []
    parts_run: List[str] = []

    # ---------------- Part A — FSM skeleton ----------------
    psg = _load_scaffold_gen()
    if psg is None:
        warnings.append(
            "phase2_scaffold_gen not importable — FSM half of the "
            "contract could not be stated; skipped rather than guessed")
    else:
        try:
            derived = list(psg.derive_fsm_states(l6))
        except Exception as exc:
            derived = []
            warnings.append(
                f"derive_fsm_states() raised {type(exc).__name__}: {exc}")
        out["derived_states"] = derived
        # v1.7.74 — for #505. Group before reasoning: the flat list is a
        # union over every machine L6 describes.
        machines = _fsm_machines(l6, derived)
        out["machines"] = machines

        raw_states = _state_entries(l6)
        fsm_asserted = (not _l6_declares_no_fsm(l6)) or bool(raw_states)

        if not fsm_asserted:
            pass  # honest "no FSM in this input" — Part A does not apply
        else:
            out["fsm_checked"] = True
            parts_run.append("fsm")
            transitions = _declared_transitions(l6)
            out["transitions_declared"] = len(transitions)

            # v1.7.74 — for #505. Report what the grouping found before
            # any verdict, so a multi-machine layer is never described
            # as one machine.
            if len(machines) > 1:
                warnings.append(
                    f"L6 attributes its states to {len(machines)} "
                    "DISTINCT state machines — "
                    + "; ".join(_machine_label(m) for m in machines[:4])
                    + ". The state list a conforming phase 2 would be "
                    "handed is their union, not one machine")
            for m in machines:
                if m.get("closed") or len(m.get("states") or []) != 1:
                    continue
                if len(machines) < 2:
                    continue
                warnings.append(
                    f"machine {m.get('machine_id')} contributes a single "
                    f"state ({(m.get('states') or ['?'])[0]}) inferred "
                    f"from {m.get('source') or 'a document'} — retained "
                    "as attributed evidence about that machine, NOT "
                    "counted as an incomplete machine of its own")

            # A1 — at least 2 states.
            if len(derived) == 0:
                fsm_failures.append(
                    "L6 asserts the input contains an FSM "
                    f"(no_fsm_in_input={l6.get('no_fsm_in_input')!r}, "
                    f"raw state entries={len(raw_states)}) but "
                    "phase2_scaffold_gen.derive_fsm_states() — the ONLY "
                    "path the scaffold contract defines from L6 into a "
                    "<top>_fsm.v — returns 0 states, so a conforming "
                    "phase 2 would write a file stamped 'intentionally "
                    "empty'. Check the state list is under a key the "
                    "emitter reads (fsm_states / fsm_hints*), not merely "
                    "under 'states'")
            elif len(derived) == 1:
                _only = machines[0] if len(machines) == 1 else None
                fsm_failures.append(
                    f"only 1 FSM state derived ({derived[0]!r}"
                    + (f", machine {_only.get('machine_id')}"
                       if _only else "")
                    + ") — emit_fsm_v() would give it a 1-bit state "
                    "register that can never change value, so the "
                    "<top>_fsm.v a conforming phase 2 owes for this L6 "
                    "is a module that cannot leave reset. A control "
                    "layer that declares an FSM must enumerate >= 2 "
                    "states")

            # A2 — at least one transition to scaffold from.
            # v1.7.74 — for #505. Same trigger, but the finding is
            # stated PER MACHINE: an eleven-state machine must not be
            # asserted where the input declares a ten-state one and
            # mentions a state of a second.
            if derived and not transitions:
                _per_machine = "; ".join(
                    _machine_label(m) for m in machines[:4]) or "?"
                fsm_failures.append(
                    "L6 declares 0 transitions (no per-state "
                    "transitions[] and no top-level fsm_transitions[]) "
                    f"for any of the {len(machines) or 1} state "
                    f"machine(s) it describes — {_per_machine}. "
                    "emit_fsm_v()'s body is literally '// TODO — "
                    "transition logic per L6.fsm_transitions', so a "
                    "conforming phase 2 would receive a state enum with "
                    "no transition information at all")

            # A3 — no dangling transition targets.
            if derived and transitions:
                try:
                    norm = {psg._sanitize_id(str(s)).upper()
                            for s in derived}
                except Exception:
                    norm = {str(s).upper() for s in derived}
                dangling: List[str] = []
                for tr in transitions:
                    tgt = _transition_target(tr)
                    if not tgt:
                        continue
                    try:
                        tgt_n = psg._sanitize_id(tgt).upper()
                    except Exception:
                        tgt_n = tgt.upper()
                    if tgt_n not in norm:
                        dangling.append(
                            f"{tr.get('_from') or '?'} -> {tgt}")
                if dangling:
                    fsm_failures.append(
                        f"{len(dangling)} transition(s) target a state "
                        "that is not in the derived state set "
                        f"({sorted(norm)}): {', '.join(dangling[:4])}. "
                        "No phase 2 can scaffold an edge to a state it "
                        "was never given")

    # ---------------- Part B — reject_rules actionability ----------------
    rules_raw = l6.get("reject_rules") or l6.get("rx_reject_rules") or []
    rules = [r for r in rules_raw if isinstance(r, dict)]
    if rules:
        l11 = _load_l11_gate()
        if l11 is None or not hasattr(l11, "_rule_keywords"):
            warnings.append(
                "l11_sequence_covers_l6_reject_rules_check not importable "
                "— reject-rule half of the contract could not be stated; "
                "skipped rather than guessed")
        else:
            parts_run.append("reject_rules")
            out["reject_rules_checked"] = len(rules)
            for idx, rule in enumerate(rules):
                ident = _rule_identity(rule)
                label = ident or f"reject_rules[{idx}]"
                cond = str(rule.get("condition") or "").strip()

                # B1 — identity + condition.
                if not ident:
                    rule_failures.append(
                        f"reject_rules[{idx}]: no name/rule_id — the "
                        "L11/L12 coverage gate reports rules by identity "
                        "and a test author cannot reference an anonymous "
                        "rule")
                    continue
                if not cond:
                    rule_failures.append(
                        f"{label}: empty condition — "
                        "l11_sequence_covers_l6_reject_rules_check "
                        "matches L11/L12 sequences against this text; "
                        "with no text the rule is uncoverable")
                    continue

                # B2 — the consumer's own extractor must find a real,
                #      token-boundary keyword.
                try:
                    kws = list(l11._rule_keywords(rule))
                except Exception as exc:
                    rule_failures.append(
                        f"{label}: consumer extractor _rule_keywords() "
                        f"raised {type(exc).__name__}: {exc}")
                    continue

                text = _rule_text(rule)
                if not kws:
                    rule_failures.append(
                        f"{label}: the consumer's own extractor "
                        "(_rule_keywords) derives NO keyword from this "
                        "rule. l11_sequence_covers_l6_reject_rules_check "
                        "then takes its 'generic rule — accept any "
                        "silent sequence' branch, so ANY one unrelated "
                        "silent sequence reports this rule as covered. "
                        "The rule is present but the coverage gate is "
                        f"vacuous for it. condition={cond[:70]!r}")
                    continue

                anchored = [k for k in kws if _kw_on_token_boundary(k, text)]
                if not anchored:
                    rule_failures.append(
                        f"{label}: every keyword the consumer derives "
                        f"({kws[:4]}) matches only INSIDE a longer token "
                        "of the condition, i.e. by accident — the "
                        "condition is a raw document fragment rather "
                        "than a distilled, machine-matchable rule. The "
                        "L11/L12 coverage gate will match sequences "
                        "against a concept this rule never meant. "
                        f"condition={cond[:70]!r}")

    if not parts_run:
        out["reason"] = (
            "L6 positively declares no FSM in the input and declares no "
            "reject_rules[] — nothing this gate can hold it to")
        return out

    # ---------------- #504 — Part A's consumer model ----------------
    # Asked ONLY once Part A has already produced a failure: a design whose L6
    # IS scaffoldable never reaches this branch and keeps its rc-0 PASS, so the
    # deferral cannot turn a verified FSM into a disclosed one. The predicate
    # is the shared reader's, not a copy.
    if fsm_failures and _scaffold_consumer_is_bypassed(project):
        out["scaffold_consumer_runs"] = False
        out["deferred_to_staged_rtl"] = fsm_failures
        fsm_failures = []
        # NO PASS WITHOUT A DENOMINATOR (_gate_denominator): the states were
        # CONSIDERED — derived out of L6, counted, named — and EXAMINED against
        # nothing, because the thing that would have examined them does not
        # run. Constructing this with examined == 0 and no reason raises, so
        # the disclosure cannot regress into silence by omission.
        _gd.attach(out, _gd.Denominator(
            unit=DENOM_UNIT,
            examined=0,
            considered=len(out["derived_states"]),
            not_applicable_reason=_deferral_reason(
                out["derived_states"], out["transitions_declared"]),
            details={
                "consumer": "phase2_scaffold_gen.emit_fsm_v",
                "consumer_runs": False,
                "actual_rtl_source": "reused_ip_rtl_consume (staged RTL)",
                "transitions_declared": out["transitions_declared"],
                "derived_states": [str(s) for s in out["derived_states"]],
            }))

    failures = fsm_failures + rule_failures
    out["failures"] = failures
    out["warnings"] = warnings
    if failures:
        # Part B failures survive the deferral: their consumer runs for every
        # design. The Part-A disclosure is reported alongside, never instead.
        out["verdict"] = "FAIL"
        out["reason"] = (
            f"{len(failures)} L6 item(s) are not actionable by their "
            f"consumers (parts checked: {'+'.join(parts_run)})")
    elif out["deferred_to_staged_rtl"]:
        # The FSM half examined nothing, so the gate has not signed it off —
        # whatever Part B found. rc 2, not rc 0.
        out["verdict"] = "VACUOUS_PASS"
        bits = [
            f"FSM scaffold contract NOT CHECKED: "
            f"{len(out['derived_states'])} state(s) derived, "
            f"{out['transitions_declared']} transition(s) declared, and "
            f"the phase2_scaffold_gen.emit_fsm_v() contract does not bind "
            f"this project (reused IP: class rtl_gen=null + staged RTL) — "
            f"disclosed skip, NOT a sign-off"]
        if "reject_rules" in parts_run:
            bits.append(f"{out['reject_rules_checked']} reject_rule(s) "
                        "machine-matchable by the L11/L12 coverage gate")
        out["reason"] = "; ".join(bits)
    else:
        bits = []
        if "fsm" in parts_run:
            bits.append(f"{len(out['derived_states'])} state(s) / "
                        f"{out['transitions_declared']} transition(s) "
                        "satisfy the phase2_scaffold_gen contract")
        if "reject_rules" in parts_run:
            bits.append(f"{out['reject_rules_checked']} reject_rule(s) "
                        "machine-matchable by the L11/L12 coverage gate")
        out["verdict"] = "PASS"
        out["reason"] = "; ".join(bits)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("project")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("[SKIP] l6_fsm_scaffold_actionable_check: "
              f"project dir not found: {project}")
        return 2

    try:
        from ic_class_profile import detect_ic_class  # noqa: E402
        ic_class = detect_ic_class(project).get("ic_class", "unknown")
    except Exception:
        ic_class = "unknown"
    if ic_class in _SKIP_CLASSES:
        print("[SKIP] l6_fsm_scaffold_actionable_check: "
              f"ic_class={ic_class} (no control FSM for this IC class)")
        return 2

    res = evaluate(project)
    res["ic_class"] = ic_class

    if args.json_out:
        try:
            p = Path(args.json_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        except OSError:
            pass

    for w in res.get("warnings", []):
        print(f"[WARN] l6_fsm_scaffold_actionable_check: {w}")

    if res["verdict"] == "SKIP":
        print(f"[SKIP] l6_fsm_scaffold_actionable_check: {res['reason']}")
        return RC_VACUOUS
    if res["verdict"] == "PASS":
        print(f"[PASS] l6_fsm_scaffold_actionable_check: {res['reason']}")
        return RC_PASS
    if res["verdict"] == "VACUOUS_PASS":
        # The FIRST stdout line is what `phase1_doc_one_shot_runner` echoes
        # into the run log (`stdout.splitlines()[0]`), so it has to carry the
        # disclosure on its own — not point at a report nobody opens.
        print("[VACUOUS_PASS] l6_fsm_scaffold_actionable_check: "
              f"{res['reason']}")
        for f in res.get("deferred_to_staged_rtl", [])[:8]:
            print(f"  • NOT CHECKED: {f}")
        denom = res.get(_gd.DENOMINATOR_KEY) or {}
        reason = str(denom.get("not_applicable_reason") or "")
        if reason:
            print(f"  {reason}")
        # Second, rc-independent channel, mirroring si_mcf_sta_check: the
        # `VACUOUS_PASS:` token `flow_compliance_check._stdout_signals_vacuous`
        # scans for, on stderr so it cannot be mistaken for the verdict line.
        print(f"VACUOUS_PASS: {reason}", file=sys.stderr)
        return RC_VACUOUS

    waived, rationale = _waived(project)
    if waived:
        print("[PASS] l6_fsm_scaffold_actionable_check: waived by "
              f"waivers.{WAIVER_KEY} ({len(res['failures'])} suppressed): "
              f"{rationale[:70]}…")
        for f in res["failures"][:6]:
            print(f"  • {f}")
        return RC_PASS

    print(f"[FAIL] l6_fsm_scaffold_actionable_check: {res['reason']}")
    for f in res["failures"][:8]:
        print(f"  • {f}")
    # A FAIL on Part B does not un-disclose Part A: if the FSM half was
    # deferred it is still reported here, so the reader is never handed a
    # verdict that silently covers a part nobody examined.
    for f in res.get("deferred_to_staged_rtl", [])[:8]:
        print(f"  • NOT CHECKED (scaffold contract does not bind this "
              f"design): {f}")
    print()
    print("  Fix in L6_CONTROL_LOGIC.json, from the design's OWN input "
          "documents only:")
    print("    fsm_states: [{name, transitions: [{to, condition}], "
          "actions, evidence}, ...]")
    print("    reject_rules: [{name|rule_id, condition: <distilled, "
          "machine-matchable predicate>, action, evidence}, ...]")
    print("  (A condition must be a distilled rule, not a scraped "
          "document line. Do NOT invent states the input does not "
          "document — set no_fsm_in_input: true instead.)")
    print(f"  Or document the alternative in waivers.json under "
          f'"{WAIVER_KEY}" (>={WAIVER_MIN_LEN} chars).')
    return RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
