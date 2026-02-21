# 🧪 Meet-Commit Bot — Test Plan

**Last updated:** 21 February 2026  
**Tested:** 14 of 33 tests

---

## 📊 Test Status Summary

✅ **PASS:** 13 tests  
⚠️ **PARTIAL:** 1 test  
❌ **FAIL:** 0 tests  
⏳ **NOT TESTED:** 19 tests

---

## 📋 Basic Commands

### ✅ Test 1: /start command [PASS]

**What we check:** Welcome message and user registration

**Date:** 16.02.2026, 15:56

**Steps:**
1. Open bot in Telegram
2. Send `/start`

**Expected:**
- Bot replies instantly (< 1 sec)
- Shows welcome message
- Lists commands by category

**Result:**
```
✅ Instant response (1 sec)
✅ Welcome message displayed:
   "🤖 Добро пожаловать в Meet-Commit!"
✅ All sections present: умею, быстрый старт, команды, повестки, проверка
✅ HTML formatting correct
✅ User registered in active_users.json
```

---

### ✅ Test 2: /help command [PASS]

**What we check:** Full command reference

**Date:** 16.02.2026, 15:56

**Steps:**
1. Send `/help`

**Expected:**
- Full command list
- Grouped by category

**Result:**
```
✅ Instant response
✅ All categories: основные, создание, запросы, повестки, люди, review
✅ Examples included
✅ Admin section referenced
✅ HTML formatting correct
```

---

## 📝 Meeting Processing

### ✅ Test 3: .txt file upload [PASS]

**What we check:** Full meeting processing pipeline

**Date:** 21.02.2026, 15:31 (clean run with test_meeting_for_test3.txt)

**Steps:**
1. Upload `test_meeting_for_test3.txt` (39 lines, 5 explicit tasks, Синк команды)
2. Select style: Detailed
3. Click "Пропустить"
4. Wait for processing

**Result:**
```
✅ Progress messages — correct bold rendering, no raw <b> tags:
   🔄 Начинаю обработку...
   🤖 Суммаризирую через AI...
   💾 Сохраняю в Notion...
   🔍 Обрабатываю коммиты...

✅ Meeting card:
   📅 test meeting for test3      (no timestamp prefix)
   🗓️ Дата: 21.02.2026
   👥 Участники: Valya Dobrynin   (expected: Маша/Глеб not in dictionary yet)
   🏷️ Теги: 7 tags auto-assigned
   🔗 Открыть в Notion (link present)

✅ Summary — detailed and structured, 3 participants mentioned in text

✅ Commits: 6 total
   • Saved directly: 3 (explicit tasks with known assignees)
   • Sent to Review Queue: 3 (no assignees — Маша/Глеб not in people.json)
     - "привести инструкцию в порядок"
     - "разобраться с жалобами на медленную загрузку"
     - "зафиксировать в документах: договоренность о презентации"

✅ Review Queue — showed 3 items, all confirmed via Confirm All button
✅ No raw HTML anywhere in the output

Note: Маша and Глеб appear as people candidates after processing.
Add them via /people_miner2 → they will be detected in future meetings.
```

---

### ✅ Test 4: PDF format [PASS]

**What we check:** PDF file parsed and processed correctly

**Date:** 21.02.2026, 15:44

**Steps:**
1. Uploaded real PDF transcript (Согласование коммерческих условий)
2. Selected style, clicked Пропустить

**Result:**
```
✅ PDF accepted and text extracted correctly
✅ Processing pipeline identical to .txt
✅ Title: "Согласование коммерческих условий и принципов тарификации"
   (no timestamp prefix, clean title)
✅ Date: 19.02.2026 (extracted from PDF content)
✅ Summary: correct, 3 key decisions and risks identified
✅ Commits: 1 direct + 1 to Review Queue
✅ No raw HTML anywhere
```

**Still to test:** `.docx` and `.vtt` formats

---

### ✅ Test 5: Plain text (no file) [PASS]

**What we check:** Bot processes pasted meeting text same as file upload

**Date:** 21.02.2026

**Steps:**
1. Pasted meeting text directly into chat (no file attachment)

**Result:**
```
✅ Bot showed style selection buttons
✅ Processing ran identically to file upload
✅ Meeting saved to Notion
```

---

## 📝 Task Creation

### ✅ Test 6: /commit interactive [PASS]

**What we check:** 4-step FSM dialog for task creation

**Date:** 21.02.2026, 15:55

**Steps:**
1. Sent `/commit`
2. Entered text: "Сделать презентацию для инвесторов в Заливе"
3. Selected заказчик: Dima Dorokhin (via button)
4. Selected исполнитель: Sasha Katanov (via button)
5. Selected дедлайн: 06.03.2026

