#!/usr/bin/env python3
"""A protocol synth must be reachable — counted across ALL dispatch shapes.

CORRECTION. This file shipped asserting something false, and the correction is
now its point. Its reachability predicate was `p.stem in runner_source` — a
literal substring test over a 51k-line file. That cannot see the runner's THREE
name-constructed dispatch loops:

    _t3_mod = __import__(f"{_t3_name}_protocol_synth")      # Tier-3
    _w3_mod = __import__(f"{_wave3_name}_protocol_synth")   # wave-3
    _w4_mod = __import__(f"{_wave4_name}_protocol_synth")   # wave-4

The module name never appears as a literal there, so 21 synths that WERE being
dispatched were measured as unreachable, `AUTO_DISPATCH = True` was added to all
of them, and each became DOUBLE-dispatched: once by its tier loop under a
curated structural condition, once by the generic [14e2b/15] loop under the
module's own `is_<x>()`. The applies are idempotent force-overwrites so nothing
was corrupted, but the two paths share neither a trigger condition nor an
ordering — the tier chain's "Zigbee runs last" contract is not something the
generic loop honours.

The irony is the lesson. The sweep that produced the wrong list was written
right after being burned by dynamic dispatch elsewhere, and written up as a
lesson learned — then reached for a substring test anyway. A reachability check
blind to the codebase's dominant dispatch idiom is exactly the shape this repo
keeps finding: it measures something adjacent to the question and reports it as
the answer.

The predicate now counts all three shapes:
  (a) a literal `<base>_protocol_synth` mention (hand-wired call sites),
  (b) membership in one of the name-constructed dispatch tuples,
  (c) `AUTO_DISPATCH = True` in the module (the generic [14e2b/15] loop).
"""
from __future__ import annotations

import re
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER = _PROGRAMS / "phase1_doc_one_shot_runner.py"

# base -> why this one is deliberately NOT reachable. Empty is the healthy state.
# (The previous `ethercat` entry was removed: it asserted ethercat was withheld
# while the runner's Tier chain has always dispatched it, so the entry was a
# false statement on the record. Its underlying detector mis-fire is real and
# unaffected by dispatch wiring — it is tracked where the detector lives.)
_WITHHELD: dict[str, str] = {}


def _modules():
    for p in sorted(_PROGRAMS.glob("*_protocol_synth.py")):
        yield p.stem[: -len("_protocol_synth")], p


def _src(p: Path) -> str:
    return p.read_text(errors="replace")


def _exports_full_interface(base: str, src: str) -> bool:
    return bool(re.search(rf"^def is_{re.escape(base)}\s*\(", src, re.M)
                and re.search(rf"^def apply_{re.escape(base)}_synth\s*\(",
                              src, re.M))


def _opted_in(src: str) -> bool:
    return bool(re.search(r"^AUTO_DISPATCH\s*=\s*True", src, re.M))


def _dynamic_dispatch_names(runner: str) -> set[str]:
    """Protocol names reached through the runner's name-constructed loops.

    Anchored on the `__import__(f"{...}_protocol_synth")` call so the parser
    follows the loops if one is renamed or a fourth is added; the names come
    from the tuple literals above each anchor, whose first element is the
    protocol name."""
    names: set[str] = set()
    lines = runner.splitlines()
    anchors = [
        i for i, ln in enumerate(lines)
        if re.search(r'(?:__import__|import_module)\(f"\{[A-Za-z_0-9]+\}'
                     r'_protocol_synth"\)', ln)
    ]
    for a in anchors:
        block = "\n".join(lines[max(0, a - 400):a])
        names |= set(re.findall(r'^\s*\(\s*"([a-z0-9_]+)"\s*,', block, re.M))
    return names


def _strip_comments(src: str) -> str:
    """Drop `#` comments so a mention inside one is not read as a call site.

    Needed because the generic dispatch loop documents itself with
    `_stem_auto = _path_auto.stem   # e.g. "espi_protocol_synth"`. Counting that
    comment as a hand-wired call made espi look double-dispatched — this guard
    reproducing, in its own first draft, the exact class of defect it exists to
    catch. Line-based and therefore approximate (a `#` inside a string literal
    truncates that line), which is acceptable here: the effect is to see FEWER
    literal call sites, so it can only ever under-claim reachability, never
    invent it."""
    return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())


def _reachable(base: str, src: str, runner_code: str, dyn: set[str]) -> bool:
    return ((f"{base}_protocol_synth" in runner_code) or (base in dyn)
            or _opted_in(src))


