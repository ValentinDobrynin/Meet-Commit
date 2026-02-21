# 🧪 Meet-Commit Bot — Test Plan

**Last updated:** 21 February 2026  
**Tested:** 19 of 33 tests

---

## 📊 Test Status Summary

✅ **PASS:** 18 tests  
⚠️ **PARTIAL:** 1 test  
❌ **FAIL:** 0 tests  
⏳ **NOT TESTED:** 14 tests

---

## 📋 Basic Commands

### ✅ Test 1: /start [PASS]

**What:** Welcome message and user registration

**Steps:**
1. Send `/start`

**Expected:**
- Instant reply (< 1 sec)
- Message "🤖 Добро пожаловать в Meet-Commit!"
- Sections: умею, быстрый старт, команды, повестки, проверка качества
- No raw `<b>` HTML tags in text

**Result — 16.02.2026:**
```
✅ Instant response (1 sec)
✅ All sections present, correct formatting
✅ User registered in active_users.json
```

---

### ✅ Test 2: /help [PASS]

**What:** Full command reference

**Steps:**
1. Send `/help`

**Expected:**
- All categories: основные, создание коммитов, быстрые запросы, повестки, люди, review
- No raw `<b>` tags

**Result — 16.02.2026:**
```
✅ All categories present, HTML rendered correctly
✅ Admin commands referenced at the bottom
```

---

## 📝 Meeting Processing

### ✅ Test 3: .txt file upload [PASS]

**What:** Full pipeline — upload → summary → commits → Notion → tag review

**Steps:**
1. Upload a `.txt` transcript with 3–5 explicit tasks
2. Select style (Brief / Detailed / Structured)
3. Click "Пропустить" (or add a prompt note)
4. Wait 30–90 sec

**Expected:**
- Progress messages render bold (not raw `<b>`)
- Meeting card: clean title (no "02 19" prefix), correct date, participants, tags, Notion link
- Summary preview shown (no raw HTML in AI text)
- Commit stats: N created + M to review
- Tag review buttons appear after processing

**Result — 21.02.2026:**
```
✅ All progress messages bold, no raw tags
✅ Title: "test meeting for test3" (no timestamp prefix)
✅ Date: 21.02.2026
✅ 6 commits total: 3 direct + 3 to Review Queue
✅ Review Queue showed and Confirm All worked
✅ No raw HTML anywhere
Note: Маша/Глеб not in people.json → unknown participants expected
```

---

### ✅ Test 4: PDF format [PASS]

**What:** PDF file extracted and processed identically to .txt

**Steps:**
1. Upload a `.pdf` meeting transcript
2. Select style, click Пропустить

**Expected:**
- Text extracted from PDF
- Pipeline identical to .txt (summary, commits, Notion)

**Result — 21.02.2026:**
```
✅ PDF text extracted correctly
✅ Title, date, summary, commits — all correct
✅ No errors specific to PDF format
Still to test: .docx and .vtt
```

---

### ✅ Test 5: Plain text (no file) [PASS]

**What:** Bot processes pasted text without file attachment

**Steps:**
1. Copy meeting notes
2. Paste text directly into chat (no attachment)

**Expected:**
- Bot shows style selection buttons
- Processing identical to file upload

**Result — 21.02.2026:**
```
✅ Bot showed style buttons after plain text input
✅ Meeting saved to Notion as expected
```

---

### ⏳ Test 4b: DOCX format [NOT TESTED]

**What:** .docx file parsed correctly

**Steps:**
1. Upload a `.docx` transcript

**Expected:**
- Text extracted (all paragraphs)
- Processing identical to .txt

---

### ⏳ Test 4c: VTT format [NOT TESTED]

**What:** Zoom/Teams subtitle file (.vtt / .webvtt) parsed correctly

**Steps:**
1. Upload a `.vtt` subtitle file from Zoom or Teams

**Expected:**
- Timestamps stripped, only dialogue text kept
- Processing identical to .txt
- Participants detected from speaker names

---

## 📝 Task Creation

### ✅ Test 6: /commit interactive [PASS]

**What:** 4-step FSM dialog for manual task creation

**Steps:**
1. Send `/commit`
2. Step 1 — Enter task text (free text)
3. Step 2 — Select заказчик (who assigned the task) via buttons or type name
4. Step 3 — Select исполнитель (assignee) via buttons or type name
5. Step 4 — Select deadline via buttons (сегодня / эта неделя / ...) or type date

