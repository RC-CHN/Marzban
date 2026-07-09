from fastapi import APIRouter

from . import admin, home, singbox

api_router = APIRouter()

routers = [
    admin.router,
    singbox.router,
    home.router,
]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]
