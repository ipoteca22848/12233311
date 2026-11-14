"""Theme calibration and conservative board recognition."""
import cv2
import numpy as np
import chess


def square_at(row, col, flipped):
    return chess.square(7 - col if flipped else col, row if flipped else 7 - row)


def feature(tile):
    # Edges suppress square colors and tolerate light/dark square backgrounds.
    gray = cv2.cvtColor(tile[:, :, :3], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 64))
    return cv2.Canny(gray, 60, 160)[7:57, 7:57].astype(np.float32) / 255


def tiles(frame):
    h, w = frame.shape[:2]
    return [(r, c, frame[round(r*h/8):round((r+1)*h/8),
                          round(c*w/8):round((c+1)*w/8)])
            for r in range(8) for c in range(8)]


class Recognizer:
    def __init__(self, frame, flipped=False):
        self.flipped = flipped
        self.samples = {}
        initial = chess.Board()
        for r, c, tile in tiles(frame):
            p = initial.piece_at(square_at(r, c, flipped))
            label = p.symbol() if p else '.'
            self.samples.setdefault(label, []).append(feature(tile))

    def read(self, frame):
        board = chess.Board(None)
        for r, c, tile in tiles(frame):
            f = feature(tile)
            scores = sorted((min(float(np.mean((f-s)**2)) for s in samples), label)
                            for label, samples in self.samples.items())
            score, label = scores[0]
            if score > 0.16 or scores[1][0] - score < 0.003:
                raise ValueError('Неуверенное распознавание. Уберите подсветку/курсор или повторите калибровку.')
            if label != '.':
                board.set_piece_at(square_at(r, c, self.flipped), chess.Piece.from_symbol(label))
        return board


def advance(previous, observed):
    """Only accept a unique legal successor, preserving castling/en passant."""
    placement = observed.board_fen()
    if previous.board_fen() == placement:
        return previous.copy()
    matches = []
    for move in previous.legal_moves:
        trial = previous.copy()
        trial.push(move)
        if trial.board_fen() == placement:
            matches.append(trial)
    if len(matches) != 1:
        raise ValueError('Позиция не совпала с одним допустимым ходом. Верните доску или начните калибровку заново.')
    return matches[0]
