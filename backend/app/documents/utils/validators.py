"""
File Validation Utilities
===========================
Validates uploaded files at the document pipeline level.
Extends the auth-layer FileValidator with document-specific rules.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_FILENAME_LENGTH = 255
SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/tiff",
    "image/bmp", "image/webp",
    "application/pdf",
    "text/csv", "text/plain",
}

MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
    b"BM": "image/bmp",
    b"%PDF": "application/pdf",
}

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


@dataclass
class ValidatedFile:
    original_filename: str
    safe_filename: str
    content_type: str
    size_bytes: int
    file_hash: str
    content: bytes


class FileValidator:
    def __init__(self, max_size_mb: Optional[int] = None) -> None:
        self.max_bytes = (max_size_mb or settings.documents.max_file_size_mb) * 1024 * 1024

    async def validate(self, file: UploadFile) -> ValidatedFile:
        content = await self._read(file)
        return await self.validate_bytes(content, file.filename or "unnamed")

    async def validate_bytes(self, content: bytes, filename: str) -> ValidatedFile:
        if not content:
            raise BadRequestException("Uploaded file is empty.")
        if len(content) > self.max_bytes:
            raise BadRequestException(
                f"File exceeds {self.max_bytes // 1024 // 1024}MB limit."
            )
        mime = self._detect_mime(content)
        if mime not in ALLOWED_MIME_TYPES:
            raise BadRequestException(f"File type '{mime}' is not permitted.")
        if EICAR in content:
            raise BadRequestException("File failed security scan.")
        safe_name = self._sanitize(filename)
        file_hash = hashlib.sha256(content).hexdigest()
        logger.info("file.validated", filename=safe_name, mime=mime, size=len(content))
        return ValidatedFile(
            original_filename=filename,
            safe_filename=safe_name,
            content_type=mime,
            size_bytes=len(content),
            file_hash=file_hash,
            content=content,
        )

    async def _read(self, file: UploadFile) -> bytes:
        content = b""
        while chunk := await file.read(65536):
            content += chunk
            if len(content) > self.max_bytes:
                raise BadRequestException(f"File exceeds size limit.")
        return content

    @staticmethod
    def _detect_mime(content: bytes) -> str:
        for magic, mime in MAGIC_BYTES.items():
            if content.startswith(magic):
                return mime
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp"
        try:
            sample = content[:512].decode("utf-8", errors="ignore")
            if "," in sample and "\n" in sample:
                return "text/csv"
            if sample.isprintable():
                return "text/plain"
        except Exception:
            pass
        return "application/octet-stream"

    @staticmethod
    def _sanitize(filename: str) -> str:
        name = filename.split("/")[-1].split("\\")[-1]
        name = name[:MAX_FILENAME_LENGTH]
        name = SAFE_FILENAME_RE.sub("_", name)
        return f"{str(uuid.uuid4())[:8]}_{name}" if name else f"{str(uuid.uuid4())[:8]}_file"
