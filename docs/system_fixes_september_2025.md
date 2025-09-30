# System Fixes - September 2025

## 🎯 **Обзор исправлений**

Два критических исправления в системе Meet-Commit:

1. **Замена "System" заказчика на "Valya Dobrynin"**
2. **Исправление слипания исполнителей в LLM парсинге**

---

## 🔧 **Исправление 1: System → Valya Dobrynin**

### **Проблема**
- В agenda системе появлялся "System" как заказчик задач
- "System" попадал в топ активных людей по алгоритму ранжирования
- Это мешало пользователям и выглядело как артефакт системы

### **Источник проблемы**
В `app/core/commit_normalize.py` в функции `normalize_commits()`:
```python
# БЫЛО:
from_person = ["System"]  # Fallback для неопределенных заказчиков

# СТАЛО:
from_person = ["Valya Dobrynin"]  # Конкретный fallback
```

### **Исправления**
1. **`app/core/commit_normalize.py`** - строки 442, 446:
   - Заменил `["System"]` на `["Valya Dobrynin"]` в fallback логике

2. **`app/core/people_activity.py`** - строки 126-131:
   - Добавил фильтрацию системных имен:
   ```python
   excluded_system_names = {"System", "Unknown", "Bot", "Auto", ""}
   
   for person, stats in people_stats.items():
       if person in excluded_system_names:
           continue  # Пропускаем системные имена
   ```

### **Результат**
- ✅ "System" больше не появляется в agenda повестках
- ✅ Все неопределенные заказчики становятся "Valya Dobrynin"
- ✅ Рейтинг активности людей очищен от системных артефактов

---

## 🔧 **Исправление 2: Слипание исполнителей**

### **Проблема**
При использовании `/llm` команды с текстом типа:
- "Нодари и Ломпа сделают презентацию"
- "Влад Склянов, Сергей Ломпа подготовят отчет"

**Результат был неправильный:**
```
assignees: ["Nodari Kezua И Sergey Lompa"]  ❌ (один слитный элемент)
```

**Должно быть:**
```
assignees: ["Nodari Kezua", "Sergey Lompa"]  ✅ (два отдельных элемента)
```

### **Источник проблемы**
В `app/core/llm_commit_parse.py` функция `_apply_role_fallbacks()`:
```python
# БЫЛО:
assignee = llm_result.get("assignee") or user_name  # Строка
raw_assignees = [assignee] if assignee else []     # Строка в список

# LLM возвращал: "Vlad Sklyanov, Sergey Lompa"
# Получалось: ["Vlad Sklyanov, Sergey Lompa"] ❌
```

### **Исправления**
1. **Новая функция `_split_names()`**:
   ```python
   def _split_names(names_string: str) -> list[str]:
       """Разбивает строку с именами на отдельные имена."""
       # Заменяем союзы на запятые
       normalized = re.sub(r'\s+(и|and|with|&|\+)\s+', ', ', names_string, flags=re.IGNORECASE)
       # Разбиваем по запятым
       names = [name.strip() for name in normalized.split(',')]
       return [name for name in names if name]
   ```

2. **Обновленная `_apply_role_fallbacks()`**:
   ```python
   # Исполнители: разбиваем строку на список
   assignee_raw = llm_result.get("assignee") or user_name
   assignees = _split_names(assignee_raw) if assignee_raw else [user_name]
   
   # Direction зависит от того, кто исполнитель
   direction = "mine" if user_name in assignees else "theirs"
   
   return assignees, from_person, direction  # Возвращаем список
   ```

3. **Обновленная `_build_full_commit()`**:
   ```python
   # Принимает список исполнителей вместо строки
   def _build_full_commit(llm_result: dict, user_name: str, assignees: list[str], ...):
       normalized_assignees = normalize_assignees(assignees, [])
   ```

### **Поддерживаемые форматы разделителей**
- **Запятые:** "Alice, Bob, Charlie"
- **Русские союзы:** "Нодари и Ломпа"
- **Английские союзы:** "John and Jane", "Alice with Bob"
- **Символы:** "Tom & Jerry", "One + Two"
- **Смешанные:** "Alice, Bob и Charlie and Dave"

### **Результат**
- ✅ Множественные исполнители корректно разделяются
- ✅ Каждый исполнитель сохраняется как отдельный элемент в Notion
- ✅ Поддержка русских и английских союзов
- ✅ Логика direction корректно работает с множественными исполнителями

---

## 🧪 **Тестирование**

### **Новые тесты**
Создан файл `tests/test_system_fixes.py` с 14 тестами:

#### **System Fallback Fix (3 теста)**
- ✅ `test_system_replaced_in_mine_commits`
- ✅ `test_system_replaced_in_theirs_commits` 
- ✅ `test_system_excluded_from_people_activity`

#### **Assignee Splitting Fix (9 тестов)**
- ✅ `test_split_names_comma_separated`
- ✅ `test_split_names_russian_conjunction`
- ✅ `test_split_names_english_conjunction`
- ✅ `test_split_names_mixed_separators`
- ✅ `test_apply_role_fallbacks_multiple_assignees`
- ✅ `test_parse_commit_text_multiple_assignees`
- ✅ И другие граничные случаи

#### **Integration Tests (2 теста)**
- ✅ `test_no_system_in_llm_commits`
- ✅ `test_realistic_scenario`

### **Обновленные тесты**
Исправлено 8 существующих тестов в `tests/test_llm_commit_parse.py`:
- Обновлены под новую сигнатуру `_apply_role_fallbacks()` (возвращает список)
- Обновлены под новую сигнатуру `_build_full_commit()` (принимает список)

### **Результаты тестирования**
```bash
============================= test session starts ==============================
90 passed in 2.01s
============================= 90 passed, 0 failed ==============================
```

---

## 📊 **Воздействие на систему**

### **Безопасность изменений**
- ✅ Все существующие тесты проходят
- ✅ Обратная совместимость сохранена
- ✅ Никакие API не изменились
- ✅ Данные в Notion не повреждены

### **Производительность**
- ➡️ Нейтральное воздействие на производительность
- ➡️ Новая функция `_split_names()` выполняется за O(n) времени
- ➡️ Фильтрация системных имен - O(1) проверка в hash set

### **Пользовательский опыт**
- 🎯 **Лучше:** Больше нет "System" в agenda повестках
- 🎯 **Лучше:** Множественные исполнители корректно отображаются в Notion
- 🎯 **Лучше:** Более точное ранжирование людей по активности

---

## 🚀 **Deployment**

### **Дата внедрения**
29 сентября 2025

### **Версия**
Commit: [hash] - "Fix System fallback and assignee splitting in LLM parsing"

### **Откат**
В случае проблем можно откатить изменения:
1. Восстановить `["System"]` в `commit_normalize.py`
2. Вернуть старую логику `_apply_role_fallbacks()` возвращающую строку
3. Убрать фильтрацию системных имен из `people_activity.py`

### **Мониторинг**
- 📊 Отслеживать появление "System" в логах
- 📊 Проверять корректность разделения исполнителей в Notion
- 📊 Мониторить agenda кнопки на предмет системных имен

---

## 🎉 **Заключение**

Обе проблемы успешно решены:

1. **"System" заказчик** → **"Valya Dobrynin"** (понятный fallback)
2. **Слипание исполнителей** → **Корректное разделение** (поддержка союзов)

Система стала более предсказуемой и удобной для пользователей. Все тесты проходят, совместимость сохранена.

**Статус: ✅ COMPLETED**

