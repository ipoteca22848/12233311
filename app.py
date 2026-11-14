import os
import sys
import math
from concurrent.futures import ThreadPoolExecutor

import chess
import chess.engine
import mss
import numpy as np
from PySide6.QtCore import Qt, QRect, QPoint, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
                              QLabel, QFileDialog, QCheckBox, QDialog)
from recognition import Recognizer, advance


class Selection(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowOpacity(0.45)
        self.setStyleSheet('background: #244060;')
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(QApplication.primaryScreen().virtualGeometry())
        self.start = self.end = None
        self.region = None

    def mousePressEvent(self, event):
        self.start = self.end = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is None:
            return
        rect = QRect(self.start, event.position().toPoint()).normalized()
        if min(rect.width(), rect.height()) < 160:
            return
        if abs(rect.width() - rect.height()) > max(rect.width(), rect.height()) * 0.04:
            return
        point = self.mapToGlobal(rect.topLeft())
        self.region = dict(left=point.x(), top=point.y(), width=rect.width(), height=rect.height())
        self.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor('white'), 3))
        painter.drawText(25, 40, 'Выделите всю доску 8×8 без координат и рамок. Esc — отмена.')
        if self.start is not None:
            painter.drawRect(QRect(self.start, self.end).normalized())


class Overlay(QWidget):
    def __init__(self, region, flipped):
        super().__init__()
        self.flipped = flipped
        self.move = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(region['left'], region['top'], region['width'], region['height'])

    def center(self, square):
        f, r = chess.square_file(square), chess.square_rank(square)
        col, row = (7-f, r) if self.flipped else (f, 7-r)
        return QPoint(round((col+.5)*self.width()/8), round((row+.5)*self.height()/8))

    def paintEvent(self, event):
        if not self.move:
            return
        a, b = self.center(self.move.from_square), self.center(self.move.to_square)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(245, 65, 55, 220)
        painter.setPen(QPen(color, max(5, self.width()/90), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(a, b)
        angle = math.atan2(b.y()-a.y(), b.x()-a.x())
        size = self.width()/28
        from PySide6.QtCore import QPointF
        points = [QPointF(b)] + [QPointF(b.x()-size*math.cos(angle+d),
                                        b.y()-size*math.sin(angle+d)) for d in (-.5, .5)]
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF(points))


class Helper(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Chess Helper')
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.resize(440, 320)
        self.engine_path = None
        self.engine = None
        self.active_engine_path = None
        self.overlay = None
        self.recognizer = None
        self.region = None
        self.board = chess.Board()
        self.future = None
        self.running = False
        self.pool = ThreadPoolExecutor(max_workers=1)
        layout = QVBoxLayout(self)
        label = QLabel('Поставьте начальную позицию и оставьте окно рядом с доской.\n'
                       'Захват и анализ выполняются локально.\n'
                       'В турнирах Chess.com внешние подсказки запрещены.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.flip = QCheckBox('Чёрные фигуры снизу')
        layout.addWidget(self.flip)
        self.engine_button = QPushButton('1. Выбрать stockfish.exe')
        self.engine_button.clicked.connect(self.choose_engine)
        layout.addWidget(self.engine_button)
        self.calibrate = QPushButton('2. Выделить доску в начальной позиции')
        self.calibrate.clicked.connect(self.select)
        layout.addWidget(self.calibrate)
        self.toggle = QPushButton('3. Запустить')
        self.toggle.clicked.connect(self.start_stop)
        layout.addWidget(self.toggle)
        self.status = QLabel('Выберите официальный Stockfish для Windows.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        exit_button = QPushButton('Выход из помощника')
        exit_button.clicked.connect(self.close)
        layout.addWidget(exit_button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(700)

    def choose_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выбрать Stockfish', '', 'Executable (*.exe);;All files (*)')
        if path:
            self.engine_path = path
            self.engine_button.setText(os.path.basename(path))

    def capture(self):
        with mss.mss() as screen:
            return np.array(screen.grab(self.region))[:, :, :3].copy()

    def select(self):
        if self.running or self.future:
            self.status.setText('Сначала остановите анализ и дождитесь завершения расчёта.')
            return
        if self.overlay:
            self.overlay.hide()
        selection = Selection()
        if selection.exec() == QDialog.Accepted:
            self.region = selection.region
            QTimer.singleShot(250, self.finish_calibration)

    def finish_calibration(self):
        try:
            self.recognizer = Recognizer(self.capture(), self.flip.isChecked())
            detected = self.recognizer.read(self.capture())
            if detected.board_fen() != chess.Board().board_fen():
                raise ValueError('Калибровка не прошла. Нужна начальная позиция, без выделений и стрелок.')
            self.board = chess.Board()
            if self.overlay:
                self.overlay.close()
            self.overlay = Overlay(self.region, self.flip.isChecked())
            self.status.setText('Калибровка выполнена. Не меняйте размер доски и тему.')
        except Exception as error:
            self.recognizer = None
            self.status.setText(str(error))

    def start_stop(self):
        if self.running:
            self.running = False
            self.engine_button.setEnabled(True)
            self.calibrate.setEnabled(True)
            self.flip.setEnabled(True)
            self.toggle.setText('Продолжить')
            self.overlay.hide()
            return
        if not self.engine_path or not self.recognizer:
            self.status.setText('Выберите Stockfish и откалибруйте доску.')
            return
        if self.flip.isChecked() != self.recognizer.flipped:
            self.status.setText('После смены ориентации повторите калибровку.')
            return
        self.running = True
        self.engine_button.setEnabled(False)
        self.calibrate.setEnabled(False)
        self.flip.setEnabled(False)
        self.toggle.setText('Остановить')

    def analyse(self, frame):
        observed = self.recognizer.read(frame)
        board = advance(self.board, observed)
        if board.is_game_over():
            return board, None, 'Партия завершена: ' + board.result()
        if self.engine is not None and self.active_engine_path != self.engine_path:
            self.engine.quit()
            self.engine = None
        if self.engine is None:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path, timeout=10)
            self.active_engine_path = self.engine_path
            self.engine.configure({'Threads': 2, 'Hash': 128})
        result = self.engine.play(board, chess.engine.Limit(time=0.6))
        move = result.move
        return board, move, ('Белые: ' if board.turn else 'Чёрные: ') + board.san(move)

    def tick(self):
        if self.future:
            if not self.future.done():
                return
            try:
                self.board, move, message = self.future.result()
                self.status.setText(message)
                self.overlay.move = move
                if self.running:
                    self.overlay.show()
                    self.overlay.update()
            except Exception as error:
                self.status.setText(str(error))
                self.overlay.hide()
            self.future = None
            return
        if self.running:
            # Hide our own arrow before capture so it cannot contaminate recognition.
            self.overlay.hide()
            QTimer.singleShot(100, self.submit)

    def submit(self):
        if not self.running or self.future:
            return
        try:
            self.future = self.pool.submit(self.analyse, self.capture())
        except Exception as error:
            self.status.setText(str(error))

    def closeEvent(self, event):
        self.running = False
        self.timer.stop()
        if self.overlay:
            self.overlay.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.engine:
            try:
                self.engine.quit()
            except Exception:
                self.engine.close()
        event.accept()


if __name__ == '__main__':
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = QApplication(sys.argv)
    window = Helper()
    window.show()
    sys.exit(app.exec())
