#!/usr/bin/env python3
"""Every PPA identity is the sha256 of a canonical document, so this encoder is
the one place where two authors could silently disagree about what a fact IS.

These are the properties the rest of the PPA work is allowed to assume. Each one
is here because its opposite is a plausible implementation somebody could write
next week without noticing what it broke.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj  # noqa: E402


def test_key_order_is_not_part_of_the_fact():
    """Two dicts with the same pairs are the same fact and must hash the same.

    Without sort_keys, the identity of a contract would depend on the order its
    builder happened to assemble it in -- so re-running the same build on the
    same inputs could produce a different identity and every comparison against
    it would silently become a comparison against something else.
    """
    a = {"b": 1, "a": {"y": 2, "x": [3, 4]}}
    b = {"a": {"x": [3, 4], "y": 2}, "b": 1}
    assert cj.sha256(a) == cj.sha256(b)


def test_list_order_IS_part_of_the_fact():
    """The mirror of the above, and the reason sorting stops at keys.

    `[3, 4]` and `[4, 3]` are different values -- a corner list, a path, a
    sequence of stages. Sorting them would erase a difference that matters.
    """
    assert cj.sha256({"x": [3, 4]}) != cj.sha256({"x": [4, 3]})


def test_whitespace_is_not_information():
    assert cj.dumps({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_non_ascii_has_one_encoding():
    """ensure_ascii=False, so 'ü' is UTF-8 bytes and not the six characters
    \\u00fc. Both are valid JSON for the same string, which is exactly why one
    of them has to be chosen here rather than by whoever calls it."""
    assert cj.dumps({"a": "ü"}) == '{"a":"ü"}'
    assert cj.dumpb({"a": "ü"}) == '{"a":"ü"}'.encode("utf-8")


def test_nan_and_infinity_are_refused():
    """NaN and Infinity are not JSON. A metric that is NaN is NOT_MEASURED with
    a reason; letting it through would put a value in a document that two
    parsers can read differently."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            cj.dumps({"x": bad})


def test_the_digest_carries_its_algorithm():
    """`digest_of` is what goes INTO a document. A bare hex string does not say
    what produced it."""
    d = cj.digest_of({"a": 1})
    assert d.startswith("sha256:")
    assert len(d) == len("sha256:") + 64
    assert d[7:] == cj.sha256({"a": 1})


def test_the_bytes_hashed_are_the_bytes_of_the_document():
    """No trailing newline, no BOM: an independent reader who hashes the file
    must get the same answer as the producer who hashed the object."""
    import hashlib
    obj = {"schema": "vibeic.ppa.metric.v1", "metric": "timing.setup.wns_ns"}
    assert cj.sha256(obj) == hashlib.sha256(cj.dumps(obj).encode("utf-8")).hexdigest()
    assert not cj.dumps(obj).endswith("\n")


def test_a_float_round_trips_to_the_same_identity():
    """The value a parser read must hash the same after a JSON round trip, or a
    recorded metric and the same metric re-read from disk would be different
    facts."""
    obj = {"value": -0.124, "unit": "ns"}
    assert cj.sha256(json.loads(cj.dumps(obj))) == cj.sha256(obj)
