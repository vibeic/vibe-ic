"""Finite reset declarations scoped to current-design clauses and exact ports.

Historical comparisons are not declarations. Conflicting explicit values remain
unknown; no corpus-global name/value join or generated-artifact inference.
"""
import re

_HISTORY = re.compile(r'\b(?:previous(?:ly)?|prior|historical|legacy|formerly)\b|先前|舊版|旧版|以前', re.I)
_COMPARISON = re.compile(r'\b(?:unlike|in contrast to|compared (?:with|to))\b|[與与].{0,16}(?:先前|舊版|旧版|以前)', re.I)
_SYNC = re.compile(r'\b(?:asynchronous|async(?:_reset)?|synchronous|sync_reset|synced reset)\b|非同步|異步|异步|同步', re.I)
_POLARITY = re.compile(r'\bactive[- _]?(low|high)\b', re.I)


def current_clause(line):
    # Keep declaration parentheses; discard only explicitly historical ones.
    line = re.sub(r'\([^()]*\)|（[^（）]*）',
                  lambda m: '' if _HISTORY.search(m[0]) or _COMPARISON.search(m[0]) else m[0], line)
    line = re.split(_COMPARISON, line, maxsplit=1)[0]
    if _HISTORY.search(line):
        return ''
    return line


def declarations(text, name=None):
    """Yield source-line-bound reset declarations; never borrow another port."""
    port = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.I) if name else None
    for number, raw in enumerate(text.splitlines(), 1):
        for clause in re.split(r'[;；。]|(?<=[a-zA-Z])\.\s+', raw):
            line = current_clause(clause)
            if not line or (port and not port.search(line)):
                continue
            if not port and not re.search(r'reset|\brst\w*\b|重置|復位|复位', line, re.I):
                continue
            syncs = {'asynchronous' if m[0].lower().startswith(('async','非','異','异')) else 'synchronous' for m in _SYNC.finditer(line)}
            polarities = {'active_' + m[1].lower() for m in _POLARITY.finditer(line)}
            if syncs or polarities:
                yield {'line': number, 'evidence': raw.strip(),
                       'sync_values': syncs, 'polarity_values': polarities}


def reset_semantics(name, text):
    rows = list(declarations(text, name))
    result = {}
    for field in ('sync', 'polarity'):
        values = set().union(*(row[field + '_values'] for row in rows))
        if values:
            result[field] = next(iter(values)) if len(values) == 1 else 'unknown'
    return result
