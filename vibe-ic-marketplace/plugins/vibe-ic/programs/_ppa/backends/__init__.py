"""Tool-specific parsing only.

A backend turns ONE tool's output into canonical records and does nothing else:
no thresholds, no verdicts, no policy. Those live in the domain module, so that
adding a tool never changes a rule (PPA_INTERFACES.md §4).

The dependency direction is one-way and it is load-bearing: a backend imports
its domain module to BUILD records; a domain module never imports a backend. If
that ever reverses, a parser gains the ability to decide what a number means.
"""
