"""`_ppa.backends` — one module per tool, and each one only PARSES.

<<<<<<< HEAD
A backend turns what a tool actually wrote into canonical metric records
(`docs/PPA_INTERFACES.md` §2) and does nothing else: no thresholds, no verdicts,
no policy. Those live in the domain modules (`_ppa/timing.py`, `_ppa/power.py`,
`_ppa/area.py`, `_ppa/feasibility.py`, …), which is what lets a second engine be
added later without touching a single rule.

The split is not tidiness. A threshold that lives in a parser is a threshold
that has to be re-agreed every time a tool is added, and the two copies drift in
the direction nobody is looking.

Four consequences that are easy to get wrong, and are therefore stated here:

* **The dependency direction is one-way.** A backend imports its domain module
  in order to BUILD records; a domain module never imports a backend. If that
  ever reverses, a parser has gained the ability to decide what a number means.

* **A backend never exits 1.** rc=1 is a claim about silicon, and a parser has
  no claims about silicon to make. A backend that cannot read its input exits 2
  with a printed marker.

* **A backend never resolves a disagreement.** When two artefacts from the same
  tool state different numbers for the same metric and scope, the backend emits
  BOTH records with different `source.path` and lets `_ppa/contract.py` detect
  the conflict. Picking a winner inside the parser would hide it.

* **A backend IS entitled to state a fact about the tool itself** — "this
  version of this tool computes power without an activity file, so its power is
  vectorless". That is not a policy; it is the tool's behaviour, it is
  measurable from the installed tool, and the module records how it was
  measured.
=======
`docs/PPA_INTERFACES.md` §4: "A backend module parses one tool's output into
canonical records and does nothing else. No thresholds, no verdicts, no policy
— those live in the domain module, so that adding a tool never changes a rule."
>>>>>>> origin/jppa-search/ppa-search-layer

The rule earns its keep at exactly the moment a tool's output is CLOSE to what a
domain wants. A backend that notices a violation count is zero and returns
"clean" has moved a threshold into the parser, and the next tool added will
either duplicate it or contradict it. So a backend's whole job is: this is what
the tool said, this is the scope it said it in, and this is what it did NOT say.
"""
