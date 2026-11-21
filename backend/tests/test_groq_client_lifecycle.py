import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.ai import groq_client


def test_completion_closes_transport_on_its_own_event_loop(monkeypatch):
    connections = []

    class LoopBoundClient:
        async def __aenter__(self):
            self.loop = asyncio.get_running_loop()
            connections.append(self)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(content="response")
                                )
                            ],
                            usage=None,
                        )
                    )
                )
            )
            return self

        async def __aexit__(self, *_args):
            assert asyncio.get_running_loop() is self.loop
            self.closed = True

    monkeypatch.setattr(
        groq_client.GroqClientManager, "new_client", lambda _settings: LoopBoundClient()
    )
    monkeypatch.setattr(
        groq_client.GroqClientManager,
        "get_settings",
        lambda: groq_client.GroqSettings(
            api_key="test", model="fixture", timeout_seconds=1, max_retries=0
        ),
    )
    for _ in range(2):
        result = asyncio.run(
            groq_client.generate_completion([{"role": "user", "content": "fixture"}])
        )
        assert result["content"] == "response"
    assert len(connections) == 2
    assert all(client.closed and client.loop.is_closed() for client in connections)
