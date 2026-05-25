"""
Shared Agent Output Schemas
==============================
All agent outputs are typed Pydantic models.
Every schema includes: confidence, explainability, escalation flag.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentDecisionEnum(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    REVIEW = "manual_review"
    PASS = "pass"
    FLAG = "flag"


class RiskLevelEnum(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LanguageEnum(str, Enum):
    EN = "en"
    HI = "hi"
    TE = "te"
    TA = "ta"
    KN = "kn"
    MR = "mr"


# ── Base Agent Output ────────────────────────

class BaseAgentOutput(BaseModel):
    agent_name: str
    run_id: str
    decision: AgentDecisionEnum
    confidence: float = Field(..., ge=0.0, le=1.0, description="0.0–1.0 confidence score")
    risk_level: RiskLevelEnum
    reasoning: str = Field(..., description="Plain-language explanation of the decision")
    key_factors: List[str] = Field(default_factory=list, description="Top factors driving the decision")
    escalation_required: bool = False
    escalation_reason: Optional[str] = None
    human_handoff: bool = False
    language_used: LanguageEnum = LanguageEnum.EN
    processing_time_ms: Optional[int] = None
    model_used: str = ""
    fallback_triggered: bool = False
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── KYC Agent Output ─────────────────────────

class DocumentCheckResult(BaseModel):
    document_type: str
    is_present: bool
    is_valid: Optional[bool]
    is_authentic: Optional[bool]
    extracted_field: Optional[str]
    issues: List[str] = Field(default_factory=list)


class KYCAgentOutput(BaseAgentOutput):
    agent_name: str = "kyc_verification_agent"
    identity_verified: bool
    documents_checked: List[DocumentCheckResult]
    name_match: Optional[bool]
    dob_match: Optional[bool]
    address_verified: Optional[bool]
    pan_verified: Optional[bool]
    aadhaar_verified: Optional[bool]
    liveness_check: Optional[bool]
    pep_check: bool = False               # Politically Exposed Person
    sanctions_check: bool = False
    adverse_media_check: bool = False
    kyc_level: str = "basic"              # basic | standard | enhanced
    missing_documents: List[str] = Field(default_factory=list)
    resubmission_required: List[str] = Field(default_factory=list)
    next_review_date: Optional[str] = None


# ── Fraud Detection Agent Output ─────────────

class FraudIndicator(BaseModel):
    indicator_name: str
    severity: str
    description: str
    score_contribution: float


class FraudAgentOutput(BaseAgentOutput):
    agent_name: str = "fraud_detection_agent"
    fraud_score: float = Field(..., ge=0.0, le=1.0)
    is_fraudulent: bool
    fraud_type: Optional[str]
    indicators: List[FraudIndicator]
    aml_risk: bool = False
    aml_flags: List[str] = Field(default_factory=list)
    transaction_velocity_flag: bool = False
    geo_anomaly: bool = False
    device_anomaly: bool = False
    pattern_match: List[str] = Field(default_factory=list)
    recommended_action: str               # block | flag | monitor | clear
    block_account: bool = False
    report_to_fiu: bool = False           # Financial Intelligence Unit
    case_id: Optional[str] = None


# ── Transaction Analysis Agent Output ────────

class TransactionInsight(BaseModel):
    category: str
    amount: float
    percentage_of_total: float
    trend: str                            # increasing | stable | decreasing


class TransactionAgentOutput(BaseAgentOutput):
    agent_name: str = "transaction_analysis_agent"
    total_transactions: int
    total_credit: float
    total_debit: float
    net_cashflow: float
    avg_monthly_balance: Optional[float]
    spending_categories: List[TransactionInsight]
    irregular_transactions: List[Dict[str, Any]]
    salary_detected: bool
    estimated_monthly_income: Optional[float]
    emi_detected: bool
    estimated_emi_burden: Optional[float]
    savings_rate: Optional[float]
    creditworthiness_signal: str          # strong | moderate | weak | poor
    anomalies: List[str] = Field(default_factory=list)
    summary: str


# ── Risk Scoring Agent Output ─────────────────

class RiskFactor(BaseModel):
    factor_name: str
    weight: float
    raw_score: float
    weighted_score: float
    description: str


class RiskAgentOutput(BaseAgentOutput):
    agent_name: str = "risk_scoring_agent"
    composite_risk_score: float = Field(..., ge=0.0, le=1.0)
    credit_risk_score: float
    fraud_risk_score: float
    operational_risk_score: float
    market_risk_score: float
    risk_factors: List[RiskFactor]
    recommended_credit_limit: Optional[float]
    recommended_interest_rate: Optional[float]
    loan_eligible: bool
    max_eligible_amount: Optional[float]
    risk_mitigation_suggestions: List[str]
    review_period_days: int = 90


# ── Customer Support Agent Output ─────────────

class SupportCitation(BaseModel):
    source: str
    relevance_score: float
    excerpt: str


class CustomerSupportOutput(BaseAgentOutput):
    agent_name: str = "customer_support_agent"
    query_intent: str
    detected_language: LanguageEnum
    response: str
    response_language: LanguageEnum
    citations: List[SupportCitation] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    related_topics: List[str] = Field(default_factory=list)
    sentiment: str = "neutral"            # positive | neutral | negative | urgent
    ticket_required: bool = False
    ticket_category: Optional[str] = None
    resolution_confidence: float = 0.0
    needs_human: bool = False


# ── Report Generation Agent Output ────────────

class ReportSection(BaseModel):
    section_title: str
    content: str
    data_points: List[Dict[str, Any]] = Field(default_factory=list)
    charts_required: List[str] = Field(default_factory=list)


class ReportAgentOutput(BaseAgentOutput):
    agent_name: str = "report_generation_agent"
    report_type: str
    report_title: str
    executive_summary: str
    sections: List[ReportSection]
    key_findings: List[str]
    recommendations: List[str]
    data_sources: List[str]
    report_period: Optional[str]
    generated_for: Optional[str]
    confidentiality_level: str = "internal"  # public | internal | confidential | restricted
    word_count: int = 0
    requires_review: bool = True
