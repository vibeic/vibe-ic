

# ── polarity is a property of SENTENCES (2026-08-04) ────────────────────────
#
# The gate reported `parse_tech_lef` — a LEF grammar parser whose every pattern
# is `^KEYWORD ... ;` — as a polarity-blind prose extractor, and blocked a PR
# that was correct. A `LAYER met4 ;` line has no clause that can DENY the value
# beside it; asking a format parser to consult a negation vocabulary is asking it
# to look for something that cannot be there. A gate that fails correct code gets
# switched off, which costs more than the case it was guarding.

_FORMAT_PARSER = '''
import re
_RE_LAYER = re.compile(r"^LAYER\\s+(\\S+)\\s*;")
def parse(text, out):
    for ln in text.splitlines():
        m = _RE_LAYER.search(ln)
        if m:
            out["layer"] = m.group(1)
'''

_PROSE_EXTRACTOR = '''
import re
_RE_PDK = re.compile(r"targeted at (\\w+)")
def parse(text, out):
    m = _RE_PDK.search(text)
    if m:
        out["pdk_target"] = m.group(1)
'''

_INTERPOLATED = '''
import re
def parse(text, name, out):
    m = re.search(rf"\\b{name}\\b\\s+is\\s+(\\w+)", text)
    if m:
        out["top_module"] = m.group(1)
'''


def _blind(src):
    import prose_polarity_consulted_check as G
    return G.scan_source(src, "m") if hasattr(G, "scan_source") else None


def test_a_format_grammar_parser_is_not_a_prose_extractor():
    import prose_polarity_consulted_check as G
    import ast
    tree = ast.parse(_FORMAT_PARSER)
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)][0]
    assert G._parses_a_format(fn, G._module_patterns(tree)), (
        "an anchored ALL-CAPS keyword grammar was judged to be prose")


def test_a_real_prose_extractor_is_still_caught():
    """The control. If narrowing the gate also excused `targeted at <PDK>` — the
    #706 defect verbatim — the narrowing has removed the gate, not sharpened it."""
    import prose_polarity_consulted_check as G
    import ast
    tree = ast.parse(_PROSE_EXTRACTOR)
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)][0]
    assert not G._parses_a_format(fn, G._module_patterns(tree)), (
        "an English sentence was judged to be a format grammar")


def test_an_INTERPOLATED_pattern_is_never_excused():
    """FAIL-SAFE, and the reason it exists.

    `rf"\\b{name}\\b"` yields the literal fragments `\\b` and `\\b`. Those contain
    no letters, so a "no words, therefore not prose" test excused
    `_extract_top_module_from_docs` — a function that mines DOCUMENTS for a
    declared value, i.e. exactly what this gate is for. A pattern that cannot be
    read must count as prose; anything else lets interpolation buy silence."""
    import prose_polarity_consulted_check as G
    import ast
    tree = ast.parse(_INTERPOLATED)
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)][0]
    assert not G._parses_a_format(fn, G._module_patterns(tree)), (
        "an interpolated pattern was judged from its literal fragments alone")
