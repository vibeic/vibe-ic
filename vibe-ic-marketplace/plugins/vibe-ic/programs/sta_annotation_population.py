"""Typed timing-annotation population; never infer exclusions from cell names."""
import hashlib
import re
from collections import defaultdict
from pathlib import Path


def classify(body, def_file):
    result = {'complete': False, 'drivers': [], 'reason': None}
    match = re.search(r'^Found (\d+) unannotated drivers\.\n(.*?)^Found (\d+) partially unannotated drivers\.$', body, re.M | re.S)
    if not match:
        result['reason'] = 'missing native annotation counts'
        return result
    drivers = [line.strip() for line in match[2].splitlines() if line.strip()]
    if len(drivers) != int(match[1]) or len(set(drivers)) != len(drivers) or int(match[3]) != 0:
        result['reason'] = 'inconsistent driver inventory or partial annotation'
        return result
    result.update(raw_missing=int(match[1]), raw_partial=int(match[3]))
    if not drivers:
        result['complete'] = True
        return result
    try:
        data = Path(def_file).read_bytes()
    except OSError:
        result['reason'] = 'DEF authority absent'
        return result
    result['def_sha256'] = hashlib.sha256(data).hexdigest()
    text = data.decode(errors='strict')
    normalize = lambda s: s.replace('\\', '').strip()
    bindings = defaultdict(list)
    wildcards = []
    regular = False
    for section in ('NETS', 'SPECIALNETS'):
        block = re.search(r'^'+section+r'\s+(\d+)\s*;(.*?)^END '+section+r'\b', text, re.M | re.S)
        if not block:
            if re.search(r'^'+section+r'\b', text, re.M):
                result['reason'] = 'malformed DEF net section'
                return result
            continue
        regular |= section == 'NETS'
        statements = list(re.finditer(r'^\s*-\s+(\S+)\s+(.*?);', block[2], re.M | re.S))
        if len(statements) != int(block[1]):
            result['reason'] = 'DEF net count mismatch'
            return result
        for statement in statements:
            uses = re.findall(r'\+\s+USE\s+(\w+)', statement[2])
            if len(uses) > 1:
                result['reason'] = 'ambiguous DEF USE declaration'
                return result
            value = (normalize(statement[1]), uses[0] if uses else 'UNDECLARED')
            for inst, pin in re.findall(r'\(\s*(\S+)\s+(\S+)\s*\)', statement[2].split('+')[0]):
                inst, pin = normalize(inst), normalize(pin)
                if inst == '*':
                    wildcards.append((pin, value))
                else:
                    bindings[pin if inst == 'PIN' else inst+'/'+pin].append(value)
    if not regular:
        result['reason'] = 'DEF regular net inventory absent'
        return result
    linked = {line.rsplit(' ', 1)[0] for line in re.findall(r'^STA_LINK_INSTANCE (.+)$', body, re.M)}
    disconnected = set(re.findall(r'^STA_UNCONNECTED_OUTPUT (\S+)$', body, re.M))
    for driver in drivers:
        inst, pin = driver.rsplit('/', 1) if '/' in driver else (None, driver)
        evidence = list(bindings[driver])
        if inst in linked:
            evidence += [value for pattern, value in wildcards if pattern == pin]
        if evidence and len(set(evidence)) == 1 and all(use in ('POWER', 'GROUND') for net, use in evidence):
            classification = 'EXPLICIT_PG_NOT_SIGNAL_PARASITICS'
        elif not evidence and inst in linked and driver in disconnected:
            classification = 'NATIVE_UNCONNECTED_OUTPUT'
        else:
            classification = 'REQUIRED_OR_UNKNOWN'
        result['drivers'].append({'driver': driver, 'classification': classification,
                                  'def_bindings': evidence})
    result['complete'] = all(row['classification'] != 'REQUIRED_OR_UNKNOWN' for row in result['drivers'])
    return result
