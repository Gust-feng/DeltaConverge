from .dashboard import router as dashboard_router
from .diff import router as diff_router
from .config import router as config_router
from .projects import router as projects_router
from .reviews import router as reviews_router
from .rule_growth import router as rule_growth_router
from .scans import router as scans_router
from .sessions import router as sessions_router
from .system import router as system_router

__all__ = [
    "dashboard_router",
    "diff_router",
    "config_router",
    "projects_router",
    "reviews_router",
    "rule_growth_router",
    "scans_router",
    "sessions_router",
    "system_router",
]
