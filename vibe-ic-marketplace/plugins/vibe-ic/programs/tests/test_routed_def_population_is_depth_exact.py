The one unexempted BLOCKING row on `main` reads:

    corpus "published cells carrying a routed DEF" is EMPTY —
    nothing was checked over it   [population: producer rc 0, 0 items]

The adjudication for it (docs/findings/2026-08-22-routed-def-corpus-restoration-
condition.md) turns on the claim that the population is zero because nothing is
published — and that claim is only worth anything if a PUBLISHED routed DEF at
the wrong depth would produce a DIFFERENT observation. It does not. The two are
the same bytes, and this file is the measurement that says so, so the next
reader is not left to re-derive it from the source.

MEASURED against the published corpus (`vibeic/benchmark-data` @ 3b58ccd42):
`protocol_parity/lpc` carries `phase3/phase3/stage3/pnr/` (28 files) and
`protocol_parity/usb_pd` carries `reports/phase3/phase3/`, where four report
names exist at both depths and three of them DIFFER. The doubled shape is not
hypothetical; it is committed.

WHAT THIS FILE DOES NOT SAY
It does not say the producer should be widened. Widening would make the row
GREEN over a run tree whose own layout is the defect a published cell was
withdrawn for on 2026-08-20 — an empty corpus must never become a pass, and a
corpus made non-empty by a malformed cell is that same pass with extra steps.
The producer is a protected authority file and is right as written. The publish
side is what refuses the shape: `benchmark_evidence_structure_check`'s
`NESTED_DUPLICATE` rule, added alongside this file.

So this test pins the CONTRACT (depth-exact) and NAMES its consequence. It goes
red if either half moves.

chip-AGNOSTIC: synthetic corpora, generic IC/PDK tokens.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
PRODUCER = REPO / "tools" / "ci" / "routed_def_corpus.py"

CANONICAL = "ic/demo/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def"
DOUBLED = "ic/demo/v9.9.9_openpdkx/phase3/phase3/stage3/pnr/routed.def"

pytestmark = pytest.mark.skipif(
    not PRODUCER.is_file(), reason=f"producer not present at {PRODUCER}")


def _corpus(root: Path, rel: str) -> Path:
    """A real git CHECKOUT — the producer reads git's INDEX, not the filesystem."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VERSION 5.8 ;\nEND DESIGN\n")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(root), *a], capture_output=True, text=True, check=True)
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "corpus")
    return root


def _population(corpus: Path) -> tuple[int, list[str]]:
    out = subprocess.run(
        [sys.executable, str(PRODUCER), "--repo", str(REPO)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(corpus),
             "VIBE_IC_BENCHMARK_DATA": str(corpus),
             "PYTHONDONTWRITEBYTECODE": "1"})
    return out.returncode, [ln for ln in out.stdout.splitlines() if ln.strip()]


def test_the_canonical_depth_is_counted(tmp_path):
    """POSITIVE CONTROL. Without this, a zero below proves only that the
    producer never finds anything."""
    rc, items = _population(_corpus(tmp_path / "canonical", CANONICAL))
    assert rc == 0, (rc, items)
    assert len(items) == 1, items
    assert items[0].endswith(CANONICAL), items


def test_one_directory_deeper_is_not_counted(tmp_path):
    rc, items = _population(_corpus(tmp_path / "doubled", DOUBLED))
    assert rc == 0, (rc, items)
    assert items == [], (
        "the producer counted a routed DEF at seven components below ic/. If "
        "this is deliberate, the adjudication in docs/findings/ that rests on "
        "the depth-exact rule needs rewriting, and the NESTED_DUPLICATE publish "
        "refusal needs re-justifying\n" + repr(items))


def test_a_published_routed_def_at_the_wrong_depth_is_indistinguishable_from_none(
        tmp_path):
    """The finding itself, stated as an assertion.

    A corpus holding a routed DEF at the doubled depth and a corpus holding no
    routed DEF at all produce the SAME observable: rc 0, empty stdout. Nothing
    downstream can tell the blocking row's stated reason ('is EMPTY') from the
    unstated one ('a routed DEF is published where I cannot count it')."""
    published_wrong = _population(_corpus(tmp_path / "wrong", DOUBLED))
    empty = _population(_corpus(tmp_path / "empty",
                                "ic/demo/v9.9.9_openpdkx/RESULT.md"))
    assert published_wrong == empty == (0, []), (published_wrong, empty)
#!/usr/bin/env python3
"""The routed-DEF population rule is depth-EXACT, and that is a decision.

`tools/ci/routed_def_corpus.py` counts an indexed path only when, relative to
the corpus `ic/` root, it has EXACTLY six components and
`parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`. A routed DEF one
directory deeper is not counted, the producer prints nothing on stdout and
exits 0 — which is byte-for-byte what an EMPTY corpus produces.

WHY THIS IS PINNED RATHER THAN ARGUED
The one unexempted BLOCKING row on `main` reads:

    corpus "published cells carrying a routed DEF" is EMPTY —
    nothing was checked over it   [population: producer rc 0, 0 items]

