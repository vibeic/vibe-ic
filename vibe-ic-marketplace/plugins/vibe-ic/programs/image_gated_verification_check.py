#!/usr/bin/env python3
"""image_gated_verification_check — a skip is green, and 13 of them are a hole
(vibe-ic#1128).

THE DEFECT
==========
107 test files gate on the EDA image being reachable. Measured on a clean
detached `origin/main` at v1.10.33, same files, two arms — arm 2 puts an
`exit 127` shim ahead of `docker` on PATH:

    image reachable     19 failed, 1419 passed, 44 skipped
    image unreachable   24 failed, 1401 passed, 57 skipped

`1419 -> 1401` is 18 passes lost: **13 became SKIP** and 5 net became FAIL. The
13 are the problem, because a skip is green. Nothing fails, nothing blocks, and
no reader of `1401 passed` learns that thirteen verifications did not happen.

The individual messages are already honest — "this half was NOT checked" is
exactly right. The defect is one level up: they are `pytest.skip`, and the
aggregate has no way to say so. `_gate_dispatch.sh` solved this for GATES with a
`NOT_CHECKED` state that is deliberately never folded into `passed`. The test
tier has no equivalent, and this is the smallest thing that gives it one.

WHAT TRIGGERS IT IS AN ANCHOR BUMP, NOT FLAKINESS
=================================================
Two test files hardcode the CURRENT anchor. Measured during #1088, before
`0.2.89` had been pulled on that host: 2 SKIPPED. On the same tree after it was
pulled: 12 passed, 0 skipped. So coverage follows the anchor — every bump
silently removes these verifications on every host until that host pulls, and
with six machines landing in parallel that is exactly when a false green is most
expensive.

(#1128 also tested and REFUTED a load-flakiness hypothesis about the 45 s
`TimeoutExpired` bound: 8 consecutive reads at load average 7.2 took ~0.5 s,
64-90x headroom. The bound is fine; the skips are genuinely "image absent".)

WHAT THIS ASKS, AND WHY IT DOES NOT RUN THE TESTS
=================================================
It performs THE SAME OPERATION the gated tests perform — read a file out of the
anchored image — once, and reports how many declared verification sites that
answer decides. Running the 107 files to count their skips would cost ~11
minutes to learn something one `docker run` already determines: if the image
cannot be read, every one of those sites skips.

The site count is DERIVED, not typed: `pytest.skip(...)` calls under
`programs/tests/` whose reason names the image or the container, found by AST so
a mention in a comment or a docstring cannot inflate it (#1012 is the standing
lesson about text scans deciding wiring in this tree).

EXIT
    0  the anchored image is readable here, so no image-gated verification is
       silently skipping. The site count is printed anyway — a gate that only
       speaks when it finds something cannot be told from one that is not
       running (#1130's item 5, and this file's own denominator rule).
    1  the image is NOT readable: N declared verification sites will skip, and a
       skip is green. Named, with the anchor that decides them.
    2  the question could not be asked (no anchor file, no docker binary). NOT a
       pass: an unanswerable question is not a clean answer.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent.parent
TESTS = HERE / "tests"
ANCHOR_FILE = REPO / "tools" / "vibeic-eda" / "VERSION"
IMAGE_REPO = "ghcr.io/vibeic/vibeic-eda"

#: rc 2 is the NOT_CHECKED tier `run_tolerating_uncheckable` records and
#: never folds into `passed` — the mechanism #1128 says the test tier lacks.
RC_OK, RC_NOT_CHECKED, RC_UNRUNNABLE = 0, 2, 2

#: A skip reason that names the image or the container. Matched against the
#: literal text of the `pytest.skip(...)` argument, never against the file.
_IMAGE_WORDS = ("image", "container", "vibeic-eda", "reachable")

#: A path inside the image that every arm of #1128's measurement reads. Chosen
#: because the gated tests read it themselves; a probe reading something else
#: would be answering a different question from the one it reports on.
_PROBE_PATH = "/usr/bin/env"


def anchor() -> Optional[str]:
    try:
        v = ANCHOR_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return v or None


def _skip_reason_text(node: ast.AST) -> str:
    """The literal text of a `pytest.skip(...)` argument, best effort."""
    out: List[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return " ".join(out)


def image_gated_sites(tests_dir: Path) -> List[Tuple[str, int, str]]:
    """Every `pytest.skip(...)` whose reason names the image or the container.

    AST, not grep: a comment or a docstring that mentions the image must not
    inflate the denominator this gate reports.
    """
    found: List[Tuple[str, int, str]] = []
    for p in sorted(tests_dir.glob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name != "skip":
                continue
            text = _skip_reason_text(n)
            if any(w in text.lower() for w in _IMAGE_WORDS):
                found.append((p.name, n.lineno, text.strip()[:120]))
    return found


def image_is_readable(image: str, timeout: int = 60) -> Tuple[bool, str]:
    """THE SAME operation the gated tests perform, once."""
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "cat", image, _PROBE_PATH],
            capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return False, "no `docker` binary on PATH"
    except subprocess.TimeoutExpired:
        return False, f"reading {_PROBE_PATH} out of {image} timed out at {timeout}s"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if r.returncode != 0:
        tail = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, f"rc={r.returncode}" + (f": {tail[-1][:160]}" if tail else "")
    if len(r.stdout) < 16:
        return False, f"read {len(r.stdout)} byte(s) — the image answered, but with nothing"
    return True, f"read {len(r.stdout)} bytes out of {image}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tests", type=Path, default=TESTS)
    ap.add_argument("--image", default=None,
                    help="override the anchored image (testing)")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)

    sites = image_gated_sites(args.tests)
    files = sorted({f for f, _, _ in sites})

    img = args.image or (f"{IMAGE_REPO}:{anchor()}" if anchor() else None)
    if img is None:
        print("image_gated_verification_check: UNRUNNABLE — no anchor at "
              f"{ANCHOR_FILE}; the question cannot be asked", file=sys.stderr)
        return RC_UNRUNNABLE

    # THE DENOMINATOR IS PRINTED WHATEVER THE VERDICT. A gate that speaks only
    # when it finds something is indistinguishable from one that is not running.
    print(f"image_gated_verification_check: {len(sites)} image-gated skip site(s) "
          f"across {len(files)} test file(s); anchor {img}")
    if not sites:
        print("NOTHING_SCANNED: no image-gated skip site was found — this is NOT "
              "a pass. Either the tests stopped gating on the image, or this "
              "gate's AST walk stopped seeing them.", file=sys.stderr)
        return RC_UNRUNNABLE

    ok, why = image_is_readable(img, args.timeout)
    report = {"anchor": img, "sites": len(sites), "files": files,
              "readable": ok, "detail": why,
              "verdict": "OK" if ok else "NOT_CHECKED"}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.json, json.dumps(report, indent=1),
                          encoding="utf-8")

    if ok:
        print(f"[PASS] the anchored image is readable here ({why}) — the "
              f"anchor-gated subset of the {len(sites)} declared site(s) is "
              f"running rather than silently skipping")
        return RC_OK

    print(f"NOT_CHECKED: the anchored image is NOT readable here — {why}",
          file=sys.stderr)
    # SAY EXACTLY WHAT WAS MEASURED. This gate measures IMAGE READABILITY
    # precisely; the site count is the declared population whose skip reason
    # names the image or a container, and not every one of them is gated on THIS
    # anchor (some name a registry, a KLayout runner, a missing VERSION file).
    # #1128 measured the anchored subset by running the suite under a `docker`
    # shim and found THIRTEEN passes become skips. Reporting the wider number as
    # if it were that one would be this gate overstating its own finding.
    print(f"  {len(sites)} declared skip site(s) across {len(files)} file(s) name "
          f"the image or a container; the subset gated on THIS anchor now skips, "
          f"and a skip is counted as green. #1128 measured that subset at 13 "
          f"passes lost (1419 -> 1401) on v1.10.33:", file=sys.stderr)
    for f, line, text in sites[:12]:
        print(f"    {f}:{line}  {text}", file=sys.stderr)
    if len(sites) > 12:
        print(f"    … and {len(sites) - 12} more", file=sys.stderr)
    print("  This is a coverage hole, not a failure of the code under test. "
          "Pull the anchored image on this host, or land from one that has it.",
          file=sys.stderr)
    return RC_NOT_CHECKED


if __name__ == "__main__":
    sys.exit(main())
