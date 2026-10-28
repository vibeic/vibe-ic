#!/usr/bin/env python3
"""pdk_family_identity.py — ONE canonical spelling per PDK family.

WHY THIS FILE EXISTS
====================
A PDK family is named by several different strings in this tree, and until
this module every reader answered "which family is that?" with its OWN
matcher.  MEASURED on c54016beddc3 (vibe-ic#2139), for the ONE family whose
registry entry is fully populated:

    selector      _registry_entry   resolve_family   _norm        device_map
    ------------  ----------------  ---------------  -----------  ----------
    ihp-sg13g2    'ihp-sg13g2'      'ihp-sg13g2'     ihpsg13g2    12 roles
    ihpsg13g2     None              None             ihpsg13g2    0 roles
    sg13g2        None              'ihp-sg13g2'     sg13g2       0 roles

The middle row is not hypothetical: ``analog_pdk_availability.resolve_pdk``
PRODUCES it — it reports ``family = _norm(target)``, punctuation stripped — so
the resolver's own output is a spelling that its own registry readers cannot
resolve.  The consequences were measured end to end:

  * ``analog_a3_netlist_emit`` REFUSED ``--pdk ihp-sg13g2`` because the block
    bound ``ihpsg13g2``, naming both spellings; and
  * ``analog_a2_topology_emit`` then refused ``--pdk ihpsg13g2`` with
    ENTRY_REQUIREMENTS_NOT_MET on four measured process constants that the
    registry entry states plainly — because the entry could not be found at
    all.

A user who follows the first refusal's hint lands on the second.  Neither
refusal is wrong about what it saw; the two readers simply do not agree on
what a family is called.

WHAT THIS MODULE IS
===================
The single authority for that question.  ``canonical_family`` answers with the
``name`` of the ``programs/pdk_registry.json`` entry a selector denotes — the
one published spelling — and every producer that needs a family id resolves
through it, so a selector that resolves for one of them cannot silently fail
to resolve for another.

The alias table is the REGISTRY ITSELF: there is no hand-typed list of
spellings here and no PDK literal anywhere in this file.  Matching is
structural on the NORMALISED strings (case folded, punctuation dropped),
strongest rule first, and an ambiguous selector resolves to nothing rather
than to a guess:

    exact          normalised strings equal
    prefix         one normalised string starts the other
    containment    one normalised string occurs inside the other
    token          a WORD of one occurs inside the other, which is how a
                   declaration like `sg13g2_maximal` names a family

with a four-character floor on every side that has to carry the match,
because a token that short does not identify a family and answering from it
would invent a finding.

chip-AGNOSTIC and NDA-safe: names come from the registry, never from here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REGISTRY_PATH = Path(__file__).resolve().parent / "pdk_registry.json"

#: A family token shorter than this does not identify a family.  Shared by
#: every rule below so "how specific must a match be" has ONE answer.
MIN_FAMILY_TOKEN = 4

#: Match strengths, strongest first.  An exact hit beats a prefix hit beats a
#: containment hit; two hits of the SAME strength are an ambiguity, never a
#: pick.
MATCH_EXACT = 4
MATCH_PREFIX = 3
MATCH_CONTAINED = 2
MATCH_TOKEN = 1
MATCH_NONE = 0

_NON_ALNUM = re.compile(r"[^a-z0-9]")
_WORD = re.compile(r"[a-z0-9]+")


def family_tokens(selector: Optional[str]) -> List[str]:
    """The WORDS of `selector` long enough to name a family."""
    return [w for w in _WORD.findall(str(selector or "").lower())
            if len(w) >= MIN_FAMILY_TOKEN]


def normalise(selector: Optional[str]) -> str:
    """Case-folded, punctuation-free spelling of `selector`.

    This is the only place the tree decides that `ihp-sg13g2` and `ihpsg13g2`
    are the same string.
    """
    return _NON_ALNUM.sub("", str(selector or "").strip().lower())


def match_strength(a: Optional[str], b: Optional[str]) -> int:
    """How strongly two selectors denote the same family: MATCH_EXACT /
    MATCH_PREFIX / MATCH_CONTAINED / MATCH_NONE.

    Both sides are normalised first, so the answer does not depend on how
    either was punctuated.  A side too short to identify a family scores
    MATCH_NONE — the caller then learns nothing, which is the honest outcome
    for a string that carries no family.
    """
    an, bn = normalise(a), normalise(b)
    if not an or not bn:
        return MATCH_NONE
    if an == bn:
        return MATCH_EXACT
    if min(len(an), len(bn)) < MIN_FAMILY_TOKEN:
        return MATCH_NONE
    if an.startswith(bn) or bn.startswith(an):
        return MATCH_PREFIX
    if an in bn or bn in an:
        return MATCH_CONTAINED
    if (any(w in bn for w in family_tokens(a))
            or any(w in an for w in family_tokens(b))):
        return MATCH_TOKEN
    return MATCH_NONE


def load_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    """Parse the registry, or `{}` when it cannot be read.

    An unreadable registry is NOT an empty one, and no caller here supplies a
    default family for it: every lookup below returns None, which every caller
    already handles as "no family", rather than a wrong name.
    """
    try:
        data = json.loads(Path(path or _REGISTRY_PATH).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def registry_names(path: Optional[Path] = None) -> List[str]:
    """Every published family `name`, in registry order."""
    return [str(e.get("name")) for e in (load_registry(path).get("pdks") or [])
            if isinstance(e, dict) and e.get("name")]


def canonical_entry(selector: Optional[str], path: Optional[Path] = None, *,
                    exact_distribution: bool = False
                    ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(canonical name, registry entry)` for `selector`, else `(None, {})`.

    AMBIGUITY IS NOT A TIE TO BREAK.  When two published families match at the
    same strength the selector does not name one of them, and returning either
    would publish one process's constants under a name the caller never asked
    for — the exact failure `pdk_analog_characterize.context_describes_target`
    was written for.  Two hits of equal strength resolve to nothing.

    ``exact_distribution`` permits only normalised spelling aliases of a
    registered name, never a family prefix or revision inference. A literal
    registered name wins; otherwise colliding registered spellings refuse.
    """
    best: Optional[Tuple[int, str, Dict[str, Any]]] = None
    ambiguous = False
    for ent in (load_registry(path).get("pdks") or []):
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "")
        if not name:
            continue
        s = match_strength(selector, name)
        if exact_distribution:
            if s != MATCH_EXACT:
                continue
            if selector == name:
                s += 1
        if s == MATCH_NONE:
            continue
        if best is None or s > best[0]:
            best, ambiguous = (s, name, ent), False
        elif s == best[0] and (name != best[1] if exact_distribution else
                              normalise(name) != normalise(best[1])):
            ambiguous = True
    if best is None or ambiguous:
        return None, {}
    return best[1], best[2]


