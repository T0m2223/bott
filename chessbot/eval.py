"""Static evaluation for the chess bot. Scores are from White's perspective in
centipawns.

Currently implemented:
  - tapered (mg/eg) material + piece-square tables driven by game phase
  - pawn structure: doubled, isolated, passed and connected-passed pawns
    computed from bitboards
  - mobility (weighted, capped per piece) and king proximity pressure
  - knight outposts, rook on open/semi-open file and on the 7th rank,
    bishop pair bonus
  - king safety via the pawn shield in front of the king
  - tempo bonus
"""

import chess

PAWN_VAL, KNIGHT_VAL, BISHOP_VAL, ROOK_VAL, QUEEN_VAL = 100, 320, 330, 500, 900
# value indexed by chess.PieceType (1..6); used for material + delta pruning
VAL = [0, PAWN_VAL, KNIGHT_VAL, BISHOP_VAL, ROOK_VAL, QUEEN_VAL, 0]

# Piece-square tables in CPW order: index 0 = a8, index 63 = h1 (rank 8 first).
# For a white piece on square sq use table[sq ^ 56]; for a black piece table[sq].
# row order: rank 8 down to rank 1.
PAWN_T = (
    0, 0, 0, 0, 0, 0, 0, 0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5, 5, 10, 25, 25, 10, 5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, -5, -10, 0, 0, -10, -5, 5,
    5, 10, 10, -20, -20, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
)

KNIGHT_T = (
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
)

BISHOP_T = (
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
)

ROOK_T = (
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0,
)

QUEEN_T = (
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20,
)

KING_MG = (
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20, 20, 0, 0, 0, 0, 20, 20,
    20, 30, 10, 0, 0, 10, 30, 20,
)

KING_EG = (
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50,
)

_TABLES = {
    chess.PAWN: (PAWN_T, PAWN_T),
    chess.KNIGHT: (KNIGHT_T, KNIGHT_T),
    chess.BISHOP: (BISHOP_T, BISHOP_T),
    chess.ROOK: (ROOK_T, ROOK_T),
    chess.QUEEN: (QUEEN_T, QUEEN_T),
    chess.KING: (KING_MG, KING_EG),
}

# game phase weights (max 24)
_PHASE_W = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1,
            chess.ROOK: 2, chess.QUEEN: 4, chess.KING: 0}

PASSED_BONUS = (0, 0, 12, 25, 45, 75, 120, 180, 260)

_FILE_BB = [0x0101010101010101 << f for f in range(8)]


def _passed_masks():
    w = [0] * 64
    b = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        lo = max(0, fl - 1)
        hi = min(7, fl + 1) + 1
        for r in range(rank + 1, 8):
            for f in range(lo, hi):
                w[sq] |= 1 << (r * 8 + f)
        for r in range(0, rank):
            for f in range(lo, hi):
                b[sq] |= 1 << (r * 8 + f)
    return w, b


PASSED_W, PASSED_B = _passed_masks()


def _knight_attacks():
    w = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        for dr, df in ((-2, -1), (-2, 1), (-1, -2), (-1, 2),
                       (1, -2), (1, 2), (2, -1), (2, 1)):
            r, f = rank + dr, fl + df
            if 0 <= r < 8 and 0 <= f < 8:
                w[sq] |= 1 << (r * 8 + f)
    return w


KNIGHT_TARGETS = _knight_attacks()


def _pawn_attacks():
    w = [0] * 64
    b = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        # white pawn from rank r attacks r+1, file +/- 1
        if rank < 7:
            if fl > 0:
                w[sq] |= 1 << (sq + 7)
            if fl < 7:
                w[sq] |= 1 << (sq + 9)
        if rank > 0:
            if fl > 0:
                b[sq] |= 1 << (sq - 9)
            if fl < 7:
                b[sq] |= 1 << (sq - 7)
    return w, b


PAWN_ATTACKS_W, PAWN_ATTACKS_B = _pawn_attacks()

# shield squares: the three squares one rank in front of the king
def _king_shield():
    w = [0] * 64
    b = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        if rank < 7:
            for f in (fl - 1, fl, fl + 1):
                if 0 <= f < 8:
                    w[sq] |= 1 << ((rank + 1) * 8 + f)
        if rank > 0:
            for f in (fl - 1, fl, fl + 1):
                if 0 <= f < 8:
                    b[sq] |= 1 << ((rank - 1) * 8 + f)
    return w, b


SHIELD_W, SHIELD_B = _king_shield()


