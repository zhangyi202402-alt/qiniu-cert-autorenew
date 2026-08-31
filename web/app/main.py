"""FastAPI 入口。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# 保证仓库根与 web/ 可导入
_WEB_DIR = Path(__file__).resolve().parents[1]
_ROOT = _WEB_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))

from app.dependencies import LoginRequired  # noqa: E402
from app.routers import auth, certs  # noqa: E402
from app.settings import get_settings  # noqa: E402

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

TEMPLATES_DIR = str(_WEB_DIR / "app" / "templates")
# 覆盖各路由中的相对 templates 路径
auth.templates = Jinja2Templates(directory=TEMPLATES_DIR)
certs.templates = Jinja2Templates(directory=TEMPLATES_DIR)

app = FastAPI(title="Qiniu Cert Web", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="qcert_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=False,
)
app.include_router(auth.router)
app.include_router(certs.router)

STATIC_DIR = _WEB_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(
        url=f"/login?next={exc.next_path}", status_code=303
    )


@app.on_event("startup")
def on_startup() -> None:
    settings.web_data_root.mkdir(parents=True, exist_ok=True)