**Expected:**
- Each step shows buttons + manual input option
- Final commit saved to Notion Commits DB
- Correct direction: "mine" if Valya is assignee, "theirs" otherwise

**Result — 21.02.2026:**
```
✅ All 4 steps worked (confirmed via Render logs)
✅ Task: "Сделать презентацию для инвесторов в Заливе"
   from Dima Dorokhin → to Sasha Katanov, due 2026-03-06
✅ Direction: theirs
✅ Saved to Notion (Direct Commits meeting)
Note: intermediate steps use edit_text → only final card visible in chat
```

---

### ✅ Test 7: /llm [PASS]

**What:** Natural language task creation via AI

**Steps:**
1. Send: `/llm Леша Козлов расскажет про Сплит в Еде до конца марта`

**Expected:**
- AI extracts: assignee, customer, deadline, direction
- Relative dates use current year (2026)
- Saved instantly to Commits DB

**Result — 21.02.2026:**
```
✅ Assignee: Lesha Kozlov (extracted from name in text)
✅ Customer: Valya Dobrynin
✅ Due: 31.03.2026 (correct year after fix)
✅ Tags: contextual
```

---

## 🔍 Search & Filtering

### ✅ Test 8: /mine [PASS]

**What:** Shows tasks where current user is assignee

**Steps:**
1. Send `/mine`

**Expected:**
- Shows list of user's tasks, or "📭 Ничего не найдено"
- Each task shows short_id, text, assignee, deadline

**Result — 16.02.2026:**
```
✅ "📭 Мои задачи (все) — Ничего не найдено"
✅ Correct (no tasks assigned to Valya at that point)
```

---

### ✅ Test 9: /due [PASS]

**What:** Shows commits with deadlines in the next 7 days

**Date:** 21.02.2026, 16:12

**Steps:**
1. Send `/due`

**Expected:**
- Shows only tasks due within 7 days
- Sorted by date ascending

**Result:**
```
✅ "📋 Дедлайны на неделю — найдено: 1 коммитов"
✅ Showed: "подготовить презентацию для совета директоров"
   due: 27.02.2026 — correct (within 7 days from 21.02)
✅ Tags shown inline
✅ Assignee shown (— for unassigned)
```

---

### ✅ Test 10: /by_tag [PASS]

**What:** Filter commits by tag

**Date:** 21.02.2026, 16:30

**Steps:**
1. Send `/by_tag finance`

**Expected:**
- Shows commits with tag `finance`
- "Ничего не найдено" for unknown tags

**Result:**
```
✅ "📋 Коммиты с тегом 'finance' — найдено: 1 коммитов"
✅ Showed: "подготовить цифры для финализации"
   Assignees: Nodari Kezua, Sergey Lompa | Tags: 15 total
✅ Format correct: text, заказчик, теги, исполнитель, статус, срок, ID

⚠️ Discrepancy vs /agenda_tag:
   /by_tag finance → 1 result
   /agenda_tag finance → 16 results
   Reason: /by_tag queries Commits DB by tag field.
   /agenda_tag returns all commits FROM meetings tagged finance
   (tag may be on the meeting, not inherited by all its commits).
   Expected behavior — both commands serve different purposes.
```

---

### ⏳ Test 10b: /by_assignee [NOT TESTED]

**What:** Shows all commits for a specific person

**Steps:**
1. Create several tasks for Sasha: `/llm Саша сделает А`, `/llm Саша сделает Б`
2. Send `/by_assignee Саша`

**Expected:**
- Shows commits where Sasha is assignee
- Works with alias "Саша" resolving to canonical name

---

## 📊 Agendas

### ✅ Test 11: /agenda_person [PASS]

**What:** Generates a personal agenda for a specific person

**Date:** 21.02.2026, 16:13

**Steps:**
1. Send `/agenda_person Lesha Kozlov`

**Expected:**
- Tasks grouped: as customer (заказчик) + as assignee (исполнитель)
- Shows deadlines, assignees
- Saved to Agendas DB