**Result:**
```
✅ All 4 steps passed (confirmed via Render logs)
✅ Each step correctly processed:
   12:55:24 — /commit started
   12:55:35 — Step 2 shown (people suggestions loaded: 6 people, 5 active)
   12:55:40 — Step 3 shown (another people list loaded)
   12:55:47 — Step 4 (deadline selected)
   12:55:54 — Saved to Notion
   12:55:55 — "Direct commit created: Сделать презентацию...
               from Dima Dorokhin to Sasha Katanov, due 2026-03-06"

✅ Direction: theirs (correct — assignee is not Valya)
✅ Saved to Direct Commits meeting in Notion
✅ Commit ID generated: ce48665f

Note: intermediate step messages use edit_text (not new messages),
so only the final result is visible in chat. All steps are functional.
```

---

### ✅ Test 7: /llm command [PASS]

**What we check:** Natural language task creation via AI

**Date:** 21.02.2026, 15:55 (after date fix) + 16.02.2026 (first test)

**Steps:**
- `/llm Леша Козлов расскажет про Сплит в Еде до конца марта`
- `/llm Саша Катанов расскажет про франшизу в Лавке до конца марта`

**Result:**
```
✅ Task created instantly
✅ Assignee: Lesha Kozlov — new person, correctly extracted
✅ Customer (заказчик): Valya Dobrynin — correct
✅ Tags: Business/Lavka — correct contextual tag
✅ Status: 🟢 Активно
✅ Due date: 31.03.2026 ← correct year 2026 (after fix)!
   (was 31.03.2025 before fix — prompt had hardcoded 2025 date)
✅ Commit ID generated: 966d50
```

---

## 🔍 Search & Filtering

### ✅ Test 8: /mine command [PASS]

**What we check:** Filter commits by assignee

**Date:** 16.02.2026, 15:48

**Steps:**
1. Send `/mine`

**Expected:**
- Shows user's tasks or "nothing found"

**Result:**
```
✅ Response: "📭 Мои задачи (все) — Ничего не найдено"
✅ Correct (no tasks assigned to me yet)
✅ Fast response
```

---

### ⏳ Tests 9–10: /due, /by_tag [NOT TESTED]

---

## 📊 Agendas

### ⏳ Tests 11–12: Agendas [NOT TESTED]

---

## 🔍 Review Queue

### ✅ Test 13: Review Queue after meeting processing [PASS]

**What we check:** Decision commits go to Review Queue

**Date:** 21.02.2026

**Steps:**
1. Uploaded commercial meeting transcript (rates, decisions)
2. Bot processed → 2 items in Review Queue
3. Clicked "Confirm All"

**Result:**
```
✅ 2 commits extracted from decision-only meeting
✅ Correctly sent to Review Queue (not directly to Commits):
   - "зафиксировать ставку 30% для Казахстана"
     assignees=[], flags=[decision], confidence=0.60
   - "договориться о коммерческих отношениях на всех потоках денег"
     assignees=[], flags=[decision], confidence=0.60

✅ Bot showed Review Queue after processing:
   "📋 Pending review (2 элементов):"
   with [Confirm] and [Confirm All] buttons

Note: prompt fix required — before this test, decision commits were not extracted.
After adding "решили/договорились" pattern to prompts/extraction/commits_extract_ru.md:
   → 0 commits → 2 commits in Review Queue ✅
```

---

### ✅ Test 14: Review confirm via "Confirm All" button [PASS]

**What we check:** Bulk confirm moves items from Review to Commits

**Date:** 21.02.2026

**Steps:**
1. Review Queue showed 2 items
2. Clicked "✅ Confirm All" button

**Result:**
```
✅ Both items confirmed:
   [cc737a] → created commit 30e344c5 in Notion
   [af1595] → created commit 30e344c5 in Notion

✅ Status set to "resolved" with linked commit IDs
✅ Review queue became empty: "📋 Review queue пуста."

Note: HTML tags fix required — "✅ <b>[id] Подтверждено</b>" was showing raw tags.
Fixed: parse_mode="HTML" added to edit_text() and answer() in handlers_inline.py.
```

---

### ⏳ Test 15: Assign via button [NOT TESTED]

---

## 👥 People Management

### ✅ Test — People auto-detection [PASS]

**What we check:** People Miner adds candidates from transcripts

**Date:** 18-21.02.2026

**Result:**
```
✅ Meeting 1: "Added 56 new candidates, updated counts for existing ones"
✅ Meeting 2: "Added 43 new candidates"
✅ People Miner picks up names from transcripts automatically

Note: Gleb Dobroradnykh detected in transcript but not in people.json yet
→ Will appear in /people_miner2 for verification
```

---

### ⏳ Tests 16–17: /people_miner2, /people_stats_v2 [NOT TESTED]

---

## 🔄 AI Commit Extraction Quality

### ✅ Test — Commit extraction with implicit tasks [PASS]

**What we check:** GPT finds implicit commits in realistic meeting text

**Date:** 21.02.2026 (manual test)

**Transcript used:** 227-word meeting about product, onboarding, integration (created locally)

