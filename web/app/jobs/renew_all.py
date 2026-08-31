"""每日续签：先复检归属，再 acme.sh --cron。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[2]
_ROOT = _WEB_DIR.parent
for p in (_ROOT, _WEB_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.cert_service import CertService  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.repositories import cert_repo  # noqa: E402
from app.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("renew_all")


def main() -> int:
    settings = get_settings()
    db = SessionLocal()
    try:
        reclaimed = cert_repo.reclaim_stale_jobs(db, settings.stale_job_minutes)
        if reclaimed:
            logger.info("reclaimed %s stale jobs", reclaimed)
        svc = CertService(db, settings)

        stuck = cert_repo.list_stuck_verified_pending(db)
        logger.info("stuck verified pending: %s", len(stuck))
        for cert in stuck:
            logger.info("compensate issue cert %s (%s)", cert.id, cert.primary_domain)
            try:
                svc.issue_certificate(cert.id, job_type="issue")
            except Exception:  # noqa: BLE001
                logger.exception("compensate issue failed cert %s", cert.id)

        certs = cert_repo.list_renew_candidates(db)
        logger.info("renew candidates: %s", len(certs))
        for cert in certs:
            logger.info("renew cert %s (%s)", cert.id, cert.primary_domain)
            try:
                svc.renew_certificate(cert.id)
            except Exception:  # noqa: BLE001
                logger.exception("renew failed cert %s", cert.id)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
