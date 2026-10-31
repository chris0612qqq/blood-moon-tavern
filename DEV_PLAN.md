# 血月酒館 — 程式設計流程表（DEV_PLAN）v1.1

> **給接手的 AI**：這份是施工順序。每一階段都有「通關條件」，**沒有通過就不准進下一階段**。
> 規格以 `SPEC.md` 為準；寫法遵守 `CODING_RULES.md`、`UI_RULES.md`；外觀聲音依 `ART_DIRECTION.md`。本檔只決定「先做什麼、做到什麼程度才算完成、要預留什麼」。

目錄：0 接手須知 ｜ 1 為什麼是這個順序 ｜ 2 全局路線圖 ｜ 3 各階段（P0–P9） ｜ 4 一定要預留的東西 ｜ 5 測試金字塔與每階段測試 ｜ 6 需要使用者配合的事 ｜ 7 進度紀錄範本 ｜ 8 文件對照索引 ｜ 9 變更紀錄

---

## 0 接手須知

### 0.1 閱讀順序（第一次接手必讀，約 30 分鐘）
1. `SPEC.md`：先讀 A1–A3（目標與模式）→ A5–A6（規則、千面狼）→ A7（保密）→ B1–B5（架構、狀態機）。其餘章節做到時再讀。
2. `CODING_RULES.md`：第 1 節總則、第 2 節 L1–L8、第 9 節 G1–G9。
3. 本檔第 2、3 節，找到目前做到哪一階段（看 `PROGRESS.md`）。
4. 做到前端時才讀 `UI_RULES.md`；做到美術時才讀 `ART_DIRECTION.md`。

### 0.2 工作守則
- **一次只做一個階段**；階段內依任務順序做，每完成一個任務就 commit（訊息格式 CODING_RULES R14）。
- **行為與 SPEC 不一致時，先改 SPEC 再改程式**，並在 SPEC D2 記一筆變更；不確定就問使用者，不要自己決定規則。
- **每階段結束**：跑完該階段的全部測試 → 依 CODING_RULES 第 8 節檢查表自我審查 → 更新 `PROGRESS.md` → 才能進下一階段。
- **不要提早做美術**：P8 之前畫面只用灰色方塊與系統字（灰盒）。業界的教訓是：太早投入美術，改規則時美術全部要重做。
- **每階段都要能跑起來**：任何時候 `main` 分支都是可以執行、測試全過的狀態。
- **版本號跟著階段走**：P*n* 期間版本為 `0.n.x`（例：P2 期間 `0.2.0`、`0.2.1`…），P9 通關後才是 `1.0.0`（CODING_RULES D6）。

---

## 1 為什麼是這個順序

業界做遊戲的共通做法（原型 → 可玩的核心循環 → 垂直切片 → 量產內容 → 打磨）套到這個專案：

| 業界原則 | 在本專案的意思 |
|---|---|
| **先驗證核心循環（core loop）** | 狼人殺的核心是「夜晚行動 → 天亮結算 → 白天投票 → 勝負判定」。先用純程式＋測試把這個循環做對（P1–P2），再談網路與畫面 |
| **先做灰盒、再上美術** | 前端先用灰色方塊做完整流程（P4），大家實際玩過、規則與節奏沒問題後，才套美術（P8） |
| **盡早找人玩（find the fun）** | P4 結束時就找朋友用灰盒版玩一局，比任何文件審查都能抓到問題 |
| **垂直切片（vertical slice）** | 美術階段先把「狼人選刀畫面」做到最終品質（含音效、動畫），確認風格與效能，再量產其他畫面 |
| **風險高的先做** | 本專案最高風險是「保密」與「斷線／換網址」，所以保密測試從 P2 就開始，網路韌性在 P7 獨立一階段處理 |
| **可擴充的東西一開始就預留** | 角色註冊表、平衡數值資料化、存檔版本、協定版本、開發工具——這些晚點補會很痛（第 4 節） |

---

## 2 全局路線圖

