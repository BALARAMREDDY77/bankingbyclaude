"""
Unit Tests — Configuration System
Tests that settings load correctly and computed properties work.
"""

import pytest
from app.core.config.settings import (
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    Environment,
)


class TestDatabaseSettings:
    @pytest.mark.unit
    def test_async_url_format(self):
        db = DatabaseSettings(
            host="localhost",
            port=5432,
            name="testdb",
            user="testuser",
            password="testpass",
        )
        url = db.async_url
        assert url.startswith("postgresql+asyncpg://")
        assert "testuser:testpass@localhost:5432/testdb" in url

    @pytest.mark.unit
    def test_sync_url_format(self):
        db = DatabaseSettings(
            host="localhost",
            port=5432,
            name="testdb",
            user="testuser",
            password="testpass",
        )
        url = db.sync_url
        assert url.startswith("postgresql+psycopg2://")


class TestRedisSettings:
    @pytest.mark.unit
    def test_url_with_password(self):
        redis = RedisSettings(
            host="localhost",
            port=6379,
            password="secret",
            db=0,
        )
        assert redis.url == "redis://:secret@localhost:6379/0"

    @pytest.mark.unit
    def test_url_without_password(self):
        redis = RedisSettings(
            host="localhost",
            port=6379,
            password="",
            db=0,
        )
        assert redis.url == "redis://localhost:6379/0"


class TestAppSettings:
    @pytest.mark.unit
    def test_is_development_flag(self):
        settings = AppSettings(APP_ENV="development")
        assert settings.is_development is True
        assert settings.is_production is False

    @pytest.mark.unit
    def test_is_production_flag(self):
        settings = AppSettings(APP_ENV="production")
        assert settings.is_production is True
        assert settings.is_development is False

    @pytest.mark.unit
    def test_debug_only_in_dev(self):
        dev = AppSettings(APP_ENV="development")
        prod = AppSettings(APP_ENV="production")
        assert dev.debug is True
        assert prod.debug is False
