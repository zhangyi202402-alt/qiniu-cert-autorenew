"""凭证页路由拆分与 Material Web 壳冒烟。"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-32bytes-minimum!!")
os.environ["WEB_MASTER_KEY"] = base64.b64encode(os.urandom(32)).decode()
os.environ["DATABASE_URL"] = "sqlite://"


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "csrf_token missing"
    return m.group(1)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "cred_pages.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEB_DATA_ROOT", str(tmp_path / "webdata"))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    from app import settings as settings_mod
    from app import database as database_mod
    from app.database import Base

    settings_mod.get_settings.cache_clear()
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    database_mod.engine = engine
    database_mod.SessionLocal = Session

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    from app.main import app
    from app.database import get_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
    settings_mod.get_settings.cache_clear()


def _register(client: TestClient) -> None:
    r = client.get("/register")
    token = _csrf(r.text)
    r = client.post(
        "/register",
        data={
            "email": "ui@example.com",
            "password": "password123",
            "csrf_token": token,
        },
    )
    assert r.status_code == 303


def test_static_app_css_served(client: TestClient):
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "md-sys-color" in r.text or "--app-" in r.text


def test_base_loads_material_web_importmap(client: TestClient):
    _register(client)
    r = client.get("/settings/credentials")
    assert r.status_code == 200
    assert 'type="importmap"' in r.text
    assert "@material/web/" in r.text
    assert "md-filled-button" in r.text or "/static/app.css" in r.text
