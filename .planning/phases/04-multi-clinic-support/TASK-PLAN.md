# Phase 04 實作計畫：多診所支援

> 給執行者（Antigravity）：本文件是完整實作規格，涵蓋 Phase 04 的 TASK-00 與
> TASK-01（TASK-02、TASK-03 不在本次範圍，見文末說明）。完成後請勿自行
> commit — 交回使用者，由 Claude（此計畫作者）驗證後再決定是否提交。
> 請先讀過 `AGENTS.md`（專案根目錄）、`.planning/HANDOFF.json`、
> `.planning/phases/04-multi-clinic-support/PLAN.md`（本文件的背景與使用者
> 決策），理解既有規範後再開始。

## 背景（已盤點程式碼確認，非假設）

`clinic_info`/`clinic_hours`/`clinic_custom_notes` 三張表已經有 `clinic_id`
欄位設計，但 `page_index_trees` **完全沒有 `clinic_id` 欄位**——診所身份只靠
`doc_id` 字串前綴（如 `zhiyan-clinic-hifu-lifting`）表達，而且解析這個前綴的
地方是硬編碼字串比對：

```python
# src/pageindex/prompt_template.py:37
_FEW_SHOT_DOC_IDS = ("zhiyan-clinic-botox-injection", "zhiyan-clinic-hifu-lifting")

# src/pageindex/prompt_template.py:47
procedure_name = tree["doc_id"].replace("zhiyan-clinic-", "")
```

`src/query/search.py` 的 `search_page_index_trees()` 也**完全沒有 clinic 過濾**
——目前查詢會回傳資料庫裡**所有診所**的療程樹，這在只有 1 家診所時看不出問題，
但技術上已經是個等多診所上線就會立刻爆炸的 bug。

另外盤點確認：`clinic_info` 目前只有 1 筆資料（`zhiyan-clinic` / 緻妍外科診所），
但**這筆資料在整個 repo 裡找不到任何 seed 腳本寫入它**（`scripts/seed_database.py`
只有 `SELECT COUNT(*) FROM clinic_info` 做統計，沒有 INSERT）——代表這筆資料是
之前某次 session 手動寫入正式 `clinic.db` 的，版控裡沒有留下可重建它的腳本。
這是本計畫 TASK-01 會一併補上的既有缺口（見 TASK-01 最後一項）。

現有 6 筆 `page_index_trees` 資料狀態（2026-09-22 實測）：

```
doc_id                                    category  source_type
zhiyan-clinic-laser-skin-resurfacing      special   manual
zhiyan-clinic-botox-injection             special   manual
zhiyan-clinic-electrowave-facelift        special   manual
zhiyan-clinic-hyaluronic-acid-filler      special   manual
zhiyan-clinic-fractional-laser            special   manual
zhiyan-clinic-hifu-lifting                special   manual
```

（Phase 02 端到端驗證生成的 3 筆新療程樹只存在於隔離測試複本，從未寫入正式
`clinic.db`，不在本次遷移範圍內，可忽略。）

## 目標

1. `page_index_trees` 新增真正的 `clinic_id` 欄位，`doc_id` 改為不含診所前綴
   的純療程 slug
2. 現有 6 筆資料與 `clinic_info`/`clinic_hours`/`clinic_custom_notes` 的
   `clinic_id` 值，從 `'zhiyan-clinic'` 遷移成台灣健保特約醫事機構代碼
   `'3503190424'`
3. 補上 `clinic_info` 目前缺失的種子腳本（讓正式資料庫可以從零重建，不再只
   活在手動寫入的既有 `clinic.db` 裡）
4. `search_page_index_trees()` 補上 `clinic_id` 過濾，修掉「查詢會回傳所有
   診所資料」這個技術上已存在、只是尚未爆炸的 bug

## 具體任務

### TASK-00：`page_index_trees` 補 `clinic_id` 欄位 + `doc_id` 去前綴化

**1. Schema 變更**（`src/db/clinic_schema.sql`）

在 `page_index_trees` 的 CREATE TABLE 裡新增一欄（放在 `doc_id` 之後、
`category` 之前，緊鄰著放合理）：

```sql
clinic_id TEXT REFERENCES clinic_info(clinic_id),  -- 所屬診所（2026-09-22
                                                     -- Phase 04 新增；原本
                                                     -- 診所身份只靠 doc_id
                                                     -- 字串前綴表達，是技術債）
```

SQLite 的 `ALTER TABLE ... ADD COLUMN` 語法可以直接加欄位不需要重建整張表
（`clinic.db` 正式環境用這個方式遷移，比重建整張表安全）。**schema.sql 本身**
也要同步更新 CREATE TABLE 語句（讓從零建庫時就有這個欄位），兩處都要改，
不要只改其中一處。

