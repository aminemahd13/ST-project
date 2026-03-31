from __future__ import annotations

from pathlib import Path

from app.config.settings import settings


class StorageService:
    """Durable filesystem storage for uploaded artifacts."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or settings.storage_path).resolve()
        self.upload_dir = self.base_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_bytes: bytes, filename: str, sha256: str) -> str:
        extension = Path(filename).suffix.lower() or ".pdf"
        target_path = self.upload_dir / f"{sha256}{extension}"
        if not target_path.exists():
            target_path.write_bytes(file_bytes)
        return str(target_path)
