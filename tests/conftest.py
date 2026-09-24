import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from koffito.core.config import Settings
from koffito.main import create_app
from tests.support import SUPABASE_URL, FakeBackend, SigningKey, claims


@pytest.fixture
def signing_key() -> SigningKey:
    return SigningKey("kid-test")


@pytest.fixture
def backend(signing_key: SigningKey) -> FakeBackend:
    return FakeBackend(signing_key)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url=SUPABASE_URL,
        supabase_publishable_key="pub-key",
        supabase_service_role_key="sb_secret_test",
        koffito_backend_key="backend-key",
        rate_limit_enabled=False,
        _env_file=None,
    )


@pytest.fixture
def app(settings: Settings, backend: FakeBackend) -> FastAPI:
    return create_app(settings, transport=httpx.MockTransport(backend))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def token(signing_key: SigningKey, user_id: uuid.UUID) -> str:
    return signing_key.sign(claims(sub=str(user_id)))


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}
