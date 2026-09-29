"""Shared pytest fixtures."""

from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tmt_workspace.core.config import get_settings


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    settings = get_settings()
    settings.database_url = "sqlite+aiosqlite:///:memory:"
    from tmt_workspace.main import create_app

    application = create_app()
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
