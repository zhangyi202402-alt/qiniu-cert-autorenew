"""HTTP 冒烟：注册 → 凭证 → 配置档 → 添加域名 → 验证页。"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-32bytes-minimum!!")
os.environ["WEB_MASTER_KEY"] = base64.b64encode(os.urandom(32)).decode()
os.environ["DATABASE_URL"] = "sqlite://"


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m, "csrf_token missing in HTML"
    return m.group(1)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "e2e.db"
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
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    database_mod.engine = engine
    database_mod.SessionLocal = TestingSessionLocal

    def override_get_db():
        db = TestingSessionLocal()
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


def test_register_login_add_verify_flow(client: TestClient):
    r = client.get("/register")
    assert r.status_code == 200
    token = _csrf(r.text)

    r = client.post(
        "/register",
        data={
            "email": "e2e@example.com",
            "password": "password123",
            "csrf_token": token,
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/credentials"

    r = client.get("/settings/credentials")
    token = _csrf(r.text)
    r = client.post(
        "/settings/credentials",
        data={
            "name": "ali",
            "provider": "aliyun",
            "access_key": "ak",
            "secret_key": "sk",
            "cas_certificate_region": "cn-hangzhou",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/settings/credentials")
    token = _csrf(r.text)
    r = client.post(
        "/settings/credentials",
        data={
            "name": "qn",
            "provider": "qiniu",
            "access_key": "qak",
            "secret_key": "qsk",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/settings/profiles")
    token = _csrf(r.text)
    # 从下拉解析真实 credential id
    import re as _re

    dns_ids = _re.findall(
        r'name="dns_credential_id"[^>]*>.*?<option value="(\d+)"',
        r.text,
        flags=_re.S,
    )
    # 页面初始 HTML 可能 option 由 JS 填充；改为直接查库 session cookie 后用已知创建顺序
    # 注册后先建 ali(1) qn(2)；SQLite autoincrement 从 1
    r = client.post(
        "/settings/profiles",
        data={
            "name": "cdn",
            "dns_provider": "dns_ali",
            "dns_credential_id": "1",
            "deploy_type": "qiniu_cdn",
            "deploy_credential_id": "2",
            "suggested_targets": "cdn.example.com",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/certs/add")
    token = _csrf(r.text)
    r = client.post(
        "/certs/add",
        data={
            "name": "main",
            "acme_email": "ops@example.com",
            "profile_id": "1",
            "issue_domains": "example.com\n*.example.com",
            "cdn_domains": "cdn.example.com",
            "renew_days": "15",
            "csrf_token": token,
        },
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/certs/") and loc.endswith("/verify")

    r = client.get(loc)
    assert r.status_code == 200
    assert "_qcert-verify" in r.text
    assert "qcert-verify=" in r.text
    token = _csrf(r.text)

    with patch("app.ownership_service.query_txt", return_value=[]):
        r = client.post(
            loc.replace("/verify", "/verify/check"),
            data={"csrf_token": token},
        )
    assert r.status_code == 200
    assert "验证失败" in r.text

    r = client.get(loc)
    m = re.search(r"qcert-verify=([A-Za-z0-9_\-]+)", r.text)
    assert m
    expected = m.group(0)
    token = _csrf(r.text)

    with patch(
        "app.ownership_service.query_txt",
        return_value=[expected],
    ), patch("app.routers.certs._run_issue") as issue_mock:
        r = client.post(
            loc.replace("/verify", "/verify/check"),
            data={"csrf_token": token},
        )
        assert r.status_code == 200
        assert "验证成功" in r.text
        assert issue_mock.called

    r = client.get("/certs")
    assert r.status_code == 200
    assert "example.com" in r.text
