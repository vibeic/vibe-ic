#!/usr/bin/env python3
"""The ONE reader of "this design's RTL is reused IP, not scaffold-generated".

WHY THIS MODULE EXISTS — the predicate had two copies. ``flow_compliance_check.
_detected_class_rtl_gen_null_and_vendor_rtl`` composed it whole; ``l_doc_
structured_field_count_check`` split it into ``_class_rtl_gen_null`` plus
``_staged_vendor_rtl_text``, and the latter's own docstring admitted the
duplication in as many words ("Mirrors flow_compliance_check.
_detected_class_rtl_gen_null_and_vendor_rtl's KEY-(a.2) vendor-RTL probe").

A predicate with N copies drifts, and the drift is invisible until two gates
disagree about the same project — which is exactly what #504 measured: an
L-doc completeness gate already declined to demand scaffold-grade completeness
from a reused-IP design, while the L6 FSM gate, holding no copy at all, blocked
Phase 1 on a claim about a scaffold consumer that never runs for it. Three
readers, two implementations, one idea. This module is the idea, written once.

WHAT THE PREDICATE MEANS
========================
A design is REUSED-IP when BOTH hold:

  (a) the detected ``ic_class`` has ``rtl_gen: null`` in
      ``ic_class_registry.json`` — i.e. the registry itself records that no
      deterministic generator authors this class's RTL; and
  (b) reused RTL is provably STAGED — ``input/vendor_rtl/`` carries at least
      one ``.v``/``.sv``, OR the staged ``rtl/SOURCE_MANIFEST.json`` declares
      ``reused_ip: true``.

Both halves are read from the project and the registry. Neither is a design
name, a vendor token or an allow-list; adding a class to the registry with
``rtl_gen: null`` is the only way to become eligible, and staging no RTL is the
only way to stop being eligible. CHIP-AGNOSTIC by construction.

FAIL-CLOSED EVERYWHERE. An unreadable registry, an unimportable classifier, an
unresolvable class, a malformed manifest — every one of them answers False, so
a design we could not classify earns no relaxation of anything.

WHY THE ELIGIBILITY SET IS A PARAMETER, NOT A CONSTANT
======================================================
The two original call sites did NOT reject the same classes, and pretending
they did would be a silent behaviour change to code neither this module nor
#504 is entitled to alter:

  * the composite (``flow_compliance_check``) rejects only the UNRESOLVABLE
    classes — ``""`` / ``unknown`` / ``unknown_protocol_class``;
  * the L-doc field-count gate ALSO rejects ``bare_fpga``, because the floors
    it relaxes are protocol floors and a bare FPGA target has no protocol.

So ``class_rtl_gen_null`` always rejects the unresolvable set and takes any
further per-caller rejections as an explicit ``fail_closed`` argument. One
implementation, one registry read, the difference stated at the call site
instead of hidden in a second copy.

MEASURED AND DELIBERATELY PRESERVED, NOT FIXED HERE: the caller-supplied
``fail_closed`` set is matched against the class NAME ONLY, so a class rejected
by name is still accepted under a SYNONYM (``bare_fpga`` is rejected by the
L-doc gate; its registry synonym ``fpga_only`` is not). That asymmetry is
pre-existing behaviour of ``_class_rtl_gen_null``; this module reproduces it
exactly rather than quietly changing what a gate does to a class it never
meant to reach. See #504's report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROG_DIR = Path(__file__).resolve().parent
if str(_PROG_DIR) not in sys.path:
    sys.path.insert(0, str(_PROG_DIR))

import _path_layout as _pl  # noqa: E402

#: The registry this module is the sole reader of, for this question.
REGISTRY_PATH = _PROG_DIR / "ic_class_registry.json"

#: Where a design stages the implementation RTL it brings with it.
VENDOR_RTL_SUBPATH = ("input", "vendor_rtl")

#: The extensions that count as staged RTL, in the order the text harvest
#: concatenates them (``.v`` group first, then ``.sv``) — pinned because the
#: harvested text is fed to a parser downstream and reordering it changes
#: what that parser sees.
RTL_GLOBS = ("*.v", "*.sv")

#: The manifest a staged tree writes to record that it did not author its RTL.
MANIFEST_NAME = "SOURCE_MANIFEST.json"

#: Classes that carry no resolvable identity. ``unknown_protocol_class`` is the
#: runner's fallback target and is registry-listed with ``rtl_gen: null``, so
#: without this it would match the eligibility test on its own — an
#: UNCLASSIFIED design with a stray staged ``.v`` would ride every relaxation
#: keyed on this predicate. Rejected up front, by every caller, always.
UNRESOLVABLE_CLASSES = frozenset({"", "unknown", "unknown_protocol_class"})

#: The extra rejection the L-doc field-count gate applies on top (its floors
#: are protocol floors; a bare FPGA target has no protocol). Named here so the
#: gate imports the set instead of re-typing the literal.
NO_PROTOCOL_FAIL_CLOSED = frozenset({"bare_fpga", "unknown_protocol_class"})


# ---------------------------------------------------------------------------
# (a) the class half — one registry read
# ---------------------------------------------------------------------------

def registry_entry(ic_class: str) -> Optional[Dict[str, Any]]:
    """The ``ic_class_registry.json`` entry for ``ic_class``, by name OR by
    synonym, or None.

    ``unknown_protocol_class`` is skipped as a MATCH TARGET (never as a
    lookup key for other classes): it is the fallback bucket, and letting a
    design match it — directly or through its ``unknown`` synonym — is the
    same fail-open hole ``UNRESOLVABLE_CLASSES`` closes. Any read/parse error
    → None (fail-closed)."""
    try:
        reg = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(reg, dict):
        return None
    for entry in reg.get("classes") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("name") == "unknown_protocol_class":
            continue
        if (entry.get("name") == ic_class
                or ic_class in (entry.get("synonyms") or [])):
            return entry
    return None


def class_rtl_gen_null(ic_class: str,
                       *, fail_closed: frozenset = frozenset()) -> bool:
    """True iff the registry marks ``ic_class`` with ``rtl_gen: null`` — a
    from-spec / reused-IP class whose RTL no deterministic generator authors.

    ``fail_closed`` is the caller's OWN extra rejection set, on top of
    ``UNRESOLVABLE_CLASSES`` which is always rejected. Unresolvable class,
    unreadable registry, or no matching entry → False."""
    if ic_class in UNRESOLVABLE_CLASSES or ic_class in fail_closed:
        return False
    entry = registry_entry(ic_class)
    if entry is None:
        return False
    return entry.get("rtl_gen") is None


def detected_ic_class(project) -> str:
    """The project's detected ``ic_class``, or ``""`` when the classifier is
    unavailable or raises. ``""`` is in ``UNRESOLVABLE_CLASSES``, so a failed
    detection can never satisfy ``class_rtl_gen_null``."""
    try:
        from ic_class_profile import detect_ic_class  # noqa: WPS433
        profile = detect_ic_class(Path(project)) or {}
    except Exception:  # noqa: BLE001 — classifier failure is fail-closed
        return ""
    return str(profile.get("ic_class") or "unknown")


# ---------------------------------------------------------------------------
# (b) the staged-RTL half — one prober
# ---------------------------------------------------------------------------

def vendor_rtl_dir(project) -> Optional[Path]:
    """``<project>/input/vendor_rtl``, or None when ``project`` is unusable."""
    if project is None:
        return None
    try:
        return Path(project).joinpath(*VENDOR_RTL_SUBPATH)
    except Exception:  # noqa: BLE001 — a non-path project is simply absent
        return None


def staged_vendor_rtl_files(project) -> List[Path]:
    """Every staged vendor/reused RTL file, ``.v`` group first then ``.sv``,
    each group sorted. Empty list when the directory is absent or carries no
    RTL — which is also the "not reused IP" answer for half (b)."""
    vdir = vendor_rtl_dir(project)
    if vdir is None or not vdir.is_dir():
        return []
    out: List[Path] = []
    for pat in RTL_GLOBS:
        out.extend(sorted(vdir.rglob(pat)))
    return out


def has_staged_vendor_rtl(project) -> bool:
    """True iff at least one staged vendor/reused RTL file exists."""
    return bool(staged_vendor_rtl_files(project))


def staged_vendor_rtl_text(project) -> Optional[str]:
    """The concatenated text of every staged vendor/reused RTL file, or None
    when there is none to read. Per-file read errors are skipped (best-effort
    harvest); a wholly absent directory → None (fail-closed signal)."""
    chunks: List[str] = []
    for f in staged_vendor_rtl_files(project):
        try:
            chunks.append(f.read_text(errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks) if chunks else None


def manifest_declares_reused_ip(project) -> bool:
    """True iff the staged ``rtl/SOURCE_MANIFEST.json`` says ``reused_ip:
    true``. Absent / unreadable / malformed / non-object → False."""
    if project is None:
        return False
    try:
        mf = _pl.rtl_dir(Path(project)) / MANIFEST_NAME
    except Exception:  # noqa: BLE001
        return False
    if not mf.is_file():
        return False
    try:
        data = json.loads(mf.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("reused_ip") is True


def staged_rtl_is_reused_ip(project) -> bool:
    """Half (b) whole: reused RTL is provably staged for this project."""
    return has_staged_vendor_rtl(project) or manifest_declares_reused_ip(project)


# ---------------------------------------------------------------------------
# (a) AND (b) — the composite
# ---------------------------------------------------------------------------

def detected_class_rtl_gen_null_and_vendor_rtl(project) -> bool:
    """The whole predicate: the detected class has ``rtl_gen: null`` AND
    reused RTL is staged.

    This is the question "does the deterministic RTL scaffold path own this
    design's implementation, or does the design bring its own?" — False means
    a generator authors the RTL, so every requirement stated in terms of what
    a generator will emit still binds."""
    if not class_rtl_gen_null(detected_ic_class(project)):
        return False
    return staged_rtl_is_reused_ip(project)
