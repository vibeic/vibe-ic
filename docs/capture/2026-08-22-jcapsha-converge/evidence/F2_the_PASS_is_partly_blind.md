# The one candidate that passes on main, passes partly over a blind spot

MEASURED 2026-08-22 in a worktree at `origin/main` = a4caccefe (v1.11.69),
`PYTHONDONTWRITEBYTECODE=1`, guard copied in from `origin/jcapsha/sha256-capture`.

## What it reported

    pad_ring.upstream_pad_variables: upstream_names=20, implemented=8,
        declared_unperformed=3, omitted_by_design=8, known_gap=1
    pad_ring.along_the_row_extent: anchors=2, pin=known_gap
    PASS: 2 registered re-implementation(s); every upstream name and every
          registered computation is accounted for.

rc=0.

## Why that PASS is not what it reads as

`PAD_FAKE_SITES` is the ONE name in `known_gap`. It is the variable whose
non-reading caused `PAD_SITE_NOT_FOUND`. **The fix for it is on main** —
`_pad_ring.py` carries `parse_pad_site_declarations` (:497),
`discover_io_site_declarations` (:550) and `IoLibrary.resolve_site` (:642).

The guard HAS a rule for exactly this staleness, at :213 —

    if n in upstream and _mentions(text, n):
        "<id>: <n> is classified known_gap and DOES appear in <module>. If the
         gap is closed, move it to implemented in the same change that closed
         it — a count of what is still wrong that keeps a name that is no
         longer wrong stops being believed."

and the rule did not fire.

## The predicate, and what it cannot see

    def _mentions(text, name):
        return (f'"{name}"' in text) or (f"'{name}'" in text)

It requires the name as a BARE QUOTED LITERAL. The landed implementation does
not consume the variable that way. It consumes it through a REGEX
(`_pad_ring.py:490`):

    r"^[^\S\n]*dict\s+set\s+::env\(\s*PAD_FAKE_SITES\s*\)\s+"

The name is inside a quoted string, but never as `"PAD_FAKE_SITES"`. So
`_mentions` answers False, and the register goes on calling an implemented
variable a known gap, indefinitely.

## Positive control — the rule fires when the predicate can see

`_mentions` widened to `return name in text` (CONTROL ONLY, not shipped),
same register, same tree:

    FAIL: 1 unaccounted name(s) across 2 registered re-implementation(s):
      - pad_ring.upstream_pad_variables: PAD_FAKE_SITES is classified
        known_gap and DOES appear in programs/_pad_ring.py. ...

So the rule is correct and reachable; the predicate is what is blind. A
negative from this guard was not believed until a positive had been produced
from it.

## Why this belongs to F2 rather than being a fourth finding

It is the SAME CLASS as F1, one level up. F1: a step read one PDK VIEW and
reported "not found" for something declared in the other. This: a guard reads
one SOURCE FORM (the quoted literal) and reports "not implemented" for
something implemented in the other (a pattern). Both are a search space
narrower than the claim made over it.

It also decides F2's deliverable shape. Shipping this checker as-is would ship
a green whose central predicate cannot see the very fix that motivated it.