```
P0 環境與骨架
 └─▶ P1 規則核心（純函式＋單元測試）              ← 核心循環「在紙上」正確
      └─▶ P2 引擎、事件、模式、保密視圖、機器人整局 ← 核心循環「無畫面」可完整跑完
           └─▶ P3 伺服器、API、WebSocket、房間     ← 可以連線
                └─▶ P4 灰盒前端：完整流程            ← ★ 第一次真人試玩（找樂趣）
                     └─▶ P5 互動品質：防呆、回饋、上帝控制台、押注
                          └─▶ P6 媒體、旁白、PWA、iOS 實機
                               └─▶ P7 部署與韌性：Pages、Tunnel、斷線、出發前檢查
                                    └─▶ P8 美術與音效：先垂直切片，再量產
                                         └─▶ P9 Beta：完整試玩、效能、凍結版本
```
對應 SPEC B11 的 M1–M8：P1＝M1、P2＝M2、P3＝M3、P4–P5＝M4–M5、P6＝M6、P7＝M7、P8＝M8；P0、P9 為本檔新增。

---

## 3 各階段

> 每階段格式：**目標**／**先讀**／**任務**（依序）／**交付**／**測試**／**通關條件**／**常見陷阱**。

### P0 環境與骨架
- **目標**：建好 repo、工具、目錄，`pytest` 與 lint 能跑（即使還沒有程式）。
- **先讀**：SPEC B1、B2；CODING_RULES R12–R14、D5–D6。
- **任務**
  1. 建 repo `chris0612qqq/blood-moon-tavern`（公開），把五份文件（SPEC、CODING_RULES、UI_RULES、ART_DIRECTION、DEV_PLAN）與 `_archive/` 放進根目錄。
  2. 依 SPEC B2 建立目錄與空模組；`pyproject.toml`（ruff、mypy、pytest 設定）、`requirements.lock`、`.gitignore`（`data/`、`local_assets/`、`server/admin.local.json`、`.venv/`）、`VERSION`＝`0.0.1`。
  3. `server/enums.py`（角色、步驟、死因、錯誤碼代號，CODING_RULES R1）、`server/balance.py`（配角色表、倒數、輪替權重，G8）、`server/rng.py`（GameRng，L27）、`server/clock.py`（Clock／FakeClock，T7）。
  4. GitHub Actions `ci.yml`：push 時跑 ruff、mypy、pytest（先只有一個空測試）。部署用的 `pages.yml` 到 P7 才做。
  5. `config.py` 建立 `FEATURES` 功能開關（押注、江湖口吻、環境音等，CODING_RULES R6）與 `DEV_MODE` 讀取。
  6. 建立 `PROGRESS.md`（第 7 節範本）。
- **交付**：可 clone、`pip install -r requirements.lock`、`pytest` 綠燈。
- **通關條件**：CI 綠燈；`git status` 乾淨；`.gitignore` 確認擋住所有私密路徑。
- **常見陷阱**：把 `admin.local.json` 或 `data/` 不小心 commit 進公開 repo。

### P1 規則核心
- **目標**：所有規則以純函式實作，單元測試涵蓋 SPEC A5、A6、A5.7 每一條。
- **先讀**：SPEC A5、A6、A5.7、A13；CODING_RULES L9–L27、G7–G8、T1–T3。
- **任務**
  1. `roles/`：六個角色定義（陣營、夜晚步驟、可選目標、死亡觸發、公開身分），G7 註冊表。
  2. `rules.role_counts(n)`、`rules.deal(ids, history, rng)`（含千面狼與整數權重輪替，L26）。
  3. `rules.eligible_targets`、`wolf_consensus`（含空刀、平手抽籤、3 秒確認的判斷函式）、`resolve_night`（救、毒、同夜禁止、首夜自救、被刀又被毒算毒）。
  4. `rules.check_win`、`can_shoot`、`tally`（棄票、平票、改票一次）、`speak_order`、`last_words_queue`、`speak_seconds(n)`（依人數）。
  5. `disguise.py`：`on_deal`、`on_round_start`（剩餘回合減 1，歸零重抽）、`on_death`、`pick_target`（排除自己、死者、上一期）。
  6. 押注計分 `score_bets`（A13）。
  7. 把以上函式名稱補進 SPEC B4（若和 SPEC 列的名稱不同，以 SPEC 為準或先改 SPEC）。
