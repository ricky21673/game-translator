@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem === Game Translator 啟動器（雙擊即可開啟 GUI）===

set "PY=.\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [錯誤] 找不到虛擬環境 python: %PY%
    echo 請確認專案資料夾下的 .venv 是否存在。
    echo.
    pause
    exit /b 1
)

echo 啟動 Game Translator ...
echo (這個黑視窗請保持開著, 翻譯服務跑在裡面; 關掉它就會停止翻譯)
echo.

"%PY%" main.py

echo.
echo 翻譯工具已關閉 (代碼 %errorlevel%)
pause