# mobility weights and per-piece caps (mg, eg)
_MOB = {chess.KNIGHT: (4, 3), chess.BISHOP: (4, 3), chess.ROOK: (3, 2),
        chess.QUEEN: (2, 1)}
_MOB_CAP = {chess.KNIGHT: 8, chess.BISHOP: 13, chess.ROOK: 14, chess.QUEEN: 27}

# squares from which a black/white pawn attacks each square
def _pawn_src_attacks():
    w = [0] * 64
    b = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        # a white pawn at rank-1 attacks sq: source = sq-7 (file+1... ) -> keep
        # explicit: sources are one rank towards the pawn's home.
        if rank > 0:
            if fl > 0:
                w[sq] |= 1 << (sq - 9)  # white pawn on (rank-1, file-1)
            if fl < 7:
                w[sq] |= 1 << (sq - 7)  # white pawn on (rank-1, file+1)
        if rank < 7:
            if fl > 0:
                b[sq] |= 1 << (sq + 7)  # black pawn on (rank+1, file-1)
            if fl < 7:
                b[sq] |= 1 << (sq + 9)  # black pawn on (rank+1, file+1)
    return w, b


PAWN_SRC_W, PAWN_SRC_B = _pawn_src_attacks()

# king zone: the king square plus all its neighbours
def _king_zones():
    z = [0] * 64
    for sq in range(64):
        rank = sq // 8
        fl = sq % 8
        mask = 1 << sq
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                r, f = rank + dr, fl + df
                if 0 <= r < 8 and 0 <= f < 8:
                    mask |= 1 << (r * 8 + f)
        z[sq] = mask
    return z


KING_ZONE = _king_zones()

_ADJ_FILE = [0] * 8
for _f in range(8):
    _m = 0
    if _f > 0:
        _m |= _FILE_BB[_f - 1]
    if _f < 7:
        _m |= _FILE_BB[_f + 1]
    _ADJ_FILE[_f] = _m


