"""兼容入口：将旧 UI.server 收敛为新的 Web adapter app。"""

from adapters.web.app import app, create_app

__all__ = ["app", "create_app"]
