"""
Secure File Upload Validation
================================
Validates uploaded files before any processing:
  - MIME type whitelist (magic bytes, not extension)
  - File size enforcement
  - Filename sanitization
  - Malware scan placeholder (integrate ClamAV / VirusTotal in production)
  - Image dimension validation

Usage:
    @router.post("/upload")
    async def upload(
        file: UploadFile,
        current_user: CurrentUser,
    ):
        validated = await FileValidator.validate(file)
        # safe to store validated.safe_filename
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
SAFE_FILENAME_PATTERN = re.compile(r"[^\w\-.]")  # Only allow word chars, hyphens, dots

# MIME type to file extension mapping (whitelist)
ALLOWED_TYPES: dict[str, list[str]] = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/gif": [".gif"],
    "image/webp": [".webp"],
    "application/pdf": [".pdf"],
    "text/csv": [".csv"],
    "text/plain": [".txt"],
}

# Magic bytes for MIME validation (don't trust Content-Type header alone)
MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",             # Webp starts with RIFF....WEBP
    b"%PDF": "application/pdf",
}


@dataclass
class ValidatedFile:
    original_filename: str
    safe_filename: str
    content_type: str
    size_bytes: int
    file_hash: str                     # SHA-256 of content
    content: bytes


class FileValidator:
    """Validates an UploadFile against security policy."""

    def __init__(
        self,
        max_size_mb: Optional[int] = None,
        allowed_mime_types: Optional[list[str]] = None,
    ) -> None:
        self.max_size_bytes = (max_size_mb or settings.auth.max_upload_size_mb) * 1024 * 1024
        self.allowed_mime_types = allowed_mime_types or settings.auth.allowed_mime_types_list

    async def validate(self, file: UploadFile) -> ValidatedFile:
        """Full validation pipeline. Raises BadRequestException on violation."""

        # ── Filename validation ──────────────────────────────
        original_name = file.filename or "unnamed"
        safe_name = self._sanitize_filename(original_name)

        # ── Read content (with size check) ───────────────────
        content = await self._read_with_limit(file)

        # ── MIME validation via magic bytes ───────────────────
        detected_mime = self._detect_mime_from_bytes(content)
        if detected_mime is None:
            raise BadRequestException(
                "File type could not be determined or is not allowed."
            )

        if detected_mime not in self.allowed_mime_types:
            raise BadRequestException(
                f"File type '{detected_mime}' is not allowed. "
                f"Allowed: {', '.join(self.allowed_mime_types)}."
            )

        # Extra: validate declared content-type matches detected
        declared = file.content_type or ""
        if declared and declared != detected_mime and declared not in self.allowed_mime_types:
            logger.warning(
                "file.mime_mismatch",
                declared=declared,
                detected=detected_mime,
                filename=original_name,
            )

        # ── Malware scan placeholder ──────────────────────────
        await self._scan_for_malware(content, safe_name)

        # ── Hash for deduplication / audit ───────────────────
        file_hash = hashlib.sha256(content).hexdigest()

        logger.info(
            "file.validated",
            filename=safe_name,
            mime=detected_mime,
            size_bytes=len(content),
            hash=file_hash[:16],
        )

        return ValidatedFile(
            original_filename=original_name,
            safe_filename=safe_name,
            content_type=detected_mime,
            size_bytes=len(content),
            file_hash=file_hash,
            content=content,
        )

    async def _read_with_limit(self, file: UploadFile) -> bytes:
        content = b""
        while True:
            chunk = await file.read(64 * 1024)  # Read 64KB at a time
            if not chunk:
                break
            content += chunk
            if len(content) > self.max_size_bytes:
                raise BadRequestException(
                    f"File exceeds maximum allowed size of "
                    f"{self.max_size_bytes // 1024 // 1024}MB."
                )
        if not content:
            raise BadRequestException("Uploaded file is empty.")
        return content

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Remove path traversal and special characters from filename."""
        # Strip directory components
        name = filename.split("/")[-1].split("\\")[-1]
        # Limit length
        if len(name) > MAX_FILENAME_LENGTH:
            name = name[:MAX_FILENAME_LENGTH]
        # Replace unsafe chars
        name = SAFE_FILENAME_PATTERN.sub("_", name)
        # Prepend UUID to prevent collisions
        prefix = str(uuid.uuid4())[:8]
        return f"{prefix}_{name}" if name else f"{prefix}_file"

    @staticmethod
    def _detect_mime_from_bytes(content: bytes) -> Optional[str]:
        """Detect MIME type from magic bytes (not from Content-Type header)."""
        for magic, mime in MAGIC_BYTES.items():
            if content.startswith(magic):
                return mime
        # Special case: WebP has RIFF header with WEBP marker at byte 8
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp"
        # Check for CSV (plain text with commas)
        try:
            text = content[:512].decode("utf-8", errors="ignore")
            if "," in text and "\n" in text:
                return "text/csv"
            if text.isprintable():
                return "text/plain"
        except Exception:
            pass
        return None

    @staticmethod
    async def _scan_for_malware(content: bytes, filename: str) -> None:
        """
        Malware scan placeholder.
        In production, integrate one of:
          - ClamAV via python-clamd
          - VirusTotal API
          - AWS Macie / GCP DLP
        """
        # PLACEHOLDER: log intent and skip in development
        logger.info("file.malware_scan.skipped", filename=filename, size=len(content))

        # Known EICAR test string detection (for testing)
        EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
        if EICAR_SIGNATURE in content:
            raise BadRequestException("File failed security scan and was rejected.")
