"""Regression: the seal-ring FAIL reason must quote what went wrong.

MEASURED, on the pinned EDA image. That image's PDK ships
`libs.tech/klayout/tech/scripts/sealring.py` WITHOUT the PCell library it
imports; the script prints one error, calls `sys.exit()` with no argument — so it
exits 0 — and writes no layout. `die_finishing_gen` catches this correctly,
because it diffs the layouts instead of trusting `rc`, and reports FAIL.

The REASON it printed was:

    the PDK seal-ring generator (.../sealring.py) produced no output layout at
    .../spm.sealed.gds — it exited 0 and said: [INFO]

`[INFO] Final PATH variable: ...` is the container launcher's banner. It is
printed BEFORE the tool runs and it is not what went wrong; the line that says
what went wrong — `Error: Couldn't load the seal ring library.` — is last, and it
was dropped. A reader following that reason goes and looks at the PATH.

A tool says what failed last, so the reason quotes the last non-empty line, and
skips launcher banners if the last line is one. The full output stays in
`generator_output` either way — this only decides which line the human-readable
reason carries.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import die_finishing_gen as G  # noqa: E402

# Verbatim from `arm_noring/reports/phase3/die_finishing.json` on 2026-08-21,
# truncated only in the PATH values.
_REAL = ("[INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin\n"
         "[INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12\n"
         "Error: Couldn't load the seal ring library.")


def test_the_tools_own_error_is_quoted_not_the_launcher_banner():
    assert G._last_said(_REAL) == "Error: Couldn't load the seal ring library."


def test_the_first_line_is_not_what_is_quoted():
    """The negative arm: pinning only the string above would also pass for an
    implementation that happened to pick line 3 by index."""
    assert not G._last_said(_REAL).startswith("[INFO]")


def test_a_single_error_line_is_quoted_unchanged():
    assert G._last_said("Segmentation fault") == "Segmentation fault"


def test_trailing_blank_lines_do_not_become_the_quote():
    assert G._last_said("boom\n\n   \n") == "boom"


def test_output_that_is_ALL_launcher_banner_still_says_something():
    """Better a banner than an empty quote — the caller has already decided
    there IS output, and printing nothing would read as 'it said nothing'."""
    assert G._last_said("[INFO] a\n[INFO] b") == "[INFO] b"


def test_no_output_quotes_nothing():
    assert G._last_said("") == ""
    assert G._last_said("   \n\n") == ""


def test_the_quote_is_bounded():
    assert len(G._last_said("x" * 5000)) == 200
    assert len(G._last_said("x" * 5000, limit=40)) == 40