**Result:**
```
✅ "👤 Повестка — Lesha Kozlov"
✅ Stats: 📋 Заказчик: 16 | 📤 Исполнитель: 1
✅ Section "Задачи от Lesha Kozlov (заказчик)": 16 tasks listed
✅ Section "Задачи для Lesha Kozlov (исполнитель)": 1 task
✅ Each task shows: text, assignee, deadline
✅ Timestamp: "Сгенерировано: 21.02 13:14 UTC"

Note: Some tasks show dates 2025-03-31 and 2025-10-02 —
these are old test tasks created before the /llm date bug was fixed.
Not a bot issue; will clear up as old test data is removed.
```

---

### ⏳ Test 12: /agenda interactive [NOT TESTED]

**What:** Interactive agenda creation via FSM buttons

**Steps:**
1. Send `/agenda`
2. Select type: 👤 Персональная / 🏢 Для встречи / 🏷️ Тематическая
3. Enter the parameter (name / meeting ID / tag)

**Expected:**
- Bot asks for type via buttons
- After selection asks for the parameter
- Generates and saves agenda

---

### ✅ Test 12b: /agenda_tag [PASS]

**What:** Topic-based agenda by tag

**Date:** 21.02.2026, 16:14

**Steps:**
1. Send `/agenda_tag finance`

**Expected:**
- Active tasks with tag `finance`
- Completed tasks (last week)
- Saved to Agendas DB

**Result:**
```
✅ "🏷️ Повестка — finance"
✅ Stats: 📋 Заказчик: 16 | ✅ Выполнено: 5
✅ Section "Активные задачи по finance": 16 tasks
✅ Section "Выполнено за неделю": 5 tasks shown
   Including: "предоставить актуальные данные для презентации", "написать напоминание Яндексу"
✅ Timestamp shown

Note: 16 active tasks tagged finance — matches the test data created during testing.
Old tasks with 2025 dates visible; will clean up as test data is removed.
```

---

## 🔍 Review Queue

### ✅ Test 13: Review Queue receives low-confidence commits [PASS]

**What:** Decision commits and tasks without clear assignee go to Review

**Steps:**
1. Upload a meeting with declarative decisions ("решили", "договорились")
2. Check `/review`

**Expected:**
- Decision commits appear in queue with flags=[decision], confidence≈0.6
- Regular commits with known assignees go directly to Commits

**Result — 21.02.2026:**
```
✅ 2 decision commits correctly sent to Review Queue
✅ "Confirm All" button shown
```

---

### ✅ Test 14: Confirm All [PASS]

**What:** Bulk confirm moves all items from Review to Commits

**Steps:**
1. Open `/review` (or it appears automatically after meeting processing)
2. Click "✅ Confirm All"

**Expected:**
- All items confirmed
- Each gets status "resolved" + linked commit ID
- Queue becomes empty
- "📋 Review queue пуста." message shown

**Result — 21.02.2026:**
```
✅ Both items confirmed and saved
✅ Queue emptied correctly
```

---

### ⏳ Test 15: /assign via button [NOT TESTED]

**What:** Assign an executor to a Review Queue item via interactive buttons

**Steps:**
1. Open `/review`
2. Click "✏️ Assign" under any item
3. Select a person from the list of buttons

**Expected:**
- Bot shows person selection keyboard
- After click: "✅ [id] Assignee → Name"
- Item updated in Notion Review DB

---

### ⏳ Test 15b: /confirm single item [NOT TESTED]

**What:** Confirm a single Review Queue item by ID

**Steps:**
1. Open `/review`, note a short_id (e.g. `a1b2c3`)
2. Send `/confirm a1b2c3`

**Expected:**
- "[a1b2c3] Коммит подтвержден"
- Item moves to Commits DB with status resolved

---

### ⏳ Test 15c: /delete review item [NOT TESTED]

**What:** Drop a Review Queue item that is not a real task

**Steps:**
1. Open `/review`
2. Click "❌ Delete" or send `/delete a1b2c3`

**Expected:**
- Item status set to "dropped"
- Disappears from `/review`

---

## 👥 People Management

### ✅ Test — People auto-detection [PASS]

**What:** People Miner adds name candidates from transcripts automatically

**Date:** 18–21.02.2026

**Result:**
```
✅ 43–56 candidates added per meeting
✅ System detects new names in transcript text
```

---

### ⏳ Test 16: /people_miner2 [NOT TESTED]

**What:** Interactive verification of new name candidates