**2. 資料遷移邏輯**（新增一個一次性遷移腳本，例如
`scripts/migrate_pageindex_clinic_id.py`，或視你認為更合理的位置放置）

對現有 6 筆資料執行：
- `clinic_id` 欄位填入 `'zhiyan-clinic'`（先用舊值，TASK-01 才會再改成
  代碼——**不要在同一步驟同時做兩件事**，先把欄位加上並填入正確關聯，
  再交給 TASK-01 統一處理值的變更，這樣任何一步出錯都比較好定位）
- `doc_id` 去掉 `zhiyan-clinic-` 前綴（如 `zhiyan-clinic-hifu-lifting` →
  `hifu-lifting`）

**這個腳本必須是冪等的**（重複執行不會出錯或重複改動已經遷移過的資料），
且比照 `db_writer.py`/`seed_trees.py` 一貫風格，遷移前後印出筆數與內容供人工
核對。

**3. 程式碼同步修改**

- `src/pageindex/seed_trees.py`：
  - `CLINIC_ID = "zhiyan-clinic"` 常數保留（TASK-01 才改值），但**用途改變**
    ——不再用來組 `doc_id` 前綴字串（`f"{CLINIC_ID}-{procedure}"` 這種寫法
    要移除），改成填入 `TREES` 列表裡每筆資料新增的 `"clinic_id": CLINIC_ID`
    欄位
  - 6 筆 `TREES` 資料的 `doc_id` 全部改成純療程 slug（去掉
    `f"{CLINIC_ID}-"` 前綴），例如
    `"doc_id": f"{CLINIC_ID}-hifu-lifting"` → `"doc_id": "hifu-lifting"`
  - 每筆資料新增 `"clinic_id": CLINIC_ID` 欄位

- `src/pageindex/db_writer.py`：
  - `CONTENT_FIELDS` 元組**不要**加入 `clinic_id`（`CONTENT_FIELDS` 語意是
    「內容變更比對用的欄位」，`clinic_id` 屬於身份欄位不是內容欄位，混進去
    會導致「clinic_id 換了但內容沒換」被誤判成內容變更、無謂遞增
    `content_version`）
  - `upsert_trees()` 的 INSERT 與 UPDATE 語句都要新增 `clinic_id` 的讀寫
    （INSERT 時寫入 `tree["clinic_id"]`；UPDATE 時**不要**覆寫
    `clinic_id`——同一個 `doc_id` 對應的診所不應該在更新時被靜默換掉，這種
    改動應該是明確的操作而非附帶效果。若 `tree` dict 裡沒有 `clinic_id`
    鍵，呼叫端應該拋出明確錯誤而非用 `None`/空字串靜默寫入，避免製造出
    「診所不明」的孤兒資料）

- `src/pageindex/prompt_template.py`：
  - `_FEW_SHOT_DOC_IDS = ("zhiyan-clinic-botox-injection", "zhiyan-clinic-hifu-lifting")`
    改成純療程 slug：`_FEW_SHOT_DOC_IDS = ("botox-injection", "hifu-lifting")`
  - `_few_shot_examples()` 函式裡的
    `procedure_name = tree["doc_id"].replace("zhiyan-clinic-", "")` 這行
    整行移除，改成 `procedure_name = tree["doc_id"]`（doc_id 已經是純療程名，
    不需要再解析）
  - `to_upsert_row(doc_id: str, category: str, tree: GeneratedTree) -> dict`
    的函式簽章新增 `clinic_id: str` 參數（建議放在 `doc_id` 後面），回傳的
    dict 新增 `"clinic_id": clinic_id` 鍵。**呼叫端** `generate_tree()` 本身
    不需要改（它不知道 clinic_id，是 `to_upsert_row()` 組裝最終寫入格式時
    才需要），但任何呼叫 `to_upsert_row()` 的地方（包含 Phase 02
    `scripts/e2e_phase02_generation.py` 若還會被重跑）要記得補上新參數

- `src/query/search.py`：
  - `search_page_index_trees()` 新增 `clinic_id` 參數（型別 `str | None`，
    預設 `None` 代表不過濾、維持向後相容），有值時在 SQL 查詢加上
    `AND clinic_id = ?` 條件（trigram FTS 分支與 LIKE fallback 分支都要加，
    不要只改其中一支）。這是修掉「查詢回傳所有診所資料」這個既有 bug 的
    必要修改，屬於本 TASK 範圍內（跟 doc_id 遷移同一批改動，理由一致：
    沒有 `clinic_id` 欄位就沒辦法做這個過濾）
  - 呼叫端（`src/query/router.py` 的 `handle_query()` 等）**是否要立刻傳入
    `clinic_id` 並強制過濾**，留給 TASK-01/TASK-02 決定（因為那涉及要不要
    移除函式預設值這個 Phase 04 PLAN.md 裡還沒定案的問題）——本 TASK 只要
    確保 `search_page_index_trees()` 這個底層函式**有能力**過濾即可，不用
    在這裡動 router.py

