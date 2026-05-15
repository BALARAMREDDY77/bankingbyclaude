"""
Bank-Specific Retrieval Contexts
==================================
Defines knowledge base configurations for different banking contexts.
Each context controls what gets retrieved and how results are filtered.

Banking contexts:
  - general_banking     : General banking regulations, products, FAQs
  - loan_underwriting   : Loan policies, credit guidelines, RBI norms
  - fraud_detection     : Fraud patterns, AML rules, suspicious indicators
  - kyc_compliance      : KYC/AML/CFT policies, document requirements
  - customer_documents  : User's own uploaded documents (private)
  - bank_policies       : Bank-specific internal policies (per-bank)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class KnowledgeBaseType(str, Enum):
    GENERAL_BANKING = "general_banking"
    LOAN_UNDERWRITING = "loan_underwriting"
    FRAUD_DETECTION = "fraud_detection"
    KYC_COMPLIANCE = "kyc_compliance"
    CUSTOMER_DOCUMENTS = "customer_documents"
    BANK_POLICIES = "bank_policies"
    REGULATORY = "regulatory"


@dataclass
class RetrievalContext:
    """
    Configuration for a specific retrieval use case.
    Controls which KB to search, filters to apply, and scoring weights.
    """
    name: str
    knowledge_bases: List[str]
    description: str
    default_top_k: int = 5
    alpha: float = 0.6              # Semantic vs BM25 weight
    rerank: bool = True
    similarity_threshold: float = 0.25
    max_context_chars: int = 6000
    allowed_doc_types: List[str] = field(default_factory=list)
    system_prompt_hint: str = ""
    metadata_filters: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────
# Context Definitions
# ──────────────────────────────────────────────

RETRIEVAL_CONTEXTS: Dict[str, RetrievalContext] = {

    KnowledgeBaseType.GENERAL_BANKING: RetrievalContext(
        name="general_banking",
        knowledge_bases=["general_banking"],
        description="General banking knowledge — products, rates, regulations, FAQs",
        default_top_k=5,
        alpha=0.65,
        rerank=True,
        max_context_chars=6000,
        system_prompt_hint=(
            "You are a knowledgeable banking assistant. Use the retrieved banking "
            "policies and product information to answer accurately and clearly."
        ),
    ),

    KnowledgeBaseType.LOAN_UNDERWRITING: RetrievalContext(
        name="loan_underwriting",
        knowledge_bases=["loan_underwriting", "general_banking"],
        description="Loan policies, credit assessment guidelines, RBI norms",
        default_top_k=7,
        alpha=0.7,          # Lean semantic — policy interpretation matters
        rerank=True,
        similarity_threshold=0.3,
        max_context_chars=8000,
        allowed_doc_types=["bank_statement", "salary_slip", "itr", "form_16"],
        system_prompt_hint=(
            "You are a senior credit analyst. Evaluate loan applications using "
            "retrieved underwriting guidelines, RBI norms, and applicant documents."
        ),
    ),

    KnowledgeBaseType.FRAUD_DETECTION: RetrievalContext(
        name="fraud_detection",
        knowledge_bases=["fraud_detection", "regulatory"],
        description="Fraud indicators, AML rules, suspicious transaction patterns",
        default_top_k=8,
        alpha=0.5,          # Balance keyword (exact pattern matching) + semantic
        rerank=True,
        similarity_threshold=0.2,
        max_context_chars=8000,
        system_prompt_hint=(
            "You are a fraud analyst. Use retrieved fraud patterns and AML rules "
            "to identify risks. Be precise and cite specific indicators."
        ),
    ),

    KnowledgeBaseType.KYC_COMPLIANCE: RetrievalContext(
        name="kyc_compliance",
        knowledge_bases=["kyc_compliance", "regulatory"],
        description="KYC/AML/CFT policies, document requirements, PMLA norms",
        default_top_k=5,
        alpha=0.6,
        rerank=True,
        max_context_chars=6000,
        allowed_doc_types=["aadhaar", "pan_card", "passport", "voter_id"],
        system_prompt_hint=(
            "You are a compliance officer. Use retrieved KYC policies and "
            "regulatory guidelines to verify documents and ensure compliance."
        ),
    ),

    KnowledgeBaseType.CUSTOMER_DOCUMENTS: RetrievalContext(
        name="customer_documents",
        knowledge_bases=["customer_documents"],
        description="User's own uploaded documents — private, user-scoped",
        default_top_k=5,
        alpha=0.55,
        rerank=True,
        similarity_threshold=0.25,
        max_context_chars=8000,
        system_prompt_hint=(
            "You are a personal banking assistant. Answer questions about the "
            "customer's own documents — be precise and reference specific values."
        ),
    ),

    KnowledgeBaseType.BANK_POLICIES: RetrievalContext(
        name="bank_policies",
        knowledge_bases=["bank_policies", "general_banking"],
        description="Bank-specific internal policies and product guidelines",
        default_top_k=5,
        alpha=0.6,
        rerank=True,
        max_context_chars=6000,
        system_prompt_hint=(
            "You are an internal banking assistant. Use retrieved bank policies "
            "to provide accurate guidance to employees."
        ),
    ),

    KnowledgeBaseType.REGULATORY: RetrievalContext(
        name="regulatory",
        knowledge_bases=["regulatory"],
        description="RBI circulars, SEBI regulations, PMLA, FEMA guidelines",
        default_top_k=6,
        alpha=0.7,
        rerank=True,
        similarity_threshold=0.3,
        max_context_chars=8000,
        system_prompt_hint=(
            "You are a regulatory compliance expert. Reference specific RBI/SEBI "
            "circulars and regulatory provisions when answering."
        ),
    ),
}


def get_context(context_name: str) -> RetrievalContext:
    """Get a retrieval context by name. Falls back to general_banking."""
    ctx = RETRIEVAL_CONTEXTS.get(context_name)
    if not ctx:
        logger.warning(
            "retrieval_context.not_found",
            context=context_name,
            fallback="general_banking",
        )
        return RETRIEVAL_CONTEXTS[KnowledgeBaseType.GENERAL_BANKING]
    return ctx


def get_context_for_loan(loan_type: Optional[str] = None) -> RetrievalContext:
    """Return appropriate context based on loan type."""
    return RETRIEVAL_CONTEXTS[KnowledgeBaseType.LOAN_UNDERWRITING]


def build_filters(
    context: RetrievalContext,
    user_id: Optional[str] = None,
    bank_id: Optional[str] = None,
    language: Optional[str] = None,
    loan_application_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build metadata filters for a retrieval context."""
    filters = dict(context.metadata_filters)

    # Customer documents are always user-scoped (privacy)
    if context.name == KnowledgeBaseType.CUSTOMER_DOCUMENTS and user_id:
        filters["user_id"] = user_id

    # Bank-specific policies scoped to the bank
    if context.name == KnowledgeBaseType.BANK_POLICIES and bank_id:
        filters["bank_id"] = bank_id

    if language:
        filters["language"] = language
    if loan_application_id:
        filters["loan_application_id"] = loan_application_id

    return filters
