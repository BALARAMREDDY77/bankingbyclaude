"""
Shared Mock Banking Tools
===========================
Simulated banking APIs for all agents.
All tools return realistic mock data — no real bank integrations.
Each tool is isolated, typed, and logged.

Tools:
  - get_credit_bureau_report     : Mock CIBIL/Experian score
  - verify_pan_number            : Simulated PAN validation
  - verify_aadhaar               : Simulated Aadhaar validation
  - get_transaction_history      : Mock bank statement
  - check_sanctions_list         : Simulated OFAC/UN sanctions
  - check_pep_database           : Simulated PEP screening
  - get_fraud_case_history       : Mock fraud database lookup
  - calculate_emi                : EMI calculation (deterministic)
  - get_rbi_guidelines           : RBI policy mock
"""

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


def _tool_log(tool_name: str, params: Dict, result: Dict) -> None:
    logger.info(
        "tool.called",
        tool=tool_name,
        param_keys=list(params.keys()),
        result_keys=list(result.keys()),
    )


# ──────────────────────────────────────────────
# Credit Bureau (Mock CIBIL/Experian)
# ──────────────────────────────────────────────

async def get_credit_bureau_report(
    pan_number: str,
    user_name: str,
    dob: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulated credit bureau report. Deterministic based on PAN."""
    # Deterministic seed from PAN so same PAN always returns same score
    seed = int(hashlib.md5(pan_number.encode()).hexdigest(), 16) % 1000
    random.seed(seed)

    credit_score = random.randint(550, 850)
    num_accounts = random.randint(1, 8)
    overdue_accounts = random.randint(0, 2)

    result = {
        "pan_number": pan_number,
        "credit_score": credit_score,
        "score_band": (
            "Excellent" if credit_score >= 750
            else "Good" if credit_score >= 700
            else "Fair" if credit_score >= 650
            else "Poor"
        ),
        "total_accounts": num_accounts,
        "active_accounts": num_accounts - overdue_accounts,
        "overdue_accounts": overdue_accounts,
        "total_credit_limit": round(random.uniform(50000, 1000000), 2),
        "total_outstanding": round(random.uniform(0, 500000), 2),
        "credit_utilization_pct": round(random.uniform(10, 80), 1),
        "payment_history": "Regular" if overdue_accounts == 0 else "Minor Delays",
        "oldest_account_years": random.randint(1, 15),
        "hard_inquiries_last_6m": random.randint(0, 5),
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "bureau": "Mock-CIBIL",
        "status": "success",
    }
    _tool_log("get_credit_bureau_report", {"pan": pan_number[:5] + "XXXXX"}, result)
    return result


# ──────────────────────────────────────────────
# PAN Verification (Mock)
# ──────────────────────────────────────────────

async def verify_pan_number(
    pan_number: str,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulated PAN verification against Income Tax database."""
    import re
    is_valid_format = bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan_number))

    result = {
        "pan_number": pan_number,
        "is_valid_format": is_valid_format,
        "is_registered": is_valid_format,
        "name_on_pan": name or "SIMULATED NAME",
        "pan_type": "Individual" if pan_number[3] == "P" else "Company",
        "status": "Active" if is_valid_format else "Invalid",
        "verification_source": "Mock-NSDL",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _tool_log("verify_pan_number", {"pan": pan_number[:5] + "XXXXX"}, result)
    return result


# ──────────────────────────────────────────────
# Aadhaar Verification (Mock)
# ──────────────────────────────────────────────

async def verify_aadhaar(
    aadhaar_uid: str,
    name: Optional[str] = None,
    dob: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulated Aadhaar verification (masked UID only)."""
    clean_uid = aadhaar_uid.replace(" ", "")
    is_valid = len(clean_uid) == 12 and clean_uid.isdigit()

    result = {
        "uid_last4": clean_uid[-4:] if len(clean_uid) >= 4 else "XXXX",
        "is_valid": is_valid,
        "is_linked_to_mobile": is_valid,
        "name_match": True if name else None,
        "dob_match": True if dob else None,
        "address_available": is_valid,
        "kyc_status": "Verified" if is_valid else "Failed",
        "verification_source": "Mock-UIDAI",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _tool_log("verify_aadhaar", {"uid_last4": result["uid_last4"]}, result)
    return result


# ──────────────────────────────────────────────
# Transaction History (Mock)
# ──────────────────────────────────────────────

async def get_transaction_history(
    user_id: str,
    months: int = 6,
    account_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulated bank statement for the past N months."""
    seed = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 10000
    random.seed(seed)

    monthly_salary = round(random.uniform(25000, 200000), 2)
    monthly_expenses = round(monthly_salary * random.uniform(0.4, 0.85), 2)
    emi = round(random.choice([0, 0, monthly_salary * 0.2, monthly_salary * 0.35]), 2)

    transactions = []
    categories = ["Groceries", "Utilities", "Dining", "Transport", "Shopping", "Medical", "Entertainment"]

    for month_offset in range(months):
        month_date = datetime.now(timezone.utc) - timedelta(days=30 * month_offset)
        # Salary credit
        transactions.append({
            "date": (month_date - timedelta(days=random.randint(1, 3))).strftime("%Y-%m-%d"),
            "type": "credit",
            "amount": monthly_salary + random.uniform(-2000, 2000),
            "description": "SALARY CREDIT",
            "category": "Income",
        })
        # EMI debit
        if emi > 0:
            transactions.append({
                "date": (month_date - timedelta(days=5)).strftime("%Y-%m-%d"),
                "type": "debit",
                "amount": emi,
                "description": "EMI PAYMENT",
                "category": "Loan Repayment",
            })
        # Expense debits
        for _ in range(random.randint(8, 20)):
            transactions.append({
                "date": (month_date - timedelta(days=random.randint(1, 28))).strftime("%Y-%m-%d"),
                "type": "debit",
                "amount": round(random.uniform(100, 15000), 2),
                "description": f"UPI/{random.choice(categories).upper()}",
                "category": random.choice(categories),
            })

    total_credit = sum(t["amount"] for t in transactions if t["type"] == "credit")
    total_debit = sum(t["amount"] for t in transactions if t["type"] == "debit")

    result = {
        "user_id": user_id,
        "period_months": months,
        "total_credit": round(total_credit, 2),
        "total_debit": round(total_debit, 2),
        "net_cashflow": round(total_credit - total_debit, 2),
        "avg_monthly_credit": round(total_credit / months, 2),
        "avg_monthly_debit": round(total_debit / months, 2),
        "estimated_monthly_salary": monthly_salary,
        "estimated_monthly_emi": emi,
        "transactions": sorted(transactions, key=lambda x: x["date"], reverse=True)[:50],
        "transaction_count": len(transactions),
        "source": "Mock-BankAPI",
    }
    _tool_log("get_transaction_history", {"user_id": user_id, "months": months}, {"count": result["transaction_count"]})
    return result


# ──────────────────────────────────────────────
# Sanctions + PEP Screening (Mock)
# ──────────────────────────────────────────────

async def check_sanctions_list(name: str, pan: Optional[str] = None) -> Dict[str, Any]:
    """Simulated OFAC/UN sanctions screening."""
    # Deterministic — names with "FRAUD" substring get flagged (for testing)
    is_sanctioned = "FRAUD" in name.upper()
    result = {
        "name_checked": name,
        "is_sanctioned": is_sanctioned,
        "match_score": 1.0 if is_sanctioned else 0.0,
        "lists_checked": ["UN-Consolidated", "OFAC-SDN", "EU-Sanctions", "RBI-Caution"],
        "status": "Hit" if is_sanctioned else "Clear",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Mock-SanctionsDB",
    }
    _tool_log("check_sanctions_list", {"name": name[:10]}, result)
    return result


async def check_pep_database(name: str, dob: Optional[str] = None) -> Dict[str, Any]:
    """Simulated Politically Exposed Person screening."""
    is_pep = "MINISTER" in name.upper() or "MP" in name.upper()
    result = {
        "name_checked": name,
        "is_pep": is_pep,
        "pep_category": "Domestic PEP" if is_pep else None,
        "risk_level": "High" if is_pep else "Low",
        "source": "Mock-PEPDB",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    _tool_log("check_pep_database", {"name": name[:10]}, result)
    return result


# ──────────────────────────────────────────────
# Fraud Case History (Mock)
# ──────────────────────────────────────────────

async def get_fraud_case_history(user_id: str) -> Dict[str, Any]:
    """Simulated internal fraud database lookup."""
    seed = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100
    has_history = seed < 5  # 5% of users have fraud history

    result = {
        "user_id": user_id,
        "has_fraud_history": has_history,
        "case_count": random.randint(1, 3) if has_history else 0,
        "last_case_date": "2023-01-15" if has_history else None,
        "case_types": ["Transaction Fraud"] if has_history else [],
        "status": "Watchlist" if has_history else "Clean",
        "source": "Mock-InternalFraudDB",
    }
    _tool_log("get_fraud_case_history", {"user_id": user_id}, result)
    return result


# ──────────────────────────────────────────────
# EMI Calculator (Deterministic)
# ──────────────────────────────────────────────

def calculate_emi(
    principal: float,
    annual_rate: float,
    tenure_months: int,
) -> Dict[str, Any]:
    """Calculate EMI using standard formula. Deterministic."""
    monthly_rate = annual_rate / (12 * 100)
    if monthly_rate == 0:
        emi = principal / tenure_months
    else:
        emi = principal * monthly_rate * (1 + monthly_rate) ** tenure_months / (
            (1 + monthly_rate) ** tenure_months - 1
        )

    total_payment = emi * tenure_months
    total_interest = total_payment - principal

    result = {
        "principal": round(principal, 2),
        "annual_interest_rate": annual_rate,
        "tenure_months": tenure_months,
        "emi": round(emi, 2),
        "total_payment": round(total_payment, 2),
        "total_interest": round(total_interest, 2),
        "interest_pct_of_principal": round((total_interest / principal) * 100, 2),
    }
    _tool_log("calculate_emi", {"principal": principal, "rate": annual_rate}, result)
    return result


# ──────────────────────────────────────────────
# RBI Guidelines (Mock policy fetch)
# ──────────────────────────────────────────────

async def get_rbi_guidelines(topic: str) -> Dict[str, Any]:
    """Simulated RBI policy database lookup."""
    guidelines = {
        "kyc": {
            "circular": "RBI/2016-17/81 Master Direction",
            "key_points": [
                "KYC must be done at account opening",
                "Aadhaar + PAN mandatory for accounts above ₹50,000 deposits",
                "Re-KYC every 2 years for high-risk customers",
                "Video KYC permitted for digital onboarding",
            ],
        },
        "loan": {
            "circular": "RBI/2023-24/53 Fair Lending Practices",
            "key_points": [
                "EMI-to-income ratio should not exceed 50%",
                "Credit score < 650 requires enhanced due diligence",
                "Processing fee: max 2% of loan amount",
                "Prepayment charges not applicable for floating rate loans",
            ],
        },
        "aml": {
            "circular": "PMLA 2002 & RBI AML/CFT Guidelines",
            "key_points": [
                "Report transactions > ₹10 lakhs to FIU",
                "Suspicious transaction report within 7 days",
                "CTR filing mandatory within 15 days",
                "Customer due diligence for all accounts",
            ],
        },
    }

    topic_lower = topic.lower()
    for key, data in guidelines.items():
        if key in topic_lower:
            return {"topic": topic, "source": "Mock-RBI-Circular", **data, "status": "found"}

    return {
        "topic": topic,
        "source": "Mock-RBI-Circular",
        "key_points": ["General RBI guidelines apply. Consult compliance team."],
        "status": "generic",
    }
