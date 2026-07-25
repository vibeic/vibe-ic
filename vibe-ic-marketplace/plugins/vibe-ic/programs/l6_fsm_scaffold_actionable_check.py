#!/usr/bin/env python3
"""l6_fsm_scaffold_actionable_check.py — SEMANTIC layer gate for L6.

BLOCKS (exit 1). Rationale for blocking rather than advising
=============================================================
Both consumers of L6 degrade SILENTLY and in the PASS direction:

  * ``phase2_scaffold_gen.emit_fsm_v()`` emits a syntactically valid
    Verilog module from whatever L6 gives it. Zero states → a file
    stamped "intentionally empty". One state → a module whose only
    behaviour is ``state <= S_<the one state>`` on reset, with the
    transition body left as a ``// TODO`` comment. Both compile. Both
    are indistinguishable from a healthy scaffold to every downstream
    step.
  * ``l11_sequence_covers_l6_reject_rules_check`` contains the literal
    branch ``if not kws: # generic rule — accept any silent sequence``.
    A reject rule whose condition yields no keyword therefore does not
    fail the coverage gate — it makes the coverage gate *vacuous* for
    that rule, so ONE unrelated silent sequence "covers" every such
    rule and the gate reports PASS.

A gate whose failure mode is a manufactured PASS four steps downstream
cannot be advisory. FAIL blocks.

The contract this gate enforces
===============================
    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an ACTIONABLE FORM — not when a token appears
    somewhere.

Part A — the FSM skeleton (previously ungated)
----------------------------------------------
``phase2_scaffold_gen.derive_fsm_states(l6)`` is the *only* path from
L6 into ``<top>_fsm.v``. It reads ``fsm_states`` / ``fsm_hints*`` — not
``states`` — so an L6 that puts its state list under a key the emitter
does not read produces an EMPTY FSM while every token-presence check
sees a populated layer. This gate calls the emitter's own derivation
function, so it measures exactly what phase 2 will receive.

Triggered only by L6's OWN self-declaration that the input contains an
FSM (``no_fsm_in_input`` / ``no_fsm_states_in_input`` both false, or a
non-empty state list). A design that honestly records "there is no FSM
in my input" is not penalised. Requirements when triggered:

  A1  ``derive_fsm_states()`` must yield >= 2 states. One state is not
      a state machine: ``emit_fsm_v`` gives it a 1-bit ``state``
      register that can never change value.
  A2  the layer must carry at least one transition — per-state
      ``transitions[]`` or a top-level ``fsm_transitions``/
      ``transitions`` list. ``emit_fsm_v``'s body is literally
      ``// TODO — transition logic per L6.fsm_transitions``; with zero
      transitions there is nothing for phase 2 to scaffold from.
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

Fail-safe / no-false-positive design
====================================
* No L6 file → SKIP(2).
* ``ic_class`` in {pure_analog, bare_fpga} → SKIP (no control FSM).
* L6 positively declares no FSM in the input → Part A SKIPs.
* No ``reject_rules[]`` → Part B SKIPs.
* If the consuming programs cannot be imported the gate SKIPs rather
  than guessing at their contract.

Waiver: ``l6_fsm_scaffold_degraded_intentional`` (>=40 chars) in
``<project>/waivers.json``.

Usage:
    python3 l6_fsm_scaffold_actionable_check.py <project_dir> \
        [--json <out.json>]

Exit codes:
    0 = PASS / SKIP-by-class / PASS_WITH_WAIVER
    1 = FAIL (blocks)
    2 = input-missing / not-applicable (skip)
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

import _path_layout as _pl  # noqa: E402

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
        "transitions_declared": 0,
        "reject_rules_checked": 0,
        "failures": [],
        "warnings": [],
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

    failures: List[str] = []
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

        raw_states = _state_entries(l6)
        fsm_asserted = (not _l6_declares_no_fsm(l6)) or bool(raw_states)

        if not fsm_asserted:
            pass  # honest "no FSM in this input" — Part A does not apply
        else:
            out["fsm_checked"] = True
            parts_run.append("fsm")
            transitions = _declared_transitions(l6)
            out["transitions_declared"] = len(transitions)

            # A1 — at least 2 states.
            if len(derived) == 0:
                failures.append(
                    "L6 asserts the input contains an FSM "
                    f"(no_fsm_in_input={l6.get('no_fsm_in_input')!r}, "
                    f"raw state entries={len(raw_states)}) but "
                    "phase2_scaffold_gen.derive_fsm_states() — the ONLY "
                    "path from L6 into <top>_fsm.v — returns 0 states. "
                    "emit_fsm_v() will write a file stamped "
                    "'intentionally empty'. Check the state list is "
                    "under a key the emitter reads (fsm_states / "
                    "fsm_hints*), not merely under 'states'")
            elif len(derived) == 1:
                failures.append(
                    f"only 1 FSM state derived ({derived[0]!r}) — "
                    "emit_fsm_v() gives it a 1-bit state register that "
                    "can never change value, so <top>_fsm.v is a module "
                    "that cannot leave reset. A control layer that "
                    "declares an FSM must enumerate >= 2 states")

            # A2 — at least one transition to scaffold from.
            if derived and not transitions:
                failures.append(
                    f"{len(derived)} state(s) derived but L6 declares 0 "
                    "transitions (no per-state transitions[] and no "
                    "top-level fsm_transitions[]). emit_fsm_v()'s body "
                    "is literally '// TODO — transition logic per "
                    "L6.fsm_transitions', so phase 2 receives a state "
                    "enum with no transition information at all")

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
                    failures.append(
                        f"{len(dangling)} transition(s) target a state "
                        "that is not in the derived state set "
                        f"({sorted(norm)}): {', '.join(dangling[:4])}. "
                        "phase 2 cannot scaffold an edge to a state it "
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
                    failures.append(
                        f"reject_rules[{idx}]: no name/rule_id — the "
                        "L11/L12 coverage gate reports rules by identity "
                        "and a test author cannot reference an anonymous "
                        "rule")
                    continue
                if not cond:
                    failures.append(
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
                    failures.append(
                        f"{label}: consumer extractor _rule_keywords() "
                        f"raised {type(exc).__name__}: {exc}")
                    continue

                text = _rule_text(rule)
                if not kws:
                    failures.append(
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
                    failures.append(
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

    out["failures"] = failures
    out["warnings"] = warnings
    if failures:
        out["verdict"] = "FAIL"
        out["reason"] = (
            f"{len(failures)} L6 item(s) are not actionable by their "
            f"consumers (parts checked: {'+'.join(parts_run)})")
    else:
        bits = []
        if "fsm" in parts_run:
            bits.append(f"{len(out['derived_states'])} state(s) / "
                        f"{out['transitions_declared']} transition(s) "
                        "reach phase2_scaffold_gen")
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
        return 2
    if res["verdict"] == "PASS":
        print(f"[PASS] l6_fsm_scaffold_actionable_check: {res['reason']}")
        return 0

    waived, rationale = _waived(project)
    if waived:
        print("[PASS] l6_fsm_scaffold_actionable_check: waived by "
              f"waivers.{WAIVER_KEY} ({len(res['failures'])} suppressed): "
              f"{rationale[:70]}…")
        for f in res["failures"][:6]:
            print(f"  • {f}")
        return 0

    print(f"[FAIL] l6_fsm_scaffold_actionable_check: {res['reason']}")
    for f in res["failures"][:8]:
        print(f"  • {f}")
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