**4. 測試更新**

現有 pytest 測試裡任何硬編碼舊 `doc_id`（`zhiyan-clinic-*`）字串的地方都要
同步改成新的純 slug 格式（先用 `grep -rn "zhiyan-clinic-" tests/` 找出所有
位置，逐一確認是否受影響）。新增至少以下測試案例：
- `upsert_trees()` 在 `tree` dict 缺少 `clinic_id` 鍵時，正確拋出錯誤（而非
  靜默寫入 `None`）
- `upsert_trees()` 對已存在的 `doc_id` 執行 UPDATE 時，`clinic_id` 值維持
  不變（驗證「更新不應該連帶改變診所歸屬」這條規則有真的生效）
- `search_page_index_trees(clinic_id=...)` 傳入值時只回傳該診所的資料；不傳
  （`None`）時回傳所有診所資料（向後相容行為）

### TASK-01：`clinic_id` 值遷移為健保代碼 + 補齊種子腳本

**這個任務依賴 TASK-00 先完成**（要先有欄位，才能遷移欄位裡的值）。

**1. 資料值遷移**

把資料庫裡所有 `clinic_id = 'zhiyan-clinic'` 的列（`clinic_info`、
`clinic_hours`、`clinic_custom_notes`，以及 TASK-00 新增的
`page_index_trees.clinic_id`）改成 `clinic_id = '3503190424'`。

用一個遷移腳本（可以和 TASK-00 的遷移腳本合併成同一支、分兩個明確步驟執行，
或分成獨立第二支腳本——你判斷哪種對後續維護更清楚），對四張表逐一執行
`UPDATE ... SET clinic_id = '3503190424' WHERE clinic_id = 'zhiyan-clinic'`，
執行前後印出各表受影響筆數供核對。**這個腳本也必須是冪等的。**

**2. 補齊 `clinic_info` 種子腳本（既有缺口）**

盤點發現 `clinic_info` 的那 1 筆資料（緻妍外科診所）在整個 repo 裡找不到任何
寫入它的腳本，是先前某次 session 手動寫入正式 `clinic.db` 的。既然這次要動
它的 `clinic_id` 值，順便把它納入可重建的種子流程，比照 `seed_trees.py` 對
`page_index_trees` 的模式，在合理位置（例如新增
`src/pageindex/seed_clinic_info.py`，或併入 `scripts/seed_database.py`，
你判斷哪個更符合現有專案結構慣例）補上：

```python
CLINIC_ID = "3503190424"  # 緻妍外科診所，台灣健保特約醫事機構代碼

def seed_clinic_info(conn):
    """INSERT OR IGNORE / UPSERT clinic_info 的那 1 筆診所基本資料。"""
    ...
```

**寫入方式必須是 UPSERT 或 `INSERT OR IGNORE`，不能是無條件 INSERT**（否則
重跑會違反 `clinic_info.clinic_id` 的 PRIMARY KEY 約束而報錯）。從
現有正式 `clinic.db` 的 `clinic_info` 表讀出目前那 1 筆完整內容（name/
phone/address/website/opening_date/clinic_type）作為種子資料的來源，
不要憑空編造。

**3. 程式碼中殘留的 `'zhiyan-clinic'` 字面值**

`src/pageindex/seed_trees.py` 的 `CLINIC_ID = "zhiyan-clinic"` 這行改成
`CLINIC_ID = "3503190424"`（TASK-00 已經把這個常數的用途改成填入
`clinic_id` 欄位而非組字串前綴，這裡只是換值）。

5 個函式的 `clinic_id: str = "zhiyan-clinic"` 預設值（`src/query/router.py`
4 處、`src/clinic/custom_notes.py` 2 處）**是否要一併改成 `"3503190424"`，
或乾脆移除預設值改成必填參數**——這是 Phase 04 PLAN.md 目前仍標記為
「待確認」的獨立問題，**不屬於本次 TASK-01 範圍**，維持原樣即可（換句話說，
遷移完成後這幾個預設值會變成「預設值指向一個資料庫裡已經不存在的舊
clinic_id」這種暫時性的不一致，這是已知且刻意留到下次決策的狀態，不要在
本任務自行決定順手改掉）。

**4. 測試更新**

`tests/test_router.py:124` 的
`assert res.clinic_info["clinic_id"] == "zhiyan-clinic"` 以及
`tests/test_custom_notes.py` 裡出現的 `"zhiyan-clinic"` 字面值，全部改成
`"3503190424"`。執行前先 `grep -rn "zhiyan-clinic" tests/` 確認改全，不要
漏改。