- **交付**：`server/rules.py`、`server/disguise.py`、`server/roles/*`、`tests/test_rules.py`、`tests/test_disguise.py`。
- **測試**：單元測試；輪替抽牌 10 萬次統計（單一名額約 25%，狼人多名額實測約 27–31%，SPEC B10）；L9–L24 每條一個測試。
- **通關條件**：`rules`、`disguise` 分支覆蓋率 100%（T1）；SPEC D4 中屬於規則的列全部有測試且通過；`mypy --strict` 通過。
- **常見陷阱**：在規則裡直接用 `random` 或 `time`（違反總則 3）；從 `set` 抽籤沒排序（L25）。

### P2 引擎、事件、模式、保密視圖、機器人整局
- **目標**：不需要網路與畫面，就能用機器人跑完整局，而且保證不洩密、一定會結束、可重播。
- **先讀**：SPEC A3、A7、A8、B4、B5；CODING_RULES L1–L8、2.4 不變式、G1–G6、S1–S4、T4、T9。
- **任務**
  1. `events.py`：領域事件與 `apply(state, event)`（G1）；`schema_version`（G4）。
  2. `engine.py`：狀態轉移表（L6）、`handle(actor, intent)`、`tick(now)`、`step_seq`（L2）、不變式檢查。
  3. `modes.py`：`GodMode`／`AutoMode`（推進、權限、白天才可暫停）。
  4. `timers.py`：倒數從旁白念完才開始（E15 公式）、步驟間隔、女巫最短 8–15 秒、暫停／繼續。
  5. `views.py`：白名單輸出、依角色類型分層（P2）、`filter_event`。
  6. `server/dev/bots.py`：機器人玩家（隨機與腳本兩種），可在 FakeClock 下秒跑一局；同一份程式之後也給 DEV_MODE 的「加入 N 個機器人」使用（CODING_RULES D1），測試只是呼叫它。
- **交付**：可執行 `python -m server.dev.bots --players 10 --mode auto --seed 42` 跑完一局並印出事件摘要；`tests/test_engine.py`、`tests/test_views.py`、`tests/test_bots.py`。
- **測試**：保密測試（T4，每步驟×每種觀看者全文搜尋秘密）；兩模式、6–20 人合計 1000 局（CI 跑小樣本，階段結束跑完整版）；重播測試（T9）；不變式；SPEC D4 全部列。
- **通關條件**：1000 局零洩密、零卡死、零不變式錯誤；重播 100% 一致；失敗時可用種子重現（T2）。
- **常見陷阱**：在 engine 外直接改狀態（違反 G1）；用「事件類型」而非白名單決定送什麼。

### P3 伺服器、API、WebSocket、房間
- **目標**：真的可以用 HTTP／WebSocket 開房、加入、玩完整局（先用測試客戶端，不用畫面）。
- **先讀**：SPEC A4、A10、A11（伺服器部分）、B6–B8；CODING_RULES E1–E9、P1–P8、N5、N8、N13–N15。
- **任務**
  1. `db.py`：SQLite WAL、資料表（B6）、索引（P4）、交易、快照、`backup()`。
  2. `auth.py`：管理員帳密（`python -m server.setup_admin` 產生 `admin.local.json`；P7 的 `setup.bat` 會呼叫同一個指令）、房間密碼、PIN、token、鎖定以裝置計（N13）。
  3. `protocol.py`：pydantic 訊息模型與外框（`msg_id`、`step_seq`、`seq`、`server_ts`）；`scripts/gen_protocol.py` 產生前端版。
  4. `main.py`：HTTP 路由（B7）、WebSocket（auth、ping、`state.request`、ack／error）、單一房間 worker（L1）、`msg_id` 去重（L3）、送出佇列與逾時（N8）。
  5. `room.py`：開房、關房（刪資料與 log）、10 分鐘結算、被踢裝置封鎖。
  6. `presence.py`：心跳、離線判定、一半以上離線自動暫停與自動繼續。
  7. 重啟還原：讀快照＋事件重播 → 系統暫停。
- **交付**：`uvicorn server.main:app` 可啟動；`tests/test_api.py` 用多個 WebSocket 客戶端跑完整局（並把 `test_api.py` 補進 SPEC B2 的 tests 清單）。
- **測試**：API 測試；故障注入（T5：寫入失敗、重複訊息、過期 `step_seq`、重啟）；效能基準（T6）。
- **通關條件**：20 個測試客戶端跑完整局；重啟後可接續；故障注入全部符合 E 系列；T6 達標。
- **常見陷阱**：在 async 處理器裡做 scrypt 或縮圖卡住整個伺服器（UI_RULES Q10，要丟執行緒池）。

