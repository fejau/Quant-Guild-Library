from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import agent.codex_backend as backend
from config import get_settings


def test_codex_exec_is_ephemeral_readonly_and_uses_oauth(
    monkeypatch,
    tmp_path,
) -> None:
    settings = replace(
        get_settings(require_openai=False),
        codex_bin="codex",
        codex_chat_model="gpt-5.4",
    )
    captured = {}

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-be-forwarded")
    monkeypatch.setattr(backend, "_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(
        backend,
        "codex_auth_status",
        lambda _settings: {"ok": True, "method": "ChatGPT OAuth"},
    )
    monkeypatch.setattr(backend.shutil, "which", lambda _name: "/usr/bin/codex")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Read-only result"},
                }
            ),
        )

    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    result = backend.CodexStrategyAgent(settings)._run_codex("Analyze only")

    args = captured["args"]
    env = captured["kwargs"]["env"]
    assert result == "Read-only result"
    assert args[:2] == ["/usr/bin/codex", "exec"]
    assert "--ephemeral" in args
    assert "--ignore-user-config" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert 'approval_policy="never"' in args
    assert 'web_search="disabled"' in args
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env
