"""create_domain_tables

Revision ID: 002_domain_tables
Revises: 001_auth_tables
Create Date: 2026-05-14

Creates all Phase 3 domain tables:
  banks, loan_applications, transactions,
  uploaded_documents, fraud_reports, ai_reports,
  chat_sessions, chat_messages, agent_traces,
  alerts, system_metrics
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "002_domain_tables"
down_revision = "001_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── ENUM types ──────────────────────────────────────────

    op.execute("CREATE TYPE bankstatus AS ENUM ('active','suspended','under_review','closed')")
    op.execute("CREATE TYPE banktier AS ENUM ('tier_1','tier_2','tier_3','nbfc','cooperative')")
    op.execute("CREATE TYPE loantype AS ENUM ('personal','home','auto','education','business','gold','agricultural','medical','credit_card')")
    op.execute("CREATE TYPE loanstatus AS ENUM ('draft','submitted','document_pending','under_review','ai_assessment','credit_check','approved','conditionally_approved','rejected','withdrawn','disbursed','active','closed','defaulted','npa')")
    op.execute("CREATE TYPE loanpurpose AS ENUM ('home_purchase','home_renovation','vehicle_purchase','education','medical','wedding','travel','debt_consolidation','business_expansion','working_capital','other')")
    op.execute("CREATE TYPE employmenttype AS ENUM ('salaried','self_employed','business_owner','freelancer','retired','student','unemployed')")
    op.execute("CREATE TYPE transactiontype AS ENUM ('credit','debit','transfer_in','transfer_out','loan_disbursement','loan_repayment','fee','interest','reversal','refund')")
    op.execute("CREATE TYPE transactionstatus AS ENUM ('pending','processing','completed','failed','reversed','disputed','on_hold')")
    op.execute("CREATE TYPE transactionchannel AS ENUM ('net_banking','mobile_app','atm','branch','api','upi','neft','rtgs','imps','swift')")
    op.execute("CREATE TYPE documenttype AS ENUM ('aadhaar','pan_card','passport','voter_id','driving_license','bank_statement','salary_slip','itr','form_16','balance_sheet','profit_loss','gst_return','property_deed','sale_agreement','noc','encumbrance_certificate','incorporation_certificate','moa','business_license','udyam_certificate','photograph','signature','other')")
    op.execute("CREATE TYPE documentstatus AS ENUM ('uploaded','under_review','verified','rejected','expired','resubmission_required')")
    op.execute("CREATE TYPE fraudtype AS ENUM ('identity_theft','document_forgery','synthetic_identity','account_takeover','loan_stacking','money_laundering','phishing','transaction_fraud','insider_fraud','application_fraud','bust_out','other')")
    op.execute("CREATE TYPE fraudseverity AS ENUM ('low','medium','high','critical')")
    op.execute("CREATE TYPE fraudstatus AS ENUM ('open','under_investigation','escalated','confirmed','dismissed','resolved','reported_to_authorities')")
    op.execute("CREATE TYPE fraudsource AS ENUM ('ai_detection','rule_engine','manual_review','user_report','bank_report','regulatory','third_party')")
    op.execute("CREATE TYPE reporttype AS ENUM ('credit_assessment','fraud_analysis','document_verification','risk_scoring','loan_recommendation','financial_health','compliance_check','market_analysis')")
    op.execute("CREATE TYPE reportstatus AS ENUM ('generating','completed','failed','expired')")
    op.execute("CREATE TYPE messagerole AS ENUM ('user','assistant','system','tool')")
    op.execute("CREATE TYPE agenttracestatus AS ENUM ('running','completed','failed','cancelled','timeout')")
    op.execute("CREATE TYPE alerttype AS ENUM ('fraud_detected','suspicious_login','large_transaction','document_expired','loan_overdue','credit_score_drop','account_locked','compliance_breach','system_error','ai_anomaly','rate_limit_breach','data_quality')")
    op.execute("CREATE TYPE alertseverity AS ENUM ('info','warning','high','critical')")
    op.execute("CREATE TYPE alertstatus AS ENUM ('open','acknowledged','in_progress','resolved','dismissed','escalated')")
    op.execute("CREATE TYPE metrictype AS ENUM ('api_latency','db_query_time','cache_hit_rate','error_rate','active_users','loan_applications_per_hour','ai_inference_time','fraud_detection_rate','queue_depth','memory_usage','cpu_usage','token_usage')")

    # ── banks ───────────────────────────────────────────────
    op.create_table(
        "banks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(500), nullable=False),
        sa.Column("short_code", sa.String(20), nullable=False, unique=True),
        sa.Column("ifsc_prefix", sa.String(4), nullable=True),
        sa.Column("swift_code", sa.String(11), nullable=True),
        sa.Column("routing_number", sa.String(20), nullable=True),
        sa.Column("tier", sa.Text, nullable=False, server_default="tier_2"),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("is_partner", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("license_number", sa.String(100), nullable=True),
        sa.Column("regulator", sa.String(100), nullable=True),
        sa.Column("regulated_since", sa.String(20), nullable=True),
        sa.Column("headquarters_city", sa.String(100), nullable=True),
        sa.Column("headquarters_country", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("support_email", sa.String(255), nullable=True),
        sa.Column("support_phone", sa.String(20), nullable=True),
        sa.Column("total_assets_crore", sa.Numeric(20, 2), nullable=True),
        sa.Column("credit_rating", sa.String(10), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_banks_short_code", "banks", ["short_code"], unique=True)
    op.create_index("ix_banks_status_tier", "banks", ["status", "tier"])
    op.create_index("ix_banks_country", "banks", ["headquarters_country"])

    # ── loan_applications ───────────────────────────────────
    op.create_table(
        "loan_applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bank_id", UUID(as_uuid=True), sa.ForeignKey("banks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_officer_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("application_number", sa.String(50), nullable=False, unique=True),
        sa.Column("loan_type", sa.Text, nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("requested_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("requested_tenure_months", sa.Integer, nullable=False),
        sa.Column("requested_interest_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("approved_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("approved_tenure_months", sa.Integer, nullable=True),
        sa.Column("approved_interest_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("emi_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("processing_fee", sa.Numeric(20, 2), nullable=True),
        sa.Column("employment_type", sa.Text, nullable=True),
        sa.Column("employer_name", sa.String(255), nullable=True),
        sa.Column("monthly_income", sa.Numeric(20, 2), nullable=True),
        sa.Column("annual_income", sa.Numeric(20, 2), nullable=True),
        sa.Column("existing_emi", sa.Numeric(20, 2), nullable=True),
        sa.Column("credit_score", sa.Integer, nullable=True),
        sa.Column("debt_to_income_ratio", sa.Numeric(5, 4), nullable=True),
        sa.Column("ai_risk_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("ai_recommendation", sa.String(50), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("ai_assessed_at", sa.String(50), nullable=True),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("conditions", JSONB, nullable=True),
        sa.Column("decided_at", sa.String(50), nullable=True),
        sa.Column("decided_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("disbursed_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("disbursed_at", sa.String(50), nullable=True),
        sa.Column("disbursement_account", sa.String(50), nullable=True),
        sa.Column("maturity_date", sa.String(20), nullable=True),
        sa.Column("outstanding_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_paid", sa.Numeric(20, 2), nullable=True),
        sa.Column("overdue_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("overdue_days", sa.Integer, nullable=True),
        sa.Column("last_payment_date", sa.String(20), nullable=True),
        sa.Column("is_priority", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("requires_physical_verification", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("collateral_type", sa.String(100), nullable=True),
        sa.Column("collateral_value", sa.Numeric(20, 2), nullable=True),
        sa.Column("collateral_description", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("requested_amount > 0", name="ck_loan_amount_positive"),
        sa.CheckConstraint("requested_tenure_months > 0", name="ck_loan_tenure_positive"),
    )
    op.create_index("ix_loans_user_status", "loan_applications", ["user_id", "status"])
    op.create_index("ix_loans_bank_status", "loan_applications", ["bank_id", "status"])
    op.create_index("ix_loans_application_number", "loan_applications", ["application_number"], unique=True)
    op.create_index("ix_loans_created_at", "loan_applications", ["created_at"])

    # ── transactions ────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bank_id", UUID(as_uuid=True), sa.ForeignKey("banks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reference_number", sa.String(100), nullable=False, unique=True),
        sa.Column("external_reference", sa.String(200), nullable=True),
        sa.Column("reversal_of_id", UUID(as_uuid=True), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("exchange_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("amount_in_base_currency", sa.Numeric(20, 4), nullable=True),
        sa.Column("fee_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("from_account", sa.String(50), nullable=True),
        sa.Column("to_account", sa.String(50), nullable=True),
        sa.Column("from_bank_code", sa.String(20), nullable=True),
        sa.Column("to_bank_code", sa.String(20), nullable=True),
        sa.Column("transaction_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("channel", sa.Text, nullable=False, server_default="api"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("narration", sa.String(500), nullable=True),
        sa.Column("is_flagged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("risk_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("fraud_report_id", UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.String(50), nullable=True),
        sa.Column("settlement_date", sa.String(20), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )
    op.create_index("ix_transactions_user_created", "transactions", ["user_id", "created_at"])
    op.create_index("ix_transactions_reference", "transactions", ["reference_number"], unique=True)
    op.create_index("ix_transactions_status_type", "transactions", ["status", "transaction_type"])
    op.create_index("ix_transactions_flagged", "transactions", ["is_flagged"])
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])

    # ── uploaded_documents ──────────────────────────────────
    op.create_table(
        "uploaded_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="uploaded"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("safe_filename", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=True),
        sa.Column("storage_key", sa.String(1000), nullable=False),
        sa.Column("storage_region", sa.String(50), nullable=True),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("issued_by", sa.String(255), nullable=True),
        sa.Column("issued_date", sa.String(20), nullable=True),
        sa.Column("expiry_date", sa.String(20), nullable=True),
        sa.Column("is_expired", sa.Boolean, server_default="false"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("verified_at", sa.String(50), nullable=True),
        sa.Column("ocr_extracted_data", JSONB, nullable=True),
        sa.Column("ai_verification_score", sa.String(10), nullable=True),
        sa.Column("is_sensitive", sa.Boolean, server_default="true"),
        sa.Column("encryption_key_id", sa.String(100), nullable=True),
        sa.Column("malware_scan_status", sa.String(50), nullable=True),
        sa.Column("malware_scanned_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_docs_user_type", "uploaded_documents", ["user_id", "document_type"])
    op.create_index("ix_docs_loan_status", "uploaded_documents", ["loan_application_id", "status"])
    op.create_index("ix_docs_file_hash", "uploaded_documents", ["file_hash"])

    # ── fraud_reports ───────────────────────────────────────
    op.create_table(
        "fraud_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reported_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transaction_id", UUID(as_uuid=True), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_reviewer_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fraud_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False, server_default="medium"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("source", sa.Text, nullable=False, server_default="ai_detection"),
        sa.Column("report_number", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("indicators", JSONB, nullable=True),
        sa.Column("estimated_loss_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("actual_loss_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("recovered_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("ai_confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("ai_model_version", sa.String(50), nullable=True),
        sa.Column("ai_detected_patterns", JSONB, nullable=True),
        sa.Column("investigation_notes", sa.Text, nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.String(50), nullable=True),
        sa.Column("is_confirmed", sa.Boolean, server_default="false"),
        sa.Column("account_blocked", sa.Boolean, server_default="false"),
        sa.Column("fir_filed", sa.Boolean, server_default="false"),
        sa.Column("fir_number", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_fraud_type_status", "fraud_reports", ["fraud_type", "status"])
    op.create_index("ix_fraud_severity_status", "fraud_reports", ["severity", "status"])
    op.create_index("ix_fraud_user", "fraud_reports", ["reported_user_id"])

    # ── ai_reports ──────────────────────────────────────────
    op.create_table(
        "ai_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("report_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="generating"),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("agent_trace_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("full_report", JSONB, nullable=True),
        sa.Column("recommendations", JSONB, nullable=True),
        sa.Column("overall_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("generation_time_ms", sa.Integer, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("expires_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ai_reports_user_type", "ai_reports", ["user_id", "report_type"])
    op.create_index("ix_ai_reports_status", "ai_reports", ["status"])

    # ── chat_sessions ───────────────────────────────────────
    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("total_messages", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("agent_type", sa.String(100), nullable=True),
        sa.Column("session_metadata", JSONB, nullable=True),
        sa.Column("ended_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_sessions_user", "chat_sessions", ["user_id"])

    # ── chat_messages ───────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("tool_input", JSONB, nullable=True),
        sa.Column("tool_output", JSONB, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("is_error", sa.Boolean, server_default="false"),
        sa.Column("message_metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_session", "chat_messages", ["session_id"])

    # ── agent_traces ────────────────────────────────────────
    op.create_table(
        "agent_traces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("agent_version", sa.String(50), nullable=True),
        sa.Column("workflow_name", sa.String(100), nullable=True),
        sa.Column("run_id", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("input_data", JSONB, nullable=True),
        sa.Column("output_data", JSONB, nullable=True),
        sa.Column("steps", JSONB, nullable=True),
        sa.Column("tool_calls", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_traceback", sa.Text, nullable=True),
        sa.Column("total_steps", sa.Integer, server_default="0"),
        sa.Column("total_tool_calls", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("completed_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_traces_run_id", "agent_traces", ["run_id"], unique=True)
    op.create_index("ix_agent_traces_agent_status", "agent_traces", ["agent_name", "status"])
    op.create_index("ix_agent_traces_user", "agent_traces", ["user_id"])

    # ── alerts ──────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("loan_application_id", UUID(as_uuid=True), sa.ForeignKey("loan_applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_to_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("alert_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False, server_default="warning"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("is_read", sa.Boolean, server_default="false"),
        sa.Column("read_at", sa.String(50), nullable=True),
        sa.Column("sent_email", sa.Boolean, server_default="false"),
        sa.Column("sent_sms", sa.Boolean, server_default="false"),
        sa.Column("sent_push", sa.Boolean, server_default="false"),
        sa.Column("resolved_at", sa.String(50), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("auto_resolved", sa.Boolean, server_default="false"),
        sa.Column("expires_at", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alerts_user_status", "alerts", ["user_id", "status"])
    op.create_index("ix_alerts_type_severity", "alerts", ["alert_type", "severity"])
    op.create_index("ix_alerts_is_read", "alerts", ["is_read"])

    # ── system_metrics ──────────────────────────────────────
    op.create_table(
        "system_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_type", sa.Text, nullable=False),
        sa.Column("metric_name", sa.String(200), nullable=False),
        sa.Column("value", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("service", sa.String(100), nullable=True),
        sa.Column("endpoint", sa.String(500), nullable=True),
        sa.Column("host", sa.String(100), nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("period_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_metrics_type_created", "system_metrics", ["metric_type", "created_at"])
    op.create_index("ix_metrics_name_created", "system_metrics", ["metric_name", "created_at"])


def downgrade() -> None:
    for table in [
        "system_metrics", "alerts", "agent_traces",
        "chat_messages", "chat_sessions", "ai_reports",
        "fraud_reports", "uploaded_documents",
        "transactions", "loan_applications", "banks",
    ]:
        op.drop_table(table)

    for enum in [
        "metrictype", "alertstatus", "alertseverity", "alerttype",
        "agenttracestatus", "messagerole", "reportstatus", "reporttype",
        "fraudsource", "fraudstatus", "fraudseverity", "fraudtype",
        "documentstatus", "documenttype", "transactionchannel",
        "transactionstatus", "transactiontype", "employmenttype",
        "loanpurpose", "loanstatus", "loantype", "banktier", "bankstatus",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
