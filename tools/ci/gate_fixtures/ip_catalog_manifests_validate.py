"""`ip-catalog manifests validate` — a manifest whose license is not whitelisted.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT. `ip_catalog_validate.py` says
it validates manifests "against schema + permissive-license whitelist", and the
escape it was written for is a manifest that declares a license nobody vetted:
the catalog is where third-party RTL enters a design, so a licence the whitelist
has never seen must be a red line at the manifest and not a discovery at tapeout.

WHAT THE CAN-FAIL DELIBERATELY DOES NOT DO. It does not delete the manifest, and
it does not name one of `FORBIDDEN_LICENSES` (GPL and friends). Both of those
reach a refusal by EMPTYING THE POPULATION rather than by changing an answer
inside it: `ip_catalog_query.load_manifests` DROPS a forbidden manifest before
the validator ever sees it, so the gate would then refuse for reading zero
manifests — the vacuity path, which proves nothing about the predicate. The
mutated licence is therefore an UNKNOWN one, which loads and is judged.

BOTH ARMS HAVE THE SAME DENOMINATOR: one manifest parsed either way, `total: 1`.
An empty subject is rc 2 by this gate's own zero-manifest refusal, so it could
never have exercised the whitelist at all.
"""
from pathlib import Path

GATE = "ip-catalog manifests validate"

#: Every field `ip_catalog_validate.REQUIRED_FIELDS` names, with a port dict
#: carrying the `name` + legal `dir` the schema arm insists on — so the ONLY
#: thing the two arms differ by is the licence string.
_MANIFEST = """ip_name: fixturecore
ip_version: "1.0.0"
ip_class: cpu
license: {lic}
canonical_url: https://example.invalid/fixturecore
description: a synthetic core that exists only to exercise this gate
implements:
  function: fixture
matches_when:
  - "L2.function == 'fixture'"
interface:
  ports:
    - {{name: clk, dir: in, width: 1}}
    - {{name: rst, dir: in, width: 1}}
rtl_files:
  - rtl/fixturecore.v
"""


def _tree(work: Path, lic: str) -> Path:
    root = work / "subject"
    d = root / "ip-catalog" / "cpu" / "fixturecore"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.yaml").write_text(_MANIFEST.format(lic=lic), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One schema-complete manifest whose licence is on the whitelist."""
    return _tree(work, "ISC")


def can_fail(work: Path):
    """The same manifest; the licence is now one nobody vetted."""
    root = _tree(work, "Weird-License-99")
    return root, "not in PERMISSIVE whitelist"
