@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem === 還原遊戲: 把 Game.exe 拖到本檔上放開即可還原 ===

if "%~1"=="" (
    echo 請把遊戲的 Game.exe 拖曳到這個 bat 檔上執行, 即可還原。
    echo.
    pause
    exit /b 0
)

".\.venv\Scripts\python.exe" restore.py "%~1"

echo.
pause
