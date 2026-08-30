#!/usr/bin/env python3
"""Does this report's headline still agree with its own six-row table?

WHY: the defect caught in J86 (`at-or-over-50-sites=0` printed beside rows reading
50.0), in J92 (a value collision), and in this addendum's own section 4 -- a registered
predicate whose summary line said "none has reached the clkswap rung" directly above its
own table showing `clkswap=yes`. Three sightings of ONE shape: a summary computed
separately from the rows it sits on top of.

(That third sighting was cited here as "J97" by the dispatch that wrote this file, and
no J97 was ever written into findings.md -- it landed in section 4 of the README beside
this script instead. A later dispatch needed the next free label and found J97 already
spoken for by a dangling citation, so it took J98 and repointed this line at where the
finding actually lives. A citation that resolves to nothing is the same defect as a
summary that disagrees with its rows: a pointer nobody re-evaluated. J98.)

This dispatch edited both the headline and section 6. So the headline is re-derived
FROM the table here and compared, rather than re-read by me.

CONTROL: the extractor must be able to disagree. It is run against a synthetic table
with a deliberately wrong headline first, and must report MISMATCH.

Run from /home/reyerchu/_jself_priv.
Exit: 0 headline matches its rows; 1 mismatch; 2 could not parse.
"""

import pathlib
import re
import sys

SIX = ["u_hawaii_adc", "edge_llm_accel", "caravel_user_project",
       "opentitan_aes", "ibex", "edge_llm_matmul_accel"]


def tier_of(cell):
    """Classify one table row's verdict cell into the brief's three tiers."""
    c = cell.upper()
    if "UNDETERMINED" in c:
        return "UNDETERMINED"
    if "NOT FEASIBLE" in c:
        return "NOT FEASIBLE"
    if re.search(r"\bPASS\b", c):
        return "PASS"
    return "?"


def rows_from(text):
    """Pull the six rows out of the table in section 1."""
    out = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0].strip("`* ")
        if name in SIX and name not in out:
            out[name] = (tier_of(cells[1]), cells[1])
    return out


def headline_counts(text):
    """The counts the headline paragraph ASSERTS, read from the headline only."""
    head = text.split("## 0.")[0]
    m = re.search(r"(\d+)\s+NOT FEASIBLE", head)
    n = re.search(r"(\d+)\s+UNDETERMINED", head)
    return (int(m.group(1)) if m else None,
            int(n.group(1)) if n else None)


def compare(text, label):
    rows = rows_from(text)
    if len(rows) != 6:
        print("  %-22s CANNOT PARSE: found %d of 6 rows (%s)"
              % (label, len(rows), sorted(rows)))
        return None
    derived = {}
    for _, (t, _) in rows.items():
        derived[t] = derived.get(t, 0) + 1
    said_nf, said_un = headline_counts(text)
    got_nf, got_un = derived.get("NOT FEASIBLE", 0), derived.get("UNDETERMINED", 0)
    ok = (said_nf == got_nf) and (said_un == got_un)
    print("  %-22s headline says NOT FEASIBLE=%s UNDETERMINED=%s | rows give %d / %d  -> %s"
          % (label, said_nf, said_un, got_nf, got_un,
             "MATCH" if ok else "*** MISMATCH ***"))
    return ok, rows, derived


SYNTH_BAD = """# x

## ALL SIX DECIDED

ALL SIX DECIDED - 3 NOT FEASIBLE and 3 UNDETERMINED.

| IC | verdict | why |
|---|---|---|
| `u_hawaii_adc` | **NOT FEASIBLE - UPHELD** | a |
| `edge_llm_accel` | **NOT FEASIBLE - UPHELD** | b |
| `caravel_user_project` | **NOT UPHELD.** Tier: UNDETERMINED | c |
| `opentitan_aes` | **NOT UPHELD.** Tier: UNDETERMINED | d |
| `ibex` | **NOT UPHELD.** Tier: UNDETERMINED | e |
| `edge_llm_matmul_accel` | **UNDETERMINED** | f |

## 0. end
"""


def main():
    print("CONTROL: the extractor must be able to say MISMATCH")
    got = compare(SYNTH_BAD, "synthetic (3/3 vs 2/4)")
    if got is None:
        return 2
    if got[0] is not False:
        print("  *** CONTROL FAILED: it agreed with a headline that is wrong ***")
        return 1
    print("  -> control held\n")

    text = pathlib.Path("RESULT.md").read_text()
    print("THE REPORT")
    got = compare(text, "RESULT.md")
    if got is None:
        return 2
    ok, rows, derived = got
    print()
    for n in SIX:
        print("    %-24s %s" % (n, rows[n][0]))
    print()
    if not ok:
        return 1
    total = sum(derived.values())
    print("  6 rows, %d classified, tiers: %s"
          % (total, ", ".join("%s=%d" % kv for kv in sorted(derived.items()))))
    if derived.get("?"):
        print("  *** %d row(s) did not classify ***" % derived["?"])
        return 1
    print("\n  The headline is derived from the rows and agrees with them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