**Result:**
```
✅ 5 commits extracted from 227-word transcript
✅ Correct assignees: Maria, Valya Dobrynin, Gleb Dobroradnykh
✅ Dates parsed: "до среды" → 2026-02-23, "к 27-му" → 2026-02-27
✅ Direction correct: "я напишу" → mine, "Маша возьмёт" → theirs
✅ All 5 went directly to Commits (confidence ≥ 0.65 after validation)
✅ 0 went to Review Queue

Commits found:
  1. привести инструкцию в порядок | Maria | conf=0.75
  2. отправить напоминание Яндексу | Valya | conf=0.70
  3. посмотреть метрики / разобраться с разработкой | Gleb | conf=0.75
  4. обновить презентацию для совета директоров | Maria | due=2026-02-27 | conf=0.80
  5. дать актуальные цифры | Valya | due=2026-02-23 | conf=0.80
```

---

### ✅ Test — Decision commits extraction [PASS]

**What we check:** "решили/договорились" patterns create follow-up commits

**Date:** 21.02.2026 (after prompt update)

**Transcript:** Commercial meeting about agency rates for Kazakhstan

**Result:**
```
✅ 3 commits extracted from decisions-only meeting
✅ Decision commits correctly flagged with assignees=[], confidence=0.60:
   - "зафиксировать в документах: 30% агентская ставка для Казахстана"
   - "обсудить российскую ставку на следующей встрече"
✅ Explicit task correctly assigned:
   - "обновить шаблон договора" → Valya Dobrynin, conf=0.75
```

---

## 🧹 Admin Functions

### ⏳ Tests 20–21: /tags_stats, /webhook_status [NOT TESTED]

---

## 🚨 Edge Cases

### ⏳ Tests 22–25: Edge cases [NOT TESTED]

---

## 🔄 Persistence & Infrastructure

### ✅ Test 26: Redis FSM persistence [PASS]

**What we check:** State preserved between restarts

**Date:** 07.02.2026 (during migration)

**Result:**
```
✅ Redis storage: "🔄 Using Redis storage for cloud mode"
✅ FSM states persist between container restarts
✅ No state loss after deploy
```

---

### ⏳ Tests 27–30: Other infrastructure tests [NOT TESTED]

---

## 🎨 Advanced Features

### ⏳ Tests 31–33: Deduplication, tag inheritance, transliteration [NOT TESTED]

---

## 📊 Final Checklist

### Critical (must work):
- [x] /start shows welcome
- [x] /help shows commands
- [x] File upload and full processing pipeline end-to-end
- [x] AI summarization works
- [x] Commits extracted from explicit tasks
- [x] Commits extracted from decisions (after prompt fix)
- [x] Saved to Notion
- [x] /mine responds correctly
- [x] Review Queue receives low-confidence commits
- [x] Confirm All moves items to Commits

### Important:
- [ ] /commit interactive (Test 6)
- [ ] /due deadlines (Test 9)
- [ ] /assign via button (Test 15)
- [ ] /agenda_person (Test 11)
- [ ] /people_miner2 verification (Test 16)

### Advanced:
- [ ] Meeting deduplication
- [ ] Tag inheritance on commits
- [ ] Multiple formats (PDF/DOCX/VTT)

---

## 🐛 Bugs Found & Fixed During Testing

| # | Bug | Fixed | Date |
|---|-----|-------|------|
| 1 | `bytes is not JSON serializable` in Redis FSM | ✅ base64 encoding | 17.02 |
| 2 | "Нет входных данных" after file upload | ✅ key `raw_bytes_b64` | 17.02 |
| 3 | `<future>` HTML parse error in summary | ✅ `html.escape()` + `parse_mode=None` | 18-19.02 |
| 4 | Default `parse_mode=HTML` causing crashes | ✅ Removed from Bot init | 19.02 |
| 5 | Date showing "—" in meeting card | ✅ Wrong meta key fixed | 20.02 |
| 6 | `🔍 <b>Обрабатываю коммиты...</b>` raw HTML | ✅ Added `parse_mode="HTML"` | 20.02 |
| 7 | Title showing "02 19 Название встречи" | ✅ Timestamp prefix strip regex | 21.02 |
| 8 | 0 commits for decision-only meetings | ✅ Decision pattern in prompt | 21.02 |
| 9 | Raw HTML in Review confirm messages | ✅ parse_mode="HTML" in handlers_inline.py | 21.02 |
| 10 | /llm: "до конца марта" → 2025 instead of 2026 | ✅ {TODAY} placeholder in llm_parse_ru.md | 21.02 |
| 11 | /commit intermediate steps not visible in chat | ℹ️ Expected: edit_text replaces messages | 21.02 |

---

## 🎯 Next Tests to Run

**Priority 1 (do next):**
1. **Test 6** — `/commit` interactive (4-step dialog)
2. **Test 15** — `/assign` via button in Review Queue
3. **Test 9** — `/due` with tasks that have real deadlines

**Priority 2:**
4. **Test 11** — `/agenda_person` with real data
5. **Test 16** — `/people_miner2` — verify Gleb Dobroradnykh from recent meetings
6. **Test 3 full** — Verify Notion content end-to-end (check Meetings + Commits DBs)

**Priority 3:**
7. **Test 31** — Deduplication (upload same file twice)
8. **Test 4** — PDF/DOCX/VTT formats
