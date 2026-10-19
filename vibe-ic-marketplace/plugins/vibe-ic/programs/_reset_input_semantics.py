"""Finite reset declarations scoped to current-design clauses and exact ports.

Historical comparisons are not declarations. Conflicting explicit values remain
unknown; no corpus-global name/value join or generated-artifact inference.
"""
import re
from pathlib import Path

_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')
_PHASE_COLUMNS = ('clock', 'reset', 'polarity', 'assertion', 'release',
                  'release synchronizer stages')


def phase_declarations(text):
    """Read only explicit reset-phase table columns, with original line basis."""
    columns = None
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip().startswith('|'):
            columns = None
            continue
        cells = [cell.strip().strip('`*').strip()
                 for cell in raw.strip().strip('|').split('|')]
        names = tuple(cell.lower() for cell in cells)
        if set(_PHASE_COLUMNS).issubset(names):
            columns = {key: names.index(key) for key in _PHASE_COLUMNS}
            continue
        if columns is None or all(re.fullmatch(r'[-:\s]+', cell) for cell in cells):
            continue
        if len(cells) <= max(columns.values()):
            continue
        if not current_clause(raw):
            continue
        values = {key: cells[index] for key, index in columns.items()}
        reset = values['reset']
        if not _NAME.fullmatch(reset):
            continue
        assertion = values['assertion'].lower()
        assertion = assertion if assertion in ('asynchronous', 'synchronous') else 'unknown'
        release = re.fullmatch(r'(asynchronous|synchronous)(?:\s+to\s+`?([A-Za-z_][\w$]*)`?)?',
                               values['release'], re.I)
        polarity = values['polarity'].lower().replace('-', '_')
        yield {'reset': reset,
               'clock': values['clock'] if _NAME.fullmatch(values['clock']) else 'unknown',
               'assertion': assertion,
               'release': release[1].lower() if release else 'unknown',
               'release_clock': release[2] if release and release[2] else 'unknown',
               'release_stages': int(values['release synchronizer stages'])
                   if re.fullmatch(r'[1-9]\d*', values['release synchronizer stages']) else 'unknown',
               'polarity': polarity if polarity in ('active_low', 'active_high') else 'unknown',
               'line': number, 'quote': raw.strip()}


def reset_domain_bindings(name, extracted):
    """Merge the same explicit domain declaration without choosing a conflict."""
    groups = {}
    for source, text in extracted.items():
        for row in phase_declarations(text):
            if row['reset'] == name:
                groups.setdefault(row['clock'], []).append((source, row))
    result = []
    for clock, rows in groups.items():
        binding = {'clock': clock}
        for field in ('assertion', 'release', 'release_clock', 'release_stages', 'polarity'):
            values = {row[field] for _, row in rows}
            binding[field] = next(iter(values)) if len(values) == 1 else 'unknown'
        binding['basis'] = [{'file': source, 'line': row['line'], 'quote': row['quote']}
                            for source, row in rows]
        result.append(binding)
    return result


