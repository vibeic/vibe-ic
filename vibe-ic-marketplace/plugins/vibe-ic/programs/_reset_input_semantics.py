"""Finite reset declarations scoped to current-design clauses and exact ports.

Historical comparisons are not declarations. Conflicting explicit values remain
unknown; no corpus-global name/value join or generated-artifact inference.
"""
import hashlib
import math
import re
from pathlib import Path

_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')
_PHASE_COLUMNS = ('clock', 'reset', 'polarity', 'assertion', 'release',
                  'release synchronizer stages')
_GUARD_COLUMNS = ('deassertion guard ns', 'release guard ns')
_NO_PHASE_LOCK = re.compile(
    r'\b(?:no|without)\s+(?:external\s+)?(?:reset\s+)?phase\s+'
    r'(?:lock|locking|relationship|guarantee)\b|'
    r'\b(?:reset\s+)?deassert(?:ion|s)?\s+(?:is\s+)?(?:not\s+)?'
    r'(?:phase[- ]locked|phase[- ]aligned)|'
    r'\b(?:reset\s+)?deassert(?:ion|s)?\s+(?:may|can)\s+(?:occur|arrive)\s+'
    r'(?:at|in)\s+any\s+(?:clock\s+)?phase\b', re.I)


def _current_phase_authority(text):
    """Apply existing history/denial rules to this phase authority only."""
    from _prose_polarity import is_denied
    if not current_clause(text):
        return False
    # Denial must govern current/binding authority, not an unrelated Note
    # such as "No enable signal is required" on a valid phase declaration.
    for phrase in re.finditer(
            r'\b(?:[A-Za-z]+(?:\s+(?:a|an|the))?\s+|non-)(?:current|binding)\b',
            text, re.I):
        if is_denied(phrase[0], ignore_bracketed=False):
            return False
    return True


def _phase_table_rows(text):
    """Keep each phase row's source position and local heading authority."""
    columns = None
    headings = []
    for number, raw in enumerate(text.splitlines(), 1):
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', raw)
        if heading:
            level = len(heading[1])
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, _current_phase_authority(heading[2])))
        if not raw.strip().startswith('|'):
            columns = None
            continue
        cells = [cell.strip().strip('`*').strip()
                 for cell in raw.strip().strip('|').split('|')]
        names = tuple(cell.lower() for cell in cells)
        if set(_PHASE_COLUMNS).issubset(names):
            columns = {key: names.index(key) for key in _PHASE_COLUMNS}
            for key in _GUARD_COLUMNS:
                if key in names:
                    columns['deassertion guard ns'] = names.index(key)
                    break
            continue
        if columns is None or all(re.fullmatch(r'[-:\s]+', cell) for cell in cells):
            continue
        if len(cells) <= max(columns.values()):
            continue
        values = {key: cells[index] for key, index in columns.items()}
        yield number, raw, values, (all(current for _, current in headings)
                                    and _current_phase_authority(raw))


def phase_declarations(text):
    """Read only current explicit reset-phase rows, with original line basis."""
    for number, raw, values, current in _phase_table_rows(text):
        if not current:
            continue
        reset = values['reset']
        if not _NAME.fullmatch(reset):
            continue
        assertion = values['assertion'].lower()
        assertion = assertion if assertion in ('asynchronous', 'synchronous') else 'unknown'
        release = re.fullmatch(r'(asynchronous|synchronous)(?:\s+to\s+`?([A-Za-z_][\w$]*)`?)?',
                               values['release'], re.I)
        polarity = values['polarity'].lower().replace('-', '_')
        try:
            guard = float(values.get('deassertion guard ns', 'unknown'))
        except ValueError:
            guard = 'unknown'
        if isinstance(guard, float) and not math.isfinite(guard):
            guard = 'unknown'
        yield {'reset': reset,
               'clock': values['clock'] if _NAME.fullmatch(values['clock']) else 'unknown',
               'assertion': assertion,
               'release': release[1].lower() if release else 'unknown',
               'release_clock': release[2] if release and release[2] else 'unknown',
               'release_stages': int(values['release synchronizer stages'])
                   if re.fullmatch(r'[1-9]\d*', values['release synchronizer stages']) else 'unknown',
               'deassertion_guard_ns': guard,
               'polarity': polarity if polarity in ('active_low', 'active_high') else 'unknown',
               'line': number, 'quote': raw.strip()}


