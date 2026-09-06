#!/usr/bin/env python3
"""The oracle sweep's two declared reports appear complete or not at all. #1082.

`oracle_self_consistency_sweep.main` wrote both of its declared artefacts with
`Path.write_text`, which TRUNCATES the destination before it writes. A death
mid-write therefore leaves a SHORT file under the FINAL name, and a reader
cannot tell it from a finished one — for these two artefacts that matters more
than usual, because a truncated `broken` list reads as a CLEANER benchmark
result than the run actually measured.

`atomic_artifact_write_check` caught it and blocked, and that gate is the
structural half. THIS FILE IS THE BEHAVIOURAL HALF, and it exists because the
module's own 27 tests never reach `main()`: neither `theoretical_max.json` nor
`ORACLE_SWEEP.md` is named anywhere in them, so before this file the two
converted lines had no executable coverage at all and a conversion that changed
the payload, the path, or the return code would have gone green.

Both directions are pinned: the bytes must be IDENTICAL to what the replaced
call produced (a conversion is not the place to also change what is written),
and the destination must never exist in a partial state.

chip-AGNOSTIC: no chip, PDK, vendor or design literal — the fixture payload is
the artefact's own schema.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import oracle_self_consistency_sweep as S     # noqa: E402

#: The artefact's own shape, carrying non-ASCII on purpose: `write_json`
#: DEFAULTS to `ensure_ascii=False`, so a conversion that took the default
#: would re-encode exactly this payload and nothing would say so.
_RES = {
    "theoretical_max": {
        "total": 3,
        "broken": [{"id": "p_001", "reason": "BROKEN_GOLDEN",
                    "evidence": "0 of 3 arms agree — Mānoa 目標"}],
        "not_measured": [{"id": "p_002", "reason": "no simulator"}],
        "max": 2,
    },
}
_MD = "# ORACLE SWEEP\n\n| id | verdict |\n|---|---|\n| p_001 | Mānoa 目標 |\n"


@pytest.fixture()
def driven(tmp_path, monkeypatch):
    """`main()` with the simulation replaced, so only the WRITE is measured."""
    monkeypatch.setattr(S, "sweep", lambda *a, **k: _RES)
    monkeypatch.setattr(S, "render_markdown", lambda *a, **k: _MD)
    monkeypatch.setattr(S, "_git_sha", lambda *a, **k: "0" * 40)
    monkeypatch.setattr(S, "_tool_versions", lambda *a, **k: {})
    out = tmp_path / "out"
    rc = S.main(["--bench", "b", "--dataset", str(tmp_path), "--out", str(out)])
    return rc, out


def test_both_declared_artefacts_are_written(driven) -> None:
    rc, out = driven
    assert rc == 0
    assert (out / "theoretical_max.json").is_file()
    assert (out / "ORACLE_SWEEP.md").is_file()


def test_the_bytes_are_what_the_replaced_call_produced(driven) -> None:
    """The conversion must not also change the payload.

    This is the assertion that fails if `write_json` is called on its DEFAULT
    `ensure_ascii=False`: the fixture's non-ASCII evidence string is escaped by
    the call being replaced and is not by the default.
    """
    _rc, out = driven
    want_json = json.dumps(_RES["theoretical_max"], indent=2) + "\n"
    assert (out / "theoretical_max.json").read_bytes() == want_json.encode()
    assert (out / "ORACLE_SWEEP.md").read_bytes() == _MD.encode()


def test_the_artefact_round_trips(driven) -> None:
    _rc, out = driven
    got = json.loads((out / "theoretical_max.json").read_text())
    assert got == _RES["theoretical_max"]


def test_no_temp_artefact_is_left_behind(driven) -> None:
    """Atomic means the scratch name is gone, not merely that the final exists."""
    import _atomic_artefact as aa
    _rc, out = driven
    leftovers = [p.name for p in out.iterdir() if aa.is_temp_artefact(p)]
    assert leftovers == [], leftovers


# A "SERIALISE-FIRST" TEST WAS WRITTEN HERE AND DELETED, ON MEASUREMENT.
# `write_json` builds the whole string before opening anything, so a
# non-serialisable value writes no file — true, and worth having where it is
# load-bearing. It is NOT load-bearing at THIS call site: the call being
# replaced was `Path.write_text(json.dumps(...) + "\n")`, where `json.dumps` is
# an ARGUMENT and therefore also raises before the destination is touched. The
# test passed identically against the pre-fix code and against every mutation
# of the fix, so it could not fail — and a check that cannot fail is a green
# light, not a check. Recorded rather than silently dropped, so the next reader
# does not add it back believing it covers something.


def test_the_writes_go_through_the_shared_helper() -> None:
    """A behavioural test can be satisfied by a second private atomic writer.

    This says WHICH writer is used, so re-growing a local one — or reverting to
    `Path.write_text` — is caught even if the bytes happen to agree.
    """
    import inspect
    src = inspect.getsource(S.main)
    assert '(out / "theoretical_max.json").write_text(' not in src
    assert '(out / "ORACLE_SWEEP.md").write_text(' not in src
    assert "write_json(out /" in src
    assert "write_text(out /" in src
    assert "ensure_ascii=True" in src
