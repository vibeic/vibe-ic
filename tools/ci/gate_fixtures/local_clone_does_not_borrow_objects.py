"""`local clone does not borrow objects` — a preparation site that clones `--shared`.

THE MUTATION IS AN OPTION, NOT A SITE
=====================================
Both arms ship the SAME two checkout-preparation files, so the denominator the
gate prints on its own line — `examined 2 file(s) containing a clone` — is
identical in both directions. What changes is one token inside one argv: the
python site's `git clone` grows `--shared`, which is exactly the option that
makes git write `.git/objects/info/alternates` and therefore the exact shape
`landing_tier_checkout_preflight` refuses on the built checkout.

Deleting a clone site would have driven rc 2 instead — `NOT CHECKED — no clone
site was found` — which proves the gate notices an empty population and nothing
at all about whether it can read an option.

The `--shared` token is written into the subject through the gate's own
`BORROWING_OPTIONS` tuple rather than typed here, so the fixture cannot drift
away from the deny-list it is supposed to exercise.

The passing arm keeps a hardlink clone (no `--no-hardlinks`) on purpose: the
gate's docstring names that form as the REMEDY two sibling programs print, so a
fixture whose "good" subject avoided it would be testing a rule the gate
deliberately does not have.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401  (kept for symmetry/API)

GATE = "local clone does not borrow objects"

#: Read from the gate itself: the fixture must not carry its own copy of the
#: deny-list, or it would keep passing after the list moved.
_PG = F.PROGRAMS
sys.path.insert(0, str(_PG))
from local_clone_does_not_borrow_objects import BORROWING_OPTIONS  # noqa: E402

_SHARED = BORROWING_OPTIONS[0]          # "--shared"

_PY_SITE = '''\
#!/usr/bin/env python3
"""A preparation site: builds the checkout a landing tier runs in."""
import subprocess
from pathlib import Path

CLONE_OPTS = ["--quiet"{extra}]


def prepare_gate_checkout(src: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone"] + CLONE_OPTS + [str(src), str(dest)],
                   check=True)
    return dest
'''

_SH_SITE = '''\
#!/usr/bin/env bash
# A second preparation site, so the denominator is >1 in both directions.
set -euo pipefail
src="$1"; dest="$2"
git clone --quiet "$src" "$dest"
'''


def _tree(work: Path, extra: str) -> Path:
    root = work / "subject"
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True, exist_ok=True)
    (ci / "prepare_checkout.py").write_text(_PY_SITE.format(extra=extra))
    (ci / "prepare_checkout.sh").write_text(_SH_SITE)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, extra="")


def can_fail(work: Path):
    root = _tree(work, extra=', "%s"' % _SHARED)
    return root, "a clone passes %r" % _SHARED
