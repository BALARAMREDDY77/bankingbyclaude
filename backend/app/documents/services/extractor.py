"""
Document Metadata Extractor
=============================
Extracts structured fields from raw OCR text per document type.

Supported documents:
  - Aadhaar Card     → name, DOB, gender, UID, address
  - PAN Card         → name, DOB, PAN number, father's name
  - Salary Slip      → employer, employee, month, gross/net salary, deductions
  - Bank Statement   → account holder, account number, IFSC, period, transactions
  - Loan Application → applicant info, loan amount, purpose

All extractors return typed dicts — downstream services validate with Pydantic.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class SupportedDocType(str, Enum):
    AADHAAR = "aadhaar"
    PAN_CARD = "pan_card"
    SALARY_SLIP = "salary_slip"
    BANK_STATEMENT = "bank_statement"
    LOAN_APPLICATION = "loan_application"
    GENERIC = "generic"


@dataclass
class ExtractedMetadata:
    doc_type: SupportedDocType
    fields: Dict[str, Any]
    confidence: float          # 0.0–1.0 based on fields found vs expected
    missing_fields: List[str]
    warnings: List[str] = field(default_factory=list)
    raw_text_snippet: str = ""


# ──────────────────────────────────────────────
# Base Extractor
# ──────────────────────────────────────────────

class BaseExtractor:
    EXPECTED_FIELDS: List[str] = []

    def extract(self, text: str) -> ExtractedMetadata:
        raise NotImplementedError

    def _confidence(self, found: Dict[str, Any]) -> tuple[float, List[str]]:
        if not self.EXPECTED_FIELDS:
            return 1.0, []
        found_keys = {k for k, v in found.items() if v is not None}
        missing = [f for f in self.EXPECTED_FIELDS if f not in found_keys]
        score = (len(self.EXPECTED_FIELDS) - len(missing)) / len(self.EXPECTED_FIELDS)
        return round(score, 3), missing

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _find(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else None

    @staticmethod
    def _find_amount(pattern: str, text: str) -> Optional[float]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").strip()
            try:
                return float(raw)
            except ValueError:
                return None
        return None


# ──────────────────────────────────────────────
# Aadhaar Extractor
# ──────────────────────────────────────────────

class AadhaarExtractor(BaseExtractor):
    EXPECTED_FIELDS = ["uid", "name", "dob", "gender", "address"]

    def extract(self, text: str) -> ExtractedMetadata:
        fields: Dict[str, Any] = {}

        # UID: 12-digit number, often spaced as XXXX XXXX XXXX
        uid_match = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", text)
        if uid_match:
            fields["uid"] = uid_match.group(1).replace(" ", "")

        # DOB: DD/MM/YYYY or DD-MM-YYYY
        dob_match = re.search(
            r"(?:DOB|Date of Birth|जन्म तिथि)[:\s]*(\d{2}[/\-]\d{2}[/\-]\d{4})",
            text, re.IGNORECASE
        )
        fields["dob"] = dob_match.group(1) if dob_match else self._find(
            r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b", text
        )

        # Gender
        gender_match = re.search(r"\b(Male|Female|MALE|FEMALE|पुरुष|महिला)\b", text)
        if gender_match:
            g = gender_match.group(1).upper()
            fields["gender"] = "M" if g in ("MALE", "पुरुष") else "F"

        # Name — line after "Name" label or before DOB
        name_match = re.search(r"(?:^|\n)([A-Z][A-Za-z\s]{3,50})(?=\n|\s+\d{2}[/\-])", text)
        fields["name"] = name_match.group(1).strip() if name_match else None

        # Address — after S/O, D/O, W/O or "Address"
        addr_match = re.search(
            r"(?:Address|पता)[:\s]*([A-Za-z0-9\s,\-\.]{20,300})",
            text, re.IGNORECASE | re.DOTALL
        )
        fields["address"] = self._clean(addr_match.group(1)) if addr_match else None

        # VID (Virtual ID) — optional
        vid_match = re.search(r"VID[:\s]*(\d{16})", text)
        fields["vid"] = vid_match.group(1) if vid_match else None

        conf, missing = self._confidence(fields)
        return ExtractedMetadata(
            doc_type=SupportedDocType.AADHAAR,
            fields=fields,
            confidence=conf,
            missing_fields=missing,
            raw_text_snippet=text[:500],
        )


# ──────────────────────────────────────────────
# PAN Card Extractor
# ──────────────────────────────────────────────

class PANExtractor(BaseExtractor):
    EXPECTED_FIELDS = ["pan_number", "name", "father_name", "dob"]

    def extract(self, text: str) -> ExtractedMetadata:
        fields: Dict[str, Any] = {}

        # PAN: AAAAA9999A format
        pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
        fields["pan_number"] = pan_match.group(1) if pan_match else None

        # DOB
        dob_match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
        fields["dob"] = dob_match.group(1) if dob_match else None

        # Name (full caps line before father's name)
        name_matches = re.findall(r"^([A-Z][A-Z\s]{5,60})$", text, re.MULTILINE)
        if len(name_matches) >= 1:
            fields["name"] = name_matches[0].strip()
        if len(name_matches) >= 2:
            fields["father_name"] = name_matches[1].strip()

        # Income Tax Dept label confirms PAN doc
        fields["is_income_tax_doc"] = bool(
            re.search(r"Income Tax|INCOME TAX|आयकर", text, re.IGNORECASE)
        )

        conf, missing = self._confidence(fields)
        return ExtractedMetadata(
            doc_type=SupportedDocType.PAN_CARD,
            fields=fields,
            confidence=conf,
            missing_fields=missing,
            raw_text_snippet=text[:500],
        )


# ──────────────────────────────────────────────
# Salary Slip Extractor
# ──────────────────────────────────────────────

class SalarySlipExtractor(BaseExtractor):
    EXPECTED_FIELDS = ["employee_name", "month_year", "gross_salary", "net_salary", "employer"]

    def extract(self, text: str) -> ExtractedMetadata:
        fields: Dict[str, Any] = {}

        # Employer name (usually at top)
        emp_match = re.search(
            r"(?:Company|Employer|Organisation|Organization)[:\s]+([A-Za-z0-9\s&\.,]+)",
            text, re.IGNORECASE
        )
        fields["employer"] = emp_match.group(1).strip() if emp_match else None

        # Employee name
        name_match = re.search(
            r"(?:Employee Name|Name of Employee|Employee)[:\s]+([A-Za-z\s\.]+)",
            text, re.IGNORECASE
        )
        fields["employee_name"] = name_match.group(1).strip() if name_match else None

        # Employee ID
        eid_match = re.search(r"(?:Employee ID|Emp\. ID|EMP ID)[:\s]+([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        fields["employee_id"] = eid_match.group(1).strip() if eid_match else None

        # Month/Year
        month_match = re.search(
            r"(?:Pay Period|Month|Salary for)[:\s]*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s,]*\d{4})",
            text, re.IGNORECASE
        )
        fields["month_year"] = month_match.group(1).strip() if month_match else None

        # Gross salary
        fields["gross_salary"] = self._find_amount(
            r"(?:Gross Salary|Gross Pay|Gross Earnings)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # Net salary
        fields["net_salary"] = self._find_amount(
            r"(?:Net Salary|Net Pay|Net Amount|Take Home)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # Basic salary
        fields["basic_salary"] = self._find_amount(
            r"(?:Basic|Basic Salary|Basic Pay)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # PF deduction
        fields["pf_deduction"] = self._find_amount(
            r"(?:PF|Provident Fund|EPF)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # TDS
        fields["tds"] = self._find_amount(
            r"(?:TDS|Income Tax)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # PAN of employee (often on salary slip)
        pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
        fields["pan_number"] = pan_match.group(1) if pan_match else None

        conf, missing = self._confidence(fields)
        return ExtractedMetadata(
            doc_type=SupportedDocType.SALARY_SLIP,
            fields=fields,
            confidence=conf,
            missing_fields=missing,
            raw_text_snippet=text[:500],
        )


# ──────────────────────────────────────────────
# Bank Statement Extractor
# ──────────────────────────────────────────────

class BankStatementExtractor(BaseExtractor):
    EXPECTED_FIELDS = ["account_holder", "account_number", "ifsc_code", "period", "closing_balance"]

    def extract(self, text: str) -> ExtractedMetadata:
        fields: Dict[str, Any] = {}

        # Account holder name
        holder_match = re.search(
            r"(?:Account Holder|Name|Customer Name)[:\s]+([A-Za-z\s\.]+)",
            text, re.IGNORECASE
        )
        fields["account_holder"] = holder_match.group(1).strip() if holder_match else None

        # Account number (masked or full)
        acc_match = re.search(
            r"(?:Account No|Acct No|Account Number)[.:\s]*([X\d]{4,20})",
            text, re.IGNORECASE
        )
        fields["account_number"] = acc_match.group(1).strip() if acc_match else None

        # IFSC code
        ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text)
        fields["ifsc_code"] = ifsc_match.group(1) if ifsc_match else None

        # Bank name
        bank_names = [
            "State Bank", "HDFC", "ICICI", "Axis", "Kotak", "Punjab National",
            "Bank of Baroda", "Canara", "Union Bank", "IndusInd", "Yes Bank"
        ]
        for bn in bank_names:
            if bn.lower() in text.lower():
                fields["bank_name"] = bn
                break

        # Statement period
        period_match = re.search(
            r"(?:Statement Period|From|Period)[:\s]*(\d{1,2}[/\-]\d{2,4})\s*(?:to|-)?\s*(\d{1,2}[/\-]\d{2,4})",
            text, re.IGNORECASE
        )
        if period_match:
            fields["period"] = f"{period_match.group(1)} to {period_match.group(2)}"

        # Opening / closing balance
        fields["opening_balance"] = self._find_amount(
            r"(?:Opening Balance|O/B)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )
        fields["closing_balance"] = self._find_amount(
            r"(?:Closing Balance|C/B)[:\s₹Rs.]*([0-9,]+(?:\.\d{2})?)", text
        )

        # Count credit/debit transactions (rough estimate from text)
        credits = len(re.findall(r"\bCr\.?\b|\bCredit\b", text, re.IGNORECASE))
        debits = len(re.findall(r"\bDr\.?\b|\bDebit\b", text, re.IGNORECASE))
        fields["credit_count"] = credits
        fields["debit_count"] = debits

        conf, missing = self._confidence(fields)
        return ExtractedMetadata(
            doc_type=SupportedDocType.BANK_STATEMENT,
            fields=fields,
            confidence=conf,
            missing_fields=missing,
            raw_text_snippet=text[:500],
        )


# ──────────────────────────────────────────────
# Extractor Registry
# ──────────────────────────────────────────────

_EXTRACTORS: Dict[SupportedDocType, BaseExtractor] = {
    SupportedDocType.AADHAAR: AadhaarExtractor(),
    SupportedDocType.PAN_CARD: PANExtractor(),
    SupportedDocType.SALARY_SLIP: SalarySlipExtractor(),
    SupportedDocType.BANK_STATEMENT: BankStatementExtractor(),
}


def get_extractor(doc_type: SupportedDocType) -> BaseExtractor:
    return _EXTRACTORS.get(doc_type, BaseExtractor())


async def extract_metadata(
    text: str,
    doc_type: SupportedDocType,
) -> ExtractedMetadata:
    """
    Extract structured metadata from OCR text.
    Runs synchronous extractor in thread pool.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    extractor = get_extractor(doc_type)
    result = await loop.run_in_executor(None, extractor.extract, text)
    logger.info(
        "metadata.extracted",
        doc_type=doc_type,
        confidence=result.confidence,
        fields_found=len([v for v in result.fields.values() if v is not None]),
        missing=result.missing_fields,
    )
    return result
