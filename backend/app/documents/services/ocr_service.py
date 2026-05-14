"""
OCR Service
============
Multi-engine document text extraction.

Strategy per document type:
  1. pdfplumber  — native text PDFs (fast, high quality)
  2. PyMuPDF     — mixed PDFs (text + images)
  3. Tesseract   — scanned PDFs / image-only PDFs (OCR fallback)

Supports: English, Hindi, and other Tesseract language packs.
All CPU-intensive ops run in a thread pool executor.
"""

import asyncio
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, Dict, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExtractionMethod(str, Enum):
    PDFPLUMBER = "pdfplumber"
    PYMUPDF = "pymupdf"
    TESSERACT = "tesseract"
    HYBRID = "hybrid"


@dataclass
class PageResult:
    page_number: int
    text: str
    confidence: float          # 0.0 - 1.0
    method: ExtractionMethod
    word_count: int
    char_count: int
    has_tables: bool = False
    tables: List[List[List[str]]] = field(default_factory=list)
    image_count: int = 0
    language_detected: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class OCRResult:
    total_pages: int
    pages: List[PageResult]
    full_text: str
    method_used: ExtractionMethod
    is_scanned: bool
    language: Optional[str]
    processing_time_ms: int
    confidence_avg: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return sum(p.word_count for p in self.pages)

    @property
    def is_empty(self) -> bool:
        return len(self.full_text.strip()) == 0


# ──────────────────────────────────────────────
# OCR Service
# ──────────────────────────────────────────────

