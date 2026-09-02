"""Transposition table keyed by python-chess board hash.

Entry: (depth, flag, score, move)
  depth: remaining search depth at which score is valid
  flag:  EXACT / LOWER (fail high) / UPPER (fail low)
  score: normalized search score
  move:  best move found, or None
"""

EXACT = 0
LOWER = 1
UPPER = 2


class TTable:
    __slots__ = ("table",)

    def __init__(self):
        self.table = {}

    def probe(self, key):
        """Return entry tuple or None."""
        return self.table.get(key)

    def store(self, key, depth, flag, score, move):
        t = self.table
        if len(t) > 2_000_000:
            t.clear()
        if move is None:
            old = t.get(key)
            if old is not None:
                move = old[3]
        t[key] = (depth, flag, score, move)