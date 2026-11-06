#!/usr/bin/env python3
"""Tool owners and public entry for phase1_one_shot_runner."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

PROGRAMS_DIR = Path(__file__).resolve().parent


D1_STEP_NAME = "phase1_ingest_render"


def _docs_hold_identical_bytes(docs_dir: Path, candidate: Path) -> bool:
    content = candidate.read_bytes()
    return any(path.is_file() and not path.name.startswith(".") and path.read_bytes() == content
               for path in docs_dir.rglob("*"))


def _run_docs_mode(project: Path, ic_name: str,
                   forwarded_args: Optional[List[str]] = None) -> int:
    docs = project / "input/docs"
    docs.mkdir(parents=True, exist_ok=True)
    prompt = project / "input/phase1_prompt.md"
    if prompt.is_file() and not _docs_hold_identical_bytes(docs, prompt):
        (docs / prompt.name).write_bytes(prompt.read_bytes())
    command = [sys.executable, str(PROGRAMS_DIR / "phase1_doc_one_shot_runner.py"), str(project)]
    if ic_name and ic_name.strip().upper() != "UNNAMED_CHIP":
        command += ["--ic-name", ic_name]
    result = subprocess.run([*command, *(forwarded_args or [])], check=False)
    return result.returncode


def main_recorded() -> int:
    return main()


def main(argv=None) -> int:
    from flow_engine_frontend import phase_main
    return phase_main(argv, scope="phase1")


if __name__ == "__main__":
    sys.exit(main())
