"""Task 2 验收:三个双模式开关 + 启动期校验。"""

import pytest
from pydantic import ValidationError

BASE = {
    "DATABASE_URL": "postgresql+psycopg://u:p@h/db",
    "MILVUS_URI": "http://m:19530",
}


def _settings(monkeypatch, **env):
    for k in (
        "LLM_MODE", "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL",
        "EMBED_MODE", "EMBED_MODEL", "DATA_SOURCE", "GITHUB_TOKEN",
        "CONTEXT_BUDGET", "MAX_AGENT_STEPS", "MAX_REPLAN",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**BASE, **env}.items():
        monkeypatch.setenv(k, str(v))
    from app.config import Settings

    return Settings(_env_file=None)


def test_默认三开关都是离线模式(monkeypatch):
    s = _settings(monkeypatch)
    assert (s.llm_mode, s.embed_mode, s.data_source) == ("mock", "mock", "snapshot")


def test_openai_模式缺_key直接启动失败(monkeypatch):
    # 给默认值等于替人猜:猜错不在启动时报错,而是第一次调模型时抛 401
    with pytest.raises(ValidationError):
        _settings(monkeypatch, LLM_MODE="openai", OPENAI_BASE_URL="https://x/v1",
                  OPENAI_MODEL="m")


def test_openai_模式三项齐全则通过(monkeypatch):
    s = _settings(monkeypatch, LLM_MODE="openai", OPENAI_BASE_URL="https://x/v1",
                  OPENAI_MODEL="m", OPENAI_API_KEY="k")
    assert s.llm_mode == "openai"


def test_mock_模式不要求_key(monkeypatch):
    assert _settings(monkeypatch).openai_api_key is None


def test_embed_openai_模式缺_model_启动失败(monkeypatch):
    with pytest.raises(ValidationError):
        _settings(monkeypatch, EMBED_MODE="openai")


def test_github_模式缺_token允许启动但工具层报错(monkeypatch):
    # 静默回退到快照会让人把假数据当真实结论,所以这里刻意不校验
    s = _settings(monkeypatch, DATA_SOURCE="github")
    assert s.github_token is None and s.data_source == "github"


def test_预算可被环境变量覆盖(monkeypatch):
    s = _settings(monkeypatch, CONTEXT_BUDGET="4000", MAX_AGENT_STEPS="3")
    assert (s.context_budget, s.max_agent_steps) == (4000, 3)