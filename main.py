# 程式進入點：啟動 QApplication 與主視窗
import sys
from PySide6.QtWidgets import QApplication
from gui.app import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.restore_last_session()  # 還原上次選的遊戲與字典（若路徑仍在）
    win.resize(360, 220)
    win.show()
    sys.exit(app.exec())