### P4 灰盒前端：完整流程（★ 第一次真人試玩）
- **目標**：用最樸素的畫面（灰色方塊、系統字、無動畫）把 S0–S27 的流程全部走通，找朋友實際玩一局。
- **先讀**：SPEC C3、C4、C8、C9；UI_RULES U1–U14；CODING_RULES G5–G6、M1–M4、V1–V4、V9。
- **任務**
  1. `store.js`、`net.js`（連線狀態機、重連、時間校正 M1、漏收重新同步 N5）。
  2. `router.js`：`resolveScreen(state, localUi)`（V1）。
  3. 共用元件灰盒版：`ActionButton`（五態，先只用文字表示）、`CountdownRing`（數字即可）、`PickGrid`、`Avatar`、`ScrollDialog`、`Toast`、`Banner`。
  4. 依 C9 走查順序做畫面：S0 → S1–S3 → S4 → S5 → S6 → S7–S10 → S11–S15 → S16–S18 → S22 → S20 → S19、S21、S25–S27。（S23 安裝引導、S24 準備檢查和 PWA、聲音有關，留到 P6。）
  5. 本機開多個瀏覽器分頁各當一位玩家，完整玩兩種模式各一局。
- **交付**：區網內可用手機瀏覽器玩（暫時用 `http://電腦IP:8765`，不用 Tunnel；伺服器同時提供畫面，所以不會有跨網域問題）。
  - 注意：非 HTTPS 的區網網址下，手機**不能**用相機、錄音、螢幕常亮、service worker——這些本來就在 P6 才做，灰盒階段不受影響。
- **測試**：多分頁手動（B10 第 7 項）；Playwright 跑一局並在每個事件後比對畫面與 store（UI_RULES UT1）。
- **通關條件（真人試玩關卡）**：和使用者及朋友至少 6 人實際玩一局完整遊戲；記下所有「看不懂、卡住、太慢、太快」的回饋；**回饋中屬於規則或流程的問題，先改 SPEC 並修好，才進 P5**。
- **常見陷阱**：忍不住先美化畫面；在事件處理器裡直接改 DOM（違反 U2）。

### P5 互動品質：防呆、回饋、上帝控制台、押注
- **目標**：把 UI_RULES 的防呆、回饋全部做到；上帝控制台與押注完整。
- **先讀**：UI_RULES 全文；SPEC C8、A13；CODING_RULES E10–E16、V5–V8、V12–V18。
- **任務**
  1. `ActionButton` 完整五態與 8 秒必解鎖（K1–K4）；不可逆操作確認框（K5）。
  2. 所有輸入框規則（K8 注音組字、K9 清理、2.2 表）。
  3. 四級回饋與 11 種異常畫面（F1–F11）；連線燈；狀態列字幕。
  4. 上帝控制台三狀態、語音選單、「手機念／我自己念」開關。
  5. 押注畫面與結算排行；規則速查 S26。
  6. `strings.js` 文字模板化（V8）、`data-testid`（V9）。
- **測試**：UI_RULES UT2（狂點）、UT3（輸入）、UT4（異常回饋）。
- **通關條件**：UI_RULES 第 6 節檢查表每個畫面全打勾；沒有任何按鈕能卡在 pending 超過 8 秒。
- **常見陷阱**：前端自己判斷誰能被投票（違反 G5，要用伺服器給的 `eligible_targets`）。

### P6 媒體、旁白、PWA、iOS 實機
- **目標**：照片、語音、旁白、加到主畫面在 iPhone 上都正常。
- **先讀**：SPEC A9、B9；CODING_RULES E11、E15–E16、V12–V17、N16–N18；ART_DIRECTION 13。
- **任務**
  1. 照片：Web Worker 壓縮、去 EXIF、縮圖（Q2、N11）；語音 `MediaRecorder`；上傳與簽章網址、過期重取（N21）。
  2. 旁白：`audio.js` 音訊管理器與優先序（V15）、zh-TW 語音選擇（V14）、長度估算、「標準／江湖」口吻、錄音覆蓋。
  3. PWA：`manifest.json`、service worker（只快取靜態檔、新版只在大廳提示）、S23 安裝引導、S24 準備檢查（聲音、靜音鍵、Wake Lock、主畫面）。
  4. 切換 App 遮住秘密（V20）、直式鎖定（V17）。