def canonical_family(selector: Optional[str], path: Optional[Path] = None
                     ) -> Optional[str]:
    """The one published spelling `selector` denotes, or None."""
    return canonical_entry(selector, path)[0]


def canonical_or_normalised(selector: Optional[str],
                            path: Optional[Path] = None) -> str:
    """The published spelling when the registry knows this family, else the
    normalised one.

    A family the registry has never heard of — a PDK installed in a container,
    a customer's staged process — still needs ONE spelling, and normalisation
    is the only one available without inventing a name.  So an unknown family
    keeps exactly the spelling it had before this module existed.
    """
    return canonical_family(selector, path) or normalise(selector)


def same_family(a: Optional[str], b: Optional[str],
                path: Optional[Path] = None) -> Optional[bool]:
    """Do two selectors denote the same family?  True / False / None.

    `None` is NOT `False`: it means the question could not be asked (a side is
    empty, or neither side is specific enough to name a family), and a caller
    must never report a contradiction it could not observe.

    Published families are compared by their CANONICAL name, so the answer
    does not depend on which of a family's spellings each side happened to
    use.  A side the registry does not know is compared structurally, by the
    same rule — a PDK this repo has never heard of gets the same treatment as
    the open ones.
    """
    an, bn = normalise(a), normalise(b)
    if not an or not bn:
        return None
    ca, cb = canonical_family(a, path), canonical_family(b, path)
    if ca and cb:
        return normalise(ca) == normalise(cb)
    strength = match_strength(a, b)
    if strength != MATCH_NONE:
        return True
    if min(len(an), len(bn)) < MIN_FAMILY_TOKEN:
        return None
    return False
