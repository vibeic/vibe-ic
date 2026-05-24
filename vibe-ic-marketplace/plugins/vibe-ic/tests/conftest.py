"""tests/conftest.py — shared pytest fixtures and helpers.

v1.6.593 — for #401. `load_real_fixture(name)` reads a hand-extracted,
chip-AGNOSTIC slice from `tests/fixtures/real_benchmark/` so that
walker / regex / merge / pipeline-stage tests can assert on
real-world shapes rather than synthetic minimal cases.

See `tests/fixtures/real_benchmark/README.md` for the rationale and
naming convention.
"""
from __future__ import annotations

from pathlib import Path


_REAL_BENCHMARK_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "real_benchmark"
)


def load_real_fixture(name: str) -> str:
    """v1.6.593 — for #401. Read a real-benchmark fixture from
    `tests/fixtures/real_benchmark/<name>` and return its content
    as a UTF-8 string.

    Raises:
        FileNotFoundError: if the fixture is not present (typo in
            test or fixture not authored yet).
        IsADirectoryError: if `name` resolves to a directory.

    Chip-AGNOSTIC: fixtures themselves are chip-AGNOSTIC; this
    helper does not introduce any chip-class literal.
    """
    path = _REAL_BENCHMARK_DIR / name
    return path.read_text(encoding="utf-8")