def evaluate(board):
    occ_w = board.occupied_co[chess.WHITE]
    occ_b = board.occupied_co[chess.BLACK]

    mg = 0
    eg = 0
    phase = 0

    pawns_w = board.pawns & occ_w
    pawns_b = board.pawns & occ_b

    # material + PST + phase from bitboards (no piece_map() call)
    for piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                       chess.ROOK, chess.QUEEN, chess.KING):
        bw = _piece_bb(board, piece_type) & occ_w
        bb = _piece_bb(board, piece_type) & occ_b
        nw = bw.bit_count()
        nb = bb.bit_count()
        tmg, teg = _TABLES[piece_type]
        phase += (nw + nb) * _PHASE_W[piece_type]

        v = VAL[piece_type]
        mg += v * (nw - nb)
        eg += v * (nw - nb)

        x = bw
        while x:
            lsb = x & -x
            sq = lsb.bit_length() - 1
            mg += tmg[sq ^ 56]
            eg += teg[sq ^ 56]
            x ^= lsb
        x = bb
        while x:
            lsb = x & -x
            sq = lsb.bit_length() - 1
            mg -= tmg[sq]
            eg -= teg[sq]
            x ^= lsb

    # penn attacks union -> so we can test "protected by a pawn" cheaply
    patk_w = 0
    x = pawns_w
    while x:
        lsb = x & -x
        patk_w |= PAWN_ATTACKS_W[lsb.bit_length() - 1]
        x ^= lsb
    patk_b = 0
    x = pawns_b
    while x:
        lsb = x & -x
        patk_b |= PAWN_ATTACKS_B[lsb.bit_length() - 1]
        x ^= lsb

    # pawn structure: doubled, isolated, passed, connected passed
    for f in range(8):
        fb = _FILE_BB[f]
        nw = (fb & pawns_w).bit_count()
        nb = (fb & pawns_b).bit_count()
        if nw > 1:
            mg -= (nw - 1) * 8
        if nb > 1:
            mg += (nb - 1) * 8
        if nw and not (_ADJ_FILE[f] & pawns_w):
            mg -= nw * 12  # isolated white pawns
        if nb and not (_ADJ_FILE[f] & pawns_b):
            mg += nb * 12  # isolated black pawns

    x = pawns_w
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        if not (PASSED_W[sq] & pawns_b):
            rank = sq // 8 + 1
            bonus = PASSED_BONUS[rank]
            mg += bonus // 2
            eg += bonus
            if patk_w & (1 << sq):  # protected -> connected passed
                mg += 15 if rank >= 4 else 10
                eg += 15
        x ^= lsb
    x = pawns_b
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        if not (PASSED_B[sq] & pawns_w):
            rank = 8 - sq // 8
            bonus = PASSED_BONUS[rank]
            mg -= bonus // 2
            eg -= bonus
            if patk_b & (1 << sq):
                mg -= 15 if rank >= 4 else 10
                eg -= 15
        x ^= lsb

    # mobility + king danger + bishop pair + rook/outpost bonuses in one pass
    knight_w = board.knights & occ_w
    knight_b = board.knights & occ_b
    bishop_w = board.bishops & occ_w
    bishop_b = board.bishops & occ_b
    rook_w = board.rooks & occ_w
    rook_b = board.rooks & occ_b
    king_w = board.kings & occ_w
    king_b = board.kings & occ_b
    wksq = (king_w & -king_w).bit_length() - 1
    bksq = (king_b & -king_b).bit_length() - 1

    # knight outposts for white
    x = knight_w
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        rank = sq // 8
        if 4 <= rank <= 5:
            if patk_w & (1 << sq) and not (PAWN_SRC_B[sq] & pawns_b):
                mg += 20
                eg += 10
        x ^= lsb
    x = knight_b
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        rank = sq // 8
        if 2 <= rank <= 3:
            if patk_b & (1 << sq) and not (PAWN_SRC_W[sq] & pawns_w):
                mg -= 20
                eg -= 10
        x ^= lsb

    # rook on open/semi-open file + 7th rank
    x = rook_w
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        fb = _FILE_BB[sq % 8]
        if not (fb & (pawns_w | pawns_b)):
            mg += 20
            eg += 6
        elif not (fb & pawns_w):
            mg += 10
            eg += 3
        if sq // 8 == 6:
            mg += 12
        x ^= lsb
    x = rook_b
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        fb = _FILE_BB[sq % 8]
        if not (fb & (pawns_w | pawns_b)):
            mg -= 20
            eg -= 6
        elif not (fb & pawns_b):
            mg -= 10
            eg -= 3
        if sq // 8 == 1:
            mg -= 12
        x ^= lsb

    # bishop pair
    if bishop_w.bit_count() >= 2:
        mg += 30
        eg += 26
    if bishop_b.bit_count() >= 2:
        mg -= 30
        eg -= 26

    # mobility + king threat proximity
    for color, own, wz, enz in ((chess.WHITE, occ_w, wksq, bksq),
                                (chess.BLACK, occ_b, bksq, wksq)):
        sign = 1 if color == chess.WHITE else -1
        for pt, (mm, em) in _MOB.items():
            pieces = _piece_bb(board, pt) & own
            cap = _MOB_CAP[pt]
            x = pieces
            while x:
                lsb = x & -x
                sq = lsb.bit_length() - 1
                att = board.attacks_mask(sq) & ~own
                mob = att.bit_count()
                if mob > cap:
                    mob = cap
                mg += sign * mm * mob
                eg += sign * em * mob
                if KING_ZONE[enz] & att and pt != chess.QUEEN:
                    if pt == chess.KNIGHT:
                        mg += sign * 4
                    else:
                        mg += sign * 3
                x ^= lsb

    # king safety: pawn shield in front of the king
    # keep it cheap: only count shield pawns and the enemy attack pressure on
    # the king zone (already captured above via wz).
    x = king_w
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        shield = (SHIELD_W[sq] & pawns_w).bit_count()
        if shield == 0 and phase >= 12:
            mg -= 30
        elif shield == 1:
            mg -= 10
        elif shield >= 2:
            mg += 8
        x ^= lsb
    x = king_b
    while x:
        lsb = x & -x
        sq = lsb.bit_length() - 1
        shield = (SHIELD_B[sq] & pawns_b).bit_count()
        if shield == 0 and phase >= 12:
            mg += 30
        elif shield == 1:
            mg += 10
        elif shield >= 2:
            mg -= 8
        x ^= lsb

    if phase > 24:
        phase = 24
    score = (mg * phase + eg * (24 - phase)) // 24

    # tempo bonus for the side to move
    if board.turn == chess.WHITE:
        score += 10
    else:
        score -= 10
    return score


def _piece_bb(board, piece_type):
    if piece_type == chess.PAWN:
        return board.pawns
    if piece_type == chess.KNIGHT:
        return board.knights
    if piece_type == chess.BISHOP:
        return board.bishops
    if piece_type == chess.ROOK:
        return board.rooks
    if piece_type == chess.QUEEN:
        return board.queens
    return board.kings