#!/usr/bin/env python3
"""Every PPA gate must map an internal error to rc 3, never to rc 1.

PPA_INTERFACES §1 reserves rc 1 for a FINDING about the design. A traceback that
propagates out of `main()` exits 1, so a crash reaches the roll-up as a verdict
nothing reached — the gate appears to have judged the design and refused it.

MEASURED before this file was written. Five of nine PPA gates had no guard:

    ppa_area_threshold_check   ppa_measurement_check   ppa_pareto_check
    ppa_feasibility_check      ppa_page_claim_check

and the defect was reachable, not theoretical: an AttributeError inside
`ppa_pareto_check` exited **1** with a bare traceback. `ppa_contract_check`,
`ppa_head_to_head_check` and `ppa_problem_integrity_check` had carried the guard
from the start, so this was one convention applied in three places out of nine.

IT BECAME LOAD-BEARING WHEN THE GATES GREW `--corpus`. While a gate took an exact
path, a crash was a local accident about one document. Sweeping a whole campaign,
ONE badly shaped document decides the entire row.

The population is DERIVED from the programs directory, not listed, because a list
is the thing that goes out of date — which is how five gates came to be missing
the convention in the first place.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

#: A PPA gate that deliberately does not carry the guard, with the reason.
#: Empty, and it must stay a DECLARATION rather than a silence.
NO_GUARD_DECLARED: dict = {}


def _ppa_gates():
    """Every `ppa_*_check.py` in the shipped programs directory."""
    return sorted(p.name for p in PROGRAMS.glob("ppa_*_check.py"))


def _has_internal_error_guard(name: str) -> bool:
    """Does the ENTRY BLOCK catch a stray exception?

    Read off `if __name__ == "__main__":` to the end, not off the whole source.
    Both ways a file-wide grep gets this wrong were measured here:

      * FALSE CLEAR — `ppa_pr_scope_check` catches Exception deep in its own
        logic, so a whole-file grep called it guarded while its entry block was
        a bare `sys.exit(main())`. That is how it was missed the first time.
      * FALSE ALARM — `ppa_problem_integrity_check` IS guarded, but its message
        splits "internal error" across two f-string lines, so a grep for that
        phrase did not find it.

    The question is only ever about the entry block, so that is what is read.
    """
    src = (PROGRAMS / name).read_text(encoding="utf-8", errors="replace")
    marker = 'if __name__ == "__main__":'
    if marker not in src:
        return False
    return "except Exception" in src[src.rindex(marker):]


def test_the_population_is_not_empty():
    """The denominator. The assertion below iterates it, and a glob that stopped
    matching would let it pass over nothing."""
    assert _ppa_gates(), (
        f"no ppa_*_check.py found under {PROGRAMS} — this detector has gone "
        "dark rather than the family having gone away")


def test_every_ppa_gate_maps_an_internal_error_to_rc_3():
    """RED BEFORE THE FIX for five of the nine gates."""
    missing = [n for n in _ppa_gates()
               if not _has_internal_error_guard(n) and n not in NO_GUARD_DECLARED]
    assert not missing, (
        "a PPA gate lets a traceback exit 1, which §1 reserves for a finding "
        "about the design:\n  " + "\n  ".join(missing)
        + "\n(add the guard, or declare it in NO_GUARD_DECLARED with a reason)")
