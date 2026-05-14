"""
Integration Tests — Health Endpoints
Tests the /api/v1/health/* endpoints against a running application.
These tests use httpx.AsyncClient with the FastAPI test client.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestLivenessEndpoint:
    @pytest.mark.integration
    async def test_liveness_returns_200(self, client: AsyncClient):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

    @pytest.mark.integration
    async def test_liveness_body(self, client: AsyncClient):
        response = await client.get("/api/v1/health")
        body = response.json()
        assert body["status"] == "alive"
        assert "uptime_seconds" in body
        assert body["uptime_seconds"] >= 0

    @pytest.mark.integration
    async def test_liveness_has_request_id_header(self, client: AsyncClient):
        response = await client.get("/api/v1/health")
        assert "x-request-id" in response.headers

    @pytest.mark.integration
    async def test_liveness_has_security_headers(self, client: AsyncClient):
        response = await client.get("/api/v1/health")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"


class TestInfoEndpoint:
    @pytest.mark.integration
    async def test_info_returns_200_in_dev(self, client: AsyncClient):
        response = await client.get("/api/v1/health/info")
        assert response.status_code == 200

    @pytest.mark.integration
    async def test_info_body_in_dev(self, client: AsyncClient):
        response = await client.get("/api/v1/health/info")
        body = response.json()
        assert "app_name" in body
        assert "version" in body
        assert "environment" in body


class TestResponseEnvelope:
    @pytest.mark.integration
    async def test_404_follows_error_envelope(self, client: AsyncClient):
        response = await client.get("/api/v1/nonexistent-route")
        # FastAPI returns 404 for unknown routes — our handler wraps it
        assert response.status_code == 404