def reset_domain_bindings(name, extracted):
    """Merge the same explicit domain declaration without choosing a conflict."""
    groups = {}
    for source, text in extracted.items():
        source_sha256 = hashlib.sha256(text.encode()).hexdigest()
        for row in phase_declarations(text):
            if row['reset'] == name:
                groups.setdefault(row['clock'], []).append((source, source_sha256, row))
    result = []
    for clock, rows in groups.items():
        binding = {'clock': clock}
        for field in ('assertion', 'release', 'release_clock', 'release_stages',
                      'deassertion_guard_ns', 'polarity'):
            values = {row[field] for _, _, row in rows}
            binding[field] = next(iter(values)) if len(values) == 1 else 'unknown'
        binding['basis'] = [{'file': source, 'line': row['line'], 'quote': row['quote'],
                             'sha256': source_sha256}
                            for source, source_sha256, row in rows]
        result.append(binding)
    # A source may deliberately state that reset deassertion has no external
    # phase guarantee.  That is different from an omitted number: it requests
    # the exact, structurally proven synchronizer exception path.  Keep the
    # source line and full-file digest so a changed reset/clock statement
    # invalidates the request before an SDC exception can be authored.
    no_phase_basis = []
    name_re = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.I)
    for source, text in extracted.items():
        headings = []
        digest = hashlib.sha256(text.encode()).hexdigest()
        for number, raw in enumerate(text.splitlines(), 1):
            heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', raw)
            if heading:
                level = len(heading[1])
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, _current_phase_authority(heading[2])))
            current = current_clause(raw)
            if (current and all(authority for _, authority in headings)
                    and name_re.search(current)
                    and _NO_PHASE_LOCK.search(current)):
                no_phase_basis.append({'file': source, 'line': number,
                                       'quote': raw.strip(), 'sha256': digest})
    if no_phase_basis:
        for binding in result:
            if ((binding.get('assertion'), binding.get('release')) ==
                    ('asynchronous', 'synchronous')
                    and binding.get('deassertion_guard_ns') == 'unknown'):
                binding['deassertion_policy'] = 'structural_sync_release'
                binding['deassertion_policy_basis'] = list(no_phase_basis)
    # A phase table is not allowed to overrule an independent declaration.
    # Compare assertion and release separately, including any explicit target
    # and depth. Unknown/conflicting values reach the existing admission refusal.
    for text in extracted.values():
        for line in _reset_prose_clauses(text, name):
            for fact in _prose_phases(line):
                targets = fact['clocks']
                if targets - set(groups):
                    for binding in result:
                        binding['release_clock'] = 'unknown'
                for binding in result:
                    if targets and binding['clock'] not in targets:
                        continue
                    phase = fact['phase']
                    if binding[phase] != fact['mode']:
                        binding[phase] = 'unknown'
                    if phase == 'release' and any(
                            depth != binding['release_stages'] for depth in fact['stages']):
                        binding['release_stages'] = 'unknown'
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
            structural = (b.get('deassertion_policy') ==
                          'structural_sync_release'
                          and isinstance(b.get('deassertion_policy_basis'), list)
                          and bool(b['deassertion_policy_basis']))
            if (name not in physical or b['clock'] not in physical or b['clock'] not in visible
                    or b['assertion'] not in ('asynchronous', 'synchronous')
                    or b['release'] not in ('asynchronous', 'synchronous')
                    or b['release_clock'] != b['clock']
                    or b['polarity'] not in ('active_low', 'active_high')
                    or type(b['release_stages']) is not int or b['release_stages'] <= 0
                    or (b['assertion'] == 'asynchronous'
                        and b['release'] == 'synchronous'
                        and not structural
                        and (type(b['deassertion_guard_ns']) not in (int, float)
                             or not math.isfinite(b['deassertion_guard_ns'])
                             or b['deassertion_guard_ns'] <= 0))):
                refuse(f'{name}: incomplete, conflicting or unbound source phase')

    def same_bindings(actual, wanted):
        if not isinstance(actual, list) or len(actual) != len(wanted):
            return False
        by_clock = {b.get('clock'): b for b in actual if isinstance(b, dict)}
        if len(by_clock) != len(actual):
            return False
        keys = ('clock', 'assertion', 'release', 'release_clock', 'release_stages',
                'deassertion_guard_ns', 'polarity', 'deassertion_policy')
        def basis(b):
            rows = b.get('basis')
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                return None
            return sorted((str(r.get('file')), str(r.get('line')), str(r.get('quote')),
                           str(r.get('sha256'))) for r in rows)
        def policy_basis(b):
            rows = b.get('deassertion_policy_basis')
            if rows is None:
                return None
            if not isinstance(rows, list) or not rows or not all(
                    isinstance(r, dict) for r in rows):
                return ()
            return sorted((str(r.get('file')), str(r.get('line')), str(r.get('quote')),
                           str(r.get('sha256'))) for r in rows)
        for w in wanted:
            a = by_clock.get(w['clock'], {})
            if (any(a.get(k) != w.get(k) for k in keys)
                    or type(a.get('release_stages')) is not int
                    or basis(a) != basis(w)
                    or policy_basis(a) != policy_basis(w)):
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
_PROSE_PHASE = re.compile(
    r'\b(?:(?P<mode>asynchronous|synchronous)\s+(?P<phase>assertion|release|deassertion)'
    r'|(?P<phase_first>assertion|release|deassertion)\s+(?:is\s+)?'
    r'(?P<mode_after>asynchronous|synchronous))\b', re.I)
