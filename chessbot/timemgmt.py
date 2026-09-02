"""Time allocation for a single move based on total remaining clock time."""

import chess


def alloc_time(board, time_left_ms):
    if time_left_ms is None or time_left_ms <= 0:
        return 200

    fullmove = board.fullmove_number
    # assume an average game lasts ~40 full moves
    remaining_full = max(1, 40 - fullmove + 1)
    moves_left = max(4, remaining_full * 2)

    soft = time_left_ms / moves_left

    # cap the share used by a single move so we never blow the clock early
    cap = time_left_ms * 0.20
    if time_left_ms < 10000:
        cap = time_left_ms * 0.12
    soft = min(soft, cap)

    return max(30, soft)