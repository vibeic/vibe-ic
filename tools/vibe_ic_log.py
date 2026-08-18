#!/usr/bin/env python3
"""
vibe-ic-log -- Unified JSON Log Format for Vibe-IC Pipeline
==============================================================
Provides a structured JSONL logging system for tracking every step
of the IC design flow across all three phases.

Format: one JSON object per line (JSONL / JSON Lines).

Example:
    {"timestamp":"2026-04-10T02:00:00","ic_name":"CD4013B","phase":2,
     "stage":"synth","tool":"yosys","status":"PASS",
     "metrics":{"cells":567,"area":14157},"errors":[],"duration_sec":5.2}

Usage (CLI):
    python3 vibe_ic_log.py log --ic CD4013B --phase 2 --stage synth \\
        --tool yosys --status PASS --metrics '{"cells":567}' --output pipeline.jsonl

    python3 vibe_ic_log.py show pipeline.jsonl                # pretty-print
    python3 vibe_ic_log.py show pipeline.jsonl --phase 2      # filter by phase
    python3 vibe_ic_log.py show pipeline.jsonl --status FAIL   # filter by status
    python3 vibe_ic_log.py summary pipeline.jsonl              # summary stats

Usage (Python API):
    from vibe_ic_log import VibeICLog
    entry = VibeICLog(ic_name="CD4013B", phase=2, stage="synth",
                      tool="yosys", status="PASS",
                      metrics={"cells": 567}, duration_sec=5.2)
    entry.append("pipeline.jsonl")
"""

import json
import sys
import argparse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


# ============================================================================
# Data Model
# ============================================================================

VALID_STATUSES = {"PASS", "FAIL", "WARN", "SKIP"}
VALID_PHASES = {1, 2, 3}


@dataclass
class VibeICLog:
    """A single log entry for the Vibe-IC pipeline."""
    ic_name: str
    phase: int                          # 1, 2, or 3
    stage: str                          # e.g. "spec_gen", "synth", "pnr", "fpga"
    tool: str                           # e.g. "ds_quality_check", "yosys", "openroad"
    status: str                         # PASS, FAIL, WARN, SKIP
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    duration_sec: float = 0.0
    timestamp: str = ""                 # ISO 8601, auto-filled if empty

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        self.status = self.status.upper()
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}', must be one of {VALID_STATUSES}")
        if self.phase not in VALID_PHASES:
            raise ValueError(f"Invalid phase {self.phase}, must be one of {VALID_PHASES}")

    # ----------------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a plain dictionary."""
        return {
            "timestamp": self.timestamp,
            "ic_name": self.ic_name,
            "phase": self.phase,
            "stage": self.stage,
            "tool": self.tool,
            "status": self.status,
            "metrics": self.metrics,
            "errors": self.errors,
            "duration_sec": self.duration_sec,
        }

    def to_json(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(',', ':'))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'VibeICLog':
        """Create from a dictionary."""
        return cls(
            ic_name=d.get('ic_name', d.get('ic', '')),
            phase=int(d.get('phase', 0)),
            stage=d.get('stage', ''),
            tool=d.get('tool', ''),
            status=d.get('status', 'SKIP'),
            metrics=d.get('metrics', {}),
            errors=d.get('errors', []),
            duration_sec=float(d.get('duration_sec', 0.0)),
            timestamp=d.get('timestamp', ''),
        )

    @classmethod
    def from_json(cls, line: str) -> 'VibeICLog':
        """Deserialize from a JSON line."""
        return cls.from_dict(json.loads(line))

    # ----------------------------------------------------------------
    # I/O
    # ----------------------------------------------------------------

    def log_entry(self) -> str:
        """Return the formatted JSONL line (with newline)."""
        return self.to_json() + '\n'

    def save(self, path: str) -> None:
        """Write this single entry to a new file (overwrites)."""
        Path(path).write_text(self.log_entry(), encoding='utf-8')

    def append(self, path: str) -> None:
        """Append this entry to an existing JSONL file (creates if missing)."""
        with open(path, 'a', encoding='utf-8') as f:
            f.write(self.log_entry())

    @staticmethod
    def load(path: str) -> List['VibeICLog']:
        """Load all entries from a JSONL file."""
        entries: List[VibeICLog] = []
        p = Path(path)
        if not p.exists():
            return entries
        for line in p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(VibeICLog.from_json(line))
                except (json.JSONDecodeError, ValueError) as e:
                    # Skip malformed lines, log to stderr
                    print(f"WARNING: Skipping malformed log line: {e}", file=sys.stderr)
        return entries


# ============================================================================
# CLI: Pretty Printer
# ============================================================================

def print_entries(entries: List[VibeICLog], verbose: bool = False):
    """Pretty-print a list of log entries."""
    if not entries:
        print("  (no entries)")
        return

    # Header
    print(f"  {'Timestamp':<22}{'IC':<14}{'Ph':<4}{'Stage':<14}{'Tool':<20}{'Status':<7}{'Duration':<10}")
    print(f"  {'─'*22}{'─'*14}{'─'*4}{'─'*14}{'─'*20}{'─'*7}{'─'*10}")

    for e in entries:
        dur = f"{e.duration_sec:.1f}s" if e.duration_sec > 0 else "-"
        print(f"  {e.timestamp:<22}{e.ic_name:<14}{e.phase:<4}{e.stage:<14}{e.tool:<20}{e.status:<7}{dur:<10}")
        if verbose and e.metrics:
            print(f"    metrics: {json.dumps(e.metrics, ensure_ascii=False)}")
        if verbose and e.errors:
            for err in e.errors:
                print(f"    error: {err}")


