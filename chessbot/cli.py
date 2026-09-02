"""Terminal chess: play a game of chess against the bot from the command line.

Usage:
    python -m chessbot.cli --color black --time 5 --depth 12

Flags:
    --color white|black   which side the human plays (default white)
    --time N              clock per player in minutes (default 5)
    --depth N             maximum search depth for the bot (default: unlimited)

Every bot move you type is read as SAN (Nf3, exd5, O-O, e8=Q) or UCI (e2e4).
Available commands while it is your turn: moves, help, resign, quit.
"""

import argparse
import time

import chess

from . import get_move

SEC_TO_MS = 1000.0


def fmt_clock(ms):
    ms = max(0, int(ms))
    m, s = divmod(ms // 1000, 60)
    return f"{m:02d}:{s:02d}"


def render(board):
    """Draw the board with coordinates, white at the bottom."""
    names = {
        chess.PAWN: "♙♟", chess.KNIGHT: "♘♞", chess.BISHOP: "♗♝",
        chess.ROOK: "♖♜", chess.QUEEN: "♕♛", chess.KING: "♔♚",
    }
    lines = ["    a  b  c  d  e  f  g  h"]
    for rank in range(7, -1, -1):
        row = f"{rank + 1}  "
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            if piece is None:
                row += " . "
            else:
                i = 0 if piece.color == chess.WHITE else 1
                row += " " + names[piece.piece_type][i] + " "
        lines.append(row + f"{rank + 1}")
    lines.append("    a  b  c  d  e  f  g  h")
    return "\n".join(lines)


def parse_human_move(board, text):
    t = text.strip().replace("0-0", "O-O")
    if not t:
        return None
    try:
        return board.parse_san(t)
    except ValueError:
        pass
    try:
        return chess.Move.from_uci(t)
    except ValueError:
        raise ValueError(f"could not understand move: {text!r}")


def outcome_text(board):
    outcome = board.outcome()
    if outcome is None:
        return None
    reason = {
        chess.Termination.CHECKMATE: "checkmate",
        chess.Termination.STALEMATE: "stalemate",
        chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
        chess.Termination.FIFTY_MOVES: "fifty-move rule",
        chess.Termination.SEVENTYFIVE_MOVES: "seventy-five-move rule",
        chess.Termination.THREEFOLD_REPETITION: "threefold repetition",
        chess.Termination.FIVEFOLD_REPETITION: "fivefold repetition",
    }.get(outcome.termination, str(outcome.termination))
    if outcome.winner is None:
        return f"Draw ({reason})"
    winner = "You" if outcome.winner == human_color else "Bot"
    return f"{winner} win ({reason})"


def main(argv=None):
    global human_color

    parser = argparse.ArgumentParser(description="Play chess against the bot.")
    parser.add_argument("--color", choices=["white", "black"], default="white",
                        help="side the human plays (default: white)")
    parser.add_argument("--time", type=float, default=5.0,
                        help="clock per player in minutes (default: 5)")
    parser.add_argument("--depth", type=int, default=None,
                        help="maximum bot search depth (default: unlimited)")
    args = parser.parse_args(argv)

    human_color = (chess.WHITE if args.color == "white" else chess.BLACK)
    bot_color = not human_color
    bot_name = "White" if bot_color == chess.WHITE else "Black"
    human_name = "White" if human_color == chess.WHITE else "Black"
    clock_ms = int(args.time * 60 * SEC_TO_MS)
    bot_ms = clock_ms

    board = chess.Board()
    print("Bot plays", bot_name, "| depth:", args.depth or "auto",
          "| clock:", args.time, "min")
    print("Commands: SAN/UCI move, 'moves', 'help', 'resign', 'quit'")

    move_no = 0
    while True:
        outcome = board.outcome()
        print()
        print(render(board))
        print("-" * 22)
        if outcome is not None:
            print(" ", outcome_text(board))
            print(" ", board.fen())
            return

        # whose turn is it?
        if board.turn == bot_color:
            if bot_ms <= 0:
                print("Bot ran out of time - you win!")
                return
            print(f"Bot ({bot_name}) to move  [{fmt_clock(bot_ms)}]")
            t0 = time.perf_counter()
            mv_uci = get_move(board.fen(), bot_ms, max_depth=args.depth or 64)
            bot_ms -= int((time.perf_counter() - t0) * SEC_TO_MS)
            mv = chess.Move.from_uci(mv_uci)
            san = board.san(mv)
            board.push(mv)
            move_no += 1
            print(f"  {san}")
        else:
            print(f"You ({human_name}) to move  [{fmt_clock(bot_ms)} left for bot]")
            while True:
                try:
                    raw = input("  Your move: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nbye")
                    return
                low = raw.lower()
                if low in ("quit", "q", "exit"):
                    print("bye")
                    return
                if low == "resign":
                    print(f"You resign - {bot_name} wins!")
                    return
                if low in ("moves", "?"):
                    print("  legal:", " ".join(board.san(m) for m in board.legal_moves))
                    continue
                if low in ("help", "h"):
                    print("  enter SAN (Nf3, exd5, O-O, e8=Q) or UCI (e2e4);"
                          " commands: moves, help, resign, quit")
                    continue
                try:
                    mv = parse_human_move(board, raw)
                except ValueError as e:
                    print("  ", e)
                    continue
                if mv is None:
                    continue
                if mv not in board.legal_moves:
                    print("  illegal move")
                    continue
                break
            board.push(mv)
            move_no += 1


if __name__ == "__main__":
    main()