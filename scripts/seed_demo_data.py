"""Recreate the demo SQLite database:  python scripts/seed_demo_data.py"""
from mcp_assistant import config
from mcp_assistant.demo_data import ensure_demo_data

db = config.data_dir() / "business.db"
db.unlink(missing_ok=True)
print("created", ensure_demo_data(config.data_dir()))
