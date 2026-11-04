import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_expert_parse_track as track


def test_long_prose_quantities_finish_without_rescanning_prefixes():
    def expired(signum, frame):
        raise TimeoutError("quantity extraction stalled on repeated ordinary prose")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(3)
    try:
        text = ("padding " * 128 + "17 ns. ") * 2048
        quantities = track._prose_quantities(text)
        assert len(quantities) == 2048
        expected = track.parse_quantity("17 ns")
        assert expected is not None
        assert all(expected.matches(value) for value in quantities)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("text, expected", [
    ("Delay (17 ns).", [17]),
    ("Delay: 17 ns.", []),
    ("from 29 to 17 ns", []),
    ("29 ns to 17 ns", []),
    ("1e+ 17 ns", []),
    ("Delay 17 ns per iteration", []),
    ("Delay 17 ns / tick", []),
    ("17 ns and 29 ns.", [17, 29]),
    ("prefix_to 17 ns.", [17]),
    ("value\\ 17 ns", []),
    ("[17 ns]", [17]),
    ("1.0e-\n17 ns", []),
])
def test_local_context_preserves_quantity_meaning(text, expected):
    assert [value.value for value in track._prose_quantities(text)] == expected