The adjudication for it (docs/findings/2026-08-22-routed-def-corpus-adjudication.md)
turns on the claim that the population is zero because nothing that could be a
member is published — and that claim is only worth anything if a PUBLISHED
routed DEF the producer cannot count would produce a DIFFERENT observation. It
does not. The two are the same bytes, and this file is the measurement that says
so, so the next reader is not left to re-derive it from the source.

This is the machine-checked half of that document's "Barrier 2". The six
`protocol_parity/<design>/` cells it measures each publish a receipt naming
`phase3/stage3/pnr/routed.def` with a size and a digest, and each sits at a depth
and under a root this rule does not count. Whether those DEFs are published or
not, the producer's answer is the same zero — which is exactly the collapse
asserted below.

MEASURED against the published corpus (`vibeic/benchmark-data` @ 3b58ccd42):
`protocol_parity/lpc` carries `phase3/phase3/` (28 files, 11 of them in
`stage3/pnr/`) and
`protocol_parity/usb_pd` carries `reports/phase3/phase3/`, where four report
names exist at both depths and three of them DIFFER. The doubled shape is not
hypothetical; it is committed.

WHAT THIS FILE DOES NOT SAY
It does not say the producer should be widened. Widening would make the row
GREEN over a run tree whose own layout is the defect a published cell was
withdrawn for on 2026-08-20 — an empty corpus must never become a pass, and a
corpus made non-empty by a malformed cell is that same pass with extra steps.
The producer is a protected authority file (`REQUIRED_AUTHORITY_PATHS` in
`tools/ci/protected_landing_transition.py`) and is right as written.

A PUBLISH-SIDE REFUSAL FOR THE DOUBLED SHAPE IS STILL NOT IN THIS CHANGE, and
this file does not pretend otherwise: nothing refuses a cell that nests a
directory inside a same-named parent, and the shape stays committed in the
corpus.

WHAT DID CLOSE, one layer over, is the SILENCE around it.
`test_routed_def_off_the_canonical_path_is_not_out_of_scope.py` pins that a run
whose `routed.def` is off the canonical path is recorded OFF_CANONICAL_PATH
rather than sharing the word NOT_PUBLISHED with the scratch the publisher
excludes on purpose, and that the publisher names it on stderr. That does not
make such a cell a population member and is not meant to -- the producer's
answer is the same zero either way, which is exactly the collapse asserted
below. It only stops the drop from being invisible.

STATUS: THIS IS A CONTRACT PIN, NOT A REPAIR. It is GREEN before this branch as
well as after — the depth rule it asserts is today's behaviour, unchanged here.
It earns its place by going RED if that rule is ever widened, which is the one
edit that would turn this blocking row green without a cell being published.

chip-AGNOSTIC: synthetic corpora, generic IC/PDK tokens.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
PRODUCER = REPO / "tools" / "ci" / "routed_def_corpus.py"

CANONICAL = "ic/demo/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def"
DOUBLED = "ic/demo/v9.9.9_openpdkx/phase3/phase3/stage3/pnr/routed.def"

pytestmark = pytest.mark.skipif(
    not PRODUCER.is_file(), reason=f"producer not present at {PRODUCER}")


def _corpus(root: Path, rel: str) -> Path:
    """A real git CHECKOUT — the producer reads git's INDEX, not the filesystem."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VERSION 5.8 ;\nEND DESIGN\n")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(root), *a], capture_output=True, text=True, check=True)
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "corpus")
    return root


def _population(corpus: Path) -> tuple[int, list[str]]:
    out = subprocess.run(
        [sys.executable, str(PRODUCER), "--repo", str(REPO)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(corpus),
             "VIBE_IC_BENCHMARK_DATA": str(corpus),
             "PYTHONDONTWRITEBYTECODE": "1"})
    return out.returncode, [ln for ln in out.stdout.splitlines() if ln.strip()]


def test_the_canonical_depth_is_counted(tmp_path):
    """POSITIVE CONTROL. Without this, a zero below proves only that the
    producer never finds anything."""
    rc, items = _population(_corpus(tmp_path / "canonical", CANONICAL))
    assert rc == 0, (rc, items)
    assert len(items) == 1, items
    assert items[0].endswith(CANONICAL), items


def test_one_directory_deeper_is_not_counted(tmp_path):
    rc, items = _population(_corpus(tmp_path / "doubled", DOUBLED))
    assert rc == 0, (rc, items)
    assert items == [], (
        "the producer counted a routed DEF at seven components below ic/. If "
        "this is deliberate, the adjudication in docs/findings/ that rests on "
        "the depth-exact rule needs rewriting, and this blocking row can now be "
        "turned green by a malformed cell\n" + repr(items))


def test_a_published_routed_def_at_the_wrong_depth_is_indistinguishable_from_none(
        tmp_path):
    """The finding itself, stated as an assertion.

    A corpus holding a routed DEF at the doubled depth and a corpus holding no
    routed DEF at all produce the SAME observable: rc 0, empty stdout. Nothing
    downstream can tell the blocking row's stated reason ('is EMPTY') from the
    unstated one ('a routed DEF is published where I cannot count it')."""
    published_wrong = _population(_corpus(tmp_path / "wrong", DOUBLED))
    empty = _population(_corpus(tmp_path / "empty",
                                "ic/demo/v9.9.9_openpdkx/RESULT.md"))
    assert published_wrong == empty == (0, []), (published_wrong, empty)
