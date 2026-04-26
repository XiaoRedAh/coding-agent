from __future__ import annotations

import json
from pathlib import Path

from bootstrap.state import WORKDIR
from utils.path import safe_path


class ArtifactStore:
    """File-backed artifact storage rooted at workspace-level artifacts/."""

    def __init__(self, root_dir: str = "artifacts"):
        self.root = safe_path(root_dir)
        self._root_relative = self.root.relative_to(WORKDIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_text(self, relative_path: str, content: str) -> str:
        target = safe_path(str(self._root_relative / relative_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target.relative_to(WORKDIR).as_posix()

    def save_json(self, relative_path: str, data: dict) -> str:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return self.save_text(relative_path, payload)

    def load_text(self, relative_path: str) -> str:
        target = safe_path(str(self._root_relative / relative_path))
        return target.read_text(encoding="utf-8")
