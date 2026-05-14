"""
Text Preprocessing Service
============================
Cleans and normalises raw OCR output before metadata extraction or chunking.

Pipeline:
  raw OCR text
    → normalize whitespace
    → fix common OCR errors
    → remove noise (headers, footers, page numbers)
    → detect and tag language
    → output clean text + stats
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CleanedText:
    raw: str
    cleaned: str
    language: Optional[str]
    char_count_before: int
    char_count_after: int
    noise_removed_percent: float
    corrections_applied: List[str]


# ──────────────────────────────────────────────
# OCR Error Correction Map
# ──────────────────────────────────────────────

# Common OCR misreads (char-level and word-level)
OCR_CORRECTIONS: List[Tuple[str, str]] = [
    # Number/letter confusion
    (r"\b0(?=[A-Za-z])", "O"),           # 0 read as O before letter
    (r"(?<=[A-Za-z])0\b", "O"),          # O at end of word
    (r"\bl\b", "1"),                     # Isolated 'l' → '1'
    (r"\bI(?=\d)", "1"),                 # I before digit → 1

    # Common word fixes
    (r"\bDa\b", "Date"),
    (r"\bNanie\b", "Name"),
    (r"\bAadhar\b", "Aadhaar"),
    (r"\bGovt\b", "Government"),
    (r"\bAc\.?\s*No\b", "Account No"),
    (r"\bA/c\b", "Account"),

    # Currency symbols
    (r"Rs\.?\s*(\d)", r"₹\1"),
    (r"INR\s*(\d)", r"₹\1"),

    # Date separator normalisation
    (r"(\d{2})[-–](\d{2})[-–](\d{4})", r"\1/\2/\3"),
]

# Patterns to strip as noise
NOISE_PATTERNS = [
    r"Page\s+\d+\s+of\s+\d+",           # Page X of Y
    r"^\s*\d+\s*$",                      # Standalone page numbers
    r"-{3,}",                            # Horizontal rules
    r"={3,}",
    r"_{3,}",
    r"\*{3,}",
    r"Continued on next page.*",
    r"This is a computer generated.*",
    r"Digitally signed.*",
    r"Powered by.*",
    r"Generated on.*\d{4}",
]


class TextPreprocessor:
    """Cleans raw OCR text for downstream processing."""

    def __init__(self) -> None:
        self._compiled_corrections = [
            (re.compile(p, re.IGNORECASE), r)
            for p, r in OCR_CORRECTIONS
        ]
        self._compiled_noise = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in NOISE_PATTERNS
        ]

    def clean(self, text: str) -> CleanedText:
        """Run full cleaning pipeline."""
        original_len = len(text)
        corrections_applied: List[str] = []

        # 1. Unicode normalization
        text = unicodedata.normalize("NFKC", text)

        # 2. Fix encoding artifacts
        text = self._fix_encoding(text)

        # 3. Normalize whitespace
        text = self._normalize_whitespace(text)
        corrections_applied.append("whitespace_normalized")

        # 4. Remove noise patterns
        before_noise = len(text)
        text = self._remove_noise(text)
        if len(text) < before_noise:
            corrections_applied.append("noise_removed")

        # 5. Apply OCR corrections
        before_corrections = len(text)
        text = self._apply_corrections(text)
        if len(text) != before_corrections:
            corrections_applied.append("ocr_corrections")

        # 6. Normalize line breaks
        text = self._normalize_lines(text)

        # 7. Detect language
        language = self._detect_language(text)

        final_len = len(text)
        noise_pct = round(max(0, (original_len - final_len) / max(original_len, 1)) * 100, 1)

        return CleanedText(
            raw=text[:200],           # Keep short snippet of raw for debug
            cleaned=text,
            language=language,
            char_count_before=original_len,
            char_count_after=final_len,
            noise_removed_percent=noise_pct,
            corrections_applied=corrections_applied,
        )

    def _fix_encoding(self, text: str) -> str:
        """Fix common encoding artifacts from PDF extraction."""
        replacements = {
            "\uf0b7": "•",
            "\uf0d8": "→",
            "\u00a0": " ",     # Non-breaking space
            "\u200b": "",      # Zero-width space
            "\ufeff": "",      # BOM
            "ﬁ": "fi",
            "ﬂ": "fl",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        return text

    def _normalize_whitespace(self, text: str) -> str:
        """Collapse multiple spaces, normalize tabs."""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _remove_noise(self, text: str) -> str:
        for pattern in self._compiled_noise:
            text = pattern.sub("", text)
        return text

    def _apply_corrections(self, text: str) -> str:
        for pattern, replacement in self._compiled_corrections:
            text = pattern.sub(replacement, text)
        return text

    def _normalize_lines(self, text: str) -> str:
        """Rejoin hyphenated line breaks, clean trailing spaces."""
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(lines)

    def _detect_language(self, text: str) -> Optional[str]:
        """Detect primary language using langdetect."""
        try:
            from langdetect import detect, LangDetectException
            sample = text[:1000]
            if len(sample.strip()) < 20:
                return None
            lang = detect(sample)
            return lang
        except Exception:
            return None


# ──────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────

_preprocessor = TextPreprocessor()


async def clean_text(raw_text: str) -> CleanedText:
    """Async wrapper — runs CPU-bound cleaning in thread pool."""
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _preprocessor.clean, raw_text)
    logger.info(
        "text.cleaned",
        before=result.char_count_before,
        after=result.char_count_after,
        noise_removed=result.noise_removed_percent,
        language=result.language,
    )
    return result
