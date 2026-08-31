"""认证路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import authenticate, register_user
from app.database import get_db
from app.dependencies import get_current_user_optional
from app.security import (
    CSRFError,
    client_ip,
    ensure_csrf_token,
    login_rate_allow,
    login_rate_clear,
    login_rate_fail,
    validate_csrf,
)

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


def _ctx(request: Request, **extra):
    data = {"csrf_token": ensure_csrf_token(request), "request": request}
    data.update(extra)
    return data


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/certs", status_code=303)
    return templates.TemplateResponse(
        request, "register.html", _ctx(request, error=None)
    )


@router.post("/register")
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
    except CSRFError:
        return templates.TemplateResponse(
            request,
            "register.html",
            _ctx(request, error="表单已过期，请刷新后重试"),
            status_code=403,
        )
    try:
        user = register_user(db, email, password)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register.html",
            _ctx(request, error=str(exc)),
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/settings/credentials", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str = "/certs",
    user=Depends(get_current_user_optional),
):
    if user:
        return RedirectResponse(next or "/certs", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", _ctx(request, error=None, next=next)
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next: str = Form("/certs"),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
    except CSRFError:
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(request, error="表单已过期，请刷新后重试", next=next),
            status_code=403,
        )

    ip = client_ip(request)
    if not login_rate_allow(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(
                request,
                error="登录尝试过多，请 1 分钟后再试",
                next=next,
            ),
            status_code=429,
        )

    user = authenticate(db, email, password)
    if not user:
        login_rate_fail(ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(request, error="邮箱或密码错误", next=next),
            status_code=400,
        )
    login_rate_clear(ip)
    request.session["user_id"] = user.id
    return RedirectResponse(next or "/certs", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
