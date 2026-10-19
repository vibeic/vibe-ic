"""Bounded, analysis-local memo of *completed* legacy cone queries.

This preserves the legacy cell-wide conservative fanin relation, including
cycles. It does not cache a partially visited DFS or infer pin-specific logic.
"""
from collections import OrderedDict
import sys


def _size(value, seen):
    """Conservatively charge retained containers and their referenced values."""
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, (tuple, frozenset)):
        size += sum(_size(item, seen) for item in value)
    return size


class CompletedConeMemo:
    def __init__(self, model, legacy, max_entries=128, max_bytes=16 * 1024 * 1024):
        self.model = model
        self.legacy = legacy
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.retained_bytes = 0
        self._entries = OrderedDict()

    def cone(self, bits, skip=None):
        seeds = frozenset(bits)
        skipped = frozenset(skip or ())
        key = ("bits", seeds, skipped)
        if len(seeds) == 1:
            bit = next(iter(seeds))
            # Legacy terminal priority MUST precede driver-cell equivalence.
            # All nonterminal outputs of a cell read the same full input list
            # in the legacy walker, even for unknown cells and cyclic graphs.
            if (not self.model.is_const(bit) and bit not in skipped
                    and bit not in self.model.flop_of_q()
                    and bit not in self.model.port_bits):
                driver = self.model.drivers.get(bit)
                if driver is not None:
                    key = ("cell", driver[0], skipped)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return set(cached[0]), set(cached[1])

        q, p = self.legacy(seeds, skip=skipped)
        # Only a fully returned query is eligible; callers cannot mutate it.
        value = (frozenset(q), frozenset(p))
        # Include a conservative per-entry allowance for OrderedDict nodes,
        # its hash table and the stored accounting tuple, as well as the key.
        size = _size((key, value), set()) + 1024
        if self.max_entries > 0 and size <= self.max_bytes:
            while self._entries and (len(self._entries) >= self.max_entries
                                     or self.retained_bytes + size > self.max_bytes):
                _old_key, (_q, _p, old_size) = self._entries.popitem(last=False)
                self.retained_bytes -= old_size
            self._entries[key] = (*value, size)
            self.retained_bytes += size
        return set(value[0]), set(value[1])
