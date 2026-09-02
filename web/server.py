"""Chessbot web server: serves a self-contained board UI and API routes that
ask the bot for moves and return the resulting positions.

Run:
    ./envy/bin/python web/server.py --port 8000 --clock 5 --depth 12

Routes:
    GET  /              -> index.html (front end, no external dependencies)
    GET  /api/health    -> {"ok": true, "engine": ..., "clock_ms": ..., "depth": ...}
    GET  /api/legal?fen -> legal moves of the position as {"from","to","san","promotion"}
    POST /api/play      -> apply a human move  (body: {"fen","from","to","promotion"?})
                           -> {"fen": ..., "san": ..., "game": {...}, "check": bool}
    POST /api/best_move -> {body: {"fen","time_left_ms"}} -> bot picks and plays,
                           same result fields plus {"move","san","elapsed_ms"}
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from chessbot import get_move  # noqa: E402

CLOCK_MS = 5 * 60 * 1000
DEPTH = None

_REASON = {
    chess.Termination.CHECKMATE: "checkmate",
    chess.Termination.STALEMATE: "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
    chess.Termination.FIFTY_MOVES: "fifty-move rule",
    chess.Termination.SEVENTYFIVE_MOVES: "seventy-five-move rule",
    chess.Termination.THREEFOLD_REPETITION: "threefold repetition",
    chess.Termination.FIVEFOLD_REPETITION: "fivefold repetition",
}


def _make_board(fen):
    return chess.Board(fen)


def _game_info(board):
    outcome = board.outcome()
    if outcome is None:
        return {"over": False, "check": board.is_check()}
    winner = {"w": "white", "b": "black", None: None}[
        "w" if outcome.winner == chess.WHITE else
        "b" if outcome.winner == chess.BLACK else None]
    result = outcome.result()
    return {
        "over": True,
        "result": result,
        "winner": winner,
        "reason": _REASON.get(outcome.termination, str(outcome.termination)),
        "check": board.is_check(),
    }


def _moves_list(board):
    moves = []
    for m in board.legal_moves:
        needs_promo = (
            m.promotion is None
            and board.piece_type_at(m.from_square) == chess.PAWN
            and chess.square_rank(m.to_square) in (0, 7)
        )
        moves.append({
            "from": chess.square_name(m.from_square),
            "to": chess.square_name(m.to_square),
            "san": board.san(m),
            "promotion": needs_promo,
        })
    return moves


def _legal_moves(fen):
    board = _make_board(fen)
    return {"moves": _moves_list(board), "turn": _turn(board),
            "game": _game_info(board)}


def _parse_move(fen, from_square, to_square, promotion=None):
    move = chess.Move(
        chess.parse_square(from_square),
        chess.parse_square(to_square),
    )
    board = _make_board(fen)
    piece = board.piece_type_at(move.from_square)
    if piece == chess.PAWN and chess.square_rank(move.to_square) in (0, 7):
        kind = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP,
                "n": chess.KNIGHT}.get((promotion or "q").lower(), chess.QUEEN)
        move.promotion = kind
    return move


def _apply_move(fen, from_square, to_square, promotion=None):
    move = _parse_move(fen, from_square, to_square, promotion)
    board = _make_board(fen)
    if move not in board.legal_moves:
        return None, None, None
    san = board.san(move)
    board.push(move)
    return board, san, _game_info(board)


def _turn(board):
    return "white" if board.turn else "black"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        if parts.path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif parts.path == "/api/health":
            self._json(200, {"ok": True, "engine": "chessbot",
                             "clock_ms": CLOCK_MS, "depth": DEPTH})
        elif parts.path == "/api/legal":
            fen = urllib.parse.parse_qs(parts.query).get("fen", [""])[0]
            try:
                _make_board(fen)  # validate
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            self._json(200, _legal_moves(fen))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/best_move":
            return self._post_best_move()
        if path == "/api/play":
            return self._post_play()
        self._json(404, {"error": "not found"})

    def _post_best_move(self):
        body = self._read_json()
        if "error" in body:
            return self._json(400, body)
        fen = body.get("fen")
        time_left_ms = body.get("time_left_ms")
        try:
            board = _make_board(fen)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        try:
            t0 = time.perf_counter()
            uci = get_move(fen, max(1, int(time_left_ms or CLOCK_MS)),
                           max_depth=DEPTH or 64)
            elapsed = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:
            return self._json(500, {"error": str(exc)})
        if uci == "0000":
            return self._json(200, {"fen": fen, "move": None, "san": None,
                                    "turn": _turn(board),
                                    "game": _game_info(board), "elapsed_ms": elapsed})
        try:
            mv = chess.Move.from_uci(uci)
        except ValueError as exc:
            return self._json(500, {"error": str(exc)})
        san = board.san(mv)
        board.push(mv)
        self._json(200, {"fen": board.fen(), "move": uci, "san": san,
                         "turn": _turn(board),
                         "game": _game_info(board), "elapsed_ms": elapsed,
                         "legal": _moves_list(board)})

    def _post_play(self):
        body = self._read_json()
        if "error" in body:
            return self._json(400, body)
        fen, from_sq, to_sq = body.get("fen"), body.get("from"), body.get("to")
        if not (fen and from_sq and to_sq):
            return self._json(400, {"error": "fen, from, to required"})
        try:
            board, san, info = _apply_move(fen, from_sq, to_sq,
                                           body.get("promotion"))
        except (ValueError, KeyError) as exc:
            return self._json(400, {"error": str(exc)})
        if board is None:
            return self._json(400, {"error": "illegal move"})
        self._json(200, {"fen": board.fen(), "san": san, "turn": _turn(board),
                         "game": info, "legal": _moves_list(board)})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {"error": "bad json body"}

    def _serve_file(self, name, ctype):
        path = os.path.join(_THIS_DIR, name)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + fmt % args + "\n")


def main(argv=None):
    global CLOCK_MS, DEPTH
    parser = argparse.ArgumentParser(description="chessbot web frontend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--clock", type=float, default=5.0,
                        help="bot clock in minutes (default 5)")
    parser.add_argument("--depth", type=int, default=None,
                        help="maximum bot search depth (default unlimited)")
    args = parser.parse_args(argv)

    CLOCK_MS = int(args.clock * 60 * 1000)
    DEPTH = args.depth
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"chessbot web UI on http://{args.host}:{args.port}"
          f"  (clock={args.clock}m, depth={args.depth})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()