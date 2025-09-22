"""Улучшенный тэггер v1 с системой scoring и предкомпилированными regex.

Новые возможности:
- Компиляция regex один раз при загрузке (оптимизация ×2-×5)
- Система weight/score для градации уверенности
- Exclude паттерны для исключений (например, email)
- Порог tags_min_score для фильтрации шума
- Обратная совместимость с существующим API
- Thread-safe архитектура с proper error handling
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.core.people_store import load_people
from app.settings import settings

logger = logging.getLogger(__name__)

# Thread-safe lock для компиляции правил
_rules_lock = threading.RLock()


class TagRule(BaseModel):
    """Модель правила тегирования с валидацией."""

    patterns: list[str] = Field(min_length=1, description="Список паттернов для поиска")
    exclude: list[str] = Field(default_factory=list, description="Исключающие паттерны")
    weight: float = Field(default=1.0, ge=0.0, le=10.0, description="Вес тега (0.0-10.0)")

    def model_post_init(self, __context: Any) -> None:
        """Валидация паттернов после создания модели."""
        # Проверяем, что все паттерны корректные regex
        for pattern in self.patterns + self.exclude:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e


class CompiledRule(BaseModel):
    """Скомпилированное правило с предкомпилированными regex."""

    patterns: list[re.Pattern[str]] = Field(description="Скомпилированные паттерны")
    excludes: list[re.Pattern[str]] = Field(description="Скомпилированные исключения")
    weight: float = Field(description="Вес тега")


class TaggerStats(BaseModel):
    """Статистика тэггера с детальными метриками."""

    total_rules: int = Field(description="Общее количество правил")
    total_patterns: int = Field(description="Общее количество паттернов")
    total_excludes: int = Field(description="Общее количество исключений")
    average_weight: float = Field(description="Средний вес правил")
    last_reload_time: float | None = Field(description="Время последней перезагрузки")

    # Детальные метрики производительности
    total_calls: int = Field(default=0, description="Общее количество вызовов")
    total_tags_found: int = Field(default=0, description="Общее количество найденных тегов")
    avg_score: float = Field(default=0.0, description="Средний score найденных тегов")
    top_tags: list[tuple[str, int]] = Field(
        default_factory=list, description="Топ тегов по частоте"
    )
    performance_ms: float = Field(default=0.0, description="Среднее время выполнения в мс")


class TaggerV1Scored:
    """Thread-safe тэггер с системой scoring."""

    def __init__(self) -> None:
        self._compiled_rules: dict[str, CompiledRule] = {}
        self._stats = TaggerStats(
            total_rules=0,
            total_patterns=0,
            total_excludes=0,
            average_weight=1.0,
            last_reload_time=None,
            total_calls=0,
            total_tags_found=0,
            avg_score=0.0,
            top_tags=[],
            performance_ms=0.0,
        )
        self._tag_frequency: dict[str, int] = {}  # Счетчик частоты тегов
        self._performance_times: list[float] = []  # Времена выполнения
        self._load_and_compile_rules()

    def _get_rules_path(self) -> Path:
        """Получает путь к файлу правил."""
        rules_path = Path(settings.tagger_v1_rules_file)

        # Если путь относительный, делаем его относительно корня проекта
        if not rules_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            rules_path = project_root / rules_path

        return rules_path

    def _normalize_yaml_format(self, raw_data: dict) -> dict[str, TagRule]:
        """Нормализует YAML в единый формат с валидацией.

        Поддерживает:
        - Старый формат: tag: [patterns]
        - Новый формат: tag: {patterns: [...], exclude: [...], weight: 1.0}
        """
        normalized: dict[str, TagRule] = {}

        for tag, spec in (raw_data or {}).items():
            try:
                if isinstance(spec, list):
                    # Старый формат: tag: [patterns]
                    rule = TagRule(patterns=spec)
                elif isinstance(spec, dict):
                    # Новый формат с валидацией
                    rule = TagRule(**spec)
                else:
                    logger.warning(f"Ignoring invalid rule format for tag '{tag}': {type(spec)}")
                    continue

                normalized[tag] = rule
                logger.debug(
                    f"Loaded rule for tag '{tag}': {len(rule.patterns)} patterns, weight={rule.weight}"
                )

            except ValidationError as e:
                logger.error(f"Invalid rule for tag '{tag}': {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing rule for tag '{tag}': {e}")
                continue

        return normalized

    def _compile_rules(self, rules: dict[str, TagRule]) -> dict[str, CompiledRule]:
        """Компилирует правила в regex паттерны."""
        compiled: dict[str, CompiledRule] = {}

        for tag, rule in rules.items():
            try:
                patterns = []
                excludes = []

                # Компилируем основные паттерны
                for pattern in rule.patterns:
                    try:
                        compiled_pattern = re.compile(pattern, re.IGNORECASE | re.UNICODE)
                        patterns.append(compiled_pattern)
                    except re.error as e:
                        logger.error(f"Failed to compile pattern '{pattern}' for tag '{tag}': {e}")
                        continue

                # Компилируем исключающие паттерны
                for exclude in rule.exclude:
                    try:
                        compiled_exclude = re.compile(exclude, re.IGNORECASE | re.UNICODE)
                        excludes.append(compiled_exclude)
                    except re.error as e:
                        logger.error(
                            f"Failed to compile exclude pattern '{exclude}' for tag '{tag}': {e}"
                        )
                        continue

                # Добавляем правило только если есть валидные паттерны
                if patterns:
                    compiled[tag] = CompiledRule(
                        patterns=patterns, excludes=excludes, weight=rule.weight
                    )
                    logger.debug(
                        f"Compiled rule for '{tag}': {len(patterns)} patterns, {len(excludes)} excludes"
                    )
                else:
                    logger.warning(f"No valid patterns for tag '{tag}', skipping")

            except Exception as e:
                logger.error(f"Error compiling rule for tag '{tag}': {e}")
                continue

        return compiled

    def _update_stats(self, compiled_rules: dict[str, CompiledRule]) -> None:
        """Обновляет статистику тэггера."""
        import time

        total_patterns = sum(len(rule.patterns) for rule in compiled_rules.values())
        total_excludes = sum(len(rule.excludes) for rule in compiled_rules.values())
        weights = [rule.weight for rule in compiled_rules.values()]
        average_weight = sum(weights) / len(weights) if weights else 1.0

        self._stats = TaggerStats(
            total_rules=len(compiled_rules),
            total_patterns=total_patterns,
            total_excludes=total_excludes,
            average_weight=average_weight,
            last_reload_time=time.time(),
        )

    def _load_and_compile_rules(self) -> None:
        """Загружает и компилирует правила из YAML файла."""
        with _rules_lock:
            try:
                rules_path = self._get_rules_path()

                if not rules_path.exists():
                    logger.warning(f"Tagger v1 rules file not found: {rules_path}")
                    self._compiled_rules = {}
                    self._update_stats({})
                    return

                # Загружаем YAML
                with open(rules_path, encoding="utf-8") as f:
                    raw_data = yaml.safe_load(f) or {}

                # Нормализуем и валидируем
                normalized_rules = self._normalize_yaml_format(raw_data)

                # Компилируем правила
                compiled_rules = self._compile_rules(normalized_rules)

                # Атомарно обновляем правила и статистику
                self._compiled_rules = compiled_rules
                self._update_stats(compiled_rules)

                logger.info(f"Loaded {len(compiled_rules)} tagger rules from {rules_path}")

            except Exception as e:
                logger.error(f"Error loading tagger rules: {e}")
                # При ошибке оставляем старые правила или пустые
                if not hasattr(self, "_compiled_rules"):
                    self._compiled_rules = {}
                    self._update_stats({})

    def reload_rules(self) -> int:
        """Перезагружает правила из файла.

        Returns:
            Количество загруженных правил
        """
        logger.info("Reloading tagger v1 rules...")
        self._load_and_compile_rules()
        return len(self._compiled_rules)

    def _extract_people_tags(self, text_lower: str) -> list[tuple[str, float]]:
        """Извлекает теги людей из текста."""
        people_tags: list[tuple[str, float]] = []

        try:
            for person in load_people():
                name_en = person.get("name_en", "").strip()
                if not name_en:
                    continue

                # Ищем любой из алиасов
                for alias in person.get("aliases", []):
                    if alias and alias.lower() in text_lower:
                        people_tags.append((f"People/{name_en}", 1.0))
                        break  # Достаточно одного совпадения на человека

        except Exception as e:
            logger.error(f"Error extracting people tags: {e}")

        return people_tags

    def _update_performance_metrics(
        self, scored_tags: list[tuple[str, float]], execution_time: float
    ) -> None:
        """Обновляет метрики производительности и статистику."""
        # Обновляем счетчики
        self._stats.total_calls += 1
        self._stats.total_tags_found += len(scored_tags)

        # Обновляем частоту тегов
        for tag, _score in scored_tags:
            self._tag_frequency[tag] = self._tag_frequency.get(tag, 0) + 1

        # Обновляем топ тегов (топ 10)
        self._stats.top_tags = sorted(
            self._tag_frequency.items(), key=lambda x: x[1], reverse=True
        )[:10]

        # Обновляем средний score
        if scored_tags:
            total_score = sum(score for _, score in scored_tags)
            avg_score = total_score / len(scored_tags)
            # Экспоненциальное скользящее среднее для стабильности
            if self._stats.avg_score == 0:
                self._stats.avg_score = avg_score
            else:
                self._stats.avg_score = 0.9 * self._stats.avg_score + 0.1 * avg_score

        # Обновляем времена выполнения (храним последние 100)
        self._performance_times.append(execution_time)
        if len(self._performance_times) > 100:
            self._performance_times.pop(0)

        # Обновляем среднее время выполнения
        self._stats.performance_ms = sum(self._performance_times) / len(self._performance_times)

    def tag_text_scored(self, text: str) -> list[tuple[str, float]]:
        """Извлекает теги с оценками из текста с метриками производительности.

        Args:
            text: Текст для анализа

        Returns:
            Список кортежей (tag, score), отсортированный по убыванию score
        """
        import time

        start_time = time.time()

        if not text or not text.strip():
            return []

        if not settings.tagger_v1_enabled:
            logger.debug("Tagger v1 is disabled")
            return []

        scored_tags: list[tuple[str, float]] = []
        text_lower = text.lower()

        try:
            # 1) Обрабатываем правила из YAML
            with _rules_lock:
                for tag, rule in self._compiled_rules.items():
                    # Проверяем исключения
                    excluded = False
                    for exclude_pattern in rule.excludes:
                        if exclude_pattern.search(text):
                            logger.debug(
                                f"Tag '{tag}' excluded by pattern: {exclude_pattern.pattern}"
                            )
                            excluded = True
                            break

                    if excluded:
                        continue

                    # Считаем совпадения основных паттернов
                    hits = 0
                    for pattern in rule.patterns:
                        matches = len(pattern.findall(text))
                        if matches > 0:
                            hits += matches
                            logger.debug(
                                f"Tag '{tag}' matched {matches} times by pattern: {pattern.pattern}"
                            )

                    if hits > 0:
                        score = rule.weight * hits
                        scored_tags.append((tag, score))

            # 2) Добавляем теги людей
            people_tags = self._extract_people_tags(text_lower)
            scored_tags.extend(people_tags)

        except Exception as e:
            logger.error(f"Error in tag_text_scored: {e}")
            return []

        # Сортируем по score (убывание), затем по имени тега
        scored_tags.sort(key=lambda x: (-x[1], x[0]))

        # Обновляем метрики производительности
        execution_time = (time.time() - start_time) * 1000  # в миллисекундах
        self._update_performance_metrics(scored_tags, execution_time)

        logger.debug(f"Found {len(scored_tags)} scored tags in {execution_time:.2f}ms")
        return scored_tags

    def tag_text(self, text: str) -> list[str]:
        """Извлекает теги, отфильтрованные по минимальному порогу.

        Args:
            text: Текст для анализа

        Returns:
            Отсортированный список тегов, прошедших порог
        """
        min_score = settings.tags_min_score
        scored_tags = self.tag_text_scored(text)

        filtered_tags = [tag for tag, score in scored_tags if score >= min_score]

        # Сортируем алфавитно для совместимости с существующими тестами
        filtered_tags.sort()

        logger.info(f"Tagged text: {len(filtered_tags)} tags passed threshold {min_score}")
        return filtered_tags

    def get_stats(self) -> dict[str, Any]:
        """Возвращает детальную статистику тэггера."""
        stats = self._stats.model_dump()

        # Добавляем дополнительные метрики
        stats.update(
            {
                "cache_hit_rate": 0.0,  # В данной реализации нет кэша
                "total_unique_tags": len(self._tag_frequency),
                "most_frequent_tag": self._stats.top_tags[0] if self._stats.top_tags else None,
                "performance_samples": len(self._performance_times),
            }
        )

        return stats

    def clear_cache(self) -> None:
        """Очищает кэш (для совместимости с существующим API)."""
        # В данной реализации нет LRU кэша, но метод нужен для совместимости
        logger.debug("Tagger v1 scored cache cleared (no-op)")


# Глобальный экземпляр тэггера (thread-safe)
_tagger_instance: TaggerV1Scored | None = None
_instance_lock = threading.Lock()


def _get_tagger() -> TaggerV1Scored:
    """Получает singleton экземпляр тэггера."""
    global _tagger_instance

    if _tagger_instance is None:
        with _instance_lock:
            if _tagger_instance is None:
                _tagger_instance = TaggerV1Scored()

    return _tagger_instance


# Публичный API для обратной совместимости
def tag_text_scored(text: str) -> list[tuple[str, float]]:
    """Возвращает теги с оценками: [(tag, score)]."""
    return _get_tagger().tag_text_scored(text)


def tag_text(text: str) -> list[str]:
    """Возвращает теги, отфильтрованные по порогу."""
    return _get_tagger().tag_text(text)


def reload_rules() -> int:
    """Перезагружает правила тегирования."""
    return _get_tagger().reload_rules()


def get_rules_stats() -> dict[str, Any]:
    """Возвращает статистику правил."""
    return _get_tagger().get_stats()


def clear_cache() -> None:
    """Очищает кэш тэггера."""
    return _get_tagger().clear_cache()


# Для совместимости с существующими тестами
def validate_rules() -> list[str]:
    """
    Валидирует YAML файл правил тегирования.

    Returns:
        Список ошибок валидации (пустой если все ок)
    """
    errors: list[str] = []

    try:
        tagger = _get_tagger()
        rules_path = tagger._get_rules_path()

        if not rules_path.exists():
            return [f"Rules file not found: {rules_path}"]

        # Загружаем сырые данные
        with open(rules_path, encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        if not isinstance(raw_data, dict):
            return ["YAML must be a dictionary"]

        seen_tags = set()
        total_patterns = 0
        total_excludes = 0

        for tag, spec in raw_data.items():
            # Проверяем дубликаты тегов
            if tag in seen_tags:
                errors.append(f"Duplicate tag: {tag}")
            seen_tags.add(tag)

            # Проверяем формат тега
            if not tag or not isinstance(tag, str):
                errors.append(f"Invalid tag name: {tag}")
                continue

            if "/" not in tag:
                errors.append(f"Tag should have category/subcategory format: {tag}")

            # Нормализуем spec в единый формат
            if isinstance(spec, list):
                patterns = spec
                excludes = []
                weight = 1.0
            elif isinstance(spec, dict):
                patterns = spec.get("patterns", [])
                excludes = spec.get("exclude", [])
                weight = spec.get("weight", 1.0)
            else:
                errors.append(f"Invalid spec format for tag {tag}: {type(spec)}")
                continue

            # Проверяем patterns
            if not patterns:
                errors.append(f"No patterns for tag: {tag}")
            elif not isinstance(patterns, list):
                errors.append(f"Patterns must be a list for tag: {tag}")
            else:
                for i, pattern in enumerate(patterns):
                    if not isinstance(pattern, str):
                        errors.append(f"Pattern {i} must be string for tag {tag}: {type(pattern)}")
                        continue
                    if not pattern.strip():
                        errors.append(f"Empty pattern {i} for tag: {tag}")
                        continue
                    try:
                        re.compile(pattern, re.IGNORECASE | re.UNICODE)
                        total_patterns += 1
                    except re.error as e:
                        errors.append(f"Invalid regex in {tag} pattern {i}: '{pattern}' -> {e}")

            # Проверяем excludes
            if excludes and isinstance(excludes, list):
                for i, exclude in enumerate(excludes):
                    if not isinstance(exclude, str):
                        errors.append(f"Exclude {i} must be string for tag {tag}: {type(exclude)}")
                        continue
                    if not exclude.strip():
                        errors.append(f"Empty exclude {i} for tag: {tag}")
                        continue
                    try:
                        re.compile(exclude, re.IGNORECASE | re.UNICODE)
                        total_excludes += 1
                    except re.error as e:
                        errors.append(f"Invalid regex in {tag} exclude {i}: '{exclude}' -> {e}")

            # Проверяем weight
            if not isinstance(weight, int | float):
                errors.append(f"Weight must be number for tag {tag}: {type(weight)}")
            elif weight < 0 or weight > 10:
                errors.append(f"Weight must be 0.0-10.0 for tag {tag}: {weight}")

        # Предупреждения о производительности
        if total_patterns > 500:
            errors.append(f"WARNING: Too many patterns ({total_patterns}), may impact performance")

        if total_excludes > 100:
            errors.append(f"WARNING: Too many excludes ({total_excludes}), may impact performance")

        logger.info(
            f"Validated {len(seen_tags)} tags, {total_patterns} patterns, {total_excludes} excludes"
        )

    except Exception as e:
        errors.append(f"Error validating rules: {e}")

    return errors


def get_compiled_rules() -> dict[str, Any]:
    """Возвращает информацию о скомпилированных правилах."""
    tagger = _get_tagger()
    with _rules_lock:
        return {
            tag: {
                "patterns_count": len(rule.patterns),
                "excludes_count": len(rule.excludes),
                "weight": rule.weight,
            }
            for tag, rule in tagger._compiled_rules.items()
        }
