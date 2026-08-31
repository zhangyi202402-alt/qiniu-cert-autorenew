"""每日归属复检。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[2]
_ROOT = _WEB_DIR.parent
for p in (_ROOT, _WEB_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.database import SessionLocal  # noqa: E402
from app.ownership_service import OwnershipService  # noqa: E402
from app.repositories import cert_repo  # noqa: E402
from app.settings import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_all")


def main() -> int:
    settings = get_settings()
    db = SessionLocal()
    try:
        reclaimed = cert_repo.reclaim_stale_jobs(db, settings.stale_job_minutes)
        if reclaimed:
            logger.info("reclaimed %s stale jobs", reclaimed)
        ownership = OwnershipService()
        certs = cert_repo.list_verify_candidates(db)
        logger.info("verify candidates: %s", len(certs))
        for cert in certs:
            result = ownership.verify_certificate(db, cert.id)
            logger.info(
                "cert %s host=%s ok=%s status=%s",
                cert.id,
                cert.verification_host,
                result.ok,
                cert_repo.get(db, cert.id).verification_status if cert_repo.get(db, cert.id) else "?",
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
