"""
Система health checks для мониторинга состояния внешних сервисов.

Проверяет доступность и производительность всех критичных зависимостей.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.core.clients import get_async_openai_client, get_notion_http_client
from app.settings import settings

logger = logging.getLogger(__name__)

HealthStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]


@dataclass
class HealthCheck:
    """Результат health check."""

    service: str
    status: HealthStatus
    response_time_ms: float
    error: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class SystemHealth:
    """Общее состояние системы."""

    overall_status: HealthStatus
    checks: list[HealthCheck]
    timestamp: float
    summary: dict[str, Any]


async def check_notion_api() -> HealthCheck:
    """Проверяет доступность Notion API."""
    start_time = time.perf_counter()

    try:
        if not settings.notion_token:
            return HealthCheck(
                service="notion_api",
                status="unhealthy",
                response_time_ms=0,
                error="NOTION_TOKEN не настроен",
            )

        # Используем context manager для правильного lifecycle
        with get_notion_http_client() as client:
            # Простой запрос для проверки доступности
            response = client.get("https://api.notion.com/v1/users/me")
            response_time_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code == 200:
            user_data = response.json()
            return HealthCheck(
                service="notion_api",
                status="healthy",
                response_time_ms=response_time_ms,
                details={
                    "user_id": user_data.get("id"),
                    "user_name": user_data.get("name"),
                    "status_code": response.status_code,
                },
            )
        else:
            return HealthCheck(
                service="notion_api",
                status="degraded",
                response_time_ms=response_time_ms,
                error=f"HTTP {response.status_code}: {response.text}",
            )

    except Exception as e:
        response_time_ms = (time.perf_counter() - start_time) * 1000
        return HealthCheck(
            service="notion_api",
            status="unhealthy",
            response_time_ms=response_time_ms,
            error=str(e),
        )


async def check_openai_api() -> HealthCheck:
    """Проверяет доступность OpenAI API."""
    start_time = time.perf_counter()

    try:
        if not settings.openai_api_key:
            return HealthCheck(
                service="openai_api",
                status="unhealthy",
                response_time_ms=0,
                error="OPENAI_API_KEY не настроен",
            )

        client = await get_async_openai_client(timeout=10.0)  # Короткий timeout для health check

        # Минимальный запрос для проверки
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1,
        )

        response_time_ms = (time.perf_counter() - start_time) * 1000

        if response.choices and response.choices[0].message:
            return HealthCheck(
                service="openai_api",
                status="healthy",
                response_time_ms=response_time_ms,
                details={
                    "model": "gpt-4o-mini",
                    "tokens_used": response.usage.total_tokens if response.usage else 0,
                },
            )
        else:
            return HealthCheck(
                service="openai_api",
                status="degraded",
                response_time_ms=response_time_ms,
                error="Пустой ответ от API",
            )

    except Exception as e:
        response_time_ms = (time.perf_counter() - start_time) * 1000
        return HealthCheck(
            service="openai_api",
            status="unhealthy",
            response_time_ms=response_time_ms,
            error=str(e),
        )
    finally:
        try:
            await client.close()
        except Exception:
            pass  # Игнорируем ошибки закрытия клиента


async def check_notion_databases() -> HealthCheck:
    """Проверяет доступность Notion баз данных."""
    start_time = time.perf_counter()

    try:
        if not all([settings.notion_db_meetings_id, settings.commits_db_id, settings.review_db_id]):
            missing = []
            if not settings.notion_db_meetings_id:
                missing.append("NOTION_DB_MEETINGS_ID")
            if not settings.commits_db_id:
                missing.append("COMMITS_DB_ID")
            if not settings.review_db_id:
                missing.append("REVIEW_DB_ID")

            return HealthCheck(
                service="notion_databases",
                status="unhealthy",
                response_time_ms=0,
                error=f"Не настроены базы: {', '.join(missing)}",
            )

        # Используем context manager для правильного lifecycle
        with get_notion_http_client() as client:
            # Проверяем доступность каждой базы
            databases_to_check = {
                "meetings": settings.notion_db_meetings_id,
                "commits": settings.commits_db_id,
                "review": settings.review_db_id,
            }

            results = {}
            for db_name, db_id in databases_to_check.items():
                try:
                    response = client.post(
                        f"https://api.notion.com/v1/databases/{db_id}/query", json={"page_size": 1}
                    )
                    results[db_name] = {
                        "status": "ok" if response.status_code == 200 else "error",
                        "status_code": response.status_code,
                    }
                except Exception as e:
                    results[db_name] = {"status": "error", "error": str(e)}

            response_time_ms = (time.perf_counter() - start_time) * 1000

        # Определяем общий статус
        all_ok = all(db["status"] == "ok" for db in results.values())
        any_error = any(db["status"] == "error" for db in results.values())

        if all_ok:
            status: HealthStatus = "healthy"
        elif any_error:
            status = "degraded"
        else:
            status = "unhealthy"

        return HealthCheck(
            service="notion_databases",
            status=status,
            response_time_ms=response_time_ms,
            details=results,
        )

    except Exception as e:
        response_time_ms = (time.perf_counter() - start_time) * 1000
        return HealthCheck(
            service="notion_databases",
            status="unhealthy",
            response_time_ms=response_time_ms,
            error=str(e),
        )


async def run_all_health_checks(timeout: float = 30.0) -> SystemHealth:
    """
    Запускает все health checks параллельно.

    Args:
        timeout: Максимальное время ожидания для всех проверок

    Returns:
        Общее состояние системы
    """
    start_time = time.perf_counter()

    try:
        # Запускаем все проверки параллельно
        checks = await asyncio.wait_for(
            asyncio.gather(
                check_notion_api(),
                check_openai_api(),
                check_notion_databases(),
                return_exceptions=True,
            ),
            timeout=timeout,
        )

        # Обрабатываем результаты
        health_checks = []
        for check in checks:
            if isinstance(check, Exception):
                health_checks.append(
                    HealthCheck(
                        service="unknown",
                        status="unhealthy",
                        response_time_ms=0,
                        error=str(check),
                    )
                )
            else:
                health_checks.append(check)  # type: ignore[arg-type]

        # Определяем общий статус
        statuses = [check.status for check in health_checks]
        if all(status == "healthy" for status in statuses):
            overall_status: HealthStatus = "healthy"
        elif any(status == "unhealthy" for status in statuses):
            overall_status = "unhealthy"
        else:
            overall_status = "degraded"

        # Собираем сводку
        summary = {
            "total_checks": len(health_checks),
            "healthy": sum(1 for s in statuses if s == "healthy"),
            "degraded": sum(1 for s in statuses if s == "degraded"),
            "unhealthy": sum(1 for s in statuses if s == "unhealthy"),
            "avg_response_time_ms": sum(check.response_time_ms for check in health_checks)
            / len(health_checks),
            "total_check_time_ms": (time.perf_counter() - start_time) * 1000,
        }

        return SystemHealth(
            overall_status=overall_status,
            checks=health_checks,
            timestamp=time.time(),
            summary=summary,
        )

    except TimeoutError:
        return SystemHealth(
            overall_status="unhealthy",
            checks=[
                HealthCheck(
                    service="system",
                    status="unhealthy",
                    response_time_ms=timeout * 1000,
                    error=f"Health checks timeout после {timeout}s",
                )
            ],
            timestamp=time.time(),
            summary={"error": "timeout"},
        )


def format_health_report(health: SystemHealth) -> str:
    """Форматирует health check отчет для отображения."""
    status_emoji = {
        "healthy": "✅",
        "degraded": "⚠️",
        "unhealthy": "❌",
        "unknown": "❓",
    }

    lines = []
    lines.append(
        f"{status_emoji[health.overall_status]} **Общий статус: {health.overall_status.upper()}**"
    )
    lines.append("")

    for check in health.checks:
        emoji = status_emoji[check.status]
        lines.append(f"{emoji} **{check.service}**: {check.status}")
        lines.append(f"   ⏱️ Время ответа: {check.response_time_ms:.1f}ms")

        if check.error:
            lines.append(f"   ❌ Ошибка: {check.error}")

        if check.details:
            for key, value in check.details.items():
                lines.append(f"   📋 {key}: {value}")
        lines.append("")

    # Сводка
    if health.summary and "total_checks" in health.summary:
        summary = health.summary
        lines.append("📊 **Сводка:**")
        lines.append(f"   🔢 Проверок: {summary['total_checks']}")
        lines.append(f"   ✅ Здоровых: {summary.get('healthy', 0)}")
        lines.append(f"   ⚠️ Деградация: {summary.get('degraded', 0)}")
        lines.append(f"   ❌ Нездоровых: {summary.get('unhealthy', 0)}")
        lines.append(f"   ⏱️ Среднее время: {summary.get('avg_response_time_ms', 0):.1f}ms")

    return "\n".join(lines)
