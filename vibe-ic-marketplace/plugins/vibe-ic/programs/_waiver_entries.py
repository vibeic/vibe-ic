#!/usr/bin/env python3
"""The ONE reader of "where a project's waiver entries live", and the ONE
vocabulary for "which flow step a waiver names".

WHY THIS MODULE EXISTS — a waivers.json carries its entry list under one of two
top-level keys, and the codebase held at least six private, mutually
inconsistent notions of which one to look at:

  * ``waived_steps`` ONLY .............. ~30 sites (incl. ``waivers_schema_check``)
  * ``waivers`` ONLY ................... 3 sites
  * ``waivers`` else ``waived_steps`` .. 12 sites (first NON-EMPTY wins)
  * ``waived_steps`` else ``waivers`` .. 2 sites (opposite precedence)
  * union of both ...................... 2 sites
  * ``waivers``/``waived_steps``/``entries``, first list wins .. 1 site

Two producers, two keys: ``waivers_materialize`` writes ``waived_steps``;
``phase3_one_shot_runner._autogen_waivers_json`` writes ``waivers``. Neither is
wrong — but a reader that knows only one of them silently sees an EMPTY waiver
list for half the corpus, and reports that emptiness as success.

That is not hypothetical. ``waivers_schema_check`` — whose entire stated purpose
is to stop rubber-stamp waivers from passing through — read ``waived_steps``
only, and returned OK the moment the key was absent. Measured over every tracked
``waivers.json``: 6 of 11 files and 8 of 19 entries were never schema-checked at
all. A gate that cannot find the data reports "0 problems", which is
indistinguishable from "0 problems found". Same shape as #515 (a skip reported
as a pass).

The invisible 8 turned out to be VALID — they are written in a second dialect
whose approval model is an evidence-gated attestation rather than a named human
(see ``waivers_schema_check``'s docstring). That does not shrink the defect: a
gate reporting "0 examined" as "0 problems" was telling the truth by accident,
and would have gone on doing so for the first malformed entry as readily as for
these well-formed ones.

N private readers of one schema drift, and the drift is invisible until two
gates disagree about the same file. This module is the idea, written once —
the same remedy #504 applied to the reused-IP predicate.

WHAT THIS MODULE DOES NOT DO
============================
It does NOT unify the ``analog_waivers`` key used by the analog A-track
(``analog_a6_block_pv_check``, ``analog_a8_before_floorplan_check``,
``analog_flow_compliance_check``). That key names a DIFFERENT list — per-block
analog PV deferrals, not main-track flow-step waivers — and merging it here
would let an analog block deferral answer a digital step's question. It is a
separate list with a separate meaning, and it stays separate.

It does NOT decide whether a waiver is HONOURED. Reading a list and granting a
permission are different jobs; this module only answers "where are the
entries". Every consumer keeps its own matching and eligibility rules.

ORDER IS DETERMINISTIC AND DOCUMENTED
=====================================
``waived_steps`` entries come first, then ``waivers``. Consumers that stop at
the first match therefore keep the precedence the majority of call sites
already had (``waived_steps`` wins), so adopting the shared reader cannot flip
a verdict that a ``waived_steps`` entry already decided.

FAIL-SOFT ON SHAPE, NEVER ON SILENCE. A non-dict document, a key holding a
non-list, an unreadable file — each contributes NO entries rather than raising,
because a reader that crashes on a malformed waiver file would take down gates
that merely wanted to ask whether a step was waived. Callers that must DISTINGUISH
"no entries" from "malformed" (the schema validator is one) use
``entries_by_key`` plus ``malformed_keys``, which report the shape explicitly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: The top-level keys under which a waivers.json may carry its entry list, in
#: the canonical order consumers see them. ``waived_steps`` is the key the
#: schema documents and the majority of readers already used; ``waivers`` is
#: the key ``phase3_one_shot_runner`` emits.
WAIVER_LIST_KEYS: Tuple[str, ...] = ("waived_steps", "waivers")

#: Default filename. Kept here so "the waiver file is called this" is also
#: stated once.
WAIVERS_FILENAME = "waivers.json"


def entries_by_key(data: Any) -> Dict[str, List[Any]]:
    """``{key: [entries]}`` for every key in :data:`WAIVER_LIST_KEYS` that is
    PRESENT and holds a list. Keys that are absent, or present holding a
    non-list, do not appear — use :func:`malformed_keys` to tell those apart."""
    out: Dict[str, List[Any]] = {}
    if not isinstance(data, dict):
        return out
    for key in WAIVER_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            out[key] = value
    return out


def malformed_keys(data: Any) -> List[str]:
    """Keys from :data:`WAIVER_LIST_KEYS` that are PRESENT but do NOT hold a
    list. A caller that validates shape must report these; a caller that only
    asks "is this step waived" may ignore them (they contribute no entries)."""
    if not isinstance(data, dict):
        return []
    return [k for k in WAIVER_LIST_KEYS
            if k in data and not isinstance(data[k], list)]


def entries(data: Any) -> List[Any]:
    """The UNION of every waiver entry in ``data``, in :data:`WAIVER_LIST_KEYS`
    order. Empty list when the document carries no entries under either key —
    which is a legitimate state (a project may carry a waivers.json holding
    only per-gate scalar keys and no flow-step waivers at all)."""
    out: List[Any] = []
    for value in entries_by_key(data).values():
        out.extend(value)
    return out


def has_entries(data: Any) -> bool:
    """True iff at least one waiver entry exists under EITHER key.

    This is the predicate that narrows the schema validator's legitimate early
    return: "no flow-step waivers here, nothing to validate" must mean NEITHER
    key holds entries, never "the one key I happen to read is absent"."""
    return bool(entries(data))


def read_document(project: Path,
                  filename: str = WAIVERS_FILENAME) -> Optional[Any]:
    """The parsed waivers document for ``project``, or None when the file does
    not exist or does not parse. None means "no readable document" — callers
    that must distinguish absent-from-corrupt should stat the path themselves."""
    path = Path(project) / filename
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def load(project: Path, filename: str = WAIVERS_FILENAME) -> List[Any]:
    """Every waiver entry for ``project``, under either key. The replacement
    for the ``json.loads(p.read_text()).get("waived_steps") or []`` idiom that
    was copied into ~30 gates."""
    return entries(read_document(project, filename))


def dict_entries(data: Any) -> List[Dict[str, Any]]:
    """:func:`entries`, filtered to the dict-shaped ones. Most consumers index
    fields off each entry and would raise on a bare string in the list."""
    return [e for e in entries(data) if isinstance(e, dict)]


# ----------------------------------------------------------------------
# Identifier vocabulary — which flow step a waiver NAMES
# ----------------------------------------------------------------------
# The two entry shapes identify their step differently:
#
#   waived_steps entries:  {"id": 31, ...}          canonical flow step id
#   waivers entries:       {"step": "lvs", ...}     runner-local ROLE NAME
#
# Both are legitimate spellings of "which step this waiver is about", and the
# mapping between them already existed — as a private constant inside
# `flow_compliance_check` (`_ENV_UNAVAILABLE_STEP_NAME_TO_ID`), reachable only
# by that module. `waivers_schema_check` therefore had no way to resolve a
# role-name and would have had to reject a perfectly well-identified waiver for
# "missing id" — complaining about spelling while the entry's REAL defect (no
# approver) went unmentioned. The map lives here now so both read one copy;
# `flow_compliance_check` imports it back under its historical name, so its
# ~10 references and the map's single definition stay in agreement.
#
# CHIP-AGNOSTIC BY CONSTRUCTION: every key is a step ROLE ("drc", "lvs",
# "fpga_compile", "analog_layout"). No vendor, no SKU, no design name, and
# adding one would be the defect the source guard exists to catch.
#
# Several role names deliberately share an id: the canonical flow's Step 31 is
# "Physical Verification (DRC + LVS + ERC + Density)", so `drc`, `lvs`, `erc`
# and `physical_verification` all resolve to 31. THE MAPPING IS MANY-TO-ONE, so
# a consumer asking "was the same step waived twice" must compare the
# identifier AS WRITTEN, never the resolved id — otherwise a project that
# waives DRC and LVS separately, which is the shape the runner emits, reads as
# one step waived twice. `waivers_schema_check` does exactly that.
STEP_NAME_TO_ID: Dict[str, Any] = {
    "formal":                   5,
    "formal_verify":            5,
    "formal_verification":      5,
    "formal_proof":             5,
    "formal_property_proof":    5,
    "fpga_compile":             6,
    "fpga_early_prototype":     6,
    "fpga_onboard_test":        39,
    "fpga_final_signoff":       39,
    "fpga_signoff":             39,
    "drc":                      31,
    "lvs":                      31,
    "erc":                      31,
    "physical_verification":    31,
    "ir_drop":                  24,
    "em":                       25,
    "antenna":                  26,
    "si":                       27,
    "signal_integrity":         27,
    "extraction":               22,
    "parasitic_extraction":     22,
    "perc":                     28,
    "esd":                      28,
    "latch_up":                 28,
    "reliability_signoff":      28,
    "post_layout_sim":          29,
    "post_layout_spice":        30,
    "metal_fill":               34,
    "dfm":                      35,
    "htol":                     44,
    "analog_netlist":           "A3",
    "analog_netlist_gen":       "A3",
    "analog_layout":            "A5",
    "analog_post_layout_resim": "A7",
    "analog_hardmacro":         "A8",
    "analog_cosim":             "A9",
    "mixed_signal_cosim":       "A9",
}


def _normalise_step_id(step_id: Any) -> Any:
    """The canonical form of a waiver's ``id``.

    ``True == 1`` in Python, so a bool must never be allowed to match an int
    id; and a digit STRING names the same step as the int, because the two
    dialects have both been observed writing it. Anything else is returned
    unchanged (``"A5"`` is an id in its own right)."""
    if step_id is None or isinstance(step_id, bool):
        return None
    if isinstance(step_id, str):
        text = step_id.strip()
        if not text:
            return None
        return int(text) if text.isdigit() else text
    return step_id


def step_names_for_id(step_id: Any) -> Tuple[str, ...]:
    """Every role name that resolves to ``step_id``, in declaration order.

    THE INVERSE OF A MANY-TO-ONE MAP IS A SET, and this returns all of it.
    Step 31 is ``drc`` AND ``lvs`` AND ``erc`` AND ``physical_verification``;
    a caller handed only the first would consult one report step and read the
    other three as "no evidence".

    Empty tuple when no role name maps to the id — including for ``None`` and
    for a bool. "This id names no step I know" is a REPORTABLE silence, never
    a guess, exactly as :func:`resolve_step_name` returns None rather than a
    default.

    WHY IT EXISTS. ``waived_steps`` entries identify their step by canonical
    flow step ID and carry no name (that is the shape both waiver synthesisers
    in ``flow_compliance_check`` emit), while ``waiver_staleness`` — the
    false-clean guard that refuses a waiver whose excused step actually ran —
    asked only for a NAME. Measured on the withdrawn spm publish run, both of
    its ENV_UNAVAILABLE cap-gap waivers answered ``condition unevaluable`` and
    were honoured unconditionally. The vocabulary that maps the two spellings
    already lived here; only its inverse was missing."""
    wanted = _normalise_step_id(step_id)
    if wanted is None:
        return ()
    return tuple(name for name, sid in STEP_NAME_TO_ID.items()
                 if not isinstance(sid, bool) and sid == wanted
                 and type(sid) is type(wanted))


def resolve_step_name(name: Any) -> Optional[Any]:
    """The canonical flow step id for a runner-local role name, or None when
    the name is not a recognised role. None means "this waiver does not name a
    step we know", which is a REPORTABLE defect — never a silent pass."""
    if not isinstance(name, str):
        return None
    return STEP_NAME_TO_ID.get(name.strip().lower())