**Steps:**
1. Process a meeting with new participants (e.g. Gleb, Маша)
2. Send `/people_miner2`

**Expected:**
- Cards shown for unverified candidates
- Each card: alias, frequency, context snippet
- Buttons: [✅ Одобрить] [✏️ Указать EN имя] [❌ Отклонить]
- After approve: person added to people.json, detected in future meetings
- After reject: alias added to stopwords

---

### ⏳ Test 17: /people_stats_v2 [NOT TESTED]

**What:** Statistics about the people dictionary

**Steps:**
1. Send `/people_stats_v2`

**Expected:**
- Total people in dictionary
- Candidates pending verification
- Top candidates by frequency
- Stopwords count

---

## 🧹 Admin Functions

### ⏳ Test 20: /tags_stats [NOT TESTED]

**What:** Tagging system statistics (admin only)

**Steps:**
1. Send `/tags_stats`

**Expected:**
- Tagging mode (both/v0/v1)
- Rules count
- Min score threshold
- Cache hit rate
- "❌ Команда доступна только администраторам" for non-admins

---

### ⏳ Test 21: /webhook_status [NOT TESTED]

**What:** Webhook health monitoring (admin only)

**Steps:**
1. Send `/webhook_status`

**Expected:**
- Current webhook URL
- Pending updates count (should be 0)
- Last error (should be None)
- IP address and max connections

---

### ⏳ Test 21b: /webhook_reset [NOT TESTED]

**What:** Reinstall webhook if problems arise

**Steps:**
1. Send `/webhook_reset`

**Expected:**
- "🔄 Переустанавливаю webhook..."
- "✅ Webhook успешно переустановлен"

---

## 🚨 Edge Cases

### ⏳ Test 22: Empty file [NOT TESTED]

**What:** Empty file handled without crash

**Steps:**
1. Create an empty `empty.txt`
2. Upload to bot

**Expected:**
- Bot handles gracefully (no 500 error)
- Either: error message "файл пустой"
- Or: meeting created with empty content

---

### ⏳ Test 23: Very long transcript [NOT TESTED]

**What:** Processing doesn't timeout on large files

**Steps:**
1. Create a file with 5,000+ words (paste transcript multiple times)
2. Upload and select Brief

**Expected:**
- Processing completes (may take 2–3 min)
- No timeout error
- Summary generated

---

### ⏳ Test 24: Filename without recognizable date [NOT TESTED]

**What:** Date falls back to upload date when not in filename or content

**Steps:**
1. Create `random_name_no_date.txt` with content that has no dates
2. Upload

**Expected:**
- Date = today's date
- No "—" shown in meeting card

---

### ⏳ Test 25: Unknown person in /llm [NOT TESTED]

**What:** Name not in dictionary → preserved as-is, added to candidates

**Steps:**
1. Send `/llm Незнакомый Человек сделает задачу`

**Expected:**
- Commit created with assignee "Незнакомый Человек"
- Name appears in `/people_miner2` candidates

---

## 🔄 Persistence & Infrastructure

### ✅ Test 26: Redis FSM persistence [PASS]

**What:** FSM state survives container restarts

**Result — 07.02.2026:**
```
✅ Redis connected on startup: "🔄 Using Redis storage for cloud mode"
✅ States persist between restarts
```

---

### ⏳ Test 27: FSM state preserved across messages [NOT TESTED]

**What:** /commit state survives if user pauses between steps

**Steps:**
1. Start `/commit`, enter text (Step 1)
2. Close Telegram for 5 minutes
3. Re-open and continue with Step 2

**Expected:**
- Bot resumes from Step 2, remembers text from Step 1
- Completes successfully

---

### ⏳ Test 28: Response time [NOT TESTED]

**What:** Simple commands respond quickly

**Steps:**
1. Send `/mine` and time the response
2. Send `/due` and time the response

**Expected:**
- `/mine`, `/due` < 3 sec (Notion query)
- `/start`, `/help` < 1 sec

---

### ⏳ Test 29: Sequential commands [NOT TESTED]

**What:** Bot handles rapid-fire commands without errors

**Steps:**
1. Quickly send: `/mine`, `/due`, `/commits`, `/review`, `/help` in sequence

**Expected:**
- All 5 respond correctly
- No 500 errors
- Order preserved

