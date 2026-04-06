"""Shared test fixtures."""
import os
import sys
import pytest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set required env vars BEFORE importing project modules
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def tmp_workdir(tmp_path, monkeypatch):
    """Create a temporary working directory and patch bootstrap.state paths."""
    monkeypatch.chdir(tmp_path)
    import bootstrap.state as st
    monkeypatch.setattr(st, "WORKDIR", tmp_path)
    monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
    monkeypatch.setattr(st, "MEMORY_DIR", tmp_path / ".xiaoagent" / "memory")
    monkeypatch.setattr(st, "TASKS_DIR", tmp_path / ".xiaoagent" / "tasks")
    monkeypatch.setattr(st, "SETTINGS_PATH", tmp_path / ".xiaoagent" / "settings.json")
    monkeypatch.setattr(st, "SKILLS_DIR", tmp_path / "skills")
    return tmp_path