# ── the guard's own predicate must see the dominant idiom ────────────────────

def test_dynamic_dispatch_loops_are_visible_to_this_guard():
    """If this finds few or no names the guard has gone blind again and every
    assertion below becomes vacuous — so assert the mechanism directly."""
    dyn = _dynamic_dispatch_names(_src(_RUNNER))
    assert len(dyn) >= 15, (
        f"only {len(dyn)} dynamically-dispatched protocol names found "
        f"({sorted(dyn)}); the runner's name-constructed loops changed shape "
        "and this guard can no longer see them — fix the parser before "
        "trusting any verdict it produces")
    for expected in ("zigbee", "ptp", "milstd1553"):
        assert expected in dyn, f"{expected} should be dynamically dispatched"


def test_a_substring_predicate_would_still_be_wrong():
    """Pins the actual defect this file shipped with: names reached only by a
    name-constructed loop do NOT appear literally in the runner."""
    runner = _src(_RUNNER)
    invisible = {n for n in _dynamic_dispatch_names(runner)
                 if f"{n}_protocol_synth" not in runner}
    assert invisible, (
        "expected at least one protocol reachable ONLY via f-string dispatch; "
        "if this is genuinely empty the substring test is no longer wrong and "
        "this guard can be simplified")


# ── the reachability property ────────────────────────────────────────────────

def test_every_complete_protocol_synth_is_reachable():
    runner = _src(_RUNNER)
    code = _strip_comments(runner)
    dyn = _dynamic_dispatch_names(runner)
    unreachable = [
        base for base, p in _modules()
        if _exports_full_interface(base, _src(p)) and base not in _WITHHELD
        and not _reachable(base, _src(p), code, dyn)
    ]
    assert not unreachable, (
        f"protocol synths with a complete dispatch interface that NO production "
        f"path can reach: {unreachable}. Add it to a runner dispatch tuple, or "
        "set AUTO_DISPATCH = True after confirming the detector passes "
        "protocol_detector_no_misfire_matrix, or record it in _WITHHELD.")


def test_no_module_is_dispatched_twice():
    """The defect the ORIGINAL guard caused. A module already reached by the
    runner must not also carry AUTO_DISPATCH: the generic loop fires on the
    module's own `is_<x>()` while a tier loop fires on a curated structural
    condition, so the two share neither trigger nor ordering."""
    runner = _src(_RUNNER)
    code = _strip_comments(runner)
    dyn = _dynamic_dispatch_names(runner)
    doubled = [base for base, p in _modules()
               if _opted_in(_src(p))
               and (base in dyn or f"{base}_protocol_synth" in code)]
    assert not doubled, (
        f"double-dispatched: {doubled} — each is already reached by the runner "
        "AND opts into the generic [14e2b/15] loop, so its synth runs twice "
        "under two different trigger conditions")


def test_opted_in_modules_export_what_the_dispatcher_calls():
    """The dispatcher looks up `is_<base>` / `apply_<base>_synth` by name and
    silently continues when either is absent — so a module that sets the flag
    without the interface is opted in and still never fires."""
    broken = [base for base, p in _modules()
              if _opted_in(_src(p)) and not _exports_full_interface(base, _src(p))]
    assert not broken, f"AUTO_DISPATCH=True but missing the interface: {broken}"


# ── _WITHHELD hygiene ────────────────────────────────────────────────────────

def test_withheld_entries_carry_a_reason():
    bad = [k for k, v in _WITHHELD.items() if not str(v).strip()]
    assert not bad, f"_WITHHELD entries with no stated reason: {bad}"


def test_withheld_entries_exist_and_are_not_already_reachable():
    """A _WITHHELD entry naming a module the runner ALREADY dispatches is a
    false statement on the record — which is what the ethercat entry was."""
    runner = _src(_RUNNER)
    dyn = _dynamic_dispatch_names(runner)
    bases = {b for b, _ in _modules()}
    assert not (set(_WITHHELD) - bases), (
        f"_WITHHELD names a module that no longer exists: "
        f"{sorted(set(_WITHHELD) - bases)}")
    contradicted = [k for k in _WITHHELD
                    if k in dyn or f"{k}_protocol_synth" in _strip_comments(runner)]
    assert not contradicted, (
        f"_WITHHELD claims these are deliberately unreachable, but the runner "
        f"dispatches them: {contradicted}")
