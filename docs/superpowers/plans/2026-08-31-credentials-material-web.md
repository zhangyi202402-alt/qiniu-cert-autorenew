# Credentials Split + Material Web Full UI Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将通用云凭证拆成列表 / 添加 / 编辑三页，并用 Material Web（CDN）重写 Web 控制台全部 Jinja 页面，同时保持现有 FastAPI 表单字段与业务语义不变。

**Architecture:** 在 `base.html` 用 import map 加载 `@material/web`，全站表单改为 `md-*` Web Components + 原生 `csrf_token` hidden；凭证新增 GET `/settings/credentials/new` 与 GET `/settings/credentials/{id}/edit`，失败回跳对应表单页；少量布局 CSS 放 `web/static/app.css` 并由 FastAPI `StaticFiles` 挂载。

**Tech Stack:** FastAPI、Jinja2、Material Web（`esm.run/@material/web`）、Google Fonts（Roboto + Noto Sans SC + Material Symbols）、pytest / TestClient。

**Spec:** `docs/superpowers/specs/2026-08-31-credentials-m3-redesign.md`

## Global Constraints

- UI 库：Material Web，CDN + import map，**无** React/Vue/npm bundler。
- 主色方向：深青绿 `#0F6B58`；浅色 surface；覆盖 `--md-sys-color-*`。
- 表单继续 `method="post"` + FastAPI `Form(...)`；字段名不变；CSRF 用原生 `<input type="hidden" name="csrf_token">`。
- 凭证列表按厂商分组：阿里云 / 腾讯云 / 七牛。
- 编辑页不提供删除；删除仅列表（可用 confirm 或 `md-dialog`）。
- 创建失败 → `/settings/credentials/new?err=`；更新失败 → `/settings/credentials/{id}/edit?err=`。
- 不改 `credential_service` / 加密 / 兼容矩阵 / Alembic `002` 迁移语义。
- 不引入暗色主题。
- 测试：`cd web && PYTHONPATH=..:. ../.venv/bin/pytest -q`（或仓库约定的 venv）须全部通过。
- 用户可见文案中文；commit message 与仓库近期风格一致。

---

## 文件地图

| 路径 | 职责 |
|------|------|
| `web/app/main.py` | 挂载 `/static` → `web/static` |
| `web/static/app.css` | 布局、App bar、Banner、主列宽、`prefers-reduced-motion` |
| `web/app/templates/base.html` | Material Web import map、字体、主题 token、App 壳、Banner 片段 |
| `web/app/routers/certs.py` | 凭证 GET new/edit；POST 失败回跳；列表不再渲染混排表单 |
| `web/app/templates/settings/credentials.html` | **删除**（由下列三文件替代） |
| `web/app/templates/settings/credentials_list.html` | 凭证列表 |
| `web/app/templates/settings/credentials_new.html` | 添加凭证 |
| `web/app/templates/settings/credentials_edit.html` | 编辑凭证 |
| `web/app/templates/login.html` / `register.html` | Material Web 表单 |
| `web/app/templates/certs/*.html` | Material Web 重写 |
| `web/app/templates/settings/profiles.html` | Material Web 重写（保留现有兼容矩阵 JS 逻辑） |
| `web/tests/test_http_e2e.py` | 覆盖 new 路由与失败回跳；断言含 `md-` 控件 |
| `web/tests/test_credentials_pages.py` | **新建**：列表/添加/编辑路由与模板名 |
| `web/README.md` | 注明需现代浏览器 + 可访问 CDN/字体 |

---

### Task 1: Static mount + Material Web `base.html` 壳

**Files:**
- Create: `web/static/app.css`
- Modify: `web/app/main.py`
- Modify: `web/app/templates/base.html`
- Test: `web/tests/test_credentials_pages.py`（本任务先写「base 含 importmap」断言，随 Task 2 扩充）

**Interfaces:**
- Consumes: 现有 `base.html` blocks `title` / `content`；`user` 上下文
- Produces: `/static/app.css`；全站可用 `md-*` 自定义元素；CSS 变量 `--md-sys-color-primary` 等

- [ ] **Step 1: 写失败测试（静态资源与 base 标记）**