## CONSTRAINT（必須遵守，違反視為交付無效）

1. **絕對禁止在任何輸出、註解、commit 訊息中出現簡體中文**。全部繁體中文。
2. **絕對不能讓本任務的測試/驗證過程寫壞正式 `clinic.db`**——所有遷移腳本的
   開發與測試階段都必須先在 `clinic.db` 的複本（`shutil.copy2()`）上跑過、
   確認結果正確後，才能對正式 `clinic.db` 執行一次。Claude 驗收時會檢查
   遷移前後的資料內容是否符合預期（不是要求 hash 不變，這次任務本來就要
   改資料——但要確認**只有**該改的欄位/值變了，其餘部分沒有意外變動）。
3. **TASK-00 必須先於 TASK-01 完成**，不可顛倒或合併成一步跳過中間驗證。
4. `CONTENT_FIELDS`（`db_writer.py`）不得把 `clinic_id` 加進去——這會混淆
   「內容變更」與「身份欄位」兩種語意，見 TASK-00 說明。
5. `upsert_trees()` 的 UPDATE 分支不得覆寫既有列的 `clinic_id`——同一
   `doc_id` 換診所必須是明確操作，不是更新內容時的副作用。
6. 不要修改 Phase 01/02 已完成的查詢邏輯以外的部分（`src/query/router.py`
   的 5 個函式預設值本次不動，見 TASK-01 說明）、不要順手處理 Phase 04
   PLAN.md 裡標記為獨立待確認的問題。
7. `src/db/clinic_schema.sql` 與正式 `clinic.db` 的 schema 必須同步（改了
   一處沒改另一處，會導致「從零建庫」跟「用現有 db 遷移」兩條路徑產生的
   schema 不一致，這正是 `AGENTS.md` 開頭強調的唯一權威來源原則）。
8. Phase 01 既有的 100 個 pytest 測試套件（含 Phase 02 新增的 9 個）不應該
   因為本次改動而失敗（doc_id/clinic_id 字面值的測試斷言更新除外，這些是
   預期要跟著改的，不算回歸）。交付前請重新執行 `pytest tests/` 確認全數
   仍然通過。

## 驗收標準（交付時請附上以下驗證結果）

1. `src/db/clinic_schema.sql` 修改後的 `page_index_trees` CREATE TABLE 完整
   內容（含新增的 `clinic_id` 欄位）。
2. 遷移腳本執行前後，四張表（`clinic_info`/`clinic_hours`/
   `clinic_custom_notes`/`page_index_trees`）的 `clinic_id` 欄位值與
   `page_index_trees.doc_id` 值的完整列表對照（遷移前 vs 遷移後）。
3. `clinic_info` 種子腳本的完整內容，以及「先清空/用新複本從零建庫、跑
   這個種子腳本、確認 `clinic_info` 內容與正式 `clinic.db` 現有那 1 筆資料
   完全一致」的驗證結果。
4. `search_page_index_trees()` 修改後的完整函式內容，附上「傳入
   `clinic_id='3503190424'` 只回傳該診所資料」與「不傳 `clinic_id` 回傳全部
   資料（向後相容）」兩種情境的實際查詢結果。
5. 執行 `pytest tests/` 的完整輸出，確認全數通過，並列出哪些測試斷言因為
   `doc_id`/`clinic_id` 字面值變更而被同步修改（附修改前後對照）。
6. 遷移在正式 `clinic.db` 上執行前後，非相關資料（drugs/service_items/
   FTS5 索引筆數等）確認沒有意外變動。
7. 交付時附上簡短說明：遷移腳本放在哪裡、是否為冪等設計（附上「重複執行
   第二次」的驗證結果）、`db_writer.py`/`prompt_template.py`/
   `seed_trees.py` 的具體改動摘要。

## 不在本任務範圍內（請勿順手處理）

- Phase 04 PLAN.md 的 TASK-02（5 個函式的 `clinic_id` 預設值是否移除）——
  獨立待確認問題，本任務不決定、不改動
- Phase 04 PLAN.md 的 TASK-03（查詢入口的 `clinic_id` 解析，依賴 Phase 05）
- `src/query/router.py`/`src/clinic/custom_notes.py` 的 `clinic_id` 預設值
  字面值本身（維持指向已遷移走的舊值，是刻意留下的已知暫時狀態）
- Phase 03（文件擷取管線）、`faq_cache` 相關任何程式碼
- OTC 本地化、查詢路由分類邏輯、FTS5 schema 本身（trigram tokenizer 等）
  ——本任務只新增一個欄位、不改動既有 FTS5 虛擬表定義

這是本專案一貫的做法，請避免越界，讓 Phase 04 的第一批任務乾淨收尾。