def print_summary(entries: List[VibeICLog]):
    """Print summary statistics from log entries."""
    if not entries:
        print("  No entries to summarize.")
        return

    # Group by IC
    ics: Dict[str, List[VibeICLog]] = {}
    for e in entries:
        ics.setdefault(e.ic_name, []).append(e)

    print(f"\n  {'IC Name':<16}{'Entries':<10}{'PASS':<8}{'FAIL':<8}{'WARN':<8}{'SKIP':<8}{'Total Time':<12}")
    print(f"  {'─'*16}{'─'*10}{'─'*8}{'─'*8}{'─'*8}{'─'*8}{'─'*12}")

    for ic_name, ic_entries in sorted(ics.items()):
        total = len(ic_entries)
        passes = sum(1 for e in ic_entries if e.status == 'PASS')
        fails = sum(1 for e in ic_entries if e.status == 'FAIL')
        warns = sum(1 for e in ic_entries if e.status == 'WARN')
        skips = sum(1 for e in ic_entries if e.status == 'SKIP')
        total_time = sum(e.duration_sec for e in ic_entries)
        time_str = f"{total_time:.1f}s"
        print(f"  {ic_name:<16}{total:<10}{passes:<8}{fails:<8}{warns:<8}{skips:<8}{time_str:<12}")

    # Overall
    total_entries = len(entries)
    total_pass = sum(1 for e in entries if e.status == 'PASS')
    total_fail = sum(1 for e in entries if e.status == 'FAIL')
    total_time = sum(e.duration_sec for e in entries)
    print(f"\n  Total: {total_entries} entries, {total_pass} PASS, {total_fail} FAIL, {total_time:.1f}s")


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='vibe-ic-log: Unified JSONL logging for IC design pipeline')
    subparsers = parser.add_subparsers(dest='command', help='Sub-commands')

    # --- log sub-command ---
    log_parser = subparsers.add_parser('log', help='Create a new log entry')
    log_parser.add_argument('--ic', required=True, help='IC name (e.g., CD4013B)')
    log_parser.add_argument('--phase', type=int, required=True, choices=[1, 2, 3],
                            help='Phase number (1/2/3)')
    log_parser.add_argument('--stage', required=True,
                            help='Stage name (e.g., spec_gen, synth, pnr, fpga)')
    log_parser.add_argument('--tool', required=True,
                            help='Tool name (e.g., ds_quality_check, yosys, openroad)')
    log_parser.add_argument('--status', required=True, choices=['PASS', 'FAIL', 'WARN', 'SKIP'],
                            help='Result status')
    log_parser.add_argument('--metrics', default='{}',
                            help='JSON string of metrics (e.g., \'{"cells":567}\')')
    log_parser.add_argument('--errors', default='[]',
                            help='JSON array of error strings')
    log_parser.add_argument('--duration', type=float, default=0.0,
                            help='Duration in seconds')
    log_parser.add_argument('--output', '-o', required=True,
                            help='Output JSONL file path (appends)')

    # --- show sub-command ---
    show_parser = subparsers.add_parser('show', help='Display log entries')
    show_parser.add_argument('logfile', help='Path to JSONL log file')
    show_parser.add_argument('--phase', type=int, help='Filter by phase')
    show_parser.add_argument('--status', help='Filter by status')
    show_parser.add_argument('--ic', help='Filter by IC name')
    show_parser.add_argument('--stage', help='Filter by stage')
    show_parser.add_argument('--verbose', '-v', action='store_true',
                             help='Show metrics and errors')

    # --- summary sub-command ---
    summary_parser = subparsers.add_parser('summary', help='Show summary statistics')
    summary_parser.add_argument('logfile', help='Path to JSONL log file')

    args = parser.parse_args()

    if args.command == 'log':
        try:
            metrics = json.loads(args.metrics)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON for --metrics: {args.metrics}", file=sys.stderr)
            sys.exit(1)
        try:
            errors = json.loads(args.errors)
            if not isinstance(errors, list):
                errors = [str(errors)]
        except json.JSONDecodeError:
            errors = [args.errors]

        entry = VibeICLog(
            ic_name=args.ic,
            phase=args.phase,
            stage=args.stage,
            tool=args.tool,
            status=args.status,
            metrics=metrics,
            errors=errors,
            duration_sec=args.duration,
        )
        entry.append(args.output)
        print(f"Logged: {entry.to_json()}")

    elif args.command == 'show':
        entries = VibeICLog.load(args.logfile)
        if args.phase:
            entries = [e for e in entries if e.phase == args.phase]
        if args.status:
            entries = [e for e in entries if e.status == args.status.upper()]
        if args.ic:
            entries = [e for e in entries if e.ic_name == args.ic]
        if args.stage:
            entries = [e for e in entries if e.stage == args.stage]

        print(f"\n{'='*60}")
        print(f"  vibe-ic-log -- Pipeline Log ({len(entries)} entries)")
        print(f"{'='*60}")
        print_entries(entries, verbose=args.verbose)
        print(f"{'='*60}\n")

    elif args.command == 'summary':
        entries = VibeICLog.load(args.logfile)
        print(f"\n{'='*60}")
        print(f"  vibe-ic-log -- Pipeline Summary")
        print(f"{'='*60}")
        print_summary(entries)
        print(f"{'='*60}\n")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