Create `web/tests/test_credentials_pages.py`:

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd /Users/Administrator/webroot/tools/qiniu-cert-autorenew/web
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_credentials_pages.py::test_static_app_css_served tests/test_credentials_pages.py::test_base_loads_material_web_importmap -v
```

Expected: FAIL（`/static/app.css` 404 或 base 无 importmap）

- [ ] **Step 3: 实现 `web/static/app.css`**

```css
:root {
  --md-sys-color-primary: #0f6b58;
  --md-sys-color-on-primary: #ffffff;
  --md-sys-color-primary-container: #a5f2d7;
  --md-sys-color-on-primary-container: #002117;
  --md-sys-color-surface: #f7f9f8;
  --md-sys-color-surface-container: #eceeec;
  --md-sys-color-surface-container-high: #e6e9e7;
  --md-sys-color-on-surface: #191c1b;
  --md-sys-color-on-surface-variant: #3d4945;
  --md-sys-color-outline: #6d7a75;
  --md-sys-color-outline-variant: #bcc9c3;
  --md-sys-color-error: #ba1a1a;
  --md-sys-color-error-container: #ffdad6;
  --app-max: 960px;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  font-family: "Noto Sans SC", Roboto, system-ui, sans-serif;
}

a { color: var(--md-sys-color-primary); text-decoration: none; }
a:hover { text-decoration: underline; }

.app-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  background: var(--md-sys-color-surface-container);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}

.app-bar__brand {
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--md-sys-color-on-surface);
  text-decoration: none;
}

.app-bar__nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.wrap {
  max-width: var(--app-max);
  margin: 0 auto;
  padding: 1.25rem;
}

.page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.page-head h1 {
  margin: 0;
  font-size: 1.75rem;
  letter-spacing: -0.03em;
}

.supporting {
  color: var(--md-sys-color-on-surface-variant);
  font-size: 0.95rem;
  line-height: 1.5;
  margin: 0.35rem 0 0;
}

.banner {
  padding: 0.85rem 1rem;
  border-radius: 12px;
  margin: 0 0 1rem;
}
.banner--ok {
  background: var(--md-sys-color-primary-container);
  color: var(--md-sys-color-on-primary-container);
}
.banner--err {
  background: var(--md-sys-color-error-container);
  color: #410002;
}

.section-card {
  background: var(--md-sys-color-surface-container-high);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: 16px;
  padding: 1rem 1.1rem;
  margin: 0 0 1rem;
}

.section-card h2 {
  margin: 0 0 0.75rem;
  font-size: 1.05rem;
}

.form-stack {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 1rem;
  max-width: 480px;
}

.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.md-danger {
  --md-text-button-label-text-color: var(--md-sys-color-error);
}

.auth-card {
  max-width: 420px;
  margin: 2rem auto;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
  }
}
```

- [ ] **Step 4: 在 `main.py` 挂载 StaticFiles**

在 `app = FastAPI(...)` 之后、`include_router` 之前加入：

```python
from fastapi.staticfiles import StaticFiles  # 与其它 import 一并整理到文件顶部

STATIC_DIR = _WEB_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
```

注意：`mount` 须在会捕获路径的路由之后或确保不遮蔽 API；本应用路由无具体路径，`/static` 挂载安全。若出现静态优先问题，把 `mount` 放到 `include_router` **之后**。

- [ ] **Step 5: 重写 `base.html`**

替换为（保留 `{% block content %}`）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}SSL 证书服务{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&family=Noto+Sans+SC:wght@400;500;700&family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/app.css">
  <!-- 内网可把下方 esm.run 换成镜像 -->
  <script type="importmap">
  {
    "imports": {
      "@material/web/": "https://esm.run/@material/web/"
    }
  }
  </script>
  <script type="module">
    import '@material/web/all.js';
    import {styles as typescaleStyles} from '@material/web/typography/md-typescale-styles.js';
    if (typescaleStyles?.styleSheet) {
      document.adoptedStyleSheets.push(typescaleStyles.styleSheet);
    }
  </script>
  <style>
    :root {
      --md-sys-color-primary: #0f6b58;
      --md-sys-color-on-primary: #ffffff;
      --md-sys-color-primary-container: #a5f2d7;
      --md-sys-color-on-primary-container: #002117;
    }
    md-icon { font-family: 'Material Symbols Outlined'; font-weight: normal; font-style: normal; }
  </style>
  {% block head %}{% endblock %}
</head>
<body>
  <header class="app-bar">
    <a class="app-bar__brand" href="/certs">Qiniu Cert Web</a>
    <nav class="app-bar__nav">
      {% if user is defined and user %}
        <md-text-button href="/certs">证书</md-text-button>
        <md-text-button href="/settings/credentials">凭证</md-text-button>
        <md-text-button href="/settings/profiles">配置档</md-text-button>
        <md-text-button href="/logout">退出</md-text-button>
      {% else %}
        <md-text-button href="/login">登录</md-text-button>
        <md-text-button href="/register">注册</md-text-button>
      {% endif %}
    </nav>
  </header>
  <main class="wrap">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

说明：`md-text-button` 的 `href` 属性以 Material Web 文档为准；若当前版本不支持 `href`，改为外包 `<a href="...">` 包 `md-text-button`，或用 `@click` + `location`。实现时以浏览器可点击跳转为准。

- [ ] **Step 6: 再跑 Step 2 测试**

Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/Administrator/webroot/tools/qiniu-cert-autorenew
git add web/static/app.css web/app/main.py web/app/templates/base.html web/tests/test_credentials_pages.py
git commit -m "$(cat <<'EOF'
feat(web): add Material Web base shell and static CSS

EOF
)"
```

