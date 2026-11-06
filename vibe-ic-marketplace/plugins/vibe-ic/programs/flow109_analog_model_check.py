"""Read native ngspice model-smoke logs and measurements."""
from __future__ import annotations

import math
import os as _os
from pathlib import Path
import re
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import _prose_polarity as _polarity

FATAL = (
    'could not find a valid modelname', 'unable to find definition of model',
    'unknown subckt', 'unknown device type', 'no simulations run',
    'simulation interrupted due to error', 'fatal error',
)
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'


def _fatal_diagnostic(text, polarity):
    """Return a live ngspice fatal marker, excluding prose that denies it.

    Each log line is a diagnostic record.  A denial *inside* a marker (for
    example ``no simulations run`` or ``could not find ...``) constitutes the
    failure and is blanked with the rest of that marker.  A denial elsewhere
    in the same record (``no fatal error occurred``) retracts the marker.
    """
    for marker in FATAL:
        for match in re.finditer(re.escape(marker), text, re.IGNORECASE):
            lo, hi = polarity.sentence_scope(
                text, match.start(), match.end(), extra_breaks=("\n",))
            clause = text[lo:hi]
            start, end = match.start() - lo, match.end() - lo
            without_marker = clause[:start] + (" " * (end - start)) + clause[end:]
            if polarity.is_denied(without_marker, ignore_bracketed=False) is None:
                return marker
    return None


def consume(project, requirements, report):
    """Read every required native smoke case and its measurements."""
    project = Path(project).resolve()
    expected = {row['id']: row for row in requirements['required_smokes']}
    rows = report.get('smokes')
    if not isinstance(rows, list) or {r.get('id') for r in rows if isinstance(r, dict)} != set(expected):
        return {'verdict': 'FAIL', 'reason': 'A02_SMOKE_COVERAGE_MISMATCH', 'smokes': []}
    checked = []
    for row in rows:
        need = expected[row['id']]
        identity = {key: row.get(key) for key in ('id', 'device', 'corner', 'model', 'deck',
                                                  'required_measurements')}
        if identity != need:
            return {'verdict': 'FAIL', 'reason': 'A02_SMOKE_IDENTITY_MISMATCH', 'smokes': checked}
        try:
            log = (project / row['log']['path']).resolve()
            if not log.is_file():
                raise OSError
            for key in ('model', 'deck'):
                path = (project / row[key]['path']).resolve()
                if not path.is_file():
                    raise OSError
        except (KeyError, OSError):
            return {'verdict': 'FAIL', 'reason': 'A02_NATIVE_INPUT_ABSENT', 'smokes': checked}
        text = log.read_text(errors='replace')
        # Diagnostics are prose records, so their polarity is canonical.  The
        # measurement records below are instead a closed ngspice grammar:
        # anchored approved identifier, '=', and NUMBER; no prose is inferred.
        fatal = _fatal_diagnostic(text, _polarity)
        if row.get('returncode') != 0 or fatal is not None:
            return {'verdict': 'FAIL', 'reason': 'A02_NATIVE_MODEL_LOAD_FAILED', 'smokes': checked}
        values = {}
        for name in need['required_measurements']:
            hits = re.findall(r'(?im)^\s*' + re.escape(name) + r'\s*=\s*(' + NUMBER + r')\b', text)
            if len(hits) != 1:
                return {'verdict': 'FAIL', 'reason': 'A02_NATIVE_MEASUREMENT_ABSENT', 'smokes': checked}
            value = float(hits[0])
            if not math.isfinite(value):
                return {'verdict': 'FAIL', 'reason': 'A02_NATIVE_MEASUREMENT_NONFINITE', 'smokes': checked}
            values[name] = value
        checked.append({'id': row['id'], 'device': row['device'], 'corner': row['corner'],
                        'measurements': values, 'log': row['log']})
    return {'verdict': 'PASS', 'reason': 'A02_DECLARED_NATIVE_SMOKES_COMPLETE',
            'smokes': checked,
            'scope': 'declared model/device component only; PDK and benchmark signoff NOT_MEASURED'}
