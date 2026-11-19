"""Memory MCP server -- durable facts the assistant keeps across sessions (preferences, corrections)."""
from __future__ import annotations

from .. import config
from ..memory import MemoryStore
from ._common import DESTRUCTIVE, READ, WRITE, make_server

PATH = config.data_dir() / "memory.json"
mcp = make_server(
    "memory",
    "Long-term memory. Store durable facts, preferences and user corrections; never store secrets.",
)


@mcp.tool(annotations=WRITE)
def remember(fact: str, tags: str = "") -> str:
    """Save a durable fact or preference (e.g. 'User prefers amounts in INR lakhs'). Never store secrets."""
    if len(fact) > 500:
        raise ValueError("Keep memories short (max 500 characters).")
    item = MemoryStore(PATH).add(fact, [t.strip() for t in tags.split(",") if t.strip()])
    return f"Remembered (id {item['id']}): {item['fact']}"


@mcp.tool(annotations=READ)
def recall(query: str, k: int = 5) -> str:
    """Search saved memories relevant to a query."""
    hits = MemoryStore(PATH).search(query, k)
    return "\n".join(f"{m['id']}: {m['fact']}" for m in hits) or "No matching memories."


@mcp.tool(annotations=READ)
def list_memories() -> str:
    """List all saved memories."""
    items = MemoryStore(PATH).items
    return "\n".join(f"{m['id']}: {m['fact']}" for m in items) or "No memories saved yet."


@mcp.tool(annotations=DESTRUCTIVE)
def forget(memory_id: str) -> str:
    """Delete a saved memory by id."""
    return "Deleted." if MemoryStore(PATH).forget(memory_id) else f"No memory with id {memory_id}."


if __name__ == "__main__":
    mcp.run()
