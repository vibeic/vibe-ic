"""`bundled work is named in NOTICE` — a bundled holder NOTICE does not name.

Both arms carry the same one SPDX-headered vendored file, so the gate's
population is identical in each: it refuses (rc 2) when no SPDX-headered source
exists at all, and a fixture that tripped that would be exercising the
zero-denominator refusal instead of the attribution rule.

The mutation removes the HOLDER LINE from NOTICE and nothing else. NOTICE still
exists — its absence is a different finding with a different message, and
proving that one would say nothing about whether the gate can read a NOTICE
that is present and incomplete.

The holder name is synthetic. A real upstream's name would make this fixture
read like an attribution record, and a reader who found it in the tree could
not tell it from one.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "bundled work is named in NOTICE"

_HOLDER = "Example Upstream Authors"
_VENDORED = ("// SPDX-License-Identifier: Apache-2.0\n"
             "// Copyright 2020 " + _HOLDER + "\n"
             "module fixture_core; endmodule\n")


def _tree(work: Path, notice: str) -> Path:
    root = F.git_init(work / "subject")
    (root / "NOTICE").write_text(notice)
    (root / "vendor").mkdir()
    (root / "vendor" / "core.sv").write_text(_VENDORED)
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, "fixture-subject\nCopyright 2026 fixturecorp\n"
                       + _HOLDER + "\n")


def can_fail(work: Path):
    return (_tree(work, "fixture-subject\nCopyright 2026 fixturecorp\n"),
            "are NOT named in NOTICE")
