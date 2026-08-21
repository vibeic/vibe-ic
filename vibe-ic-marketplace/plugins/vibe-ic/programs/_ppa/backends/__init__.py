"""`_ppa.backends` — one module per tool, and each one only PARSES.

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

The rule earns its keep at exactly the moment a tool's output is CLOSE to what a
domain wants. A backend that notices a violation count is zero and returns
"clean" has moved a threshold into the parser, and the next tool added will
either duplicate it or contradict it. So a backend's whole job is: this is what
the tool said, this is the scope it said it in, and this is what it did NOT say.
"""

# ---------------------------------------------------------------------------
# THE DRIVER SEAM
# ---------------------------------------------------------------------------
# `ppa_metric_extract.py --backend TOOL` refused for EVERY tool until v1.11.33,
# including the five that exist, with "ppa_metric_extract does not drive
# backends yet". Measured: five backend modules ship and the canonical
# extraction CLI could extract from none of them, so a downloaded plugin had no
# supported way to turn a tool artefact into records at all.
#
# A backend that can turn ONE artefact path into canonical records declares
# `extract_records(path, **opts)`. A backend that CANNOT declares
# `NO_DRIVER_REASON` saying why, and the CLI prints that reason instead of a
# blanket refusal. Both are read by attribute, so teaching a backend to be
# driven is a change to that backend and to nothing else -- this file does not
# hold a list that can go stale behind the tree.
#
# The reason for the split is the one in the module docstring above: a backend
# PARSES. `opensta.py` produces a `Report`, and turning that into rows is
# `_ppa/timing.py`'s job because deciding what a slack MEANS is a domain rule;
# `orfs.py` reads AutoTuner result rows the search layer already holds. Neither
# is a defect, and neither may be papered over by inventing a reader here.
import importlib
from typing import Any, Callable, Dict, List, Optional, Tuple

#: Every backend module in this package. Named, not globbed: a file that
#: appears here without anyone deciding it is a backend is exactly the drift
#: this package's ownership rule exists to prevent.
BACKENDS: Tuple[str, ...] = ("librelane", "openroad", "opensta", "orfs", "yosys")

DRIVER_ATTR = "extract_records"
NO_DRIVER_ATTR = "NO_DRIVER_REASON"
REQUIRES_ATTR = "EXTRACT_REQUIRES"


class BackendNotDrivable(Exception):
    """The backend exists and declares that it cannot be driven from a path.

    Carries the module's own stated reason. NOT the same exception as "no such
    backend": "this tool has no parser" and "this parser is not a record
    producer" are different sentences to whoever has to fix the invocation.
    """

    def __init__(self, tool: str, reason: str, requires: Tuple[str, ...] = ()):
        super().__init__(reason)
        self.tool = tool
        self.reason = reason
        self.requires = tuple(requires)


def load(tool: str):
    """The backend module for `tool`. Raises ImportError if there is none."""
    return importlib.import_module(f"{__name__}.{tool}")


def driver_for(tool: str) -> Callable[..., List[Dict[str, Any]]]:
    """`tool`'s path->records driver, or raise `BackendNotDrivable` with the
    module's own reason. Never returns a stub that yields `[]`: a tool that
    cannot be read must not produce an empty record set."""
    mod = load(tool)
    fn = getattr(mod, DRIVER_ATTR, None)
    if fn is None:
        raise BackendNotDrivable(
            tool,
            getattr(mod, NO_DRIVER_ATTR, None)
            or (f"`_ppa/backends/{tool}.py` declares no {DRIVER_ATTR}() and no "
                f"{NO_DRIVER_ATTR}, so nothing here can say what it reads"))
    return fn


def drivable() -> Tuple[str, ...]:
    """Every backend that can be driven from a path, for a refusal that names
    the alternatives instead of leaving a caller to guess."""
    out = []
    for tool in BACKENDS:
        try:
            driver_for(tool)
        except (BackendNotDrivable, ImportError):
            continue
        out.append(tool)
    return tuple(out)


def requirements(tool: str) -> Tuple[str, ...]:
    """Options `tool`'s driver cannot work without (e.g. yosys needs `stage`:
    the two blocks it prints are two stages of one run and neither the path nor
    the text says which). Declared by the backend, never guessed here."""
    return tuple(getattr(load(tool), REQUIRES_ATTR, ()) or ())
