"""`_ppa.backends` — one module per EDA tool, and each one only PARSES.

A backend turns what a tool actually wrote into canonical metric records
(`docs/PPA_INTERFACES.md` §2) and does nothing else: no thresholds, no verdicts,
no policy. Those live in the domain modules (`_ppa/timing.py`, `_ppa/area.py`,
`_ppa/feasibility.py`, ...), which is what lets a second engine be added later
without touching a single rule.

Two consequences that are easy to get wrong and are therefore stated here:

* **A backend never exits 1.** rc=1 is a claim about silicon and a parser has no
  claims about silicon to make. A backend that cannot read its input exits 2
  with a printed marker.
* **A backend never resolves a disagreement.** When two artefacts from the same
  tool state different numbers for the same metric and scope, the backend emits
  BOTH records with different `source.path` and lets `_ppa/contract.py` detect
  the conflict. Picking a winner inside the parser would hide it.
"""