若 `web/` 尚未被 git 跟踪，本步起将所需 `web/` 文件纳入版本库（勿提交 `web/.env`、`web/.venv`）。

---

### Task 2: 凭证路由拆分（TDD）

**Files:**
- Modify: `web/app/routers/certs.py`（credentials 段约 L86–188）
- Modify: `web/tests/test_credentials_pages.py`
- Modify: `web/tests/test_http_e2e.py`（创建成功后仍回列表；可选断言 Location）

**Interfaces:**
- Consumes: `create_credential` / `update_credential` / `delete_credential`；`credential_repo.list_credentials` / `get_credential`
- Produces:
  - `GET /settings/credentials` → `credentials_list.html`
  - `GET /settings/credentials/new` → `credentials_new.html`
  - `GET /settings/credentials/{cred_id}/edit` → `credentials_edit.html`
  - POST create 失败 → `303` to `/settings/credentials/new?err=...`
  - POST update 失败 → `303` to `/settings/credentials/{id}/edit?err=...`

- [ ] **Step 1: 扩展失败测试**

追加到 `test_credentials_pages.py`：

```python
def test_credentials_new_page(client: TestClient):
    _register(client)
    r = client.get("/settings/credentials/new")
    assert r.status_code == 200
    assert "添加凭证" in r.text
    assert 'name="provider"' in r.text or "provider" in r.text


def test_credentials_edit_page(client: TestClient):
    _register(client)
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
    )
    assert r.status_code == 303
    r = client.get("/settings/credentials/1/edit")
    assert r.status_code == 200
    assert "编辑凭证" in r.text
    assert "ali" in r.text


def test_create_error_redirects_to_new(client: TestClient):
    _register(client)
    r = client.get("/settings/credentials/new")
    token = _csrf(r.text)
    r = client.post(
        "/settings/credentials",
        data={
            "name": "x",
            "provider": "invalid",
            "access_key": "a",
            "secret_key": "b",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings/credentials/new?")
```

- [ ] **Step 2: 运行确认失败**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_credentials_pages.py -v
```

Expected: `new`/`edit` 404 或模板缺失

- [ ] **Step 3: 改路由（最小可用模板可先用临时 HTML 字符串，但推荐直接进入 Task 3 模板；本步至少改 Python）**

在 `certs.py` 凭证段替换/新增：

```python
@router.get("/settings/credentials", response_class=HTMLResponse)
def credentials_list_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    creds = credential_repo.list_credentials(db, user.id)
    by_provider = {"aliyun": [], "tencent": [], "qiniu": []}
    for c in creds:
        by_provider.setdefault(c.provider, []).append(c)
    return templates.TemplateResponse(
        request,
        "settings/credentials_list.html",
        _ctx(
            request,
            user=user,
            by_provider=by_provider,
            error=request.query_params.get("err"),
            ok=request.query_params.get("ok"),
        ),
    )


@router.get("/settings/credentials/new", response_class=HTMLResponse)
def credentials_new_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "settings/credentials_new.html",
        _ctx(
            request,
            user=user,
            error=request.query_params.get("err"),
        ),
    )


