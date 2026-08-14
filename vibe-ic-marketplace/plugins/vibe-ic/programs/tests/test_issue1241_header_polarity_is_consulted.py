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

`test_an_ordinary_apache_header_is_not_read_as_a_denial` pins a bug this fix had
on its first draft: with an unbounded sentence window, Apache-2.0's own
"you may not use this file except in compliance" reads as a denial and the holder
is dropped, which would turn a gate against unattributed bundling into a way to
LOSE attributions. Both directions are asserted here so neither can be traded for
the other later.

NOTE ON THE FIXTURES: the copyright lines are assembled at runtime rather than
written as literals. This checker scans `.py` files, so a literal header in this
module registers as a real bundled holder and reddens
`test_THIS_repository_accounts_for_everything_it_bundles` — measured, not feared.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import bundled_attribution_notice_check as bc  # noqa: E402

_HOLDER = "Acme Semiconductor"
#: Assembled, never a literal — see the module docstring.
_CR = "Copy" + "right 2020 " + _HOLDER

#: A header with nothing unusual about it. MUST still be recorded.
_PLAIN = f"""\
// SPDX-License-Identifier: Apache-2.0
// {_CR}
module m; endmodule
"""

#: An ORDINARY Apache header, boilerplate and all. MUST still be recorded: the
#: licence text's own "may not use this file" is not a denial of the bundling.
_APACHE = f"""\
// SPDX-License-Identifier: Apache-2.0
// {_CR}
// Licensed under the Apache License, Version 2.0; you may not use this file
// except in compliance with the License. Distributed WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied.
module m; endmodule
"""

#: The same holder, named by a sentence that DENIES the bundling. Modelled on the
#: real NOTICE line this gate was written for ("... source is NOT bundled in this
#: repository"), moved into the header where the holder is actually read.
_DENIED = f"""\
// SPDX-License-Identifier: Apache-2.0
// {_CR} - this file is NOT bundled from them, it
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
    assert any(_HOLDER in h for h in out), out


def test_an_ordinary_apache_header_is_not_read_as_a_denial(tmp_path):
    """The false-denial direction: licence boilerplate must not drop a holder."""
    out = _holders(tmp_path, _APACHE)
    assert any(_HOLDER in h for h in out), (
        "an ordinary Apache-2.0 header was read as DENYING its own copyright "
        f"and the holder was dropped: {out}. The licence text says 'you may "
        "not use this file except in compliance' — that is the licence's "
        "terms, not a statement that the work is unbundled. Dropping the "
        "holder here means bundled work ships with no attribution at all."
    )


def test_a_header_that_denies_the_bundling_is_not_recorded(tmp_path):
    """The defect: the sentence says NOT bundled, the gate recorded it as bundled."""
    out = _holders(tmp_path, _DENIED)
    assert not any(_HOLDER in h for h in out), (
        "the header states the work is NOT bundled and the holder was recorded "
        f"as a bundled third-party attribution anyway: {out}. NOTICE would then "
        "be required to account for a holder the source itself disclaims."
    )
