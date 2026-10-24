from fastapi import APIRouter

from app.api.v1 import health

API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX)
router.include_router(health.router)