def admit_reset_phases(project, documents, surface=None):
    """Admit native phase bindings against current ordinary design input.

    This optional consumer boundary preserves legacy single-phase behavior.
    It does not rewrite layers, infer a reset timing cut, or certify hardware.
    ``sync`` summarizes assertion; release is a separate per-clock contract.
    """
    def refuse(reason):
        raise ValueError('RESET_PHASE_SOURCE_ADMISSION_REFUSED: ' + reason)

    def scopes(doc):
        result = [doc]
        if isinstance(doc.get('fields'), dict):
            result.append(doc['fields'])
        return result

    l9 = documents[0]
    pins = {}
    for scope in scopes(l9):
        for key in ('top_ports', 'ports', 'top_module_pins'):
            for pin in scope.get(key, []) or []:
                if isinstance(pin, dict):
                    pins.setdefault(pin.get('name'), pin)
    physical = {name for name, p in pins.items()
                if (p.get('direction') or p.get('mode') or p.get('io') or p.get('dir')) == 'input'
                and type(p.get('width')) is int and p['width'] == 1}
    root = Path(project) / 'input/docs'
    extracted = {p.relative_to(project).as_posix(): p.read_text(encoding='utf-8')
                 for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()
                 and p.suffix.lower() in ('.md', '.txt')
                 and p.resolve().is_relative_to(root.resolve())} if root.is_dir() else {}
    reset_names = {row['reset'] for text in extracted.values() for row in phase_declarations(text)}
    visible = set(pins) if surface is None else set(surface)
    selected = reset_names & visible
    expected = {name: reset_domain_bindings(name, extracted) for name in selected}
    for name, bindings in expected.items():
        for b in bindings:
            if (name not in physical or b['clock'] not in physical or b['clock'] not in visible
                    or b['assertion'] not in ('asynchronous', 'synchronous')
                    or b['release'] not in ('asynchronous', 'synchronous')
                    or b['release_clock'] != b['clock']
                    or b['polarity'] not in ('active_low', 'active_high')
                    or type(b['release_stages']) is not int or b['release_stages'] <= 0):
                refuse(f'{name}: incomplete, conflicting or unbound source phase')

    def same_bindings(actual, wanted):
        if not isinstance(actual, list) or len(actual) != len(wanted):
            return False
        by_clock = {b.get('clock'): b for b in actual if isinstance(b, dict)}
        if len(by_clock) != len(actual):
            return False
        keys = ('clock', 'assertion', 'release', 'release_clock', 'release_stages', 'polarity')
        def basis(b):
            rows = b.get('basis')
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                return None
            return sorted((str(r.get('file')), str(r.get('line')), str(r.get('quote'))) for r in rows)
        for w in wanted:
            a = by_clock.get(w['clock'], {})
            if (any(a.get(k) != w[k] for k in keys)
                    or type(a.get('release_stages')) is not int or basis(a) != basis(w)):
                return False
        return True

    primary = set()
    for index, document in enumerate(documents):
        for scope in scopes(document):
            containers = [scope]
            if isinstance(scope.get('clock_and_reset_waveform'), dict):
                containers.append(scope['clock_and_reset_waveform'])
            for container in containers:
                for key in ('reset_domains', 'resets'):
                    for row in container.get(key, []) or []:
                        if not isinstance(row, dict):
                            continue
                        name = row.get('name')
                        if surface is not None and name not in surface:
                            continue
                        bindings = row.get('domain_bindings')
                        if bindings is None:
                            continue
                        wanted = expected.get(name)
                        if not wanted or not same_bindings(bindings, wanted):
                            refuse(f'{name}: bindings do not match current source')
                        assertions = {b['assertion'] for b in wanted}
                        summary = next(iter(assertions)) if len(assertions) == 1 else 'unknown'
                        if row.get('sync') != summary or any(row.get('polarity') != b['polarity'] for b in wanted):
                            refuse(f'{name}: assertion summary/polarity mismatch')
                        if index == 0:
                            primary.add(name)
                for key in ('clock_domains', 'clocks'):
                    for clock in container.get(key, []) or []:
                        if not isinstance(clock, dict) or 'reset_bindings' not in clock:
                            continue
                        records = clock['reset_bindings']
                        if not isinstance(records, list) or not all(isinstance(b, dict) for b in records):
                            refuse('clock reset_bindings must be typed records')
                        wanted = {name: [b for b in bindings if b['clock'] in
                                         (clock.get('name'), clock.get('source_pin'))]
                                  for name, bindings in expected.items()}
                        wanted = {n: b for n, b in wanted.items() if b}
                        actual = {}
                        for binding in records:
                            name = binding.get('reset')
                            if surface is None or name in surface:
                                actual.setdefault(name, []).append(binding)
                        if set(actual) != set(wanted) or any(
                                not same_bindings(actual[n], wanted[n]) for n in wanted):
                            refuse('clock projection mismatch')
    if primary != selected:
        refuse('declared physical reset phase bindings missing from L9')
    return expected

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
    phases = {row['line']: row for row in phase_declarations(text)}
    for number, raw in enumerate(text.splitlines(), 1):
        phase = phases.get(number)
        if phase is not None:
            if name is None or name == phase['reset']:
                yield {'line': number, 'evidence': raw.strip(),
                       'sync_values': {phase['assertion']},
                       'polarity_values': {phase['polarity']}}
            continue
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
