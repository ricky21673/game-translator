# 一般開啟（不翻譯直接啟動）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加一顆「一般開啟」按鈕，直接啟動已選遊戲、跳過所有翻譯/部署/server（工具在沙盒內 → 遊戲也進沙盒）。

**Architecture:** 只改 `gui/app.py`：把「開始」改名「翻譯並開啟」、新增 `launch_btn`（一般開啟）→ `on_launch_only` 只呼叫既有 `launch_game(exe_path)`；選遊戲後啟用。

**Tech Stack:** Python 3.10、PySide6、pytest。

## Global Constraints

- **全程繁體中文**（程式碼註解、commit 訊息、回報）。
- **禁止自動 `git commit`/`git push`**：commit 步驟須先取得使用者當次明確同意（鐵則 #2）；commit 訊息**不得含任何人名**、結尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- Python 一律 `.\.venv\Scripts\python.exe`；測試 `-m pytest -q`；**pytest 全綠再交付**；小步 TDD。
- **只動 `gui/app.py` 與測試檔**；不改翻譯 pipeline / server / launcher。
- `on_launch_only` **只呼叫既有 `launch_game(exe_path)`**，不碰部署/翻譯/server；全程 try/except 容錯。
- 按鈕屬性名沿用 `self.start_btn`（只改顯示 label），既有測試不得被破壞。

---

### Task 1: 「一般開啟」按鈕與直接啟動

**Files:**
- Modify: `gui/app.py`（按鈕建立、signal 連接、新增 `on_launch_only`、`_apply_game` 啟用）
- Test: `tests/test_gui_offline_dict.py`（既有檔，補測試；已有 `QApplication`、`_mk_mv_game` helper）

**Interfaces:**
- Consumes: 既有 `launch_game(exe_path)`（`gui/app.py` 已 import）、`self.exe_path`、`self.info`、`_apply_game`。
- Produces: `self.launch_btn`（QPushButton「一般開啟」）、`on_launch_only(self)`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_gui_offline_dict.py` 末端加：

```python
def test_launch_only_launches_selected_game(monkeypatch):
    # 有選遊戲 → on_launch_only 呼叫 launch_game(exe_path)
    called = {}
    monkeypatch.setattr(app_module, "launch_game", lambda p: called.setdefault("path", p))
    win = app_module.MainWindow()
    win.exe_path = r"C:\game\Game.exe"
    win.on_launch_only()
    assert called.get("path") == r"C:\game\Game.exe"
    assert "已直接啟動" in win.info.text()


def test_launch_only_no_game_does_nothing(monkeypatch):
    # 沒選遊戲 → 不呼叫 launch_game、不崩、提示先選遊戲
    called = {}
    monkeypatch.setattr(app_module, "launch_game", lambda p: called.setdefault("path", p))
    win = app_module.MainWindow()
    win.exe_path = None
    win.on_launch_only()
    assert "path" not in called
    assert "請先選擇遊戲" in win.info.text()


def test_launch_only_handles_exception(monkeypatch):
    # launch_game 丟例外 → 狀態列顯示失敗、不逸出
    def boom(p):
        raise RuntimeError("x")
    monkeypatch.setattr(app_module, "launch_game", boom)
    win = app_module.MainWindow()
    win.exe_path = r"C:\game\Game.exe"
    win.on_launch_only()
    assert "啟動失敗" in win.info.text()


def test_launch_btn_disabled_initially_enabled_after_apply(tmp_path):
    # 初始 disabled；套用遊戲後 enabled
    game_dir, www = _mk_mv_game(tmp_path)
    exe = game_dir / "Game.exe"
    exe.write_text("", encoding="utf-8")
    win = app_module.MainWindow()
    assert win.launch_btn.isEnabled() is False
    win._apply_game(str(exe))
    assert win.launch_btn.isEnabled() is True
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gui_offline_dict.py -q`
Expected: FAIL（`launch_btn`／`on_launch_only` 尚不存在）

- [ ] **Step 3: 寫實作**

在 `gui/app.py`：

3a) 按鈕建立區（現為）：
```python
        self.start_btn = QPushButton("開始")
        self.start_btn.setEnabled(False)
        self.restore_btn = QPushButton("還原遊戲（移除翻譯修改）")
        self.restore_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.restore_btn)
```
改成：
```python
        self.start_btn = QPushButton("翻譯並開啟")
        self.start_btn.setEnabled(False)
        self.launch_btn = QPushButton("一般開啟")
        self.launch_btn.setEnabled(False)
        self.restore_btn = QPushButton("還原遊戲（移除翻譯修改）")
        self.restore_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.launch_btn)
        btn_row.addWidget(self.restore_btn)
```

3b) signal 連接區（現有 `self.start_btn.clicked.connect(self.on_start)` 之後）新增一行：
```python
        self.launch_btn.clicked.connect(self.on_launch_only)
```

3c) 新增方法（放在 `on_start` 附近）：
```python
    def on_launch_only(self):
        # 一般開啟：直接啟動已選遊戲，不部署/不翻/不起 server。
        # 工具已被強制進沙盒，故從這裡啟動的遊戲也會在同一個沙盒內。
        if not self.exe_path:
            self.info.setText("請先選擇遊戲主程式")
            return
        try:
            launch_game(self.exe_path)
            self.info.setText("已直接啟動遊戲（未重新翻譯）")
        except Exception as e:
            self.info.setText(f"啟動失敗：{e}")
```

3d) `_apply_game` 內，現有 `self.start_btn.setEnabled(ok)` 之後新增一行：
```python
        self.launch_btn.setEnabled(True)  # 選了遊戲就能「一般開啟」（只跑該 exe，與是否翻過無關）
```

- [ ] **Step 4: 執行測試確認通過 + 全套無回歸**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gui_offline_dict.py -q`
Expected: PASS（新 4 測試 + 既有全綠）

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全套 PASS（`test_server.py` 偶發 Windows socket flaky，單獨重跑即綠）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add gui/app.py tests/test_gui_offline_dict.py
git commit -m "feat(gui): 新增「一般開啟」直接啟動遊戲（不翻譯），開始改名「翻譯並開啟」"
```

---

## 驗收清單

- [ ] `pytest -q` 全綠（新增 4 測試 + 既有）。
- [ ] `一般開啟` 只呼叫 `launch_game`，不碰部署/翻譯/server。
- [ ] `開始` 改名「翻譯並開啟」，行為未變；`start_btn` 屬性名沿用、既有測試未破。
- [ ] `一般開啟` 初始 disabled，選遊戲後 enabled。
