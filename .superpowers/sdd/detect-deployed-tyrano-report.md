# 讓 detector 認出「已被本工具部署過的 TyranoScript 遊戲」

## 背景與 Bug
原本 detector 判定 Electron 打包的 TyranoScript，只看 `<game>/resources/app.asar` 是否存在、且其 asar
內含 `.ks` 檔或路徑含 `"tyrano"`。

但本工具部署 TyranoScript 後，會把 `app.asar` **改名成 `app.asar.trbak`**（備份原始檔），並把內容
**解包成 `resources/app/` 資料夾**。此時 `app.asar` 已不存在，原判定失效，detector 把「已翻譯的
Tyrano 遊戲」判成 `unknown`，導致重新選取時偵測不到，連「還原」按鈕都無法按。

## 改動範圍
只改：
- `core/detector.py`
- `tests/test_detector.py`

## 判定邏輯（擴充成兩種狀態，任一成立即回 `Detection("tyrano", game_dir)`）

### 1. 未部署（既有邏輯保留）
`resources/app.asar` 存在，讀 asar header（`core.asar`），檔案清單中任一路徑
以 `.ks` 結尾或含 `"tyrano"`。讀取失敗（非合法 asar）以 try/except 容錯，不誤判、往下走。

### 2. 已被本工具部署過（新增）
在 `resources/` 下，符合下列任一即判 tyrano，全程 try/except 容錯：
- **(2a)** `resources/app.asar.trbak` 存在 —— 本工具部署時的備份，代表這是我們處理過的 Tyrano。
- **(2b)** `resources/app/` 資料夾存在，且用 `os.walk` 在其中找到第一個 `.ks` 檔即可（例如
  `resources/app/data/scenario/*.ks`），不必全掃。

其餘 mv / mz / unity / 未打包 tyrano（`data/scenario`）判定均不受影響，順序不變。

## 新增測試（tests/test_detector.py）
- `test_detects_tyrano_via_deployed_trbak_backup`：只有 `resources/app.asar.trbak`（無 app.asar）→ engine == 'tyrano'。
- `test_detects_tyrano_via_deployed_unpacked_app_dir`：只有 `resources/app/data/scenario/first.ks`
  （無 app.asar、無 .trbak）→ engine == 'tyrano'。
- `test_empty_resources_dir_not_detected_as_tyrano`：只有空的 `resources/` 資料夾 → engine == 'unknown'（不誤判）。

既有測試全部維持：
- `test_detects_tyrano_via_electron_asar`（app.asar 內含 .ks）仍通過。
- `test_asar_without_ks_or_tyrano_not_detected_as_tyrano`、`test_corrupt_asar_does_not_crash_detect` 等仍通過。

## 實際測試輸出

detector 測試：
```
$ ./.venv/Scripts/python.exe -m pytest tests/test_detector.py -q
..........                                                               [100%]
10 passed in 0.09s
```

全套：
```
$ ./.venv/Scripts/python.exe -m pytest -q
........................................................................ [ 40%]
........................................................................ [ 81%]
.................................                                        [100%]
177 passed in 8.59s
```

本次全綠，未出現 server flaky。

## 疑慮 / 備註
- (2b) 使用 `os.walk` 找到第一個 `.ks` 即回傳；若 `resources/app/` 非常巨大且完全不含 .ks，理論上會走完整棵樹，但一般 Tyrano 專案量級可忽略。
- (2a) 只認 `app.asar.trbak` 這個固定備份檔名；若未來部署流程改用別的備份命名，需同步更新此判定。
