"""Search: negamax alpha-beta with PVS, iterative deepening, aspiration windows,
transposition table, null-move pruning, LMR, check extension and a quiescence
search with delta pruning."""

import time

import chess

from .eval import evaluate, VAL
from .moveorder import MoveOrder, MAX_PLY
from .tt import EXACT, LOWER, UPPER

INF = 32000
MATE = 30000
# small draw incentive to avoid endless shuffling in flat positions
_CONTEMPT = 6


class _TimeUp(Exception):
    """Raised internally when the hard time budget is hit; unwinds the search
    without storing garbage TT entries and with the board restored."""


def _tt_store(score, ply):
    if score > MATE - MAX_PLY:
        return score + ply
    if score < -(MATE - MAX_PLY):
        return score - ply
    return score


def _tt_load(score, ply):
    if score > MATE - MAX_PLY:
        return score - ply
    if score < -(MATE - MAX_PLY):
        return score + ply
    return score


def _eval_stm(board):
    """Static eval from the perspective of the side to move."""
    e = evaluate(board)
    return e if board.turn == chess.WHITE else -e


class Search:
    def __init__(self, board, tt, alloc_ms, hard_ms=None):
        self.board = board
        self.tt = tt
        self.alloc_ms = alloc_ms
        self.hard_ms = hard_ms or (alloc_ms * 4)
        self.order = MoveOrder()
        self.nodes = 0
        self.best = None
        self.root_scores = []

    def elapsed_ms(self):
        return (time.perf_counter() - self.t0) * 1000.0

    def _check_time(self):
        # called periodically from the hot loops
        if self.nodes & 4095 == 0 and self.elapsed_ms() > self.hard_ms:
            raise _TimeUp

    # ----- root / iterative deepening -------------------------------------

    def go(self, max_depth=64):
        self.t0 = time.perf_counter()
        board = self.board

        prev_score = None
        self.best = None
        prev_moves = None
        prev_scores = None
        last_iter_ms = 0.0
        prev_iter_ms = 0.0

        depth = 0
        while True:
            depth += 1
            if depth > max_depth:
                break

            iter_start = time.perf_counter()
            root_moves = list(board.generate_legal_moves())
            if not root_moves:
                if board.is_check():
                    return "0000"
                return "0000"

            # order root moves: previous iteration's best, then by score
            scored = [(self.root_score_for(m, prev_moves, prev_scores), m)
                      for m in root_moves]
            scored.sort(key=lambda t: t[0], reverse=True)
            root_moves = [m for _, m in scored]
            root_scores = [0] * len(root_moves)

            alpha = -INF
            beta = INF
            score = 0

            if depth >= 3 and prev_score is not None:
                delta = 40
                # aspiration windows
                while True:
                    alpha = max(-INF, prev_score - delta)
                    beta = min(INF, prev_score + delta)
                    try:
                        score = self._root(root_moves, root_scores, depth,
                                           alpha, beta)
                    except _TimeUp:
                        score = None
                        break
                    if score <= alpha:
                        delta += delta
                        continue
                    if score >= beta:
                        delta += delta
                        continue
                    break
            else:
                try:
                    score = self._root(root_moves, root_scores, depth,
                                       alpha, beta)
                except _TimeUp:
                    score = None

            if score is None:
                # interrupted mid-iteration; keep the best from a completed
                # earlier iteration
                break

            self.root_scores = root_scores
            prev_moves = root_moves
            prev_scores = dict(zip(root_moves, root_scores))

            # locked in the move returned by this completed iteration
            if root_moves and root_scores:
                best_i = max(range(len(root_scores)), key=root_scores.__getitem__)
                self.best = root_moves[best_i]
            else:
                self.best = None

            last_iter_ms = (time.perf_counter() - iter_start) * 1000.0
            elapsed = self.elapsed_ms()

            # easy move: huge gap to the second best -> stop early
            if depth >= 6 and len(root_scores) >= 2:
                ordered = sorted(root_scores, reverse=True)
                if ordered[0] - ordered[1] > 150 and elapsed > self.alloc_ms * 0.3:
                    break

            # stop if the next iteration is likely to overrun (geometric
            # estimate based on the growth of the last two iterations)
            if depth >= 4:
                growth = (last_iter_ms / prev_iter_ms) if prev_iter_ms else 2.0
                expected = last_iter_ms * max(2.0, growth)
                remaining = max(1.0, self.alloc_ms - elapsed)
                if expected > remaining * 1.2:
                    break

            if elapsed >= self.alloc_ms * 0.9:
                break

            prev_score = score
            prev_iter_ms = last_iter_ms

        if self.best is None:
            return "0000"
        if hasattr(self.best, "uci"):
            return self.best.uci()
        return "0000"

    def root_score_for(self, move, prev_moves, prev_scores):
        if prev_scores is not None:
            return prev_scores.get(move, -1)
        return 0

    def _root(self, moves, scores, depth, alpha, beta):
        board = self.board
        best = -INF
        best_move = None
        orig_alpha = alpha
        tt_move = None
        entry = self.tt.probe(board._transposition_key())
        if entry:
            tt_move = entry[3]

        # keep the loose order already given by go() (previous iteration's
        # best-first); just promote the TT move to the front
        if tt_move in moves:
            i = moves.index(tt_move)
            moves[0], moves[i] = moves[i], moves[0]
            scores[0], scores[i] = scores[i], scores[0]

        for i, mv in enumerate(moves):
            self._check_time()
            board.push(mv)
            try:
                if i == 0:
                    score = -self._search(depth - 1, -beta, -alpha, 1)
                else:
                    score = -self._search(depth - 1, -alpha - 1, -alpha, 1)
                    if score > alpha and score < beta:
                        score = -self._search(depth - 1, -beta, -alpha, 1)
            finally:
                board.pop()
            scores[i] = score

            if score > best:
                best = score
                best_move = mv
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break

        key = board._transposition_key()
        flag = EXACT
        if best <= orig_alpha:
            flag = UPPER
        elif best >= beta:
            flag = LOWER
        self.tt.store(key, depth, flag, _tt_store(best, 0), best_move)
        return best

    # ----- internal search ------------------------------------------------

    def _search(self, depth, alpha, beta, ply, parent_move=None):
        self.nodes += 1
        board = self.board
        key = board._transposition_key()

        entry = self.tt.probe(key)
        if entry is not None and entry[0] >= depth:
            mv = entry[3]
            score = _tt_load(entry[2], ply)
            if entry[1] == EXACT:
                return score
            if entry[1] == LOWER and score > alpha:
                alpha = score
            elif entry[1] == UPPER and score < beta:
                beta = score
            if alpha >= beta:
                return score

        if ply > 0:
            if board.is_fifty_moves():
                return 0
            if board.is_repetition(2):
                # contempt: in an objectively equal/quiet position, slightly
                # de-prioritize repeating moves so the bot keeps playing for a
                # win instead of shuffling pieces aimlessly
                return -_CONTEMPT

        in_check = board.is_check()
        if in_check:
            depth += 1  # check extension
        if depth <= 0:
            return self._qsearch(alpha, beta, ply)

        moves = list(board.generate_legal_moves())
        if not moves:
            if in_check:
                return -MATE + ply
            return 0

        tt_move = entry[3] if entry is not None else None

        # null move pruning
        pieces = (board.occupied & ~(board.pawns | board.kings)).bit_count()
        if (not in_check and depth >= 3 and pieces >= 2
                and (tt_move is None or entry[0] < depth)):
            board.push(chess.Move.null())
            try:
                score = -self._search(depth - 1 - (3 if depth < 8 else 4),
                                      -beta, -beta + 1, ply + 1)
            finally:
                board.pop()
            if score >= beta:
                return beta

        moves = self.order.order(board, moves, tt_move, ply, parent_move)
        best = -INF
        best_move = None
        orig_alpha = alpha
        best_quiet = None

        # static eval for futility pruning on quiet moves at low depth
        static = None
        if not in_check and depth <= 3 and len(moves) > 1:
            static = _eval_stm(board)

        for i, mv in enumerate(moves):
            self._check_time()
            capture = board.is_capture(mv)
            promotion = bool(mv.promotion)

            # futility pruning of quiet moves
            if (static is not None and not capture and not promotion
                    and best > -INF and depth <= 3):
                margin = 110 * depth + 40
                if static + margin <= alpha:
                    continue

            board.push(mv)
            next_depth = depth - 1

            reduce = 0
            if (i >= 3 and depth >= 3 and not in_check and not capture
                    and not promotion and mv != tt_move):
                reduce = 1 + (i // 8)
                if depth >= 8 and i >= 12:
                    reduce += 1

            try:
                if i == 0:
                    score = -self._search(next_depth, -beta, -alpha, ply + 1, mv)
                else:
                    if reduce:
                        s_depth = next_depth - reduce
                        if s_depth <= 0:
                            score = -self._qsearch(-beta, -alpha, ply + 1)
                        else:
                            score = -self._search(s_depth, -alpha - 1, -alpha,
                                                  ply + 1, mv)
                            if score > alpha:
                                score = -self._search(next_depth, -beta,
                                                      -alpha, ply + 1, mv)
                    else:
                        score = -self._search(next_depth, -alpha - 1, -alpha,
                                              ply + 1, mv)
                        if score > alpha and score < beta:
                            score = -self._search(next_depth, -beta, -alpha,
                                                  ply + 1, mv)
            finally:
                board.pop()

            if score > best:
                best = score
                best_move = mv
            if score > alpha:
                alpha = score
                if not capture:
                    self.order.add_killer(mv, ply)
                    self.order.add_history(board, mv, next_depth + 1)
                    best_quiet = mv
            if alpha >= beta:
                break

        flag = EXACT
        if best <= orig_alpha:
            flag = UPPER
        elif best >= beta:
            flag = LOWER
        self.tt.store(key, depth, flag, _tt_store(best, ply), best_move)

        # record the countermove: parent's quiet move -> this node's best quiet
        # reply, to improve move ordering on repeated positions at shallow search
        # key by the side that played parent_move (the opponent of current side)
        if parent_move is not None and best_quiet is not None and best > alpha - 30:
            parent_side = 1 - (0 if board.turn == chess.WHITE else 1)
            self.order.countermove[
                parent_side * 4096 + parent_move.from_square * 64 + parent_move.to_square
            ] = best_quiet
        return best

    # ----- quiescence ------------------------------------------------------

    def _qsearch(self, alpha, beta, ply):
        self.nodes += 1
        board = self.board
        if ply > MAX_PLY - 2:
            return _eval_stm(board)

        stand = _eval_stm(board)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand

        in_check = board.is_check()
        if in_check:
            moves = list(board.generate_legal_moves())
        else:
            moves = list(board.generate_legal_captures())

        # order captures MVV/LVA
        scores = []
        for mv in moves:
            if board.is_capture(mv):
                victim = board.piece_type_at(mv.to_square)
                if victim is None:
                    victim = chess.PAWN
                scores.append(_qmv(victim))
            else:
                scores.append(0)
        order = sorted(range(len(moves)), key=scores.__getitem__, reverse=True)
        moves = [moves[i] for i in order]

        for mv in moves:
            self._check_time()
            if not board.is_capture(mv) and not in_check:
                # only captures reach here normally
                break

            # delta pruning
            if not in_check and board.is_capture(mv):
                victim = board.piece_type_at(mv.to_square)
                if victim is None:
                    victim = chess.PAWN
                if stand + VAL[victim] + 200 <= alpha:
                    continue

            board.push(mv)
            try:
                score = -self._qsearch(-beta, -alpha, ply + 1)
            finally:
                board.pop()

            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha


def _qmv(piece_type):
    return [0, 1, 3, 3, 5, 9, 0][piece_type] * 100 - 1