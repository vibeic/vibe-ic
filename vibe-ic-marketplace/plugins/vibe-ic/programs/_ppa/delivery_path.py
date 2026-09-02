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
`flow_compliance_check._check_condition` over the project tree with conditions
DERIVED FROM THEIRS. So when a router artefact is renamed, or a fourth route is
added, this module follows the flow instead of describing an older one. The
same rule `test_path_step_matrix_ic_and_ip.py` states for itself: nothing here
reads the yaml and asserts what it thinks it says.

37.5ip IS NO LONGER A ROUTE SELECTOR, AND THAT IS WHY THE IP CONDITION IS
DERIVED RATHER THAN READ. OWNER RULING 2026-09-02, encoded by df8163448 and
pinned by `test_delivery_route_step_reachability.py`: "an IC runs BOTH 37.5ic
and 37.5ip; only a pure-IP route skips 37.5ic", because a die also ships the
IP deliverable set. 37.5ip's condition was widened from the single router
`NO_TEMPLATE.txt` to `any_of` over ALL THREE, so "37.5ip's condition is met"
became true of every routed tree. This module read that as evidence of a
hardmacro delivery and answered BOTH on every chip design — MEASURED at
20031834c1: `resolve(chip_tree)["path"] == "BOTH"`, which is
`PATH_UNDETERMINED` for the ECO axis, on every tape-out-bound run.

The asymmetry the ruling kept is the whole answer, and it is stated by the
flow itself: 37.5ic still names the TWO chip routers and still EXCLUDES
`NO_TEMPLATE.txt`. So the routers that reach the IP terminal and NOT the chip
terminal are exactly the IP route, and that set is a subtraction over the two
conditions this module already reads — not a fourth place where a router
filename is spelled. Add a router to both terminals and it reads as a chip
route; add it to 37.5ip alone and it reads as an IP route; make the two
terminals accept the same set and no route can be established at all, which is
UNREADABLE and says so. Nothing here is retyped, and nothing here degrades
into a silent CHIP or a silent IP.

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


#: The only two keys a terminal's condition may carry for the subtraction below
#: to be meaningful. A third key would mean the terminals select on something
#: other than the presence of a router file, and a set difference over
#: `files_exist` would then be answering a question the flow is no longer
#: asking. Refused loudly rather than ignored.
_ROUTE_CONDITION_KEYS = {"any_of", "files_exist"}


def _route_conditions() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """({PATH_CHIP: condition, PATH_IP: condition}, reason-it-could-not-be-read)

    CHIP is step 37.5ic's condition VERBATIM: that terminal is still the chip
    route's own, and it still excludes the IP router.

    IP is DERIVED — the routers that reach 37.5ip and NOT 37.5ic — because
    since the 2026-09-02 owner ruling 37.5ip runs on every route and so is no
    longer a route selector. See this module's header.

    Every way the derivation could stop meaning what it says is a REASON, not
    a fallback: a condition carrying a key other than `any_of`/`files_exist`,
    a terminal that is not `any_of`, a chip terminal that names no router, or
    an empty difference (the two terminals accept the same set, so the flow no
    longer distinguishes the routes). Each returns UNREADABLE and names
    itself; none of them silently picks a route.
    """
    conditions, why = _terminal_conditions()
    if conditions is None:
        return None, why
    for sid in (STEP_CHIP, STEP_IP):
        cond = conditions[sid]
        if not isinstance(cond, Mapping):
            return None, (f"step {sid}'s condition is {type(cond).__name__}, "
                          "not a mapping, so the route it selects could not "
                          "be read")
        extra = sorted(set(cond) - _ROUTE_CONDITION_KEYS)
        if extra:
            return None, (f"step {sid}'s condition carries {extra}, so it no "
                          "longer selects purely on which router artefact is "
                          "present and a route cannot be read from it")
        if not cond.get("any_of"):
            return None, (f"step {sid}'s condition is not `any_of`, so its "
                          "`files_exist` list is a conjunction rather than "
                          "the set of routers that reach it")
    chip_files = [str(f) for f in (conditions[STEP_CHIP].get("files_exist")
                                   or [])]
    ip_files = [str(f) for f in (conditions[STEP_IP].get("files_exist") or [])]
    if not chip_files:
        return None, (f"step {STEP_CHIP} names no router artefact, so no tree "
                      "can be shown to be on the chip path")
    ip_only = [f for f in ip_files if f not in chip_files]
    if not ip_only:
        return None, (f"every router that reaches {STEP_IP} also reaches "
                      f"{STEP_CHIP}, so the two terminals no longer "
                      "distinguish a hardmacro delivery from a die and no "
                      "route can be established from them")
    return ({PATH_CHIP: dict(conditions[STEP_CHIP]),
             PATH_IP: {"any_of": True, "files_exist": ip_only}}, None)


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

    conditions, why = _route_conditions()
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
        on_chip = bool(FCC._check_condition(root, conditions[PATH_CHIP]))
        on_ip = bool(FCC._check_condition(root, conditions[PATH_IP]))
    except Exception as exc:                                # pragma: no cover
        return {"path": PATH_UNREADABLE,
                "reason": (f"the flow's condition predicate raised {exc!r} on "
                           f"{root}, so no route was established"),
                "evidence": {"project": str(root)}}

    evidence = {
        "project": str(root),
        "flow": str(_flow_path()),
        "predicate": "flow_compliance_check._check_condition",
        #: Keyed by ROUTE, not by step id: `PATH_IP`'s condition is derived
        #: from the two terminals (see `_route_conditions`) and is not any one
        #: step's own, so labelling it `STEP_IP` would misname it.
        "conditions": {PATH_CHIP: conditions[PATH_CHIP],
                       PATH_IP: conditions[PATH_IP]},
        "met": {PATH_CHIP: on_chip, PATH_IP: on_ip},
    }
    if on_chip and on_ip:
        return {"path": PATH_BOTH,
                "reason": ("this tree carries a chip router AND a router that "
                           f"reaches {STEP_IP} and not {STEP_CHIP}. The three "
                           "router artefacts are mutually exclusive by "
                           "construction and no silicon corresponds to a tree "
                           "holding two of them; `tapeout_declaration_check` "
                           "is the refusal. This module will not pick one of "
                           "them"),
                "evidence": evidence}
    if on_chip:
        return {"path": PATH_CHIP,
                "reason": (f"{STEP_CHIP}'s condition is met, so this design is "
                           "on the chip path and is tape-out-bound"),
                "evidence": evidence}
    if on_ip:
        return {"path": PATH_IP,
                "reason": (f"this tree carries only a router that reaches "
                           f"{STEP_IP} and not {STEP_CHIP}, so this design "
                           "terminates at the hardmacro/IP delivery and is "
                           "not tape-out-bound"),
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
