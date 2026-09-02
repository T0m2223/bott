"""Move ordering: TT move, captures by MVV/LVA, promotions, killer moves,
history heuristic, then a cheap positional tie-breaker."""

import chess

MAX_PLY = 128

# MVV/LVA weights indexed by piece type (index used = piece_type)
_MVV = [0, 1, 3, 4, 5, 9, 0]

_SCORE_TT = 1_000_000_000_000
_SCORE_KILLER1 = 900_000_000
_SCORE_KILLER2 = 850_000_000
_SCORE_CAPTURE_BASE = 1_000_000
_SCORE_PROMO_BASE = 600_000_000
_SCORE_COUNTER = 800_000_000


class MoveOrder:
    __slots__ = ("killers", "history", "countermove")

    def __init__(self):
        self.killers = [[None, None] for _ in range(MAX_PLY)]
        # indexed by (color * 64 + from_square) * 64 + to_square
        self.history = [0] * (2 * 64 * 64)
        # indexed by (side-that-moved * 64 + from) * 64 + to : a refutation
        # move to play immediately after the opponent plays this quiet move
        self.countermove = [None] * (2 * 64 * 64)

    def reset_ply(self, ply):
        self.killers[ply] = [None, None]
        if ply + 1 < MAX_PLY:
            self.killers[ply + 1] = [None, None]

    def add_killer(self, move, ply):
        k = self.killers[ply]
        if k[0] == move:
            return
        if k[1] == move:
            return
        k[1] = k[0]
        k[0] = move

    def add_history(self, board, move, depth):
        side = 0 if board.turn == chess.WHITE else 1
        idx = ((side * 64 + move.from_square) * 64 + move.to_square)
        h = self.history
        h[idx] += depth * depth
        if h[idx] > 1_000_000:
            for i in range(len(h)):
                h[i] //= 2

    def score(self, board, move, tt_move, ply, parent_move=None):
        if move == tt_move:
            return _SCORE_TT

        promo = move.promotion
        capture = board.is_capture(move)
        if capture:
            victim = board.piece_type_at(move.to_square)
            if victim is None:  # en passant
                victim = chess.PAWN
            attacker = board.piece_type_at(move.from_square)
            s = _SCORE_CAPTURE_BASE + _MVV[victim] * 100 - _MVV[attacker]
            if promo:
                s += _SCORE_PROMO_BASE
            return s

        if promo:
            return _SCORE_PROMO_BASE + _MVV[promo] * 1000

        k = self.killers[ply]
        if k[0] == move:
            return _SCORE_KILLER1
        if k[1] == move:
            return _SCORE_KILLER2

        if parent_move is not None:
            parent_side = 1 - (0 if board.turn == chess.WHITE else 1)
            idx = parent_side * 4096 + parent_move.from_square * 64 + parent_move.to_square
            if self.countermove[idx] == move:
                return _SCORE_COUNTER

        side = 0 if board.turn == chess.WHITE else 1
        return self.history[((side * 64 + move.from_square) * 64 + move.to_square)]

    def order(self, board, moves, tt_move, ply, parent_move=None):
        n = len(moves)
        scores = [self.score(board, m, tt_move, ply, parent_move) for m in moves]
        order = sorted(range(n), key=scores.__getitem__, reverse=True)
        return [moves[i] for i in order]