---

### ⏳ Test 30: Recovery after deploy [NOT TESTED]

**What:** Bot automatically reconfigures webhook after redeploy

**Steps:**
1. Trigger Manual Deploy in Render Dashboard
2. Wait for completion (~3 min)
3. Send `/start`

**Expected:**
- Bot responds immediately after deploy
- Startup greetings sent to active users
- Webhook auto-configured

---

## 🎨 Advanced Features

### ⏳ Test 31: Meeting deduplication [NOT TESTED]

**What:** Same file uploaded twice → no duplicate in Notion

**Steps:**
1. Upload `transcript.txt` and process it
2. Upload the **same file** again

**Expected:**
- Second upload detected as duplicate
- Message: "⚠️ Встреча с таким содержимым уже обработана"
- Link to existing meeting shown
- No new entry in Meetings DB

---

### ⏳ Test 32: Tag inheritance [NOT TESTED]

**What:** Meeting tags are inherited by its commits

**Steps:**
1. Upload a finance meeting (auto-tagged: `finance/budgets`)
2. Check the generated commits in Notion

**Expected:**
- Commits have same tags as the parent meeting
- Filtering `/by_tag finance` returns both meetings and their commits

---

### ⏳ Test 33: Name transliteration [NOT TESTED]

**What:** Russian aliases map to canonical English names

**Steps:**
1. Create tasks using Russian aliases:
   ```
   /llm Саша сделает А
   /llm Маша сделает Б
   /llm Петя сделает В
   ```
2. Check Commits in Notion
3. Try `/by_assignee Саша`

**Expected:**
- Notion stores canonical names (Alexander, Maria, Petr)
- `/by_assignee Саша` returns same results as `/by_assignee Alexander`

---

## 📊 Final Checklist

### Critical (must work):
- [x] /start shows welcome
- [x] /help shows commands
- [x] File upload and full processing pipeline
- [x] AI summarization works
- [x] Commits extracted from explicit tasks
- [x] Commits extracted from decisions ("решили/договорились")
- [x] Saved to Notion
- [x] /mine responds correctly
- [x] /commit 4-step FSM works
- [x] /llm creates task with correct date
- [x] Review Queue receives low-confidence commits
- [x] Confirm All moves items to Commits

### Important (test next):
- [x] /due — deadlines this week (Test 9)
- [x] /agenda_person (Test 11)
- [x] /agenda_tag (Test 12b)
- [x] /by_tag — filter by tag (Test 10)
- [ ] /assign via button in Review (Test 15)
- [ ] /people_miner2 — verify new people (Test 16)
- [ ] DOCX format (Test 4b)
- [ ] VTT format (Test 4c)

### Advanced:
- [ ] Meeting deduplication (Test 31)
- [ ] Tag inheritance on commits (Test 32)
- [ ] FSM state after reconnect (Test 27)
- [ ] /tags_stats, /webhook_status (Tests 20–21)

---

## 🐛 Bugs Found & Fixed During Testing

| # | Bug | Fixed | Date |
|---|-----|-------|------|
| 1 | `bytes is not JSON serializable` in Redis FSM | ✅ base64 encoding | 17.02 |
| 2 | "Нет входных данных" after file upload | ✅ key `raw_bytes_b64` | 17.02 |
| 3 | `<future>` HTML parse error in summary | ✅ `html.escape()` + `parse_mode=None` | 18-19.02 |
| 4 | Default `parse_mode=HTML` causing crashes | ✅ Removed from Bot init | 19.02 |
| 5 | Date showing "—" in meeting card | ✅ meta key was "meeting_date" → "date" | 20.02 |
| 6 | `🔍 <b>Обрабатываю коммиты...</b>` raw HTML | ✅ Added `parse_mode="HTML"` | 20.02 |
| 7 | Title showing "02 19 Название встречи" | ✅ Timestamp prefix strip regex | 21.02 |
| 8 | 0 commits for decision-only meetings | ✅ Decision pattern added to prompt | 21.02 |
| 9 | Raw HTML in Review confirm messages | ✅ `parse_mode="HTML"` in handlers_inline.py | 21.02 |
| 10 | /llm: "до конца марта" → 2025 instead of 2026 | ✅ `{TODAY}` placeholder in llm_parse_ru.md | 21.02 |
