"""v2 系统 / 配置兼容端点测试（真实 ASGI app）。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from adapters.web.app import create_app
from adapters.web.dependencies import get_facade
from Agent.core.api.factory import LLMFactory
from kernel.application import KernelFacade, ReviewOrchestrator, RunEventBus
from kernel.application.services.config_service import ConfigService
from kernel.application.services.project_service import ProjectService
from kernel.application.services.review_service import ReviewService
from kernel.application.services.rule_service import RuleService
from kernel.application.services.session_service import SessionService
from kernel.application.services.system_service import SystemService
from kernel.infrastructure import FileArtifactStore, SQLiteKernelStore
from kernel.infrastructure.config_adapter import LegacyConfigAdapter


def _build_facade(tmp_path: Path) -> KernelFacade:
    store = SQLiteKernelStore(tmp_path / "kernel.db")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    event_bus = RunEventBus()
    orchestrator = ReviewOrchestrator(store, artifacts, event_bus)
    return KernelFacade(
        store=store,
        artifact_store=artifacts,
        event_bus=event_bus,
        orchestrator=orchestrator,
        review_service=ReviewService(store, artifacts, event_bus, orchestrator),
        session_service=SessionService(store, artifacts),
        config_service=ConfigService(config_port=LegacyConfigAdapter(root=tmp_path)),
        project_service=ProjectService(),
        rule_service=RuleService(),
        system_service=SystemService(),
    )


@pytest.fixture()
def http_transport(tmp_path: Path) -> httpx.ASGITransport:
    app = create_app()
    app.dependency_overrides[get_facade] = lambda: _build_facade(tmp_path)
    return httpx.ASGITransport(app=app)


def _request(transport: httpx.ASGITransport, method: str, url: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(run())


def _clear_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for config in LLMFactory.PROVIDERS.values():
        monkeypatch.delenv(config.api_key_env, raising=False)


def test_system_env_fields(http_transport, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = str(tmp_path / "project")
    roots = [str(tmp_path / "root_a"), str(tmp_path / "root_b")]
    monkeypatch.setenv("DEFAULT_PROJECT_ROOT", project_root)
    monkeypatch.setenv("ALLOWED_PROJECT_ROOTS", os.pathsep.join(roots))
    monkeypatch.delenv("DOCKER_PATH_RESTRICTIONS", raising=False)
    for flag in ("RUNNING_IN_DOCKER", "DOCKER", "IS_DOCKER"):
        monkeypatch.delenv(flag, raising=False)

    response = _request(http_transport, "GET", "/api/v2/system/env")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "is_docker",
        "platform",
        "default_project_root",
        "allowed_project_roots",
        "docker_path_restrictions",
        "drives",
        "base",
        "cwd",
    }
    assert data["is_docker"] is False
    assert data["docker_path_restrictions"] is False
    assert data["platform"] == sys.platform
    assert data["default_project_root"] == project_root
    assert data["allowed_project_roots"] == roots
    assert data["cwd"] == str(Path.cwd())
    assert data["base"] == str(Path.cwd())
    assert isinstance(data["drives"], list)


def test_system_env_default_root_falls_back_to_cwd(http_transport, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFAULT_PROJECT_ROOT", raising=False)

    data = _request(http_transport, "GET", "/api/v2/system/env").json()

    assert data["default_project_root"] == str(Path.cwd())


def test_system_env_docker_flag_and_restrictions(http_transport, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNNING_IN_DOCKER", "1")
    monkeypatch.setenv("DOCKER_PATH_RESTRICTIONS", "true")

    data = _request(http_transport, "GET", "/api/v2/system/env").json()

    assert data["is_docker"] is True
    assert data["docker_path_restrictions"] is True


def test_pick_folder_success_and_none(http_transport, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("legacy.ui_v1.dialogs.pick_folder", lambda: str(tmp_path))

    response = _request(http_transport, "POST", "/api/v2/system/pick-folder", json={})
    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path)}

    monkeypatch.setattr("legacy.ui_v1.dialogs.pick_folder", lambda: None)
    response = _request(http_transport, "POST", "/api/v2/system/pick-folder")
    assert response.status_code == 200
    assert response.json() == {"path": None}


def test_pick_folder_error_returns_success_status(http_transport, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("no display")

    monkeypatch.setattr("legacy.ui_v1.dialogs.pick_folder", boom)

    response = _request(http_transport, "POST", "/api/v2/system/pick-folder", json={})

    assert response.status_code == 200
    assert response.json() == {"error": "no display"}


def test_provider_keys_read_write_mask_and_delete(
    http_transport, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_provider_keys(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("# keep me\nOTHER_KEY=keep\n", encoding="utf-8")

    response = _request(http_transport, "GET", "/api/v2/providers/keys")
    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()["providers"]}
    assert "deepseek" in providers
    assert set(providers["deepseek"]) == {"provider", "label", "configured", "masked"}
    assert providers["deepseek"]["configured"] is False
    assert providers["deepseek"]["masked"] == ""

    secret = "sk-abcdefghijkl"
    response = _request(
        http_transport,
        "POST",
        "/api/v2/providers/keys",
        json={"provider": "deepseek", "value": secret},
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "provider": "deepseek", "configured": True}
    assert os.environ["DEEPSEEK_API_KEY"] == secret

    text = env_file.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "OTHER_KEY=keep" in text
    assert "DEEPSEEK_API_KEY" in text

    providers = {
        item["provider"]: item
        for item in _request(http_transport, "GET", "/api/v2/providers/keys").json()["providers"]
    }
    assert providers["deepseek"]["configured"] is True
    assert providers["deepseek"]["masked"] == "sk-a****ijkl"

    # 短值全星号
    _request(
        http_transport,
        "POST",
        "/api/v2/providers/keys",
        json={"provider": "deepseek", "value": "short"},
    )
    providers = {
        item["provider"]: item
        for item in _request(http_transport, "GET", "/api/v2/providers/keys").json()["providers"]
    }
    assert providers["deepseek"]["masked"] == "*****"

    # 空值删除，并保留其它键
    response = _request(
        http_transport,
        "POST",
        "/api/v2/providers/keys",
        json={"provider": "deepseek", "value": ""},
    )
    assert response.json() == {"success": True, "provider": "deepseek", "configured": False}
    assert "DEEPSEEK_API_KEY" not in os.environ
    text = env_file.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in text
    assert "OTHER_KEY=keep" in text
    assert "# keep me" in text


def test_provider_keys_errors(http_transport, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_keys(monkeypatch)
    (tmp_path / ".env").write_text("OTHER_KEY=keep\n", encoding="utf-8")

    unknown = _request(
        http_transport,
        "POST",
        "/api/v2/providers/keys",
        json={"provider": "not-a-provider", "value": "x"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "Unknown provider"

    newline = _request(
        http_transport,
        "POST",
        "/api/v2/providers/keys",
        json={"provider": "deepseek", "value": "bad\nvalue"},
    )
    assert newline.status_code == 400
    assert newline.json()["detail"] == "Invalid value"


@pytest.fixture()
def isolated_model_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把 LLMFactory 的模型配置重定向到临时副本，避免污染仓库文件。"""
    source = Path(LLMFactory._CONFIG_PATH)
    target = tmp_path / "models_config.json"
    shutil.copyfile(source, target)
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", target)
    monkeypatch.setattr(LLMFactory, "_MODELS", {})
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_DISABLED_PROVIDERS", set())
    monkeypatch.setattr(LLMFactory, "_BASE_PROVIDERS", dict(LLMFactory._BASE_PROVIDERS or LLMFactory.PROVIDERS))
    monkeypatch.setattr(LLMFactory, "PROVIDERS", dict(LLMFactory.PROVIDERS))
    return target


