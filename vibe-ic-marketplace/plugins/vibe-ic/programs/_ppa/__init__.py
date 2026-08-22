"""`_ppa` — the PPA measurement, closure, search and agent-control library.

This package exists so that PPA logic stops being added to
`phase3_one_shot_runner.py`, which is already large enough that a change in one
domain cannot be reviewed without reading the others.

The module map, the public signatures and the CLI contract every top-level
`ppa_*.py` must honour are frozen in `docs/PPA_INTERFACES.md`. Read that before
adding a module: it is what lets several authors implement different domains at
the same time without agreeing on anything afterwards.
"""
