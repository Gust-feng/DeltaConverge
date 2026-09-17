from __future__ import annotations

import unittest
from unittest.mock import patch

from Agent.core.api.factory import LLMFactory


class LLMFactoryTests(unittest.TestCase):
    def test_create_accepts_plain_model_name(self) -> None:
        with patch.object(LLMFactory, "_ensure_models_loaded", return_value=None), patch.object(
            LLMFactory,
            "_MODELS",
            {
                "deepseek": ["deepseek-reasoner", "deepseek-chat"],
                "moonshot": ["kimi-k2-thinking"],
            },
        ), patch.object(
            LLMFactory,
            "_create_client",
            side_effect=lambda provider_name, trace_id, model_override=None: {
                "provider": provider_name,
                "model": model_override,
            }
            if provider_name == "deepseek"
            else None,
        ):
            client, provider = LLMFactory.create("deepseek-reasoner")

        self.assertEqual(provider, "deepseek")
        self.assertEqual(client["provider"], "deepseek")
        self.assertEqual(client["model"], "deepseek-reasoner")

    def test_provider_model_syntax_still_supported(self) -> None:
        with patch.object(LLMFactory, "_ensure_models_loaded", return_value=None), patch.object(
            LLMFactory,
            "_create_client",
            return_value={"provider": "glm", "model": "glm-4.7"},
        ) as create_client:
            client, provider = LLMFactory.create("glm:glm-4.7")

        self.assertEqual(provider, "glm")
        self.assertEqual(client["model"], "glm-4.7")
        create_client.assert_called_once_with("glm", None, "glm-4.7")

    def test_auto_mode_raises_when_no_provider_is_available(self) -> None:
        with patch.object(LLMFactory, "_ensure_models_loaded", return_value=None), patch.object(
            LLMFactory,
            "_create_client",
            return_value=None,
        ), patch.object(
            LLMFactory,
            "PROVIDERS",
            {"deepseek": object(), "glm": object()},
        ):
            with self.assertRaisesRegex(RuntimeError, "未找到可用 LLM 客户端"):
                LLMFactory.create("auto")


if __name__ == "__main__":
    unittest.main()
