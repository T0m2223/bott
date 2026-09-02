"""Public interface of the chess bot.

get_move(fen: str, time_left_ms: int) -> str
    Returns the best move as a UCI string ('e2e4', 'e7e8q', ...).
    time_left_ms is the total time remaining for this side in the game.
"""

import chess

from .search import Search
from .timemgmt import alloc_time
from .tt import TTable

# transposition table persists across moves of the same game
_TT = TTable()


def get_move(fen, time_left_ms, max_depth=64):
    board = chess.Board(fen)
    alloc = alloc_time(board, time_left_ms)
    hard = alloc_ms_hard(alloc, time_left_ms)
    search = Search(board, _TT, alloc, hard_ms=hard)
    return search.go(max_depth=max_depth)


def alloc_ms_hard(alloc, time_left_ms):
    """Absolute ceiling for a single root iteration, so one runaway search
    can never consume the entire remaining clock."""
    if time_left_ms is None:
        return alloc * 4
    return max(alloc, min(time_left_ms, alloc * 4))