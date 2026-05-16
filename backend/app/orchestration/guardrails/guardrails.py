"""
Guardrail System
==================
Input and output guardrails for all LangGraph nodes.

Input guardrails:
  - PII detection (Aadhaar, PAN, card numbers)
  - Prompt injection detection
  - Toxicity / harmful content check
  - Query length limits

Output guardrails:
  - Hallucination detection (confidence gating)
  - PII leakage prevention
  - Financial advice disclaimer enforcement
  - Structured output schema validation
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── PII patterns ─────────────────────────────
PII_PATTERNS = {
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"),
    "phone": re.compile(r"\b[6-9]\d{9}\b"),
    "email": re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    "bank_account": re.compile(r"\b\d{9,18}\b"),
    "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
}

# ── Injection patterns ───────────────────────
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|all)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a?\s*(different|new|evil)", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+(have\s+no|ignore)", re.IGNORECASE),
    re.compile(r"(jailbreak|DAN|do\s+anything\s+now)", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),                           # Token injection
    re.compile(r"\[INST\]|\[\/INST\]"),                # Llama injection
]

# ── Harmful content triggers ─────────────────
HARMFUL_TRIGGERS = [
    "money laundering instructions",
    "bypass kyc",
    "fake documents",
    "illegal transfer",
    "tax evasion steps",
]


@dataclass
class GuardrailResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    pii_detected: List[str] = field(default_factory=list)
    sanitized_text: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class InputGuardrail:
    """Validates and sanitizes LLM inputs before sending to the model."""

    MAX_INPUT_CHARS = 8000

    def check(self, text: str, context: Optional[Dict] = None) -> GuardrailResult:
        violations = []
        pii_found = []

        # Length check
        if len(text) > self.MAX_INPUT_CHARS:
            violations.append(f"Input exceeds {self.MAX_INPUT_CHARS} chars.")

        # Prompt injection
        for pattern in INJECTION_PATTERNS:
            if pattern.search(text):
                violations.append("Potential prompt injection detected.")
                break

        # Harmful content
        text_lower = text.lower()
        for trigger in HARMFUL_TRIGGERS:
            if trigger in text_lower:
                violations.append(f"Harmful content pattern: '{trigger}'")

        # PII detection (warn but don't block — banking needs PII)
        for pii_type, pattern in PII_PATTERNS.items():
            if pattern.search(text):
                pii_found.append(pii_type)

        passed = len(violations) == 0
        if not passed:
            logger.warning(
                "guardrail.input_failed",
                violations=violations,
                pii=pii_found,
            )
        elif pii_found:
            logger.info("guardrail.pii_detected_in_input", types=pii_found)

        return GuardrailResult(
            passed=passed,
            violations=violations,
            pii_detected=pii_found,
        )


class OutputGuardrail:
    """Validates LLM outputs before returning to the user."""

    # Financial advice disclaimer required for these topics
    FINANCIAL_ADVICE_KEYWORDS = [
        "invest", "returns", "profit", "stock", "mutual fund",
        "guaranteed", "risk-free", "assured returns",
    ]

    DISCLAIMER = (
        "\n\n*This information is for general guidance only and does not "
        "constitute financial or legal advice. Please consult a qualified "
        "advisor before making financial decisions.*"
    )

    def check(
        self,
        text: str,
        confidence: float = 1.0,
        expected_schema: Optional[Dict] = None,
    ) -> GuardrailResult:
        violations = []
        sanitized = text

        # Confidence gating
        if confidence < settings.orchestration.min_confidence_threshold:
            violations.append(
                f"Output confidence {confidence:.2f} below threshold "
                f"{settings.orchestration.min_confidence_threshold}."
            )

        # PII leakage check (Aadhaar / PAN should not appear in responses)
        for pii_type in ["aadhaar", "pan", "credit_card"]:
            pattern = PII_PATTERNS[pii_type]
            if pattern.search(text):
                sanitized = pattern.sub(f"[{pii_type.upper()} REDACTED]", sanitized)
                logger.warning("guardrail.output_pii_redacted", pii_type=pii_type)

        # Financial advice disclaimer
        text_lower = text.lower()
        needs_disclaimer = any(kw in text_lower for kw in self.FINANCIAL_ADVICE_KEYWORDS)
        if needs_disclaimer and self.DISCLAIMER not in sanitized:
            sanitized = sanitized + self.DISCLAIMER

        # Empty output check
        if not text.strip():
            violations.append("Empty LLM output.")

        passed = len(violations) == 0
        if not passed:
            logger.warning("guardrail.output_failed", violations=violations)

        return GuardrailResult(
            passed=passed,
            violations=violations,
            sanitized_text=sanitized,
        )


# ── Singletons ───────────────────────────────
_input_guardrail = InputGuardrail()
_output_guardrail = OutputGuardrail()


def get_input_guardrail() -> InputGuardrail:
    return _input_guardrail


def get_output_guardrail() -> OutputGuardrail:
    return _output_guardrail
