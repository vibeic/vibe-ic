"""Tool availability helpers for native integration tests."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Sequence, Tuple
SENTINEL = 'NOT_VERIFIED:'
PROBE_PRESENT = 'PRESENT'
PROBE_ABSENT = 'ABSENT'
PROBE_UNANSWERED = 'UNANSWERED'
UNANSWERED_MARK = 'PROBE UNANSWERED'
PROBE_TIMEOUT_S = 60
PROBE_STALL_LOOKS = None
PROBE_POLL_S = None

def _probe_supervision() -> Dict[str, object]:
    kw: Dict[str, object] = {}
    if PROBE_STALL_LOOKS is not None:
        kw['stall_looks'] = int(PROBE_STALL_LOOKS)
    if PROBE_POLL_S is not None:
        kw['poll_s'] = float(PROBE_POLL_S)
    return kw

def _stall_sentence(stall) -> str:
    live = ','.join(sorted((k for (k, v) in stall.signals.items() if v))) or 'none'
    return f'every readable progress signal sat still across {stall.looks} consecutive looks ({stall.poll_s:.2f}s apart, {stall.elapsed_s:.1f}s elapsed); signals readable: {live}'
_PROBE_CACHE: Dict[Tuple[str, ...], Tuple[str, str]] = {}

def skip_not_verified(reason: str, remedy: str='') -> None:
    import pytest
    text = f'{SENTINEL} {reason}'
    if remedy:
        text = f'{text} — remedy: {remedy}'
    pytest.skip(text)

def not_verified_reason(reason: str, remedy: str='') -> str:
    text = f'{SENTINEL} {reason}'
    return f'{text} — remedy: {remedy}' if remedy else text

def probe(argv: Sequence[str], timeout: int=PROBE_TIMEOUT_S, use_cache: bool=True) -> Tuple[str, str]:
    import shutil
    import subprocess
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _progress_run as _pr
    key = tuple(argv)
    if use_cache and key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    printed = ' '.join(argv)
    if shutil.which(argv[0]) is None:
        out = (PROBE_ABSENT, f'`{argv[0]}` is not on PATH')
    else:
        try:
            cp = _pr.run(list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, hard_ceiling_s=float(timeout), **_probe_supervision())
            returncode = cp.returncode
        except _pr.Stalled as stall:
            out = (PROBE_UNANSWERED, f'`{printed}` never answered: {_stall_sentence(stall)}')
        except OSError as exc:
            out = (PROBE_UNANSWERED, f'`{printed}` could not be run: {exc}')
        else:
            out = (PROBE_PRESENT, '') if returncode == 0 else (PROBE_ABSENT, f'`{printed}` exited {returncode}')
    if use_cache:
        _PROBE_CACHE[key] = out
    return out

def probe_skip_reason(state: str, detail: str, absent_reason: str, remedy: str='') -> str:
    if state == PROBE_PRESENT:
        return ''
    if state == PROBE_UNANSWERED:
        return not_verified_reason(f'{UNANSWERED_MARK} — {detail}. The probe lost a race (typically host load); NOTHING was established about what this test verifies WITH, so this is NOT a finding that it is missing', 're-run this file on a host that is not saturated')
    return not_verified_reason(absent_reason, remedy)
