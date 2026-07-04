# CLI 還原工具：把 game-translator 對遊戲檔案的修改復原成部署前的原始狀態。
# 用法：python restore.py <Game.exe 或遊戲資料夾路徑>
import os
import sys

from core.detector import detect
from launcher import restore_mv_adapter

_SUPPORTED_ENGINES = ("mv", "mz")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python restore.py <Game.exe 或遊戲資料夾路徑>")
        return 0

    target = argv[1]
    # detect() 內部用 os.path.dirname(exe_path) 取得遊戲根目錄，
    # 若使用者傳入的是「遊戲資料夾路徑」而非 exe 檔，需先組一個該資料夾下的
    # 假路徑餵給 detect()，避免 dirname 誤取到上一層目錄
    if os.path.isdir(target):
        target = os.path.join(target, "Game.exe")
    detection = detect(target)

    if detection.engine not in _SUPPORTED_ENGINES or not detection.www_dir:
        print("非 MV 遊戲或找不到 www，無法還原")
        return 1

    restore_mv_adapter(detection.www_dir)
    print("還原流程已執行完畢")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
