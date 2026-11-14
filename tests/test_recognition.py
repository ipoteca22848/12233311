import unittest
import chess
from recognition import advance, square_at


class TrackingTests(unittest.TestCase):
    def test_orientation(self):
        self.assertEqual(square_at(0, 0, False), chess.A8)
        self.assertEqual(square_at(0, 0, True), chess.H1)

    def test_preserves_move_state(self):
        previous = chess.Board()
        after = previous.copy()
        after.push_uci('e2e4')
        observed = chess.Board(None)
        observed.set_board_fen(after.board_fen())
        tracked = advance(previous, observed)
        self.assertEqual(tracked.fen(), after.fen())
        self.assertEqual(tracked.ep_square, chess.E3)

    def test_rejects_missed_moves(self):
        after = chess.Board()
        after.push_uci('e2e4')
        after.push_uci('e7e5')
        with self.assertRaises(ValueError):
            advance(chess.Board(), after)

    def test_unchanged(self):
        board = chess.Board()
        self.assertEqual(advance(board, board).fen(), board.fen())

    def test_castling(self):
        before = chess.Board('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
        after = before.copy()
        after.push_uci('e1g1')
        self.assertEqual(advance(before, after).fen(), after.fen())

    def test_en_passant(self):
        before = chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
        after = before.copy()
        after.push_uci('e5d6')
        self.assertEqual(advance(before, after).fen(), after.fen())

    def test_promotion(self):
        before = chess.Board('4k3/P7/8/8/8/8/8/4K3 w - - 0 1')
        after = before.copy()
        after.push_uci('a7a8q')
        self.assertEqual(advance(before, after).fen(), after.fen())