@router.get("/settings/credentials/{cred_id}/edit", response_class=HTMLResponse)
def credentials_edit_page(
    request: Request,
    cred_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cred = credential_repo.get_credential(db, cred_id, user.id)
    if not cred:
        return RedirectResponse("/settings/credentials?err=凭证不存在", status_code=303)
    return templates.TemplateResponse(
        request,
        "settings/credentials_edit.html",
        _ctx(
            request,
            user=user,
            cred=cred,
            error=request.query_params.get("err"),
        ),
    )


@router.post("/settings/credentials")
def credentials_create(...):  # 签名保持不变
    try:
        validate_csrf(request, csrf_token)
        create_credential(...)
        return RedirectResponse("/settings/credentials?ok=1", status_code=303)
    except CSRFError:
        return RedirectResponse("/settings/credentials/new?err=csrf", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/settings/credentials/new?err={exc}", status_code=303
        )


@router.post("/settings/credentials/{cred_id}/update")
def credentials_update(...):
    try:
        validate_csrf(request, csrf_token)
        update_credential(...)
        return RedirectResponse("/settings/credentials?ok=updated", status_code=303)
    except CSRFError:
        return RedirectResponse(
            f"/settings/credentials/{cred_id}/edit?err=csrf", status_code=303
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/settings/credentials/{cred_id}/edit?err={exc}", status_code=303
        )
```

**路由顺序：** `GET .../new` 必须注册在 `GET .../{cred_id}/edit` 之前（避免 `new` 被当成 id）。FastAPI 按声明顺序匹配。

删除对旧模板 `settings/credentials.html` 的引用。

- [ ] **Step 4: 若尚无模板，先建三份最小 Jinja（Task 3 再精修 Material）** 使测试能 200

最小 `credentials_new.html` 必须含「添加凭证」、`csrf_token`、`name="provider"`（可用原生 select 过渡，Task 3 换成 `md-outlined-select`）。

- [ ] **Step 5: 测试 PASS**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_credentials_pages.py -v
```

- [ ] **Step 6: Commit**

```bash
git add web/app/routers/certs.py web/tests/test_credentials_pages.py web/app/templates/settings/credentials_*.html
git commit -m "$(cat <<'EOF'
feat(web): split credential list/new/edit routes

EOF
)"
```

---

### Task 3: 凭证三页 Material Web 模板

**Files:**
- Create/overwrite: `web/app/templates/settings/credentials_list.html`
- Create/overwrite: `web/app/templates/settings/credentials_new.html`
- Create/overwrite: `web/app/templates/settings/credentials_edit.html`
- Delete: `web/app/templates/settings/credentials.html`
- Modify: `web/tests/test_credentials_pages.py`（断言 `md-outlined-text-field` / `md-filled-button`）

**Interfaces:**
- Consumes: Task 2 路由上下文 `by_provider` / `cred` / `error` / `ok` / `csrf_token`
- Produces: 符合规格的列表分组、添加/编辑表单字段名：`name`, `provider`, `access_key`, `secret_key`, `cas_certificate_region`, `csrf_token`

- [ ] **Step 1: 加强断言**

```python
def test_credentials_list_uses_material_controls(client: TestClient):
    _register(client)
    r = client.get("/settings/credentials")
    assert "md-filled-button" in r.text
    assert "/settings/credentials/new" in r.text
```

- [ ] **Step 2: 实现 `credentials_list.html`**

关键结构：

```html
{% extends "base.html" %}
{% block title %}云凭证 — SSL 证书服务{% endblock %}
{% block content %}
{% if ok %}<div class="banner banner--ok">已保存（{{ ok }}）</div>{% endif %}
{% if error %}<div class="banner banner--err">{{ error }}</div>{% endif %}
<div class="page-head">
  <div>
    <h1 class="md-typescale-headline-small">通用云凭证</h1>
    <p class="supporting">按云厂商保存密钥；用途在配置档里引用。列表不回显 Secret。</p>
  </div>
  <md-filled-button href="/settings/credentials/new">
    <md-icon slot="icon">add</md-icon>
    添加凭证
  </md-filled-button>
</div>
{% for provider, label in [('aliyun','阿里云'), ('tencent','腾讯云'), ('qiniu','七牛')] %}
<section class="section-card">
  <h2>{{ label }}</h2>
  {% set items = by_provider.get(provider, []) %}
  {% if items %}
  <md-list>
    {% for c in items %}
    <md-list-item>
      <div slot="headline">{{ c.name }}</div>
      <div slot="supporting-text">{{ label }}</div>
      <div slot="end">
        <md-text-button href="/settings/credentials/{{ c.id }}/edit">编辑</md-text-button>
        <form method="post" action="/settings/credentials/{{ c.id }}/delete" style="display:inline;" onsubmit="return confirm('确认删除？');">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <md-text-button class="md-danger" type="submit">删除</md-text-button>
        </form>
      </div>
    </md-list-item>
    {% endfor %}
  </md-list>
  {% else %}
  <p class="supporting">暂无凭证</p>
  {% endif %}
</section>
{% endfor %}
<p class="supporting">下一步：到 <a href="/settings/profiles">配置档</a> 组合 DNS + 部署方式。</p>
{% endblock %}
```

若 `md-filled-button` 不支持 `href`，改为：

```html
<a href="/settings/credentials/new" style="text-decoration:none;">
  <md-filled-button type="button">添加凭证</md-filled-button>
</a>
```

- [ ] **Step 3: 实现 `credentials_new.html`**

字段：`md-outlined-text-field`（name/access_key/secret_key/cas）、`md-outlined-select`（provider）。CAS 行用 `id="cas-field"`，JS 在 provider≠aliyun 时 `hidden`。

`md-outlined-select` 示例：

```html
<md-outlined-select name="provider" label="云厂商" id="provider" required>
  <md-select-option value="aliyun"><div slot="headline">阿里云</div></md-select-option>
  <md-select-option value="tencent"><div slot="headline">腾讯云</div></md-select-option>
  <md-select-option value="qiniu"><div slot="headline">七牛</div></md-select-option>
</md-outlined-select>
```

表单 actions：`md-outlined-button` 取消（链回列表）+ `md-filled-button type="submit"` 保存。

- [ ] **Step 4: 实现 `credentials_edit.html`**

- 展示厂商 chip（只读）
- `name` 预填 `cred.name`
- AK/SK placeholder「留空表示不修改」，`required` 去掉
- 阿里云显示 CAS；其它厂商 hidden 默认 `cn-hangzhou`
- **无删除按钮**

- [ ] **Step 5: 删除旧 `credentials.html`**

- [ ] **Step 6: 跑测试**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_credentials_pages.py tests/test_http_e2e.py -q
```

Expected: PASS（e2e 仍 POST `/settings/credentials`，不依赖旧单页）

- [ ] **Step 7: Commit**

```bash
git add web/app/templates/settings/ web/tests/test_credentials_pages.py
git commit -m "$(cat <<'EOF'
feat(web): Material Web templates for credential pages

EOF
)"
```

---

### Task 4: 登录 / 注册页 Material Web

**Files:**
- Modify: `web/app/templates/login.html`
- Modify: `web/app/templates/register.html`
- Test: 现有 `test_http_e2e.py::test_register_login_add_verify_flow`（注册仍 303）

- [ ] **Step 1: 重写 login（字段名不变）**

```html
{% extends "base.html" %}
{% block title %}登录 — SSL 证书服务{% endblock %}
{% block content %}
<div class="section-card auth-card">
  <h1 class="md-typescale-headline-small">登录</h1>
  {% if error %}<div class="banner banner--err">{{ error }}</div>{% endif %}
  <form method="post" action="/login" class="form-stack">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="next" value="{{ next or '/certs' }}">
    <md-outlined-text-field label="邮箱" type="email" name="email" required autocomplete="username"></md-outlined-text-field>
    <md-outlined-text-field label="密码" type="password" name="password" required autocomplete="current-password"></md-outlined-text-field>
    <div class="form-actions">
      <md-filled-button type="submit">登录</md-filled-button>
    </div>
  </form>
  <p class="supporting">没有账号？<a href="/register">注册</a></p>
