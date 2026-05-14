"""
Storage Abstraction Layer
===========================
Unified async interface for file storage backends.
Supports: local filesystem, AWS S3, MinIO (S3-compatible).

Switch backend via DOC_STORAGE_BACKEND env var.
All paths are structured: {env}/{user_id}/{doc_type}/{date}/{filename}

Usage:
    storage = get_storage()
    key = await storage.save(content, "docs/file.pdf")
    url = await storage.get_presigned_url(key)
    await storage.delete(key)
"""

import abc
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, BinaryIO, Optional

import aiofiles
import aiofiles.os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Abstract Base
# ──────────────────────────────────────────────

class StorageBackend(abc.ABC):
    """Abstract storage interface — all backends implement this."""

    @abc.abstractmethod
    async def save(self, content: bytes, key: str) -> str:
        """Persist bytes to storage. Returns the storage key."""

    @abc.abstractmethod
    async def read(self, key: str) -> bytes:
        """Read file content by storage key."""

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a file. Returns True if deleted."""

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a file exists at key."""

    @abc.abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a time-limited URL for direct client access."""

    @abc.abstractmethod
    async def get_size(self, key: str) -> int:
        """Return file size in bytes."""

    def build_key(
        self,
        user_id: uuid.UUID,
        doc_type: str,
        filename: str,
        env: Optional[str] = None,
    ) -> str:
        """
        Build a structured, collision-safe storage key.
        Format: {env}/{user_id}/{doc_type}/{YYYY/MM/DD}/{uuid}_{filename}
        """
        env_prefix = env or settings.app_env.value
        date_path = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        unique_prefix = str(uuid.uuid4())[:8]
        safe_filename = filename.replace(" ", "_")
        return f"{env_prefix}/{user_id}/{doc_type}/{date_path}/{unique_prefix}_{safe_filename}"


# ──────────────────────────────────────────────
# Local Filesystem Backend
# ──────────────────────────────────────────────

class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage — for development and testing.
    NOT for production (not scalable, not durable).
    """

    def __init__(self, base_path: Optional[str] = None) -> None:
        self.base_path = Path(base_path or settings.documents.local_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        full = self.base_path / key
        full.parent.mkdir(parents=True, exist_ok=True)
        return full

    async def save(self, content: bytes, key: str) -> str:
        path = self._full_path(key)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        logger.info("storage.local.saved", key=key, size=len(content))
        return key

    async def read(self, key: str) -> bytes:
        path = self._full_path(key)
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> bool:
        path = self._full_path(key)
        try:
            await aiofiles.os.remove(path)
            return True
        except FileNotFoundError:
            return False

    async def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # Local: return a path-based URL (works with dev server)
        return f"/api/v1/documents/download/{key}"

    async def get_size(self, key: str) -> int:
        path = self._full_path(key)
        stat = await aiofiles.os.stat(path)
        return stat.st_size


# ──────────────────────────────────────────────
# S3 / MinIO Backend
# ──────────────────────────────────────────────

class S3StorageBackend(StorageBackend):
    """
    AWS S3 or MinIO (S3-compatible) storage backend.
    Uses boto3 in a thread pool to avoid blocking the async event loop.
    """

    def __init__(self) -> None:
        import boto3
        self._s3 = boto3.client(
            "s3",
            region_name=settings.documents.s3_region,
            aws_access_key_id=settings.documents.s3_access_key or None,
            aws_secret_access_key=settings.documents.s3_secret_key or None,
            endpoint_url=settings.documents.s3_endpoint_url or None,
        )
        self.bucket = settings.documents.s3_bucket

    async def _run_in_executor(self, func, *args, **kwargs):
        import asyncio
        from functools import partial
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def save(self, content: bytes, key: str) -> str:
        await self._run_in_executor(
            self._s3.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ServerSideEncryption="AES256",
        )
        logger.info("storage.s3.saved", bucket=self.bucket, key=key, size=len(content))
        return key

    async def read(self, key: str) -> bytes:
        response = await self._run_in_executor(
            self._s3.get_object, Bucket=self.bucket, Key=key
        )
        return response["Body"].read()

    async def delete(self, key: str) -> bool:
        await self._run_in_executor(
            self._s3.delete_object, Bucket=self.bucket, Key=key
        )
        return True

    async def exists(self, key: str) -> bool:
        try:
            await self._run_in_executor(
                self._s3.head_object, Bucket=self.bucket, Key=key
            )
            return True
        except Exception:
            return False

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        url = await self._run_in_executor(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    async def get_size(self, key: str) -> int:
        response = await self._run_in_executor(
            self._s3.head_object, Bucket=self.bucket, Key=key
        )
        return response["ContentLength"]


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────

_storage_instance: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """
    Return the configured storage backend (singleton).
    Controlled via DOC_STORAGE_BACKEND env var.
    """
    global _storage_instance
    if _storage_instance is None:
        backend = settings.documents.storage_backend.lower()
        if backend == "s3":
            _storage_instance = S3StorageBackend()
            logger.info("storage.backend.initialized", backend="s3")
        else:
            _storage_instance = LocalStorageBackend()
            logger.info("storage.backend.initialized", backend="local")
    return _storage_instance
