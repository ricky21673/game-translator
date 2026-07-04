@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem === Game Translator 還原工具（把 Game.exe 拖曳到本 bat 上即可一鍵還原）===

if "%~1"=="" (
    echo 請把遊戲的 Game.exe 拖曳到這個 bat 檔上執行，即可還原。
    pause
    exit /b 0
)

".\.venv\Scripts\python.exe" restore.py "%~1"
pause
