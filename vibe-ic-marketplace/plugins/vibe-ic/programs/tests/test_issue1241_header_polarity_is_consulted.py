"""`scan()` must ask whether the header SENTENCE denies the bundling (vibe-ic#1241).

BATCH IDX group (c). `_named_without_denial` already asks this of NOTICE — it was
added because a bare substring search let a sentence DENYING the bundling satisfy
the very requirement it denies. The same question was never asked of the FILE
HEADER the holder is read out of, so the gate could still record an attribution
that the source text explicitly disclaims, and then require NOTICE to account for
a holder the source says is not bundled.

An extractor blind to polarity does not merely miss things: it confidently records
the OPPOSITE of what the document says. That is why the plain-header control below
is not decoration — without it, this module would still pass if `scan()` stopped
recording anything at all, which is the cheapest possible way to make a polarity
test look green.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import bundled_attribution_notice_check as bc  # noqa: E402

#: A header with nothing unusual about it. MUST still be recorded.
_PLAIN = """\
// SPDX-License-Identifier: Apache-2.0
// Copyright 2020 Acme Semiconductor
module m; endmodule
"""

#: The same holder, named by a sentence that DENIES the bundling. Modelled on the
#: real NOTICE line this gate was written for ("... source is NOT bundled in this
#: repository"), moved into the header where the holder is actually read.
_DENIED = """\
// SPDX-License-Identifier: Apache-2.0
// Copyright 2020 Acme Semiconductor - this file is NOT bundled from them, it
// was rewritten from the public specification
module m; endmodule
"""


def _holders(tmp_path: Path, text: str) -> list:
    (tmp_path / "a.v").write_text(text)
    return sorted(bc.scan(tmp_path))


def test_a_plain_header_is_still_recorded(tmp_path):
    """POSITIVE CONTROL — the polarity test must not be able to pass vacuously."""
    out = _holders(tmp_path, _PLAIN)
    assert out, "a plain SPDX + Copyright header must still be recorded"
    assert any("Acme" in h for h in out), out


def test_a_header_that_denies_the_bundling_is_not_recorded(tmp_path):
    """The defect: the sentence says NOT bundled, the gate recorded it as bundled."""
    out = _holders(tmp_path, _DENIED)
    assert not any("Acme" in h for h in out), (
        "the header states the work is NOT bundled and the holder was recorded "
        f"as a bundled third-party attribution anyway: {out}. NOTICE would then "
        "be required to account for a holder the source itself disclaims."
    )
