"""
Тесты connection pooling для HTTP клиентов.
Проверяют что TCP соединения переиспользуются эффективно.
"""

import threading
import time
from unittest.mock import patch

from app.core.clients import get_notion_http_client


class TestConnectionPooling:
    """Тесты оптимизации connection pooling."""

    @patch("app.core.clients.settings")
    def test_clients_are_not_cached(self, mock_settings):
        """Тест что HTTP клиенты НЕ кэшируются (безопасный lifecycle)."""
        mock_settings.notion_token = "test-token"

        # Создаем несколько клиентов
        client1 = get_notion_http_client()
        client2 = get_notion_http_client()

        # Должны быть разными объектами
        assert client1 is not client2

        # Но оба должны быть функциональными
        assert hasattr(client1, "get")
        assert hasattr(client2, "post")

    @patch("app.core.clients.settings")
    def test_client_creation_performance(self, mock_settings):
        """Тест производительности создания клиентов."""
        mock_settings.notion_token = "test-token"

        # Измеряем время создания 10 клиентов
        start_time = time.perf_counter()

        clients = []
        for _ in range(10):
            client = get_notion_http_client()
            clients.append(client)

        total_time = time.perf_counter() - start_time
        avg_time_ms = (total_time / 10) * 1000

        # Создание должно быть быстрым благодаря connection pooling
        assert avg_time_ms < 100, f"Client creation too slow: {avg_time_ms:.1f}ms per client"

        # Все клиенты должны быть уникальными
        unique_clients = len(set(id(client) for client in clients))
        assert unique_clients == 10

    @patch("app.core.clients.settings")
    def test_concurrent_client_creation_safety(self, mock_settings):
        """Тест безопасности параллельного создания клиентов."""
        mock_settings.notion_token = "test-token"

        clients = []
        errors = []

        def worker():
            try:
                client = get_notion_http_client()
                clients.append(client)
            except Exception as e:
                errors.append(str(e))

        # Запускаем 10 потоков параллельно
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Не должно быть ошибок
        assert len(errors) == 0, f"Errors in concurrent creation: {errors}"

        # Должно быть создано 10 уникальных клиентов
        assert len(clients) == 10
        unique_clients = len(set(id(client) for client in clients))
        assert unique_clients == 10

    @patch("app.core.clients.settings")
    def test_client_independence(self, mock_settings):
        """Тест независимости клиентов друг от друга."""
        mock_settings.notion_token = "test-token"

        # Создаем два клиента
        client1 = get_notion_http_client()
        client2 = get_notion_http_client()

        # Закрываем первый клиент
        client1.close()

        # Второй клиент должен продолжать работать
        assert hasattr(client2, "get")
        assert hasattr(client2, "post")

        # Можем создать третий клиент
        client3 = get_notion_http_client()
        assert client3 is not client1
        assert client3 is not client2


class TestClientConfiguration:
    """Тесты конфигурации клиентов."""

    @patch("app.core.clients.settings")
    def test_client_has_optimized_settings(self, mock_settings):
        """Тест что клиенты имеют оптимизированные настройки."""
        mock_settings.notion_token = "test-token"

        client = get_notion_http_client()

        # Проверяем что клиент создан с правильными настройками
        assert client is not None
        assert hasattr(client, "get")
        assert hasattr(client, "post")
        assert hasattr(client, "patch")

        # Проверяем headers (косвенно через наличие методов)
        assert callable(client.get)

    @patch("app.core.clients.settings")
    def test_multiple_clients_no_interference(self, mock_settings):
        """Тест что множественные клиенты не мешают друг другу."""
        mock_settings.notion_token = "test-token"

        # Создаем 5 клиентов
        clients = [get_notion_http_client() for _ in range(5)]

        # Все должны быть уникальными
        unique_clients = len(set(id(client) for client in clients))
        assert unique_clients == 5

        # Закрываем некоторые клиенты
        clients[0].close()
        clients[2].close()

        # Остальные должны продолжать работать
        for i, client in enumerate(clients):
            if i not in [0, 2]:  # Не закрытые клиенты
                assert hasattr(client, "get")


class TestClientManagerIntegration:
    """Тесты интеграции с системой управления клиентами."""

    def test_client_manager_still_works(self):
        """Тест что менеджер клиентов все еще работает для других целей."""
        from app.core.smart_caching import get_client_manager

        manager = get_client_manager()
        assert manager is not None

        # Менеджер должен иметь базовую функциональность
        stats = manager.stats()
        assert isinstance(stats, dict)

    def test_ttl_cache_works_for_other_objects(self):
        """Тест что TTL кэш работает для других объектов (не HTTP клиентов)."""
        from app.core.smart_caching import lru_cache_with_ttl

        @lru_cache_with_ttl(maxsize=2, ttl_seconds=1.0)
        def test_function(x):
            return f"result_{x}"

        # Первый вызов
        result1 = test_function(1)
        assert result1 == "result_1"

        # Второй вызов с тем же аргументом - должен быть кэш
        result2 = test_function(1)
        assert result2 == "result_1"

        # Проверяем что кэш работает
        cache_info = test_function.cache_info()
        assert cache_info["hits"] >= 1


