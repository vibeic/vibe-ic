"""ROUND 19 — the LEF ORIGIN reader is exercised against a real LEF.

WHY THIS EXISTS. `_lef_macro_origins_text` does not live in this repository as
code. It lives inside a NON-RAW Python string in `phase3_one_shot_runner.py`
that is written out as a generated script and executed there. That extra layer
is a trap, and it caught a reader of this branch: read as source, the branch's
`r"^\\\\s*MACRO..."` looks like a doubled-escape corruption that could never
match a LEF. It is not. Through a non-raw enclosing string `\\\\s` emits `\\s`,
so the generated script gets the correct pattern — and the single-backslash
spelling it replaced is an INVALID ESCAPE SEQUENCE that Python already rejects
under `-W error::SyntaxWarning`.

Both spellings emit the same script today, so no eyeball on the source can
settle it. Only running the emitted function on a real LEF can, and nothing
did. These tests do.

They fail against a genuinely broken emit in either direction: a pattern whose
whitespace class is a literal backslash (matches nothing) and a backreference
written as a non-raw `\\1` (emits the control byte 0x01).
"""
import io
import re
import tokenize
from pathlib import Path

RUNNER = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"

LEF = """\
VERSION 5.8 ;
MACRO delta_sigma
  CLASS BLOCK ;
  ORIGIN -12.500 -7.250 ;
  SIZE 100 BY 80 ;
END delta_sigma
MACRO u_ldo
  CLASS BLOCK ;
  ORIGIN 0.000 0.000 ;
END u_ldo
"""


def _emitted_script() -> str:
    """The generated-script text that carries `_lef_macro_origins_text`."""
    src = RUNNER.read_text()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if (tok.type == tokenize.STRING
                and "_lef_macro_origins_text" in tok.string
                and "MACRO" in tok.string):
            return eval(tok.string)          # noqa: S307 - our own literal
    raise AssertionError("the emitted script carrying _lef_macro_origins_text "
                         "was not found in phase3_one_shot_runner.py")


def _emitted_reader():
    """`_lef_macro_origins_text` as the generated script really defines it."""
    text = _emitted_script()
    start = text.index("def _lef_macro_origins_text")
    body = text[start:]
    end = body.find("\n\n\n")
    ns = {}
    exec(body if end < 0 else body[:end], ns)   # noqa: S102 - emitted by us
    return ns["_lef_macro_origins_text"]


def test_the_reader_returns_a_non_zero_origin_from_a_real_lef():
    # The whole point: a gate that reads no macro origin and finds none is a
    # gate that always passes. This asserts it actually reads one.
    assert _emitted_reader()(LEF).get("delta_sigma") == (-12.5, -7.25)


def test_a_zero_origin_is_not_reported_as_a_finding():
    # The function's contract is NON-ZERO origins only; u_ldo states 0 0.
    assert "u_ldo" not in _emitted_reader()(LEF)


def test_the_emitted_pattern_carries_no_control_byte():
    # Writing the backreference as a non-raw `\1` emits chr(1) and the macro
    # can never close. That is the failure a source-level "repair" introduces.
    line = next(l for l in _emitted_script().splitlines()
                if "finditer" in l and "MACRO" in l)
    assert not [c for c in line if ord(c) < 32 and c != "\t"], (
        f"emitted MACRO pattern carries a control byte: {line!r}")


def test_the_emitted_whitespace_class_is_a_class_not_a_literal_backslash():
    line = next(l for l in _emitted_script().splitlines()
                if "finditer" in l and "MACRO" in l)
    assert r"\\s" not in line, (
        "the emitted pattern has a DOUBLED escape, so its whitespace class is "
        f"a literal backslash and matches no LEF: {line!r}")


def test_the_enclosing_literal_has_no_invalid_escape_sequence():
    # The spelling this branch replaced (`\s` inside a NON-raw string) is an
    # invalid escape sequence; Python already errors on it under
    # -W error::SyntaxWarning and will eventually error unconditionally.
    src = RUNNER.read_text()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if (tok.type == tokenize.STRING
                and "_lef_macro_origins_text" in tok.string
                and "MACRO" in tok.string):
            prefix = tok.string[:len(tok.string) - len(tok.string.lstrip("rRbBfFuU"))]
            if "r" in prefix.lower():
                return                       # a raw literal has no such trap
            bad = re.findall(r"(?<!\\)\\(?![\\nrtvfab0-7xNuU'\"\n])", tok.string)
            assert not bad, (
                f"the enclosing NON-raw literal has {len(bad)} invalid escape "
                f"sequence(s); double them or make the literal raw")
            return
    raise AssertionError("literal not found")