</div>
{% endblock %}
```

- [ ] **Step 2: 同样方式重写 `register.html`**（保持现有 action/字段）

- [ ] **Step 3: 跑 e2e 注册段**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_http_e2e.py::test_register_login_add_verify_flow -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/app/templates/login.html web/app/templates/register.html
git commit -m "$(cat <<'EOF'
feat(web): Material Web login and register pages

EOF
)"
```

---

### Task 5: 证书页 Material Web

**Files:**
- Modify: `web/app/templates/certs/list.html`
- Modify: `web/app/templates/certs/add.html`
- Modify: `web/app/templates/certs/edit.html`
- Modify: `web/app/templates/certs/verify.html`
- Test: `tests/test_http_e2e.py`（验证页仍含 `_qcert-verify`）

**Interfaces:**
- Consumes: 现有模板变量（certs、profiles、profiles_json、error 等）一字不改语义
- Produces: 同字段名的 `md-outlined-text-field` / `md-outlined-select` / `md-filled-button`

- [ ] **Step 1: 逐页替换原生 input/button/table 为 Material 控件与 `section-card`**
  - `list.html`：表格可保留语义表或改 `md-list`；操作按钮改为 `md-text-button` / `md-filled-button`
  - `add.html` / `edit.html`：表单 `form-stack`；保留 `profiles_json` 预填 JS
  - `verify.html`：保留 TXT 展示与验证按钮文案（e2e 依赖「验证失败」「验证成功」）