class OCRService:
    """
    Unified OCR service supporting scanned and digital PDFs.
    Automatically selects the best extraction strategy per document.
    """

    SCANNED_THRESHOLD = 50    # chars per page — below this = likely scanned
    MIN_CONFIDENCE = 0.3

    def __init__(self) -> None:
        self.langs = settings.documents.ocr_languages
        self.dpi = settings.documents.ocr_dpi
        self.timeout = settings.documents.ocr_timeout_seconds
        self.max_pages = settings.documents.max_pages_per_doc
        self._tesseract_configured = False

    def _configure_tesseract(self) -> None:
        if not self._tesseract_configured:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = settings.documents.tesseract_cmd
            self._tesseract_configured = True

    # ──────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(settings.documents.max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def extract(self, content: bytes, filename: str = "") -> OCRResult:
        """
        Main extraction method. Automatically chooses strategy:
        - Native PDF text → pdfplumber
        - Mixed / image PDF → PyMuPDF + Tesseract fallback
        - Pure scanned → Tesseract on rendered pages
        """
        import time
        start = time.perf_counter()

        ext = filename.lower().split(".")[-1] if filename else "pdf"

        if ext in ("jpg", "jpeg", "png", "tiff", "bmp", "webp"):
            result = await self._extract_image(content)
        else:
            result = await self._extract_pdf(content)

        result.processing_time_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "ocr.extraction_complete",
            filename=filename,
            pages=result.total_pages,
            method=result.method_used,
            words=result.word_count,
            time_ms=result.processing_time_ms,
            is_scanned=result.is_scanned,
        )
        return result

    # ──────────────────────────────────────────
    # PDF Extraction
    # ──────────────────────────────────────────

    async def _extract_pdf(self, content: bytes) -> OCRResult:
        loop = asyncio.get_event_loop()

        # Step 1: Try pdfplumber (fastest for native text)
        native_result = await loop.run_in_executor(
            None, partial(self._extract_native_pdf, content)
        )

        avg_chars = (
            sum(p.char_count for p in native_result.pages) / max(len(native_result.pages), 1)
        )

        if avg_chars >= self.SCANNED_THRESHOLD:
            # Good native text — use pdfplumber result
            return native_result

        # Step 2: Scanned / low text — fall back to PyMuPDF + Tesseract
        logger.info("ocr.falling_back_to_tesseract", avg_chars_per_page=avg_chars)
        return await loop.run_in_executor(
            None, partial(self._extract_scanned_pdf, content)
        )

    def _extract_native_pdf(self, content: bytes) -> OCRResult:
        """Extract text from native (non-scanned) PDF using pdfplumber."""
        import pdfplumber

        pages: List[PageResult] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            doc_meta = {
                "page_count": len(pdf.pages),
                "metadata": pdf.metadata or {},
            }
            for i, page in enumerate(pdf.pages[:self.max_pages]):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []
                clean_tables = [[list(map(str, row)) for row in t] for t in tables if t]

                pages.append(PageResult(
                    page_number=i + 1,
                    text=text,
                    confidence=0.95 if text.strip() else 0.1,
                    method=ExtractionMethod.PDFPLUMBER,
                    word_count=len(text.split()),
                    char_count=len(text),
                    has_tables=bool(clean_tables),
                    tables=clean_tables,
                ))

        full_text = "\n\n".join(p.text for p in pages if p.text.strip())
        avg_conf = sum(p.confidence for p in pages) / max(len(pages), 1)

        return OCRResult(
            total_pages=len(pages),
            pages=pages,
            full_text=full_text,
            method_used=ExtractionMethod.PDFPLUMBER,
            is_scanned=False,
            language=None,
            processing_time_ms=0,
            confidence_avg=avg_conf,
            metadata=doc_meta,
        )

    def _extract_scanned_pdf(self, content: bytes) -> OCRResult:
        """
        Render each PDF page as image and run Tesseract OCR.
        Uses PyMuPDF for high-quality rendering.
        """
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        self._configure_tesseract()

        pages: List[PageResult] = []
        doc = fitz.open(stream=content, filetype="pdf")

        for i in range(min(doc.page_count, self.max_pages)):
            page = doc[i]

            # Render at configured DPI (300 DPI = production quality)
            matrix = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))

            # Preprocess image for better OCR accuracy
            image = self._preprocess_image(image)

            # Run Tesseract with confidence data
            ocr_data = pytesseract.image_to_data(
                image,
                lang=self.langs,
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 3",
            )

            text = pytesseract.image_to_string(
                image,
                lang=self.langs,
                config="--oem 3 --psm 3",
            )

            # Calculate confidence from Tesseract data
            confidences = [
                int(c) for c in ocr_data.get("conf", [])
                if str(c).strip() not in ("-1", "")
            ]
            conf = (sum(confidences) / len(confidences) / 100) if confidences else 0.0

            pages.append(PageResult(
                page_number=i + 1,
                text=text,
                confidence=conf,
                method=ExtractionMethod.TESSERACT,
                word_count=len(text.split()),
                char_count=len(text),
            ))

        doc.close()
        full_text = "\n\n".join(p.text for p in pages if p.text.strip())
        avg_conf = sum(p.confidence for p in pages) / max(len(pages), 1)

        return OCRResult(
            total_pages=len(pages),
            pages=pages,
            full_text=full_text,
            method_used=ExtractionMethod.TESSERACT,
            is_scanned=True,
            language=None,
            processing_time_ms=0,
            confidence_avg=avg_conf,
        )

    # ──────────────────────────────────────────
    # Image Extraction
    # ──────────────────────────────────────────

    async def _extract_image(self, content: bytes) -> OCRResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, partial(self._run_tesseract_on_image, content)
        )

    def _run_tesseract_on_image(self, content: bytes) -> OCRResult:
        import pytesseract
        from PIL import Image

        self._configure_tesseract()
        image = Image.open(io.BytesIO(content))
        image = self._preprocess_image(image)

        text = pytesseract.image_to_string(image, lang=self.langs, config="--oem 3 --psm 3")
        data = pytesseract.image_to_data(image, lang=self.langs, output_type=pytesseract.Output.DICT)

        confidences = [int(c) for c in data.get("conf", []) if str(c).strip() not in ("-1", "")]
        conf = (sum(confidences) / len(confidences) / 100) if confidences else 0.0

        page = PageResult(
            page_number=1,
            text=text,
            confidence=conf,
            method=ExtractionMethod.TESSERACT,
            word_count=len(text.split()),
            char_count=len(text),
        )
        return OCRResult(
            total_pages=1,
            pages=[page],
            full_text=text,
            method_used=ExtractionMethod.TESSERACT,
            is_scanned=True,
            language=None,
            processing_time_ms=0,
            confidence_avg=conf,
        )

    # ──────────────────────────────────────────
    # Image Preprocessing
    # ──────────────────────────────────────────

    @staticmethod
    def _preprocess_image(image):
        """
        Enhance image quality before OCR:
        - Convert to grayscale
        - Increase contrast
        - Denoise
        Returns PIL Image.
        """
        try:
            import cv2
            import numpy as np
            from PIL import ImageEnhance

            # Grayscale
            if image.mode != "L":
                image = image.convert("L")

            # Enhance contrast
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

            # Convert to numpy for OpenCV operations
            img_array = np.array(image)

            # Denoise
            img_array = cv2.fastNlMeansDenoising(img_array, h=10)

            # Adaptive threshold (better than global for varied lighting)
            img_array = cv2.adaptiveThreshold(
                img_array, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2,
            )

            from PIL import Image as PILImage
            return PILImage.fromarray(img_array)

        except ImportError:
            # OpenCV not available — return grayscale only
            return image.convert("L") if image.mode != "L" else image
