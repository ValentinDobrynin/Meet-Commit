"""
Мониторинг и восстановление Telegram webhook.

Этот модуль обеспечивает:
1. Проверку статуса webhook
2. Автоматическое восстановление при сбое
3. Логирование проблем
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def check_webhook_status(bot) -> dict[str, Any]:
    """
    Проверяет текущий статус webhook в Telegram.
    
    Returns:
        Dict с информацией о webhook:
        - url: текущий URL webhook
        - has_custom_certificate: использует ли кастомный сертификат
        - pending_update_count: количество ожидающих обновлений
        - last_error_date: дата последней ошибки (если есть)
        - last_error_message: текст последней ошибки (если есть)
    """
    try:
        webhook_info = await bot.get_webhook_info()
        
        info = {
            "url": webhook_info.url,
            "has_custom_certificate": webhook_info.has_custom_certificate,
            "pending_update_count": webhook_info.pending_update_count,
            "last_error_date": webhook_info.last_error_date,
            "last_error_message": webhook_info.last_error_message,
            "max_connections": webhook_info.max_connections,
            "ip_address": webhook_info.ip_address,
        }
        
        logger.info(f"Webhook status checked: URL={info['url']}, pending={info['pending_update_count']}")
        
        return info
        
    except Exception as e:
        logger.error(f"Failed to check webhook status: {e}")
        return {
            "error": str(e),
            "url": None,
        }


async def ensure_webhook_configured(bot) -> bool:
    """
    Проверяет что webhook настроен правильно и восстанавливает при необходимости.
    
    Returns:
        True если webhook настроен корректно
        False если не удалось настроить
    """
    try:
        deployment_mode = os.getenv("DEPLOYMENT_MODE", "local")
        
        # В локальном режиме webhook не нужен
        if deployment_mode != "render":
            logger.debug("Local mode - webhook not required")
            return True
        
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            logger.warning("WEBHOOK_URL not configured")
            return False
        
        # Проверяем текущий статус
        info = await check_webhook_status(bot)
        
        current_url = info.get("url", "")
        
        # Webhook уже настроен правильно
        if current_url == webhook_url:
            # Проверяем наличие ошибок
            if info.get("last_error_message"):
                logger.warning(
                    f"Webhook has errors: {info['last_error_message']} "
                    f"(date: {info.get('last_error_date')})"
                )
            else:
                logger.info(f"✅ Webhook is configured correctly: {webhook_url}")
            return True
        
        # Webhook не настроен или URL не совпадает - настраиваем
        logger.warning(
            f"Webhook misconfigured: current='{current_url}' vs expected='{webhook_url}'"
        )
        
        await bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True
        )
        
        logger.info(f"✅ Webhook reconfigured: {webhook_url}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to ensure webhook configured: {e}")
        return False


async def get_webhook_health_report(bot) -> str:
    """
    Генерирует текстовый отчет о здоровье webhook для админов.
    
    Returns:
        Форматированный текст отчета
    """
    try:
        info = await check_webhook_status(bot)
        
        report = "🔗 <b>Webhook Health Report</b>\n\n"
        
        # URL
        url = info.get("url")
        if url:
            report += f"📍 <b>URL:</b> {url}\n"
        else:
            report += "⚠️ <b>URL:</b> Не настроен\n"
        
        # Pending updates
        pending = info.get("pending_update_count", 0)
        if pending > 0:
            report += f"⚠️ <b>Ожидающих обновлений:</b> {pending}\n"
        else:
            report += f"✅ <b>Ожидающих обновлений:</b> {pending}\n"
        
        # Last error
        last_error = info.get("last_error_message")
        if last_error:
            error_date = info.get("last_error_date")
            report += f"\n❌ <b>Последняя ошибка:</b>\n"
            report += f"   {last_error}\n"
            if error_date:
                report += f"   <i>Дата: {error_date}</i>\n"
        else:
            report += f"\n✅ <b>Ошибок нет</b>\n"
        
        # Max connections
        max_conn = info.get("max_connections")
        if max_conn:
            report += f"\n🔌 <b>Max connections:</b> {max_conn}\n"
        
        # IP address
        ip = info.get("ip_address")
        if ip:
            report += f"🌐 <b>IP address:</b> {ip}\n"
        
        return report
        
    except Exception as e:
        return f"❌ <b>Ошибка получения webhook health:</b>\n{e}"