_STAGE_NUMBER = {word: i for i, word in enumerate(
    ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'))}


def _reset_prose_clauses(text, name):
    port = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.I)
    table_lines = {number for number, _, _, _ in _phase_table_rows(text)}
    for number, raw in enumerate(text.splitlines(), 1):
        if number in table_lines:
            continue
        for clause in re.split(r'[;；。]|(?<=[a-zA-Z])\.\s+', raw):
            line = current_clause(clause)
            if line and port.search(line):
                yield line


def _prose_phases(line):
    """Finite named phase clauses; unsupported qualifiers stay unknown.

    The returned spans cover only phase-qualified synchrony tokens. Every
    unqualified token still participates in the legacy ambiguity vote.
    """
    from _prose_polarity import is_denied
    matches = list(_PROSE_PHASE.finditer(line))
    for i, match in enumerate(matches):
        phase = (match['phase'] or match['phase_first']).lower()
        phase = 'release' if phase == 'deassertion' else phase
        suffix = line[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(line)]
        prefix = line[matches[i - 1].end() if i else 0:match.start()]
        # Validate complete target clauses, not a recognized prefix. Conjunctive
        # lists admit every named clock; alternatives or unsupported remainder
        # leave the phase unknown even when no stage qualifier is present.
        targets = list(re.finditer(r'\b(?:to|on)\s+', suffix, re.I))
        clocks = set()
        invalid_targets = False
        for j, target in enumerate(targets):
            clause = suffix[target.end():targets[j + 1].start()
                            if j + 1 < len(targets) else len(suffix)]
            # Stage values are validated below. Remove only their finite
            # qualifier grammar here; any other trailing text must still parse.
            clause = re.sub(r'\s+(?:through|with|after)\s+[\w.+-]+[ -]stages?\b',
                            '', clause, flags=re.I).strip().rstrip('.!?').strip()
            if j + 1 < len(targets):
                clause = re.sub(r'\s+and$', '', clause, flags=re.I)
            for token in re.split(r'\s*,\s*(?:and\s+)?|\s+and\s+', clause, flags=re.I):
                clock = re.fullmatch(r'`([A-Za-z_][\w$]*)`|([A-Za-z_][\w$]*)', token)
                name = (clock[1] or clock[2]) if clock else None
                if name is None or name.lower() in ('and', 'or'):
                    invalid_targets = True
                else:
                    clocks.add(name)
        stages = []
        if phase == 'release':
            before = re.search(r'(?<![\w.-])([\w.+-]+)[ -]stages?\s*$', prefix, re.I)
            stage_text = (before[0] if before else '') + ' ' + suffix
            for depth in re.finditer(r'(?<![\w.-])([\w.+-]+)[ -]stages?\b', stage_text, re.I):
                value = depth[1].lower()
                stages.append(int(value) if value.isdigit() else _STAGE_NUMBER.get(value, 'unknown'))
            if re.search(r'\bstages?\b', stage_text, re.I) and not stages:
                stages.append('unknown')
            if stages and re.search(r'\bor\b|/|\bat\s+(?:least|most)\b', stage_text, re.I):
                stages.append('unknown')
        mixed = re.search(r'\b(?:asynchronous|synchronous)\s*(?:/|or|and)\s*$', prefix, re.I)
        yield {'phase': phase, 'mode': 'unknown' if invalid_targets or mixed or is_denied(line, ignore_bracketed=False)
               else (match['mode'] or match['mode_after']).lower(),
               'clocks': clocks, 'stages': stages, 'span': match.span()}
    # A synchrony word beside an unparsed phase is not permission to use the
    # table's answer. Leave it unresolved at the same consumer boundary.
    for phase in re.finditer(r'\b(assertion|release|deassertion)\b', line, re.I):
        if _SYNC.search(line) and not any(m.start() <= phase.start() < m.end() for m in matches):
            yield {'phase': 'assertion' if phase[1].lower() == 'assertion' else 'release',
                   'mode': 'unknown', 'clocks': set(), 'stages': [], 'span': (0, 0)}


def current_clause(line):
    # Keep declaration parentheses; discard only explicitly historical ones.
    line = re.sub(r'\([^()]*\)|（[^（）]*）',
                  lambda m: '' if _HISTORY.search(m[0]) or _COMPARISON.search(m[0]) else m[0], line)
    line = re.split(_COMPARISON, line, maxsplit=1)[0]
    if _HISTORY.search(line):
        return ''
    return line


def explicit_reset_port(name, text):
    """Whether current source explicitly assigns this exact port the reset role."""
    from _prose_polarity import is_denied
    if any(row['reset'] == name for row in phase_declarations(text)):
        return True
    port = r'`?' + re.escape(name) + r'`?(?![\w])'
    role_first = re.compile(r'\breset(?:\s+(?:input|signal|port))?\s*(?:is|:|=)\s*' + port, re.I)
    name_first = re.compile(
        r'(?<![\w])' + port + r'\s*(?:is|:)\s*'
        r'(?:(?:an?|the|current|external|global|system|input|read|write|asynchronous|synchronous|'
        r'active[- _]?(?:low|high))\s+)*reset\b', re.I)
    for raw in text.splitlines():
        for clause in re.split(r'[;；。]|(?<=[a-zA-Z])\.\s+', raw):
            line = current_clause(clause)
            match = role_first.search(line) or name_first.search(line)
            if match and not is_denied(line[:match.end()], ignore_bracketed=False):
                return True
    return False


def event_declarations(text):
    """Finite named/role-bound edge events, not an RTL or prose parser.

    An unnamed ``the reset signal`` binds only to a unique explicitly
    defined reset input. Only an OR/comma event list containing a clock
    edge supplies asynchronous assertion; release timing is never inferred.
    """
    from _prose_polarity import is_denied
    roles = {'clock': set(), 'reset': set()}
    for raw in text.splitlines():
        definition = re.match(r'^\s*[-*]?\s*`?([A-Za-z_][\w$]*)`?\s*:', raw)
        if not definition:
            continue
        name = definition[1]
        current = current_clause(raw)
        if explicit_reset_port(name, current):
            roles['reset'].add(name)
        if re.match(r'^\s*(?:(?:the|chip|input|primary|system)\s+)*clock\b',
                    current[definition.end():], re.I) and not is_denied(current):
            roles['clock'].add(name)
    edge = re.compile(
        r'\b(?:(?P<rtl>posedge|negedge)\s+(?P<name>[A-Za-z_][\w$]*)|'
        r'(?P<prose>positive|rising|negative|falling)\s+edge\s+of\s+'
        r'(?:the\s+)?(?P<role>clock|reset)(?:\s+signal)?'
        r'(?:\s*\(\s*(?:posedge\s+|negedge\s+)?'
        r'(?P<bound>[A-Za-z_][\w$]*)\s*\))?)', re.I)
    for number, raw in enumerate(text.splitlines(), 1):
        for clause in re.split(r'[;；。]|(?<=[a-zA-Z])\.\s+', raw):
            line = current_clause(clause)
            matches = list(edge.finditer(line))
            if not matches or is_denied(line[:matches[-1].end()], ignore_bracketed=False):
                continue
            events = []
            for m in matches:
                role = (m['role'] or '').lower()
                name = m['name'] or m['bound']
                if not name and len(roles.get(role, ())) == 1:
                    name = next(iter(roles[role]))
                if not name:
                    continue
                if not role:
                    role = next((r for r, names in roles.items() if name in names), '')
                if not role:
                    continue
                value = (m['rtl'] or m['prose']).lower()
                events.append((m, name, role,
                               'posedge' if value in ('posedge', 'positive', 'rising') else 'negedge'))
            for match, name, role, value in events:
                clocks = [m for m, _, r, _ in events if r == 'clock']
                asynchronous = role == 'reset' and any(
                    re.search(r'\bor\b|,', line[min(m.end(), match.end()):max(m.start(), match.start())], re.I)
                    for m in clocks)
                yield {'name': name, 'role': role, 'edge': value,
                       'asynchronous': bool(asynchronous), 'line': number,
                       'evidence': raw.strip()}


def clock_edge_semantics(name, extracted):
    """Read exact input edges and attach source authority per field."""
    rows = []
    for source, text in extracted.items():
        for row in event_declarations(text):
            if row['name'] == name and row['role'] == 'clock':
                rows.append((source, text, row))
    values = {row['edge'] for _, _, row in rows}
    if not values:
        return {'edge': 'posedge', 'semantic_provenance': {'edge': {
            'kind': 'convention', 'rule': 'default_positive_clock_edge'}}}
    return {'edge': next(iter(values)) if len(values) == 1 else 'unknown',
            'semantic_provenance': {'edge': {
                'kind': 'explicit' if len(values) == 1 else 'conflict',
                'basis': [{'file': str(source), 'line': row['line'],
                           'quote': row['evidence'],
                           'sha256': hashlib.sha256(text.encode()).hexdigest()}
                          for source, text, row in rows]}}}


def reset_semantic_provenance(name, extracted):
    """Separate explicit source facts from an emitter's compatibility default."""
    rows = [(source, text, row) for source, text in extracted.items()
            for row in declarations(text, name)]
    result = {}
    for field in ('sync', 'polarity'):
        found = [(source, text, row) for source, text, row in rows
                 if row[field + '_values']]
        values = set().union(*(row[field + '_values'] for _, _, row in found))
        if values:
            result[field] = {
                'kind': 'explicit' if len(values) == 1 and 'unknown' not in values else 'conflict',
                'basis': [{'file': str(source), 'line': row['line'],
                           'quote': row['evidence'],
                           'sha256': hashlib.sha256(text.encode()).hexdigest()}
                          for source, text, row in found]}
        else:
            result[field] = {'kind': 'unspecified'}
    return result


def declarations(text, name=None):
    """Yield source-line-bound reset declarations; never borrow another port."""
    port = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.I) if name else None
    phases = {row['line']: row for row in phase_declarations(text)}
    phased = any(name is None or row['reset'] == name for row in phases.values())
    phase_lines = {number for number, _, _, _ in _phase_table_rows(text)}
    for event in event_declarations(text):
        if (event['role'] == 'reset' and event['asynchronous']
                and (name is None or event['name'] == name)):
            yield {'line': event['line'], 'evidence': event['evidence'],
                   'sync_values': {'asynchronous'},
                   'polarity_values': {'active_high' if event['edge'] == 'posedge' else 'active_low'}}
    for number, raw in enumerate(text.splitlines(), 1):
        phase = phases.get(number)
        if phase is not None:
            if name is None or name == phase['reset']:
                yield {'line': number, 'evidence': raw.strip(),
                       'sync_values': {phase['assertion']},
                       'polarity_values': {phase['polarity']}}
            continue
        # A filtered phase row is not legacy prose: release wording must not
        # become a second assertion declaration through the generic fallback.
        if number in phase_lines:
            continue
        # A port-definition row owns its whole description, including a
        # second sentence defining the reset's active/inactive binary levels.
        # Keep the exact port scope; a separate row cannot lend its polarity.
        if name and re.match(r'^\s*`?' + re.escape(name) + r'`?\s*:', raw):
            levels = set()
            if explicit_reset_port(name, raw):
                for match in re.finditer(
                        r'\b([01])\s+for\s+reset\s+and\s+([01])\s+for\s+'
                        r'(?:reset\s+)?signal\s+inactive\b', current_clause(raw), re.I):
                    if match[1] != match[2]:
                        levels.add('active_low' if match[1] == '0' else 'active_high')
            if levels:
                yield {'line': number, 'evidence': raw.strip(),
                       'sync_values': set(), 'polarity_values': levels}
        for clause in re.split(r'[;；。]|(?<=[a-zA-Z])\.\s+', raw):
            line = current_clause(clause)
            if not line or (port and not port.search(line)):
                continue
            if not port and not re.search(r'reset|\brst\w*\b|重置|復位|复位', line, re.I):
                continue
            facts = list(_prose_phases(line)) if phased else []
            syncs = {'asynchronous' if m[0].lower().startswith(('async','非','異','异')) else 'synchronous'
                     for m in _SYNC.finditer(line)
                     if not any(f['span'][0] <= m.start() < f['span'][1] for f in facts)}
            syncs.update(f['mode'] for f in facts if f['phase'] == 'assertion')
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
