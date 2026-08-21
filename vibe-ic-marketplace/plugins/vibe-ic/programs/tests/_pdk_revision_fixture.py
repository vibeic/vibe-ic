"""programs/tests/_pdk_revision_fixture.py — a synthesized PDK tree that states
its own revision, and the run record derived from it.

WHY A SHARED HELPER
===================
`benchmark_evidence_publish` REFUSES a run that cannot name the PDK revision it
signed off against, so every synthetic converged run in the suite needs the
record. Written out by hand in each test file, the record would be a
hand-authored JSON blob that nobody re-checks against the program that actually
writes it — and a fixture that drifts from the writer tests the fixture.

So this helper builds a TREE and runs the REAL resolver over it. What lands in
`reports/pdk_revision.json` is what `pdk_revision_resolve` produces, byte for
byte, and a change to the record's shape shows up here immediately.

The tree is SYNTHESIZED: `procx` / `cellsA` are placeholders, and the revision
is a fixed hex string with no meaning. No process, foundry, node, SKU or vendor
identifier appears here, and the layout is the STRUCTURE a content-addressed
PDK volume manager installs — not a copy of any real one.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:                  # pragma: no cover - path setup
    sys.path.insert(0, str(_PROGRAMS))

import pdk_revision_resolve as _prr                 # noqa: E402

#: An arbitrary, fixed 40-hex token. It identifies nothing; it is here so a
#: test can assert on an exact value.
FIXTURE_REVISION = "4f2b8c1d9e0a7361bd52c48af90136e7ab2d5c80"

#: What the resolver renders for a tree whose revision comes from its install
#: path (no component is named by a path segment, so the key is the tree).
FIXTURE_REVISION_STR = f"{_prr.TREE_COMPONENT}:{FIXTURE_REVISION}"


def synth_pdk_tree(base: Path, revision: str = FIXTURE_REVISION) -> Path:
    """A content-addressed PDK install under *base*, returning the entry path.

    Two declared sources on purpose — the `versions/<rev>/` install segment and
    a root `SOURCES` line — so a test exercising this fixture also exercises the
    resolver's corroboration between them.
    """
    store = base / "pdkstore" / "versions" / revision / "procx"
    (store / "libs.ref" / "cellsA" / "lib").mkdir(parents=True, exist_ok=True)
    (store / "SOURCES").write_text(f"upstream_pdk {revision}\n", encoding="utf-8")
    (store / "libs.ref" / "cellsA" / "lib" / "cellsA__tt.lib").write_text(
        "/* synthesized liberty stub */\n", encoding="utf-8")
    entry = base / "procx"
    if not entry.exists():
        entry.symlink_to(Path("pdkstore") / "versions" / revision / "procx")
    return entry


def write_run_pdk_revision(run: Path, base: Optional[Path] = None,
                           revision: str = FIXTURE_REVISION) -> Path:
    """Give *run* the PDK-revision record `benchmark_evidence_publish` requires.

    Produced by the real resolver against a tree built by :func:`synth_pdk_tree`
    — never hand-written.
    """
    base = Path(base) if base is not None else Path(run).parent / "_pdks"
    base.mkdir(parents=True, exist_ok=True)
    tree = synth_pdk_tree(base, revision)
    fs = _prr.Fs(None)
    rec = _prr.build_record([_prr.resolve_tree(fs, str(tree))], "host",
                            "test fixture")
    out = Path(run) / _prr.RECORD_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    _prr._emit(str(out), rec)
    return out