- **測試**：B10 第 8 項 iOS 實機（需使用者協助）。
- **通關條件**：至少一支 iPhone、一支 Android 實機完成：加入主畫面、拍照、錄音、聽到旁白、長按角色卡、鎖屏後回來接續。
- **常見陷阱**：等 `speechSynthesis` 的 `onend` 才推進（iOS 常不觸發，E15）。

### P7 部署與韌性
- **目標**：透過 GitHub Pages＋Tunnel 從外面連進來玩，斷線、換網址、慢速手機都能撐住。
- **先讀**：SPEC B1、A11、A12；CODING_RULES 第 12 節 N1–N24、D7–D8、S8。
- **任務**
  1. `.github/workflows/pages.yml`（`workflow_dispatch` 帶 `api` 參數產生 `server.json`）。
  2. `scripts/setup.bat`、`start.bat`（啟動、阻止睡眠、自動重啟、Tunnel、發布位址、健康檢查、換網址前先暫停、顯示 QR）、`preflight.bat`。
  3. 前端：讀 `server.json`、連不上重讀位址（N4）、退避加抖動（N2）、`online` 事件重連（N3）。
  4. `DEV_MODE` 開著時拒絕對外開 Tunnel（S8）。
- **測試**：CODING_RULES 12.8 全部網路測試（模擬 3G、掉包、切網路、遊戲中重開 Tunnel、同 IP 打錯 PIN、慢速手機）。
- **通關條件**：使用者在家開 `start.bat`，朋友用 4G 從外面加入並玩完一局；遊戲中刻意重開 Tunnel，所有手機 2 分鐘內自動回到原步驟。
- **常見陷阱**：service worker 快取了 `server.json`；IP 鎖定把同一熱點的人全鎖住。

### P8 美術與音效（先垂直切片，再量產）
- **目標**：套上 ART_DIRECTION 的完整外觀與聲音，舊手機仍流暢。
- **先讀**：ART_DIRECTION 全文；UI_RULES Q 系列；CODING_RULES V5–V7、V10–V11。
- **任務**
  1. `tokens.css`（SPEC C2＋ART 3.2 延伸色、字級三級、動畫時間變數）。
  2. **垂直切片**：只做「夜晚·狼人選刀（S8）」到最終品質——材質、按鈕五態、爪痕、倒數環火星、狼嚎＋旁白、3 秒確認演出；在 iPhone SE 級舊機測 ≥ 50 fps。**使用者看過切片並同意風格後才量產**。
  3. 量產：依 ART 第 8 節逐一套用其他畫面；`/dev/components` 元件目錄（V7）。
  4. 音效：Web Audio 合成全部 40 項（ART 12.6）、混音層級與 ducking（12.2）、夜晚靜音規則。
  5. 內建 SVG 素材：圖示、20 種預設圖騰、卡背、六張角色剪影卡、四個場景簡化版；`local_assets` 覆蓋與退路（V11）。
- **測試**：截圖比對（T10）、字級 130%（T11）、舊手機幀率（T8）、色弱模擬（ART 15）。
- **通關條件**：ART_DIRECTION 第 15 節驗收檢查表全打勾；使用者確認整體風格。
- **常見陷阱**：動畫改到 `width`／`top` 造成卡頓（Q6）；夜晚在非旁白手機播出聲音（洩密）。

### P9 Beta 與凍結
- **目標**：正式出遊前的最後驗證。
- **任務**
  1. 完整試玩兩種模式各一局（實際人數 8 人以上），使用 `start.bat` 對外連線。
  2. 修正試玩問題（規則問題先改 SPEC）。
  3. 跑全部自動化測試、CODING_RULES 與 UI_RULES 檢查表、ART 驗收表。
  4. `VERSION` 升為 `1.0.0`，寫 `README.md`（給使用者的操作說明：如何開房、出發前檢查、常見問題）。
  5. 出發前在使用者電腦跑 `preflight.bat` 全綠。
- **通關條件**：兩局完整試玩無阻斷性問題；所有測試綠燈；使用者簽核。

---

