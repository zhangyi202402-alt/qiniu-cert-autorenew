"""证书、凭证、配置档路由。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.cert_service import CertService, CredentialsError, OwnershipError
from app.credential_service import (
    create_credential,
    create_profile,
    delete_credential,
    delete_profile,
    update_credential,
    update_profile,
)
from app.database import SessionLocal, get_db
from app.dependencies import get_current_user, get_current_user_optional
from app.models import User
from app.ownership_service import OwnershipService
from app.repositories import cert_repo, credential_repo
from app.renew_hint import job_was_no_renewal, renew_hint
from app.schemas import (
    CertCreateForm,
    CertUpdateForm,
    format_deploy_targets_for_form,
    parse_deploy_targets_form,
    parse_domain_lines,
    parse_suggested_targets_text,
)
from app.security import CSRFError, ensure_csrf_token, validate_csrf
from app.settings import get_settings

router = APIRouter(tags=["certs"])
templates = Jinja2Templates(directory="app/templates")


def _ctx(request: Request, **extra):
    data = {"csrf_token": ensure_csrf_token(request), "request": request}
    data.update(extra)
    return data


def _run_issue(cert_id: int) -> None:
    db = SessionLocal()
    try:
        CertService(db).issue_certificate(cert_id, job_type="issue")
    finally:
        db.close()


def _run_retry(cert_id: int) -> None:
    db = SessionLocal()
    try:
        CertService(db).issue_certificate(cert_id, job_type="retry")
    finally:
        db.close()


def _run_deploy(cert_id: int) -> None:
    db = SessionLocal()
    try:
        CertService(db).deploy_certificate(cert_id)
    finally:
        db.close()


def _run_renew(cert_id: int) -> None:
    db = SessionLocal()
    try:
        CertService(db).renew_certificate(cert_id)
    finally:
        db.close()


def _has_profiles(db: Session, user_id: int) -> bool:
    return bool(credential_repo.list_profiles(db, user_id))


def _profiles_json(profiles) -> str:
    return json.dumps(
        {
            str(p.id): {
                "deploy_type": p.deploy_type,
                "suggested": p.suggested_targets_json or [],
            }
            for p in profiles
        }
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/certs", status_code=303)
    return RedirectResponse("/login", status_code=303)


# ----- credentials -----


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
def credentials_create(
    request: Request,
    name: str = Form(...),
    provider: str = Form(...),
    access_key: str = Form(...),
    secret_key: str = Form(...),
    cas_certificate_region: str = Form("cn-hangzhou"),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        create_credential(
            db,
            user.id,
            name=name,
            provider=provider,
            access_key=access_key,
            secret_key=secret_key,
            cas_certificate_region=cas_certificate_region,
        )
        return RedirectResponse("/settings/credentials?ok=1", status_code=303)
    except CSRFError:
        return RedirectResponse("/settings/credentials/new?err=csrf", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/settings/credentials/new?err={exc}", status_code=303
        )


@router.post("/settings/credentials/{cred_id}/update")
def credentials_update(
    request: Request,
    cred_id: int,
    name: str = Form(...),
    access_key: str = Form(""),
    secret_key: str = Form(""),
    cas_certificate_region: str = Form("cn-hangzhou"),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        update_credential(
            db,
            user.id,
            cred_id,
            name=name,
            access_key=access_key or None,
            secret_key=secret_key or None,
            cas_certificate_region=cas_certificate_region,
        )
        return RedirectResponse("/settings/credentials?ok=updated", status_code=303)
    except CSRFError:
        return RedirectResponse(
            f"/settings/credentials/{cred_id}/edit?err=csrf", status_code=303
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/settings/credentials/{cred_id}/edit?err={exc}", status_code=303
        )


@router.post("/settings/credentials/{cred_id}/delete")
def credentials_delete(
    request: Request,
    cred_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        delete_credential(db, user.id, cred_id)
        return RedirectResponse("/settings/credentials?ok=deleted", status_code=303)
    except CSRFError:
        return RedirectResponse("/settings/credentials?err=csrf", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/settings/credentials?err={exc}", status_code=303)


# ----- profiles -----


def _credentials_json(creds) -> str:
    return json.dumps(
        [{"id": c.id, "name": c.name, "provider": c.provider} for c in creds]
    )


def _suggested_targets_textarea(deploy_type: str, suggested) -> str:
    lines: list[str] = []
    for t in suggested or []:
        if deploy_type == "qiniu_cdn" and t.get("type") == "qiniu_cdn":
            lines.extend(t.get("domains") or [])
        elif deploy_type == "aliyun_clb" and t.get("type") == "aliyun_clb":
            parts = [
                t.get("region_id", ""),
                t.get("load_balancer_id", ""),
                str(t.get("listener_port") or 443),
            ]
            if t.get("probe_host"):
                parts.append(t["probe_host"])
            lines.append(",".join(parts))
    return "\n".join(lines)


@router.get("/settings/profiles", response_class=HTMLResponse)
def profiles_list_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profiles = credential_repo.list_profiles(db, user.id)
    return templates.TemplateResponse(
        request,
        "settings/profiles_list.html",
        _ctx(
            request,
            user=user,
            profiles=profiles,
            error=request.query_params.get("err"),
            ok=request.query_params.get("ok"),
        ),
    )


@router.get("/settings/profiles/new", response_class=HTMLResponse)
def profiles_new_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    creds = credential_repo.list_credentials(db, user.id)
    return templates.TemplateResponse(
        request,
        "settings/profiles_new.html",
        _ctx(
            request,
            user=user,
            credentials=creds,
            credentials_json=_credentials_json(creds),
            error=request.query_params.get("err"),
        ),
    )


@router.get("/settings/profiles/{profile_id}/edit", response_class=HTMLResponse)
def profiles_edit_page(
    request: Request,
    profile_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = credential_repo.get_profile(db, profile_id, user.id)
    if not profile:
        return RedirectResponse("/settings/profiles?err=配置档不存在", status_code=303)
    creds = credential_repo.list_credentials(db, user.id)
    return templates.TemplateResponse(
        request,
        "settings/profiles_edit.html",
        _ctx(
            request,
            user=user,
            profile=profile,
            credentials=creds,
            credentials_json=_credentials_json(creds),
            suggested_targets_text=_suggested_targets_textarea(
                profile.deploy_type, profile.suggested_targets_json
            ),
            error=request.query_params.get("err"),
        ),
    )


@router.post("/settings/profiles")
def profiles_create(
    request: Request,
    name: str = Form(...),
    dns_provider: str = Form(...),
    dns_credential_id: int = Form(...),
    deploy_type: str = Form(...),
    deploy_credential_id: int = Form(...),
    suggested_targets: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        suggested = parse_suggested_targets_text(deploy_type, suggested_targets)
        create_profile(
            db,
            user.id,
            name=name,
            dns_provider=dns_provider,
            dns_credential_id=dns_credential_id,
            deploy_type=deploy_type,
            deploy_credential_id=deploy_credential_id,
            suggested_targets_json=suggested,
        )
        return RedirectResponse("/settings/profiles?ok=1", status_code=303)
    except CSRFError:
        return RedirectResponse("/settings/profiles/new?err=csrf", status_code=303)
    except (ValueError, json.JSONDecodeError) as exc:
        return RedirectResponse(f"/settings/profiles/new?err={exc}", status_code=303)


@router.post("/settings/profiles/{profile_id}/update")
def profiles_update(
    request: Request,
    profile_id: int,
    name: str = Form(...),
    dns_provider: str = Form(...),
    dns_credential_id: int = Form(...),
    deploy_type: str = Form(...),
    deploy_credential_id: int = Form(...),
    suggested_targets: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        suggested = parse_suggested_targets_text(deploy_type, suggested_targets)
        update_profile(
            db,
            user.id,
            profile_id,
            name=name,
            dns_provider=dns_provider,
            dns_credential_id=dns_credential_id,
            deploy_type=deploy_type,
            deploy_credential_id=deploy_credential_id,
            suggested_targets_json=suggested if suggested is not None else [],
        )
        return RedirectResponse("/settings/profiles?ok=updated", status_code=303)
    except CSRFError:
        return RedirectResponse(
            f"/settings/profiles/{profile_id}/edit?err=csrf", status_code=303
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return RedirectResponse(
            f"/settings/profiles/{profile_id}/edit?err={exc}", status_code=303
        )


@router.post("/settings/profiles/{profile_id}/delete")
def profiles_delete(
    request: Request,
    profile_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        delete_profile(db, user.id, profile_id)
        return RedirectResponse("/settings/profiles?ok=deleted", status_code=303)
    except CSRFError:
        return RedirectResponse("/settings/profiles?err=csrf", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/settings/profiles?err={exc}", status_code=303)


from qiniu_cert.cert_utils import tls_not_after

_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


def _fmt_expiry_local(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return utc.astimezone(_DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def _days_until(expires: datetime, now: datetime) -> int:
    return int((expires - now).total_seconds() // 86400)


def _probe_host_for_cert(cert) -> str:
    """选取 TLS 探活域名：优先 deploy 目标，否则 primary。"""
    for target in cert.deploy_targets or []:
        if not isinstance(target, dict):
            continue
        if target.get("type") == "qiniu_cdn":
            domains = target.get("domains") or []
            if domains:
                return str(domains[0]).strip().lower().rstrip(".")
        if target.get("type") == "aliyun_clb":
            probe = target.get("probe_host")
            if probe:
                return str(probe).strip().lower().rstrip(".")
    return cert.primary_domain.rstrip(".")


# ----- certificates -----


@router.get("/certs", response_class=HTMLResponse)
def certs_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    certs = cert_repo.list_for_user(db, user.id)
    latest_jobs = {c.id: cert_repo.latest_job(db, c.id) for c in certs}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days_left: dict[int, int | None] = {}
    deployed_expires: dict[int, datetime | None] = {}
    deployed_days_left: dict[int, int | None] = {}
    expiry_labels: dict[int, str | None] = {}
    expiry_display: dict[int, str | None] = {}
    expiry_mismatch: dict[int, bool] = {}
    for c in certs:
        if c.expires_at:
            days_left[c.id] = _days_until(c.expires_at, now)
        else:
            days_left[c.id] = None

        probe_host = _probe_host_for_cert(c)
        live = tls_not_after(probe_host, server_hostname=c.primary_domain.rstrip("."))
        deployed_expires[c.id] = live
        if live:
            deployed_days_left[c.id] = _days_until(live, now)
        else:
            deployed_days_left[c.id] = None

        if live:
            expiry_display[c.id] = _fmt_expiry_local(live)
            expiry_labels[c.id] = "线上"
            local_days = days_left.get(c.id)
            live_days = deployed_days_left[c.id]
            expiry_mismatch[c.id] = (
                local_days is not None
                and live_days is not None
                and abs(local_days - live_days) > 1
            )
        elif c.expires_at:
            expiry_display[c.id] = _fmt_expiry_local(c.expires_at)
            expiry_labels[c.id] = "本地"
            expiry_mismatch[c.id] = False
        else:
            expiry_display[c.id] = None
            expiry_labels[c.id] = None
            expiry_mismatch[c.id] = False
    renew_hints = {}
    job_no_renewal: dict[int, bool] = {}
    for c in certs:
        renew_hints[c.id] = renew_hint(
            expires_at=c.expires_at,
            renew_days=c.renew_days,
            now=now,
            enabled=c.enabled,
            verification_status=c.verification_status,
        )
        job = latest_jobs.get(c.id)
        job_no_renewal[c.id] = bool(
            job
            and job.job_type == "renew"
            and job.status == "success"
            and job_was_no_renewal(job.log_tail)
        )
    return templates.TemplateResponse(
        request,
        "certs/list.html",
        _ctx(
            request,
            user=user,
            certs=certs,
            latest_jobs=latest_jobs,
            days_left=days_left,
            deployed_days_left=deployed_days_left,
            expiry_display=expiry_display,
            expiry_labels=expiry_labels,
            expiry_mismatch=expiry_mismatch,
            local_expiry_display={
                c.id: _fmt_expiry_local(c.expires_at) if c.expires_at else None
                for c in certs
            },
            renew_hints=renew_hints,
            job_no_renewal=job_no_renewal,
            has_profiles=_has_profiles(db, user.id),
            err=request.query_params.get("err"),
            ok=request.query_params.get("ok"),
        ),
    )


@router.get("/certs/add", response_class=HTMLResponse)
def certs_add_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    profiles = credential_repo.list_profiles(db, user.id)
    return templates.TemplateResponse(
        request,
        "certs/add.html",
        _ctx(
            request,
            user=user,
            error=None,
            default_renew_days=settings.default_renew_days,
            profiles=profiles,
            profiles_json=_profiles_json(profiles),
            form={},
        ),
    )


@router.post("/certs/add")
def certs_add_submit(
    request: Request,
    name: str = Form(...),
    acme_email: str = Form(...),
    profile_id: int = Form(...),
    issue_domains: str = Form(...),
    cdn_domains: str = Form(""),
    clb_targets: str = Form(""),
    renew_days: int = Form(15),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    profiles = credential_repo.list_profiles(db, user.id)

    def _err(msg: str, code: int = 400):
        return templates.TemplateResponse(
            request,
            "certs/add.html",
            _ctx(
                request,
                user=user,
                error=msg,
                default_renew_days=settings.default_renew_days,
                profiles=profiles,
                profiles_json=_profiles_json(profiles),
                form={
                    "name": name,
                    "acme_email": acme_email,
                    "profile_id": profile_id,
                    "issue_domains": issue_domains,
                    "cdn_domains": cdn_domains,
                    "clb_targets": clb_targets,
                    "renew_days": renew_days,
                },
            ),
            status_code=code,
        )

    try:
        validate_csrf(request, csrf_token)
    except CSRFError:
        return _err("表单已过期，请刷新后重试", 403)

    profile = credential_repo.get_profile(db, profile_id, user.id)
    if not profile:
        return _err("配置档不存在")

    try:
        targets = parse_deploy_targets_form(
            profile.deploy_type,
            cdn_domains_text=cdn_domains,
            clb_targets_text=clb_targets,
        )
        form = CertCreateForm(
            name=name,
            acme_email=acme_email,
            profile_id=profile_id,
            issue_domains=parse_domain_lines(issue_domains),
            deploy_targets=targets,
            renew_days=max(7, min(60, renew_days)),
        )
        cert = CertService(db, settings).create_certificate(user.id, form)
    except (ValueError, json.JSONDecodeError) as exc:
        return _err(str(exc))
    return RedirectResponse(f"/certs/{cert.id}/verify", status_code=303)


@router.get("/certs/{cert_id}/edit", response_class=HTMLResponse)
def certs_edit_page(
    request: Request,
    cert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cert = cert_repo.get_for_user(db, cert_id, user.id)
    if not cert:
        return RedirectResponse("/certs", status_code=303)
    settings = get_settings()
    profiles = credential_repo.list_profiles(db, user.id)
    profile = credential_repo.get_profile(db, cert.profile_id, user.id)
    deploy_type = profile.deploy_type if profile else "qiniu_cdn"
    filled = format_deploy_targets_for_form(deploy_type, cert.deploy_targets or [])
    return templates.TemplateResponse(
        request,
        "certs/edit.html",
        _ctx(
            request,
            user=user,
            cert=cert,
            error=None,
            default_renew_days=cert.renew_days or settings.default_renew_days,
            profiles=profiles,
            profiles_json=_profiles_json(profiles),
            form={
                "name": cert.name,
                "acme_email": cert.acme_email,
                "profile_id": cert.profile_id,
                "issue_domains": "\n".join(cert.issue_domains or []),
                "cdn_domains": filled["cdn_domains"],
                "clb_targets": filled["clb_targets"],
                "renew_days": cert.renew_days,
            },
        ),
    )


@router.post("/certs/{cert_id}/edit")
def certs_edit_submit(
    request: Request,
    cert_id: int,
    name: str = Form(...),
    acme_email: str = Form(...),
    profile_id: int = Form(...),
    issue_domains: str = Form(...),
    cdn_domains: str = Form(""),
    clb_targets: str = Form(""),
    renew_days: int = Form(15),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cert = cert_repo.get_for_user(db, cert_id, user.id)
    if not cert:
        return RedirectResponse("/certs", status_code=303)
    settings = get_settings()
    profiles = credential_repo.list_profiles(db, user.id)

    def _err(msg: str, code: int = 400):
        return templates.TemplateResponse(
            request,
            "certs/edit.html",
            _ctx(
                request,
                user=user,
                cert=cert,
                error=msg,
                default_renew_days=renew_days,
                profiles=profiles,
                profiles_json=_profiles_json(profiles),
                form={
                    "name": name,
                    "acme_email": acme_email,
                    "profile_id": profile_id,
                    "issue_domains": issue_domains,
                    "cdn_domains": cdn_domains,
                    "clb_targets": clb_targets,
                    "renew_days": renew_days,
                },
            ),
            status_code=code,
        )

    try:
        validate_csrf(request, csrf_token)
        profile = credential_repo.get_profile(db, profile_id, user.id)
        if not profile:
            return _err("配置档不存在")
        targets = parse_deploy_targets_form(
            profile.deploy_type,
            cdn_domains_text=cdn_domains,
            clb_targets_text=clb_targets,
        )
        updated = CertService(db, settings).update_certificate(
            cert_id,
            user.id,
            CertUpdateForm(
                name=name,
                acme_email=acme_email,
                profile_id=profile_id,
                issue_domains=parse_domain_lines(issue_domains),
                deploy_targets=targets,
                renew_days=max(7, min(60, renew_days)),
            ),
        )
    except CSRFError:
        return _err("表单已过期，请刷新后重试", 403)
    except (ValueError, json.JSONDecodeError) as exc:
        return _err(str(exc))

    if updated.verification_status != "verified":
        return RedirectResponse(f"/certs/{cert_id}/verify", status_code=303)
    return RedirectResponse("/certs?ok=updated", status_code=303)


@router.get("/certs/{cert_id}/verify", response_class=HTMLResponse)
def cert_verify_page(
    request: Request,
    cert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cert = cert_repo.get_for_user(db, cert_id, user.id)
    if not cert:
        return RedirectResponse("/certs", status_code=303)
    ownership = OwnershipService()
    profile = credential_repo.get_profile(db, cert.profile_id, user.id)
    return templates.TemplateResponse(
        request,
        "certs/verify.html",
        _ctx(
            request,
            user=user,
            cert=cert,
            expected_txt=ownership.expected_txt(cert.verification_token),
            message=None,
            has_profiles=bool(profile),
        ),
    )


@router.post("/certs/{cert_id}/verify/check")
def cert_verify_check(
    request: Request,
    cert_id: int,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
    except CSRFError:
        return RedirectResponse("/certs", status_code=303)
    cert = cert_repo.get_for_user(db, cert_id, user.id)
    if not cert:
        return RedirectResponse("/certs", status_code=303)
    ownership = OwnershipService()
    result = ownership.verify_certificate(db, cert_id)
    cert = cert_repo.get(db, cert_id)
    assert cert is not None
    profile = credential_repo.get_profile(db, cert.profile_id, user.id)
    message = "验证成功！" if result.ok else f"验证失败：{result.message}"
    ready = result.ok and profile and cert.deploy_targets
    if ready and cert.status in ("pending_verification", "failed"):
        background_tasks.add_task(_run_issue, cert_id)
        message += " 已开始签发…"
    elif result.ok and not ready:
        message += " 配置档或部署目标不完整，无法签发。"
    return templates.TemplateResponse(
        request,
        "certs/verify.html",
        _ctx(
            request,
            user=user,
            cert=cert,
            expected_txt=ownership.expected_txt(cert.verification_token),
            message=message,
            has_profiles=bool(profile),
        ),
    )


@router.post("/certs/{cert_id}/retry")
def cert_retry(
    request: Request,
    cert_id: int,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        CertService(db).retry(cert_id, user.id)
        background_tasks.add_task(_run_retry, cert_id)
    except CSRFError:
        return RedirectResponse("/certs?err=csrf", status_code=303)
    except (ValueError, OwnershipError, CredentialsError) as exc:
        return RedirectResponse(f"/certs?err={exc}", status_code=303)
    return RedirectResponse("/certs?ok=retry_started", status_code=303)


@router.post("/certs/{cert_id}/deploy")
def cert_deploy(
    request: Request,
    cert_id: int,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        CertService(db).deploy_now(cert_id, user.id)
        background_tasks.add_task(_run_deploy, cert_id)
    except CSRFError:
        return RedirectResponse("/certs?err=csrf", status_code=303)
    except (ValueError, OwnershipError, CredentialsError) as exc:
        return RedirectResponse(f"/certs?err={exc}", status_code=303)
    return RedirectResponse("/certs?ok=deploy_started", status_code=303)


@router.post("/certs/{cert_id}/renew")
def cert_renew(
    request: Request,
    cert_id: int,
    background_tasks: BackgroundTasks,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        CertService(db).renew_now(cert_id, user.id)
        background_tasks.add_task(_run_renew, cert_id)
    except CSRFError:
        return RedirectResponse("/certs?err=csrf", status_code=303)
    except (ValueError, OwnershipError, CredentialsError) as exc:
        return RedirectResponse(f"/certs?err={exc}", status_code=303)
    cert = cert_repo.get_for_user(db, cert_id, user.id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hint = (
        renew_hint(
            expires_at=cert.expires_at,
            renew_days=cert.renew_days,
            now=now,
            enabled=cert.enabled,
            verification_status=cert.verification_status,
        )
        if cert
        else None
    )
    ok_code = "renew_started" if hint and hint.in_window else "renew_early"
    return RedirectResponse(f"/certs?ok={ok_code}", status_code=303)


@router.post("/certs/{cert_id}/toggle")
def cert_toggle(
    request: Request,
    cert_id: int,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        validate_csrf(request, csrf_token)
        CertService(db).toggle(cert_id, user.id)
    except CSRFError:
        return RedirectResponse("/certs?err=csrf", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/certs?err={exc}", status_code=303)
    return RedirectResponse("/certs?ok=toggled", status_code=303)


@router.get("/api/certs/{cert_id}/status")
def cert_status_api(
    cert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        data = CertService(db).get_status_json(cert_id, user.id)
    except ValueError:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(data)
