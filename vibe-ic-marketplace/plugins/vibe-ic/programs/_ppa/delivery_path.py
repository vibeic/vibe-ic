#!/usr/bin/env python3
"""`_ppa/delivery_path.py` — is this design going to a die, or to somebody
else's die? Answered by the ROUTE THE FLOW TOOK, never by guesswork.

WHY THIS EXISTS
===============
The `eco_readiness` axis refuses a candidate that does not carry the spare/ECO
population its design declared. It had one hole: the declaration was OPT-IN, so
a tape-out-bound run that simply omitted it got NOT_APPLICABLE — the pre-fix
behaviour, silently. Closing that needs a predicate for "is this design
tape-out-bound", and the obvious candidates are all wrong:

    a GDS exists            an IP/hardmacro delivery streams a GDS too
    the PDK is a real one   every design here targets a real PDK
    somebody declared it    a new declaration is a new thing to forget, which
                            is the hole one level up wearing a new name

The flow already answers it and cannot be made to forget. Step `0.5ic` routes
every design down exactly one of three routes and writes exactly one ROUTER
ARTEFACT to say which:

    input/submission_template/slots/*.yaml     SHUTTLE      -> CHIP
    input/submission_template/SELF_TAPEOUT.txt SELF_TAPEOUT -> CHIP
    input/submission_template/NO_TEMPLATE.txt  IP           -> IP

A design on the CHIP path (0.5ic -> 15.5ic -> 26.5ic -> 37.5ic) is
tape-out-bound. A design that terminates at 37.5ip is an IP/hardmacro delivery
and is not. That is not a new declaration; it is a route a design cannot
accidentally omit, because 0.5ic's own gate refuses a tree with no router
artefact as NEVER_LOOKED rather than letting the absence be inferred from four
downstream skips.

THE PREDICATE IS THE FLOW'S OWN, RUN — NOT REIMPLEMENTED
========================================================
This module does not glob for `SELF_TAPEOUT.txt`. It loads the flow yaml,
finds steps `37.5ic` and `37.5ip`, and drives
`flow_compliance_check._check_condition` over the project tree with THEIR
conditions. So when a router artefact is renamed, or a fourth route is added,
this module follows the flow instead of describing an older one. The same rule
`test_path_step_matrix_ic_and_ip.py` states for itself: nothing here reads the
yaml and asserts what it thinks it says.

FIVE ANSWERS, AND FOUR OF THEM ARE NOT "CHIP"
=============================================
    CHIP            37.5ic's condition is met: a die, tape-out-bound
    IP              37.5ip's condition is met: a hardmacro delivery
    BOTH            both conditions are met, which is not a design any silicon
                    corresponds to. `tapeout_declaration_check` refuses such a
                    tree; this module refuses to pick one of them.
    NOT_DETERMINED  no router artefact at all. 0.5ic never ran, or ran and the
                    design did not say what it is. NOT "probably IP".
    UNREADABLE      the flow could not be loaded or the steps are not in it, so
                    no route could be established by anybody.

Only CHIP asserts tape-out-bound. Every other answer is a reason to refuse or
to make no finding, and each one says which it is.

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK name appears in this file.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, Mapping, Optional, Tuple

#: The two terminal steps. Named, because a route decided by a step id spelled
#: inline in three places is a route that drifts.
STEP_CHIP = "37.5ic"
STEP_IP = "37.5ip"

PATH_CHIP = "CHIP"
PATH_IP = "IP"
PATH_BOTH = "BOTH"
PATH_NOT_DETERMINED = "NOT_DETERMINED"
PATH_UNREADABLE = "UNREADABLE"
#: Nobody asked. Distinct from every answer above: those are findings ABOUT a
#: design, this is the absence of a question. A caller that supplied no project
#: gets this and never `NOT_DETERMINED`, because "the design did not say what
#: it is" is a defect in the design and "you did not tell me where it lives"
#: is not.
PATH_NOT_SUPPLIED = "NOT_SUPPLIED"

#: Only this one means tape-out-bound.
TAPEOUT_BOUND = (PATH_CHIP,)


def _programs_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def _flow_path() -> pathlib.Path:
    return _programs_dir().parent / "flow" / "phase1_phase2_phase3.yaml"


def _terminal_conditions() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """({step_id: condition}, reason-it-could-not-be-read).

    Read from the flow yaml every call rather than cached at import: a cached
    condition is a condition that stops following the flow the moment the flow
    changes under a long-lived process.
    """
    try:
        import yaml  # noqa: WPS433 — optional, and its absence is a REASON
    except Exception as exc:                                # pragma: no cover
        return None, (f"pyyaml is not importable ({exc!r}), so the flow's own "
                      "terminal-step conditions could not be read and no "
                      "route could be established")
    p = _flow_path()
    if not p.is_file():
        return None, f"the flow document is not at {p}"
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"the flow document at {p} could not be parsed: {exc}"
    steps = (doc or {}).get("steps")
    if not isinstance(steps, list):
        return None, f"the flow document at {p} declares no `steps` list"
    found: Dict[str, Any] = {}
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        sid = str(step.get("id"))
        if sid in (STEP_CHIP, STEP_IP):
            found[sid] = step.get("condition") or {}
    missing = [s for s in (STEP_CHIP, STEP_IP) if s not in found]
    if missing:
        return None, (f"the flow document declares no step {missing}; the "
                      "terminal this module reads the route from is not there")
    return found, None


def resolve(project: Optional[Any]) -> Dict[str, Any]:
    """Which delivery path a project tree is on, and the evidence for it.

    Returns `{"path", "reason", "evidence"}`. `path` is one of the six
    constants above and is never inferred from a GDS, a PDK, or the presence of
    any artefact other than the flow's own router files.
    """
    if project is None or str(project).strip() == "":
        return {"path": PATH_NOT_SUPPLIED,
                "reason": ("no project was supplied, so the route this design "
                           "took was not established. This is not a finding "
                           "that the design is an IP delivery"),
                "evidence": {}}
    root = pathlib.Path(str(project))
    if not root.is_dir():
        return {"path": PATH_UNREADABLE,
                "reason": f"{root} is not a directory, so no route could be "
                          "read from it",
                "evidence": {"project": str(root)}}

    conditions, why = _terminal_conditions()
    if conditions is None:
        return {"path": PATH_UNREADABLE, "reason": why,
                "evidence": {"project": str(root), "flow": str(_flow_path())}}

    programs = str(_programs_dir())
    if programs not in sys.path:
        sys.path.insert(0, programs)
    try:
        import flow_compliance_check as FCC  # noqa: E402
    except Exception as exc:                                # pragma: no cover
        return {"path": PATH_UNREADABLE,
                "reason": (f"flow_compliance_check could not be imported "
                           f"({exc!r}), so the flow's own condition predicate "
                           "could not be run"),
                "evidence": {"project": str(root)}}

    try:
        on_chip = bool(FCC._check_condition(root, conditions[STEP_CHIP]))
        on_ip = bool(FCC._check_condition(root, conditions[STEP_IP]))
    except Exception as exc:                                # pragma: no cover
        return {"path": PATH_UNREADABLE,
                "reason": (f"the flow's condition predicate raised {exc!r} on "
                           f"{root}, so no route was established"),
                "evidence": {"project": str(root)}}

    evidence = {
        "project": str(root),
        "flow": str(_flow_path()),
        "predicate": "flow_compliance_check._check_condition",
        "conditions": {STEP_CHIP: conditions[STEP_CHIP],
                       STEP_IP: conditions[STEP_IP]},
        "met": {STEP_CHIP: on_chip, STEP_IP: on_ip},
    }
    if on_chip and on_ip:
        return {"path": PATH_BOTH,
                "reason": (f"both {STEP_CHIP} and {STEP_IP} conditions are met "
                           "on this tree. The two router artefacts are "
                           "mutually exclusive by construction and no silicon "
                           "corresponds to a tree holding both; "
                           "`tapeout_declaration_check` is the refusal. This "
                           "module will not pick one of them"),
                "evidence": evidence}
    if on_chip:
        return {"path": PATH_CHIP,
                "reason": (f"{STEP_CHIP}'s condition is met, so this design is "
                           "on the chip path and is tape-out-bound"),
                "evidence": evidence}
    if on_ip:
        return {"path": PATH_IP,
                "reason": (f"{STEP_IP}'s condition is met, so this design "
                           "terminates at the hardmacro/IP delivery and is not "
                           "tape-out-bound"),
                "evidence": evidence}
    return {"path": PATH_NOT_DETERMINED,
            "reason": ("neither terminal's condition is met: this tree carries "
                       "no router artefact, so step 0.5ic either never ran or "
                       "ran and the design did not say what it is. That is not "
                       "a finding that it is an IP delivery"),
            "evidence": evidence}


def is_tapeout_bound(path: Any) -> bool:
    """True only for CHIP. Written as a function so no caller spells the
    comparison itself and quietly includes `NOT_DETERMINED` in it."""
    return path in TAPEOUT_BOUND
