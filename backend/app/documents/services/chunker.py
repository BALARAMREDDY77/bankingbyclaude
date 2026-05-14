"""
Document Chunking Service
===========================
Splits cleaned document text into overlapping chunks
for embedding preparation (Phase 5 — RAG pipeline).

Strategies:
  - FixedSize: fixed char window with overlap
  - Semantic:  splits on sentence/paragraph boundaries
  - Page:      one chunk per PDF page
  - Hybrid:    semantic within page-size windows (default)

Each chunk carries full provenance metadata so embeddings
can be traced back to source page + position.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChunkStrategy(str, Enum):
    FIXED_SIZE = "fixed_size"
    SEMANTIC = "semantic"
    PAGE = "page"
    HYBRID = "hybrid"


@dataclass
class DocumentChunk:
    chunk_id: str                        # {doc_id}_chunk_{index}
    document_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    page_numbers: List[int]             # Which pages this chunk spans
    word_count: int
    char_count: int
    strategy: ChunkStrategy
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding_vector: Optional[List[float]] = None    # Populated in Phase 5

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0


@dataclass
class ChunkingResult:
    document_id: str
    total_chunks: int
    chunks: List[DocumentChunk]
    strategy: ChunkStrategy
    total_chars: int
    avg_chunk_size: float
    overlap_chars: int


class DocumentChunker:
    """
    Splits document text into chunks for downstream embedding.
    Overlap ensures no information is lost at chunk boundaries.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        strategy: ChunkStrategy = ChunkStrategy.HYBRID,
    ) -> None:
        self.chunk_size = chunk_size or settings.documents.chunk_size_chars
        self.overlap = overlap or settings.documents.chunk_overlap_chars
        self.strategy = strategy

        # Sentence boundary patterns
        self._sentence_endings = re.compile(
            r"(?<=[.!?।])\s+(?=[A-Z\u0900-\u097F])"  # Latin + Devanagari
        )
        # Paragraph boundary
        self._para_break = re.compile(r"\n{2,}")

    def chunk(
        self,
        text: str,
        document_id: str,
        page_texts: Optional[List[str]] = None,
    ) -> ChunkingResult:
        """
        Main chunking entry point. Choose strategy based on content.
        page_texts: per-page text list for page-aware chunking.
        """
        if self.strategy == ChunkStrategy.PAGE and page_texts:
            chunks = self._chunk_by_page(page_texts, document_id)
        elif self.strategy == ChunkStrategy.SEMANTIC:
            chunks = self._chunk_semantic(text, document_id)
        elif self.strategy == ChunkStrategy.FIXED_SIZE:
            chunks = self._chunk_fixed(text, document_id)
        else:
            # HYBRID: semantic within bounded windows
            chunks = self._chunk_hybrid(text, document_id, page_texts)

        # Filter empty chunks
        chunks = [c for c in chunks if not c.is_empty]

        result = ChunkingResult(
            document_id=document_id,
            total_chunks=len(chunks),
            chunks=chunks,
            strategy=self.strategy,
            total_chars=len(text),
            avg_chunk_size=sum(c.char_count for c in chunks) / max(len(chunks), 1),
            overlap_chars=self.overlap,
        )

        logger.info(
            "chunking.complete",
            document_id=document_id,
            strategy=self.strategy,
            total_chunks=result.total_chunks,
            avg_size=round(result.avg_chunk_size),
        )
        return result

    def _chunk_fixed(self, text: str, doc_id: str) -> List[DocumentChunk]:
        """Fixed-size window with overlap."""
        chunks = []
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            chunks.append(self._make_chunk(doc_id, idx, chunk_text, start, end, []))
            idx += 1
            start += self.chunk_size - self.overlap
        return chunks

    def _chunk_semantic(self, text: str, doc_id: str) -> List[DocumentChunk]:
        """Split on paragraph, then sentence boundaries."""
        # Split by paragraphs first
        paragraphs = self._para_break.split(text)
        chunks = []
        current = ""
        current_start = 0
        idx = 0
        pos = 0

        for para in paragraphs:
            if len(current) + len(para) <= self.chunk_size:
                current += ("\n\n" if current else "") + para
            else:
                if current:
                    end = current_start + len(current)
                    chunks.append(self._make_chunk(doc_id, idx, current, current_start, end, []))
                    idx += 1
                    # Overlap: keep last N chars of current
                    overlap_text = current[-self.overlap:]
                    current_start = end - self.overlap
                    current = overlap_text + "\n\n" + para
                else:
                    # Single para larger than chunk_size — split by sentences
                    sentences = self._sentence_endings.split(para)
                    for sent in sentences:
                        if len(current) + len(sent) <= self.chunk_size:
                            current += " " + sent
                        else:
                            if current:
                                end = current_start + len(current)
                                chunks.append(self._make_chunk(doc_id, idx, current, current_start, end, []))
                                idx += 1
                                current_start = end - self.overlap
                                current = current[-self.overlap:] + " " + sent
                            else:
                                # Sentence itself exceeds chunk — force split
                                chunks.extend(self._force_split(sent, doc_id, idx, pos))
                                idx += len(chunks)
            pos += len(para) + 2

        if current.strip():
            end = current_start + len(current)
            chunks.append(self._make_chunk(doc_id, idx, current, current_start, end, []))

        return chunks

    def _chunk_by_page(self, page_texts: List[str], doc_id: str) -> List[DocumentChunk]:
        """One chunk per page (with overflow splitting if page is large)."""
        chunks = []
        idx = 0
        for page_num, page_text in enumerate(page_texts, start=1):
            if len(page_text) <= self.chunk_size:
                chunks.append(
                    self._make_chunk(doc_id, idx, page_text, 0, len(page_text), [page_num])
                )
                idx += 1
            else:
                # Page too large — sub-chunk it
                sub_chunks = self._force_split(page_text, doc_id, idx, 0)
                for c in sub_chunks:
                    c.page_numbers = [page_num]
                chunks.extend(sub_chunks)
                idx += len(sub_chunks)
        return chunks

    def _chunk_hybrid(
        self, text: str, doc_id: str, page_texts: Optional[List[str]]
    ) -> List[DocumentChunk]:
        """
        Semantic chunking within page-sized windows.
        Best balance of context and boundary preservation.
        """
        if page_texts and len(page_texts) > 1:
            return self._chunk_by_page(page_texts, doc_id)
        return self._chunk_semantic(text, doc_id)

    def _force_split(
        self, text: str, doc_id: str, start_idx: int, char_offset: int
    ) -> List[DocumentChunk]:
        """Force-split text that exceeds chunk_size regardless of boundaries."""
        chunks = []
        idx = start_idx
        pos = 0
        while pos < len(text):
            end = min(pos + self.chunk_size, len(text))
            chunk_text = text[pos:end]
            chunks.append(
                self._make_chunk(doc_id, idx, chunk_text, char_offset + pos, char_offset + end, [])
            )
            idx += 1
            pos += self.chunk_size - self.overlap
        return chunks

    @staticmethod
    def _make_chunk(
        doc_id: str,
        idx: int,
        text: str,
        char_start: int,
        char_end: int,
        pages: List[int],
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=f"{doc_id}_chunk_{idx:04d}",
            document_id=doc_id,
            chunk_index=idx,
            text=text.strip(),
            char_start=char_start,
            char_end=char_end,
            page_numbers=pages,
            word_count=len(text.split()),
            char_count=len(text),
            strategy=ChunkStrategy.HYBRID,
        )


# ── Singleton ────────────────────────────────

_chunker = DocumentChunker()


async def chunk_document(
    text: str,
    document_id: str,
    page_texts: Optional[List[str]] = None,
    strategy: ChunkStrategy = ChunkStrategy.HYBRID,
) -> ChunkingResult:
    """Async wrapper for chunking (CPU-bound)."""
    import asyncio
    chunker = DocumentChunker(strategy=strategy)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: chunker.chunk(text, document_id, page_texts)
    )
