import pytest

from mcp_assistant.demo_data import ensure_demo_data


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data/log dirs so tests never touch real memory, index or audit logs."""
    data, logs = tmp_path / "data", tmp_path / "logs"
    monkeypatch.setenv("MCP_ASSISTANT_DATA", str(data))
    monkeypatch.setenv("MCP_ASSISTANT_LOGS", str(logs))
    monkeypatch.setenv("DISABLE_EMBEDDINGS", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ensure_demo_data(data)
    return tmp_path
