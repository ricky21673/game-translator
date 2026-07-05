# 一般開啟（不翻譯直接啟動遊戲）— 設計（spec）

> 目標：在翻譯工具加一顆「一般開啟」按鈕，直接啟動已選遊戲、**跳過所有翻譯/部署/server**，
> 給「已翻好只想再玩」用。因工具被強制進 Sandboxie 沙盒，從工具啟動遊戲＝遊戲也在沙盒內。

## 1. 背景與問題

現在只有「開始」一種啟動方式，會跑完整翻譯流程（加密 MZ/Tyrano 批次翻、RPG Maker 部署+起 server）再啟動。已翻好的遊戲想再玩一次，只能再按「開始」→ 重跑流程（加密 MZ 會重解密/重嵌入，多餘）。且使用者已把 `GameTranslator.exe` 設為 Sandboxie 強制程式，**從工具啟動的遊戲才會一起進沙盒**（直接雙擊 Game.exe 不會）。故需要「從工具直接開遊戲、但不重翻」。

## 2. 目標與非目標

**目標**：加「一般開啟」＝純啟動已選遊戲 exe（不部署、不翻、不起 server），在沙盒內執行。

**非目標**：
- 線上即時翻的模式（不起 server，故未翻過的新文字不會被翻——這是預期，本功能就是「直接開，不翻」）。
- 自動判斷遊戲是否已翻（一律直接啟動；沒翻過就是開原文）。

## 3. 設計（只動 `gui/app.py`）

### 3.1 UI：三顆按鈕

- **`翻譯並開啟`**：由現有「開始」按鈕**改名**（屬性仍為 `self.start_btn`），行為完全不變（`on_start`）。
- **`一般開啟`**（新）：`self.launch_btn`，接 `on_launch_only`。
- **`還原遊戲（移除翻譯修改）`**：不變。

### 3.2 行為：`on_launch_only`

```
def on_launch_only(self):
    守衛：self.exe_path 為 None → 顯示提示、return
    try:
        launch_game(self.exe_path)
        info 顯示「已直接啟動遊戲（未重新翻譯）」
    except Exception as e:
        info 顯示「啟動失敗：{e}」
```

- 只呼叫既有 `launch_game(exe_path)`（`subprocess.Popen([exe], cwd=遊戲資料夾)`），不碰 pipeline/server/deploy。
- 全程 try/except 容錯，不讓例外逸出 Qt 事件迴圈。

### 3.3 啟用時機

- `一般開啟` 只要**選了遊戲**（`self.exe_path` 有值）即可按——因為只是跑該 exe，與引擎/是否翻過無關。
- 於 `on_pick`（選遊戲）與 `restore_last_session`（啟動還原）後，一併 `self.launch_btn.setEnabled(self.exe_path is not None)`。
- 初始（未選遊戲）為 disabled。

### 3.4 與現有功能的關係

- `翻譯並開啟`（原 `on_start`）、`還原遊戲`、翻譯 pipeline、server、字典、選項——全部不變。
- 與「記住上次遊戲/字典」相輔：重開工具自動還原遊戲後，`一般開啟` 立即可按，一鍵重玩。

## 4. 測試策略（TDD、pytest 全綠再交付）

於 `tests/test_gui_redesign.py`（或 `test_gui_state.py`）補：

- **有選遊戲**：設好 `win.exe_path`，monkeypatch `launch_game`，呼叫 `win.on_launch_only()` → `launch_game` 被以 `exe_path` 呼叫一次；狀態列含「已直接啟動」。
- **沒選遊戲**：`win.exe_path = None`，呼叫 `on_launch_only()` → `launch_game` **未**被呼叫、不崩、狀態列提示需先選遊戲。
- **啟用狀態**：新建視窗 `launch_btn` disabled；選遊戲（或 `_apply_game`）後 enabled。
- **例外容錯**：`launch_game` 丟例外時，狀態列顯示「啟動失敗」、不逸出。
- **回歸**：既有 `start_btn`（翻譯並開啟）、還原、狀態列相關測試不受影響（按鈕改名只動 label，屬性 `start_btn` 沿用）。

## 5. 風險與對策

| 風險 | 對策 |
|---|---|
| 對沒翻過的遊戲按「一般開啟」＝開原文 | 預期行為；狀態列註明「未重新翻譯」 |
| 改名「開始」影響既有測試 | 屬性名 `self.start_btn` 不變，只改顯示 label；若有測試斷言 label 文字再一併更新 |
| 使用者以為「一般開啟」也會翻 | 按鈕名與狀態列訊息明確區分「翻譯並開啟」vs「一般開啟」 |