## 4 一定要預留的東西（晚點補會很痛）

| 預留 | 為什麼 | 在哪裡 |
|---|---|---|
| **角色註冊表** | 之後加守衛、白痴、警長等，只新增角色檔，不改引擎 | `server/roles/`（G7） |
| **平衡數值資料化** | 配角色表、倒數、輪替權重、千面狼換期回合可直接調 | `server/balance.py`（G8） |
| **事件紀錄＋存檔版本** | 看真相、回上一步、除錯重現；旅途中升級伺服器不會讀壞舊存檔 | `events.py`、`migrations/`（G1–G4） |
| **協定版本** | 前後端版本不符時能提示更新，而不是怪錯誤 | `auth.client_version`（M7） |
| **文字集中** | 改文案、之後要做英文版都只改一個檔 | `strings.js`、`narration.py`（R2、V8） |
| **設計變數** | 換主題、調顏色不用翻程式 | `tokens.css`（V5） |
| **開發工具** | 一個人也能測完整一局、重現 bug | `DEV_MODE`：機器人、時間加速、固定種子、狀態檢視器（D1–D4） |
| **素材覆蓋層** | 使用者之後換插圖、音效不必改程式 | `local_assets/`（SPEC C1、V11） |
| **功能開關** | 新功能可以先關著上線、試玩後再開 | `config.py` 的 `FEATURES = {...}`（例如押注、江湖口吻） |
| **觀測點** | 出問題時知道發生什麼 | 每房間 log、前端錯誤紀錄匯出（S7、E14） |
| **時間緩衝** | 業界經驗：真人試玩後一定會有預期外的修改 | P4 與 P9 之後各保留一段修正時間，不要排滿 |

---

## 5 測試金字塔與每階段測試

```
          ▲ 少      真人試玩（P4、P9）
         ───        iOS／Android 實機（P6、P7）
        ─────       Playwright 端到端＋截圖比對（P4、P5、P8）
       ───────      API／WebSocket 整合測試＋故障注入（P3、P7）
      ─────────     機器人整局 1000 局＋保密＋重播（P2）
     ───────────    規則單元測試（P1）            ▼ 多、最快
```

| 階段 | 必跑測試 | 對應文件 |
|---|---|---|
| P1 | 規則單元、輪替統計、L9–L24 | CODING_RULES T1–T3 |
| P2 | 機器人整局、保密全文搜尋、重播、不變式、SPEC D4 | T2、T4、T9 |
| P3 | API 整合、故障注入、效能基準 | T5、T6 |
| P4 | 多分頁手動、畫面同步自動比對、**真人試玩** | UI_RULES UT1 |
| P5 | 狂點、輸入、異常回饋 | UT2–UT4 |
| P6 | iOS／Android 實機 | SPEC B10 第 8 項、UT6 |
| P7 | 網路測試全套 | CODING_RULES 12.8 |
| P8 | 截圖比對、字級、舊手機幀率、色弱 | T8、T10、T11、ART 15 |
| P9 | 全部＋兩局真人試玩 | — |

**每次 commit 都要跑**：P1–P3 的自動化測試（CI）。**每階段結束跑**：該階段以前的全部測試。

---

## 6 需要使用者配合的事

| 階段 | 使用者要做的事 |
|---|---|
| P0 | 確認 GitHub 帳號 `chris0612qqq` 可建立公開 repo；在電腦安裝 Python 3.11+、Git、GitHub CLI 並執行 `gh auth login` |
| P3 | 執行 `python -m server.setup_admin` 設定管理員帳號密碼（之後由 `setup.bat` 代勞） |
| P4 | 找 5 位以上朋友試玩灰盒版一局並回饋 |
| P6 | 用自己的 iPhone 協助實機測試（加入主畫面、拍照、錄音、旁白） |
| P7 | 安裝 `cloudflared`；在 GitHub repo 的 Settings → Pages 把來源設為「GitHub Actions」；在家開 `start.bat`，請朋友用 4G 從外面連進來測試 |
| P8 | 看垂直切片並確認風格；（選擇性）用 AI 生成插圖放進 `local_assets/`（ART 14） |
| P9 | 安排一次正式試玩；出發前跑 `preflight.bat` |

---

## 7 進度紀錄範本（`PROGRESS.md`）

