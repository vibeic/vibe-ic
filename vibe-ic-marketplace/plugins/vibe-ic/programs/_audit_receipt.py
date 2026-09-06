#!/usr/bin/env python3
"""Producer-written audit receipts (#2050).

WHY THIS EXISTS. `_shared/skill_compliance_check.py::_cc_audit_receipt_evidence`
discharges a named audit obligation by finding that audit's OWN report on disk,
confirming it is that producer's report, and reading its verdict. To find it,
the checker needs a FILENAME CONVENTION. Five auditors already had one because
they write a fixed name into an `--out-dir`
(`interface_encoding_audit_report.json`, `crc_bitorder_report.json`,
`phy_counter_audit_report.json`, `mcp_execution_verify_report.json`,
`fpga_pullup_lint.json`).

Four did not, and were listed in `UNREGISTERED_AUDITORS` where they BLOCK::

    gds_size_check                       write to a caller-chosen `--json PATH`.
    synth_netlist_check                  The bytes are fine; there is simply no
    tapeout_signoff_check                name in the tree for the checker to
    fpga_async_input_synchronizer_check  look for.

v1.17.76 refused to invent a filename for them inside the CHECKER, and that
refusal was right: a consumer that guesses where its evidence lives is guessing.
The producer is the half that KNOWS. So the convention is written here, by the
producing side, and the checker only reads what the producer states it wrote:

    <directory of the caller's --json> / <auditor>_receipt.json

The receipt is a SIBLING of the caller's own `--json` output, never a
replacement for it: the caller keeps the path it asked for, byte for byte, and
the receipt adds the four facts the caller's payload does not carry in a
uniform place — who audited, what verdict, how many items were examined, and
WHICH SUBJECT.

THE SUBJECT HASH IS THE LOAD-BEARING FIELD. Without it a receipt is only
evidence that SOME run of this auditor passed, and a stale receipt beside a new
report reads exactly like a fresh one. `subject.sha256` is taken over the
audited artefacts themselves, so a receipt produced for another subject
mismatches a `subject:` declared in a compliance.yaml and is reported FAIL —
not PASS, and not NOT_MEASURED, because a receipt naming the wrong subject IS a
measurement, of something else.

`basis` says how the digest was taken and is never assumed:

  * ``content`` — every item was a readable file and its own sha256 went into
    the digest. The strongest form: the subject cannot change without the
    digest changing.
  * ``path``    — at least one item is a directory, or was unreadable. Only the
    paths went in. Still separates one subject from another, which is what the
    mismatch check needs; it does NOT witness the bytes, and says so.

DEGRADE LOUDLY, NEVER SILENTLY. Writing a receipt must not change the auditor's
verdict or its exit code — an auditor that fails because its receipt could not
be written would be reporting the filesystem, not the design. A write failure
prints to stderr and returns None, so the checker then reports NOT_MEASURED
(blocking) rather than a pass on a receipt nobody wrote.
"""
from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

# Bumped only when the on-disk shape changes in a way a reader must notice.
# `_shared/skill_compliance_check.py` identifies a receipt by this key plus the
# auditor name, so a payload from any other producer is never mistaken for one.
RECEIPT_VERSION = 1

RECEIPT_SUFFIX = '_receipt.json'

BASIS_CONTENT = 'content'
BASIS_PATH = 'path'


def receipt_filename(auditor: str) -> str:
    """The one name the checker looks for. Stated in exactly one place."""
    return f'{auditor}{RECEIPT_SUFFIX}'


def receipt_path_for(auditor: str, json_path: Union[str, Path]) -> Path:
    """Where `auditor`'s receipt goes for a caller who asked for `json_path`.

    A SIBLING of the caller's output. The caller chose the directory; the
    producer chooses the name inside it. Neither half guesses.
    """
    return Path(json_path).parent / receipt_filename(auditor)


# `Path.resolve()` raises a BARE `RuntimeError` for ELOOP on CPython
# (`pathlib.check_eloop`), not an `OSError` — an `except OSError` written for
# exactly that case never fires. `programs/eda_report_audit.py::_in_scope`
# records the same trap and the same measurement, reached through the
# production command `drc_report_check . --mode drc --signoff --under
# reports/phase3/drc_signoff.rpt`. Measured again here at #2057, when the
# `--json` document started carrying a subject digest: a mutually-pointing
# pair of report-named symlinks turned that gate from "a verdict about 11 DRC
# items" into a traceback and NO verdict document at all. Every filesystem
# touch in this module is guarded for both, and an unreadable item is recorded
# as `basis: path` — never dropped, and never silently digested as empty.
_FS_ERRORS = (OSError, RuntimeError, ValueError)