def test_models_add_delete_idempotent(http_transport, isolated_model_config: Path) -> None:
    model_name = "compat-test-model"

    response = _request(
        http_transport,
        "POST",
        "/api/v2/models/add",
        json={"provider": "deepseek", "model_name": model_name},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # 重复添加保持幂等，不产生重复项
    response = _request(
        http_transport,
        "POST",
        "/api/v2/models/add",
        json={"provider": "deepseek", "model_name": model_name},
    )
    assert response.status_code == 200

    saved = json.loads(isolated_model_config.read_text(encoding="utf-8"))
    models = saved["providers"]["deepseek"]["models"]
    assert models.count(model_name) == 1

    response = _request(
        http_transport,
        "POST",
        "/api/v2/models/delete",
        json={"provider": "deepseek", "model_name": model_name},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # 删除不存在的模型同样幂等
    response = _request(
        http_transport,
        "POST",
        "/api/v2/models/delete",
        json={"provider": "deepseek", "model_name": model_name},
    )
    assert response.status_code == 200

    saved = json.loads(isolated_model_config.read_text(encoding="utf-8"))
    assert model_name not in saved["providers"]["deepseek"]["models"]


def test_models_errors(http_transport, isolated_model_config: Path) -> None:
    unknown = _request(
        http_transport,
        "POST",
        "/api/v2/models/add",
        json={"provider": "not-a-provider", "model_name": "x"},
    )
    assert unknown.status_code == 400
    assert "Unknown provider" in unknown.json()["detail"]

    missing = _request(
        http_transport,
        "POST",
        "/api/v2/models/add",
        json={"provider": "deepseek", "model_name": ""},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"] == "model required"

    unknown_delete = _request(
        http_transport,
        "POST",
        "/api/v2/models/delete",
        json={"provider": "not-a-provider", "model_name": "x"},
    )
    assert unknown_delete.status_code == 400


@pytest.fixture()
def provider_update_config(isolated_model_config: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """使用可预测的临时服务配置，覆盖模型元数据和额外配置的保留行为。"""
    monkeypatch.setattr(
        LLMFactory,
        "_BASE_PROVIDERS",
        {name: LLMFactory.PROVIDERS[name] for name in ("deepseek", "glm")},
    )
    for name in ("deepseek", "glm"):
        key_env = LLMFactory.PROVIDERS[name].api_key_env
        monkeypatch.delenv(f"{key_env.split('_API_KEY')[0]}_BASE_URL", raising=False)
    config = {
        "selected_model": "deepseek:review-model",
        "providers": {
            "deepseek": {
                "base_url": "https://old.example/v1",
                "protocol": "chat_completions",
                "limits": {"context_window": 12345},
                "models": [
                    "review-model",
                    {"id": "override-model", "protocol": "chat_completions", "limits": {"max_output_tokens": 123}},
                ],
            },
            "glm": {"models": ["other-model"]},
        },
    }
    isolated_model_config.write_text(json.dumps(config), encoding="utf-8")
    return isolated_model_config


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_provider_connection_update_persists_without_losing_models(
    http_transport, provider_update_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, protocol: str
) -> None:
    before = json.loads(provider_update_config.read_text(encoding="utf-8"))
    before["providers"]["deepseek"]["protocol"] = (
        "chat_completions" if protocol == "responses" else "responses"
    )
    provider_update_config.write_text(json.dumps(before), encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_KEY=keep\n", encoding="utf-8")
    response = _request(
        http_transport,
        "PATCH",
        "/api/v2/models/providers/deepseek",
        json={"protocol": protocol, "base_url": "  https://new.example/v2/  "},
    )
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "provider": "deepseek",
        "disabled": False,
        "protocol": protocol,
        "base_url": "https://new.example/v2",
    }
    expected = json.loads(json.dumps(before))
    expected["providers"]["deepseek"].update(protocol=protocol, base_url="https://new.example/v2")
    assert json.loads(provider_update_config.read_text(encoding="utf-8")) == expected
    assert env_file.read_text(encoding="utf-8") == "OTHER_KEY=keep\n"

    # 模拟重新加载：配置落盘后，服务列表和新建客户端都使用新连接配置。
    LLMFactory.reload()
    providers = _request(http_transport, "GET", "/api/v2/models/providers").json()["items"]
    current = next(item for item in providers if item["id"] == "deepseek")
    assert current["protocol"] == protocol
    assert current["base_url"] == "https://new.example/v2"
    assert current["models"] == ["review-model", "override-model"]

    class Client:
        def __init__(self, *, model, api_key, base_url):
            self.model = model
            self.base_url = base_url

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(LLMFactory.PROVIDERS["deepseek"], "client_class", Client)
    client, provider = LLMFactory.create("deepseek:review-model")
    assert provider == "deepseek"
    assert client.model == "review-model"
    assert client.protocol == protocol
    assert client.base_url == "https://new.example/v2"
    overridden, _ = LLMFactory.create("deepseek:override-model")
    assert overridden.protocol == "chat_completions"


def test_added_connection_persists_separately_from_provider_catalog(
    http_transport, provider_update_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_provider_keys(monkeypatch)
    original = json.loads(provider_update_config.read_text(encoding="utf-8"))
    original_models = original["providers"]["deepseek"]["models"]
    response = _request(http_transport, "GET", "/api/v2/models/providers?include_disabled=true")
    before = next(item for item in response.json()["items"] if item["id"] == "deepseek")
    assert before["added"] is False

    added = _request(http_transport, "PATCH", "/api/v2/models/providers/deepseek", json={"disabled": False})
    assert added.status_code == 200
    LLMFactory.reload()
    response = _request(http_transport, "GET", "/api/v2/models/providers")
    connection = next(item for item in response.json()["items"] if item["id"] == "deepseek")
    assert connection["added"] is True
    assert connection["configured"] is False
    saved = json.loads(provider_update_config.read_text(encoding="utf-8"))
    assert saved["providers"]["deepseek"]["models"] == original_models
    assert saved["providers"]["deepseek"]["base_url"] == original["providers"]["deepseek"]["base_url"]

    removed = _request(http_transport, "PATCH", "/api/v2/models/providers/deepseek", json={"disabled": True})
    assert removed.status_code == 200
    response = _request(http_transport, "GET", "/api/v2/models/providers")
    assert all(item["id"] != "deepseek" for item in response.json()["items"])
    response = _request(http_transport, "GET", "/api/v2/models/providers?include_disabled=true")
    assert any(item["id"] == "deepseek" for item in response.json()["items"])


def test_provider_partial_updates_and_soft_disable_compatibility(http_transport, provider_update_config: Path) -> None:
    url = "/api/v2/models/providers/deepseek"
    original = json.loads(provider_update_config.read_text(encoding="utf-8"))
    disabled = _request(http_transport, "PATCH", url, json={"disabled": True})
    assert disabled.status_code == 200
    assert disabled.json() == {"success": True, "provider": "deepseek", "disabled": True}

    changed = _request(http_transport, "PATCH", url, json={"protocol": "responses"})
    assert changed.status_code == 200
    assert changed.json()["disabled"] is True
    entry = json.loads(provider_update_config.read_text(encoding="utf-8"))["providers"]["deepseek"]
    assert entry["disabled"] is True
    assert entry["base_url"] == original["providers"]["deepseek"]["base_url"]
    assert entry["models"] == original["providers"]["deepseek"]["models"]

    snapshot = provider_update_config.read_bytes()
    for patch in ({}, {"protocol": None, "disabled": None, "base_url": None}):
        assert _request(http_transport, "PATCH", url, json=patch).status_code == 200
        assert provider_update_config.read_bytes() == snapshot

    restored = _request(http_transport, "PATCH", url, json={"disabled": False})
    assert restored.json() == {"success": True, "provider": "deepseek", "disabled": False}
    assert "disabled" not in json.loads(provider_update_config.read_text(encoding="utf-8"))["providers"]["deepseek"]


@pytest.mark.parametrize(
    ("patch", "status"),
    [
        ({"protocol": "anthropic"}, 422),
        ({"protocol": ""}, 422),
        ({"base_url": ""}, 400),
        ({"base_url": "ftp://example.com"}, 400),
        ({"base_url": "https://"}, 400),
        ({"base_url": "https://bad host/v1"}, 400),
        ({"base_url": "https://example.com:bad/v1"}, 400),
        ({"base_url": "https://example.com/v1?key=value"}, 400),
        ({"base_url": "https://example.com/v1#fragment"}, 400),
    ],
)
def test_provider_invalid_updates_do_not_change_config(
    http_transport, provider_update_config: Path, patch: dict, status: int
) -> None:
    before = provider_update_config.read_bytes()
    response = _request(
        http_transport,
        "PATCH",
        "/api/v2/models/providers/deepseek",
        json={"disabled": True, **patch},
    )
    assert response.status_code == status
    assert provider_update_config.read_bytes() == before
    assert "deepseek" not in LLMFactory._DISABLED_PROVIDERS

    with pytest.raises(ValueError, match="协议仅支持"):
        LegacyConfigAdapter().update_provider("deepseek", protocol="anthropic")
    assert provider_update_config.read_bytes() == before


def test_provider_update_unknown_and_last_active_service(http_transport, provider_update_config: Path) -> None:
    before = provider_update_config.read_bytes()
    unknown = _request(
        http_transport, "PATCH", "/api/v2/models/providers/unknown", json={"protocol": "responses"}
    )
    assert unknown.status_code == 400
    assert "Unknown provider" in unknown.json()["detail"]
    assert provider_update_config.read_bytes() == before

    assert _request(
        http_transport, "PATCH", "/api/v2/models/providers/glm", json={"disabled": True}
    ).status_code == 200
    snapshot = provider_update_config.read_bytes()
    blocked = _request(
        http_transport,
        "PATCH",
        "/api/v2/models/providers/deepseek",
        json={"disabled": True, "protocol": "responses"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "至少保留一个服务"
    assert provider_update_config.read_bytes() == snapshot
    assert LLMFactory._PROVIDER_SETTINGS["deepseek"]["protocol"] == "chat_completions"
    assert "deepseek" not in LLMFactory._DISABLED_PROVIDERS


def test_provider_url_environment_override_is_actionable_and_atomic(
    http_transport, provider_update_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://environment.example/v1")
    before = provider_update_config.read_bytes()
    blocked = _request(
        http_transport,
        "PATCH",
        "/api/v2/models/providers/deepseek",
        json={"protocol": "responses", "base_url": "https://new.example/v1", "disabled": True},
    )
    assert blocked.status_code == 400
    assert "DEEPSEEK_BASE_URL" in blocked.json()["detail"]
    assert "修改或移除" in blocked.json()["detail"]
    assert provider_update_config.read_bytes() == before
    assert "deepseek" not in LLMFactory._DISABLED_PROVIDERS

    # 环境变量不妨碍协议修改；保存相同的实际地址也不会产生误导。
    assert _request(
        http_transport, "PATCH", "/api/v2/models/providers/deepseek", json={"protocol": "responses"}
    ).status_code == 200
    assert _request(
        http_transport,
        "PATCH",
        "/api/v2/models/providers/deepseek",
        json={"base_url": "https://environment.example/v1/"},
    ).status_code == 200


def test_provider_update_preserves_legacy_model_lists(http_transport, provider_update_config: Path) -> None:
    config = json.loads(provider_update_config.read_text(encoding="utf-8"))
    config["providers"]["deepseek"] = ["first-model", "second-model"]
    provider_update_config.write_text(json.dumps(config), encoding="utf-8")
    response = _request(
        http_transport, "PATCH", "/api/v2/models/providers/deepseek", json={"protocol": "responses"}
    )
    assert response.status_code == 200
    saved = json.loads(provider_update_config.read_text(encoding="utf-8"))
    assert saved["providers"]["deepseek"] == {
        "models": ["first-model", "second-model"],
        "protocol": "responses",
    }
