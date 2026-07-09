from fastapi import APIRouter

from config import CORE_RUNTIME

if CORE_RUNTIME == "singbox":
    from . import admin, home, singbox
else:
    from . import (
        admin,
        core,
        node,
        subscription,
        system,
        singbox,
        user_template,
        user,
        home,
    )

api_router = APIRouter()

if CORE_RUNTIME == "singbox":
    routers = [
        admin.router,
        singbox.router,
        home.router,
    ]
else:
    routers = [
        admin.router,
        core.router,
        node.router,
        subscription.router,
        system.router,
        singbox.router,
        user_template.router,
        user.router,
        home.router,
    ]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]
