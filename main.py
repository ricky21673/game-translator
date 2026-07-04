# 程式進入點：啟動 QApplication 與主視窗
import sys
from PySide6.QtWidgets import QApplication
from gui.app import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(360, 220)
    win.show()
    sys.exit(app.exec())
