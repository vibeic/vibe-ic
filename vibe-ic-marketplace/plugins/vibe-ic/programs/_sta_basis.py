#!/usr/bin/env python3
"""The ONE reader of the `STA_BASIS:` stamp, and the ONE token table behind it.

WHY THIS FILE EXISTS
====================
A report stamps which side of place-and-route its numbers come from:

    # STA_BASIS: POST_ROUTE_SPEF

Reading that stamp is not `m.group(1)`. The emitter already ships suffixed
values (`POST_ROUTE_SPEF`, `POST_ROUTE_NO_SPEF`), so the stamp is read as a
PREFIX and NORMALISED to one of the two canonical names. A reader that returns
the raw capture answers a different question — "what does the stamp literally
say" — and every consumer downstream compares that string against a canonical
name it will not equal.

MEASURED, 2026-08-05. `eda_report_audit` held the only compiled reader in the
tree. Two pending changes each added their own, byte-copying the regex and
re-implementing the normalisation around it — one of them returning `str` where
the original returns `Optional[str]`, which is a different contract at the call
site. Across a 24-stamp corpus the copies disagreed with the original on **7**.

One stamp, five readers, seven disagreements. So the reader moved here and the
copies were deleted rather than corrected: a corrected copy diverges again the
next time the emitter grows a suffix, and the emitter has grown one twice.

WHAT A CALLER GETS
==================
`declared_basis(text)` -> `"PRE_LAYOUT"` | `"POST_ROUTE"` | `None`.

`None` means the text carries no stamp, or carries one this table does not
recognise. It does NOT mean "pre-layout" and it does not mean "post-route" —
callers must treat it as *undeclared* and take their no-op branch, which is what
"the caller stated no side of PnR" has always meant here.

chip-, PDK- and vendor-AGNOSTIC: flow-stage vocabulary only.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

#: Basis -> the spellings that name it, in scope paths and in stamps alike.
#: One table: a path token and a stamp token that disagree would be the same
#: defect one level down.
BASIS_TOKENS: Dict[str, Tuple[str, ...]] = {
    "PRE_LAYOUT": ("pre_pnr", "pre-pnr", "prepnr", "pre_layout", "pre-layout",
                   "prelayout", "pre_route", "pre-route", "pre_floorplan"),
    "POST_ROUTE": ("post_route", "post-route", "postroute", "post_pnr",
                   "post-pnr", "postpnr", "post_layout", "post-layout",
                   "postlayout"),
}

#: The `STA_BASIS: <VALUE>` stamp the STA emitters write into a report body.
#: Read as a PREFIX so a new suffix needs no change here.
STAMP_RE = re.compile(r"^\s*#?\s*STA_BASIS\s*:\s*([A-Z_]+)", re.M)


def normalise_basis(value: str) -> Optional[str]:
    """A raw stamp value -> its canonical basis name, or None.

    Prefix-matched, so `POST_ROUTE_SPEF` and `POST_ROUTE_NO_SPEF` both resolve
    to `POST_ROUTE`. This is the step a copied regex leaves out.
    """
    if not value:
        return None
    val = value.upper()
    for basis, toks in BASIS_TOKENS.items():
        if any(val.startswith(t.replace("-", "_").upper()) for t in toks):
            return basis
    return None


def declared_basis(text: str) -> Optional[str]:
    """The basis a report DISCLOSES ABOUT ITSELF, from its `STA_BASIS:` stamp."""
    m = STAMP_RE.search(text)
    if not m:
        return None
    return normalise_basis(m.group(1))