- [ ] **Step 2: 跑测试**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest tests/test_http_e2e.py tests/test_auth_and_fsm.py -q
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/app/templates/certs/
git commit -m "$(cat <<'EOF'
feat(web): Material Web certificate pages

EOF
)"
```

---

### Task 6: 配置档页 Material Web

**Files:**
- Modify: `web/app/templates/settings/profiles.html`
- Test: `tests/test_http_e2e.py`（POST profiles 仍用 `dns_credential_id` 等）

- [ ] **Step 1: 重写 profiles 为 Material 控件**
  - 保留现有 `creds` JSON + `getDisplayOptions` / 兼容矩阵过滤 JS；仅把 `<select class="dns-cred">` 换成可被 JS 填充的 `md-outlined-select`，**或**在 Material 外壳下继续用原生 `<select>` 若 md-select 动态填充成本过高。
  - **实现约束：** 若 `md-outlined-select` 动态 option 在一天内搞不定，允许配置档凭证下拉保持原生 `<select>`，但按钮/文本框仍用 Material（在 README 记一笔「profiles 下拉原生」）。优先尝试 md-select。

- [ ] **Step 2: 确保隐藏/动态 option 仍带 `name="dns_credential_id"` 且 value 可被 TestClient POST**

- [ ] **Step 3: 跑全量 web 测试**

```bash
PYTHONPATH=..:. ../.venv/bin/pytest -q
```

Expected: 全部 PASS（当前基线 27；本 plan 新增用例后应 ≥29）

- [ ] **Step 4: Commit**

```bash
git add web/app/templates/settings/profiles.html
git commit -m "$(cat <<'EOF'
feat(web): Material Web deploy profiles page

EOF
)"
```

---

### Task 7: README 与验收扫尾

**Files:**
- Modify: `web/README.md`
- Optional: 手动浏览器冒烟清单写入 README「浏览器要求」小节

- [ ] **Step 1: README 增加**

```markdown
## 浏览器与 CDN

控制台 UI 使用 Material Web（CDN `esm.run`）与 Google Fonts。需现代浏览器（支持 Web Components / import maps）。
内网环境请将 `base.html` 中 import map 与字体链接改为可达镜像。
```

并更新用户流程第 2 步：凭证为「列表 → 添加 / 编辑」分页面。

- [ ] **Step 2: 全量测试**

```bash
cd web && PYTHONPATH=..:. ../.venv/bin/pytest -q
```

- [ ] **Step 3: Docker 重建冒烟（可选但推荐）**

```bash
cd web && docker compose -f docker-compose.web.yml up -d --build web
curl -sS -o /dev/null -w 'login %{http_code}\n' http://127.0.0.1:8000/login
```

Expected: `login 200`；HTML 含 `importmap` 与 `/static/app.css`

- [ ] **Step 4: Commit**

```bash
git add web/README.md
git commit -m "$(cat <<'EOF'
docs(web): note Material Web CDN and credential page split

EOF
)"
```

---

## Spec 覆盖自检

| Spec 项 | Task |
|---------|------|
| Material Web CDN + import map | 1 |
| 主题 primary `#0F6B58` | 1 |
| 凭证 list/new/edit 路由与失败回跳 | 2 |
| 列表按厂商分组 + CTA | 3 |
| 编辑无删除、密钥留空 | 3 |
| 登录/注册/证书/配置档重写 | 4–6 |
| 无 bundler / 业务语义不变 | Global + 各 Task |
| README CDN/浏览器 | 7 |
| e2e 通过 | 3–7 |

无占位符步骤；profiles 下拉若退回原生 select 已写明接受条件。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-31-credentials-material-web.md`.

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每任务新开子代理，任务间复查，迭代快  
2. **Inline Execution** — 本会话按 executing-plans 批量推进并设检查点  

选哪一种？
