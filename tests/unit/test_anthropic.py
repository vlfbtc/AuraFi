from __future__ import annotations

import unittest

from services.conversation.anthropic import (
    AnthropicConfig,
    AnthropicConfigurationError,
    AnthropicLlm,
    AnthropicTransportError,
)
from services.conversation.service import LlmRequest


class AnthropicAdapterTests(unittest.TestCase):
    def test_sends_only_minimized_text_and_provider_headers(self) -> None:
        captured = {}

        def post_json(url, *, headers, payload, timeout_seconds, max_response_bytes):
            captured.update(
                url=url,
                headers=dict(headers),
                payload=dict(payload),
                timeout=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
            return {
                "model": "claude-test-provider",
                "content": [{"type": "text", "text": "Resposta clara e educativa."}],
            }

        adapter = AnthropicLlm(
            AnthropicConfig(api_key="secret-provider-key", model="claude-test"),
            post_json=post_json,
        )
        result = adapter.complete(
            LlmRequest(
                text="Explique o que é APY para maria@example.com.",
                account_id="acc-sensitive",
                conversation_id="cnv-sensitive",
                context=(
                    {"role": "user", "text": "Meu objetivo é entender riscos."},
                    {"role": "assistant", "text": "Vamos avaliar as premissas."},
                ),
            )
        )

        self.assertEqual(result.mode, "provider")
        self.assertEqual(result.provider, "claude")
        self.assertEqual(result.text, "Resposta clara e educativa.")
        serialized = repr(captured["payload"])
        self.assertNotIn("acc-sensitive", serialized)
        self.assertNotIn("cnv-sensitive", serialized)
        self.assertNotIn("secret-provider-key", repr(captured["payload"]))
        self.assertNotIn("maria@example.com", serialized)
        self.assertIn("[email removido]", serialized)
        self.assertEqual(
            [item["role"] for item in captured["payload"]["messages"]],
            ["user", "assistant", "user"],
        )
        self.assertEqual(captured["headers"]["x-api-key"], "secret-provider-key")

    def test_config_hides_key_and_rejects_non_official_endpoint(self) -> None:
        config = AnthropicConfig(api_key="secret-provider-key")
        self.assertNotIn("secret-provider-key", repr(config))

        with self.assertRaises(AnthropicConfigurationError):
            AnthropicConfig(
                api_key="secret-provider-key",
                messages_url="http://api.anthropic.com/v1/messages",
            )
        with self.assertRaises(AnthropicConfigurationError):
            AnthropicConfig(
                api_key="secret-provider-key",
                messages_url="https://attacker.example/v1/messages",
            )

    def test_empty_provider_content_fails_without_exposing_request(self) -> None:
        adapter = AnthropicLlm(
            AnthropicConfig(api_key="secret-provider-key"),
            post_json=lambda *args, **kwargs: {"content": []},
        )
        with self.assertRaises(AnthropicTransportError) as raised:
            adapter.complete(LlmRequest("texto sensível", "acc", "cnv"))
        message = str(raised.exception)
        self.assertNotIn("secret-provider-key", message)
        self.assertNotIn("texto sensível", message)


if __name__ == "__main__":
    unittest.main()