```markdown
# 進度

目前階段：P2 引擎、事件、模式、保密視圖、機器人整局
目前版本：0.2.0

## 階段狀態
| 階段 | 狀態 | 通關日期 | 備註 |
|---|---|---|---|
| P0 | ✔ 通關 | 2026-11-02 | |
| P1 | ✔ 通關 | 2026-11-05 | 覆蓋率 100% |
| P2 | ⏳ 進行中 | | 任務 4/6 |
| P3–P9 | ☐ | | |

## 本階段任務
- [x] events.py
- [x] engine.py 轉移表
- [x] modes.py
- [ ] timers.py（女巫最短時間未做）
- [ ] views.py
- [ ] bots

## 待使用者決定
- （無）

## 與 SPEC 的差異（已同步修改 SPEC 的請註明版本）
- （無）

## 已知問題
- （無）
```

---

## 參考
- 原型、垂直切片、里程碑的業界做法：[Vertical slice vs prototype](https://bugnet.io/blog/vertical-slice-vs-prototype-what-to-build-first)、[Milestones for indie game projects](https://bugnet.io/blog/milestones-for-indie-game-projects)、[Setting game development milestones](https://www.wayline.io/blog/setting-game-development-milestones-concept-launch)、[Game development process guide](https://rocketbrush.com/blog/game-development-process-guide)、[Unity production milestones](https://pctechmag.com/2026/06/unity-production-milestones-what-each-stage-should-deliver/)。

---

## 8 文件對照索引（每階段要對照的章節一覽）

| 階段 | SPEC | CODING_RULES | UI_RULES | ART_DIRECTION |
|---|---|---|---|---|
| P0 | B1、B2 | R12–R14、D5–D6、R6（FEATURES） | — | — |
| P1 | A5、A6、A5.7、A13、B4 | L9–L27、G7–G8、T1–T3 | — | — |
| P2 | A3、A7、A8、B4、B5、D4 | L1–L8、2.4、G1–G6、S1–S4、T4、T9、E15 | — | — |
| P3 | A4、A10、A11、B6–B8 | E1–E9、P1–P8、N5、N8、N13–N15、T5–T6 | Q10–Q11 | — |
| P4 | C3、C4、C8、C9 | G5–G6、M1–M4、V1–V4、V9 | U1–U14、UT1 | —（灰盒） |
| P5 | C8、A13、S26 | E10–E16、V5–V8、V12–V18 | K、F 全部、UT2–UT4、第 6 節 | — |
| P6 | A9、B9、C7、S23–S24 | E11、E15–E16、V12–V17、V20、N16–N18 | Q2、UT6 | 13（旁白） |
| P7 | B1、A11、A12 | 第 12 章 N1–N24、D7–D8、S8 | F1–F3 | — |
| P8 | C1、C2、C5、C6 | V5–V7、V10–V11、V11a、T8、T10–T11 | Q 全部 | 全文、第 15 節驗收 |
| P9 | 全部 | 第 8 節檢查表 | 第 6 節檢查表 | 第 15 節 |

## 9 變更紀錄
**v1.0 → v1.1**（與其他文件交叉核對）
| # | 修正 | 原因 |
|---|---|---|
| 1 | 機器人放在 `server/dev/bots.py`，測試與 DEV_MODE 共用 | 原本測試用一份、DEV_MODE 又要一份，重複 |
| 2 | 管理員設定改為 `python -m server.setup_admin`，`setup.bat` 呼叫它 | P3 就需要管理員帳號，但 `setup.bat` 到 P7 才做 |
| 3 | P4 灰盒不做 S23、S24（移到 P6）；註明區網 http 下相機、錄音等不能用 | 這兩個畫面依賴 PWA 與聲音，P4 做不出來 |
| 4 | P0 新增 `ci.yml` 與 `FEATURES` 功能開關；文件數改為五份 | SPEC B2 只有 `pages.yml`；功能開關在第 4 節提到卻沒有對應的規矩 |
| 5 | 版本號跟著階段走（`0.n.x`） | 與 CODING_RULES D6 對齊 |
| 6 | 使用者配合事項補「GitHub Pages 來源設為 Actions」 | 不設定的話 P7 部署會失敗 |
| 7 | 新增第 8 節文件對照索引 | 每階段一眼看出要對照哪些章節 |