def _safe_resolve(p: Path) -> Path:
    try:
        return p.resolve()
    except _FS_ERRORS:
        return p


def _safe_is_file(p: Path) -> bool:
    try:
        return p.is_file()
    except _FS_ERRORS:
        return False


def _file_digest(p: Path) -> Optional[str]:
    try:
        return sha256(p.read_bytes()).hexdigest()
    except _FS_ERRORS:
        return None


def subject_of(items: Iterable[Union[str, Path]],
               relative_to: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Describe what was audited, deterministically.

    Paths are resolved and sorted so two runs over the same subject in a
    different argument order produce the same digest, and a run over a
    different subject does not.

    `relative_to` (#2057) re-expresses each item's recorded `path` relative to
    that directory when it is under it. It CANNOT change the digest — the
    digest is taken over basename + content hash and never over a path — and
    it exists because a receipt that is itself a committed artefact must not
    carry the absolute path of the machine that produced it. Omitted, the
    resolved path is recorded exactly as before.
    """
    resolved: List[Path] = [_safe_resolve(Path(it)) for it in items]
    resolved.sort(key=str)

    base: Optional[Path] = None
    if relative_to is not None:
        base = _safe_resolve(Path(relative_to))

    entries: List[Dict[str, Any]] = []
    basis = BASIS_CONTENT if resolved else BASIS_PATH
    for p in resolved:
        is_file = _safe_is_file(p)
        digest = _file_digest(p) if is_file else None
        if digest is None:
            basis = BASIS_PATH
        shown = p
        if base is not None:
            try:
                shown = p.relative_to(base)
            except ValueError:
                shown = p
        entries.append({
            'path': str(shown),
            'sha256': digest,
            'is_file': is_file,
        })

    # THE DIGEST IS MACHINE-INDEPENDENT ON PURPOSE. It is taken over
    # basename + content hash, never over the absolute path, so the same
    # subject audited in two checkouts produces the SAME digest and a
    # compliance.yaml can pin one. `items` still records the resolved path
    # for a reader tracing the run; that path is deliberately NOT in the
    # digest, or the digest would be a fact about the machine.
    blob = '\n'.join(sorted(
        f"{Path(e['path']).name}\0{e['sha256'] or ''}" for e in entries))
    return {
        'basis': basis,
        'items': entries,
        'sha256': sha256(blob.encode('utf-8')).hexdigest(),
    }


def build_receipt(auditor: str, verdict: str, examined: int,
                  subject_items: Sequence[Union[str, Path]],
                  json_path: Optional[Union[str, Path]] = None,
                  extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The receipt payload, with no side effect. Separated from the write so a
    test can assert the shape without touching a filesystem."""
    payload: Dict[str, Any] = {
        'receipt_version': RECEIPT_VERSION,
        'auditor': auditor,
        'verdict': verdict,
        'examined': int(examined),
        'subject': subject_of(subject_items),
    }
    if json_path is not None:
        # The name only, never the absolute path: an audit trail must not
        # embed the machine it ran on (`no_volatile_paths` exists for the
        # same reason on the report side).
        payload['audit_json'] = Path(json_path).name
    if extra:
        payload['detail'] = extra
    return payload


def emit_receipt(auditor: str, json_path: Optional[Union[str, Path]],
                 verdict: str, examined: int,
                 subject_items: Sequence[Union[str, Path]],
                 extra: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """Write `auditor`'s receipt beside `json_path`. Never raises.

    Returns the path written, or None. None is the honest outcome when the
    caller asked for no `--json` at all (there is no directory the receipt
    belongs beside) or when the write failed; either way the downstream
    compliance check reports NOT_MEASURED, which blocks. It never reports a
    pass on a receipt that does not exist.
    """
    if not json_path:
        return None
    target = receipt_path_for(auditor, json_path)
    payload = build_receipt(auditor, verdict, examined, subject_items,
                            json_path=json_path, extra=extra)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                          + '\n')
    except OSError as e:
        print(f"{auditor}: NO RECEIPT WRITTEN to {target}: "
              f"{e.__class__.__name__}: {e}", file=sys.stderr)
        return None
    return target
