#!/usr/bin/env python3
"""Tapeout signoff check — wrapper for signoff_audit --mode tapeout.

Forwards all passthrough arguments (--json, --lenient, --strict, etc.) to
the underlying signoff_audit entry point. Prior versions hardcoded only
the project_dir + --mode and silently dropped --json PATH, preventing
reports/tapeout_checklist.json from being written when called via the
33-step flow gate. Fix recorded 2026-04-22 via <benchmark> full-flow pilot."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signoff_audit import main  # noqa: E402
from _audit_receipt import emit_receipt  # noqa: E402


def _json_target(argv):
    """The `--json PATH` this run was asked for, or None.

    Both spellings, because a receipt that only appears for one of them is a
    receipt whose absence means nothing.
    """
    for i, a in enumerate(argv):
        if a == "--json" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--json="):
            return a.split("=", 1)[1]
    return None


def emit_receipt_for(project_dir, json_path):
    """#2050 — the receipt this 22-line shim owes the compliance checker.

    `signoff_audit` has already written the caller's `--json`; this reads that
    file back rather than re-deriving anything, so the receipt can never
    disagree with the audit it certifies. Reading back is also the only option
    available: the shim never sees the AuditResult, only an exit code.

    `verdict` keeps `signoff_audit`'s own spelling. A PASS_WITH_WAIVERS run is
    passing but not clean, and rule 11 forbids collapsing it onto a bare PASS,
    so it travels as PASS_WITH_WAIVERS and lands on the non-PASS side of the
    compliance checker's line.
    """
    if not json_path:
        return None
    src = Path(json_path)
    try:
        payload = json.loads(src.read_text())
    except (OSError, ValueError) as e:
        print(f"tapeout_signoff_check: NO RECEIPT — could not read back "
              f"{src}: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None
    summary = payload.get("summary") or {}
    tier = summary.get("verdict_tier") or ""
    if payload.get("passed"):
        verdict = "PASS_WITH_WAIVERS" if tier == "PASS_WITH_WAIVERS" else "PASS"
    else:
        verdict = "FAIL"
    return emit_receipt(
        "tapeout_signoff_check", json_path, verdict,
        int(summary.get("evidence_count") or 0), [project_dir],
        extra={"program": payload.get("program"),
               "verdict_tier": tier,
               "threshold": summary.get("threshold")})


def run(user_args):
    if not user_args:
        user_args = ["."]
    # Inject --mode tapeout if the user hasn't explicitly overridden it
    if "--mode" not in user_args:
        user_args = user_args + ["--mode", "tapeout"]
    rc = main(user_args)
    emit_receipt_for(user_args[0], _json_target(user_args))
    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
