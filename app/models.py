from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .database import Base

uuid_default = text("gen_random_uuid()")
now_default = func.now()


# ─────────────────────────── ENUMS ───────────────────────────


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    EXECUTIVE = "EXECUTIVE"


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class MemberRole(str, enum.Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    REP = "REP"


class ContactStage(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    RESEARCHED = "RESEARCHED"
    QUALIFIED = "QUALIFIED"
    CONTACTED = "CONTACTED"
    ENGAGED = "ENGAGED"
    MEETING = "MEETING"
    OPPORTUNITY = "OPPORTUNITY"
    REJECTED = "REJECTED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class Channel(str, enum.Enum):
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"
    SMS = "SMS"
    VOICE = "VOICE"


class Direction(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class DraftStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    EXEC_EDITED = "EXEC_EDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED_AND_APPROVED = "EDITED_AND_APPROVED"


class AgentType(str, enum.Enum):
    ICP_FITMENT = "ICP_FITMENT"
    LEAD_RESEARCH = "LEAD_RESEARCH"
    OUTREACH_STRATEGY = "OUTREACH_STRATEGY"
    PERSONALISATION = "PERSONALISATION"
    CONVERSATION = "CONVERSATION"
    VOICE_SDR = "VOICE_SDR"
    FOLLOW_UP = "FOLLOW_UP"


class AgentRunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class CallOutcome(str, enum.Enum):
    CONNECTED = "CONNECTED"
    NO_ANSWER = "NO_ANSWER"
    VOICEMAIL = "VOICEMAIL"
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    CALLBACK = "CALLBACK"
    ESCALATED = "ESCALATED"


class SuppressionType(str, enum.Enum):
    EMAIL = "EMAIL"
    DOMAIN = "DOMAIN"
    PHONE = "PHONE"
    LINKEDIN = "LINKEDIN"


# SQLAlchemy Enum objects bound to PostgreSQL native enum names
sa_user_role = SAEnum(UserRole, name="user_role", create_type=False)
sa_campaign_status = SAEnum(CampaignStatus, name="campaign_status", create_type=False)
sa_member_role = SAEnum(MemberRole, name="member_role", create_type=False)
sa_contact_stage = SAEnum(ContactStage, name="contact_stage", create_type=False)
sa_channel = SAEnum(Channel, name="channel", create_type=False)
sa_direction = SAEnum(Direction, name="direction", create_type=False)
sa_draft_status = SAEnum(DraftStatus, name="draft_status", create_type=False)
sa_approval_decision = SAEnum(ApprovalDecision, name="approval_decision", create_type=False)
sa_agent_type = SAEnum(AgentType, name="agent_type", create_type=False)
sa_agent_run_status = SAEnum(AgentRunStatus, name="agent_run_status", create_type=False)
sa_call_outcome = SAEnum(CallOutcome, name="call_outcome", create_type=False)
sa_suppression_type = SAEnum(SuppressionType, name="suppression_type", create_type=False)


# ─────────────────────────── USERS ───────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    role: Mapped[UserRole] = mapped_column(sa_user_role, nullable=False, default=UserRole.EXECUTIVE, server_default="EXECUTIVE")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    working_hours: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    channel_access: Mapped[Optional[list[Channel]]] = mapped_column(ARRAY(sa_channel), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    @validates("role")
    def validate_role(self, key: str, value: Any) -> UserRole:
        if isinstance(value, str):
            if value.upper() == "EXE":
                return UserRole.EXECUTIVE
            return UserRole(value.upper())
        return value

    @validates("channel_access")
    def validate_channel_access(self, key: str, values: Any) -> Optional[list[Channel]]:
        if values is None:
            return None
        return [Channel(v) if isinstance(v, str) else v for v in values]

    # Naming convention compatibility properties
    @property
    def password_hash(self) -> Optional[str]:
        return self.hashed_password

    @password_hash.setter
    def password_hash(self, value: Optional[str]) -> None:
        self.hashed_password = value

    @property
    def passwordHash(self) -> Optional[str]:
        return self.hashed_password

    @passwordHash.setter
    def passwordHash(self, value: Optional[str]) -> None:
        self.hashed_password = value

    @property
    def isActive(self) -> bool:
        return self.is_active

    @isActive.setter
    def isActive(self, value: bool) -> None:
        self.is_active = value

    @property
    def dailyLimit(self) -> int:
        return self.daily_limit

    @dailyLimit.setter
    def dailyLimit(self, value: int) -> None:
        self.daily_limit = value

    @property
    def workingHours(self) -> Optional[dict[str, Any]]:
        return self.working_hours

    @workingHours.setter
    def workingHours(self, value: Optional[dict[str, Any]]) -> None:
        self.working_hours = value

    @property
    def channelAccess(self) -> Optional[list[str]]:
        return self.channel_access # type: ignore

    @channelAccess.setter
    def channelAccess(self, value: Optional[list[str]]) -> None:
        self.channel_access = value # type: ignore

    # Relationships
    owned_campaigns: Mapped[list[Campaign]] = relationship("Campaign", back_populates="owner")
    memberships: Mapped[list[CampaignMember]] = relationship("CampaignMember", back_populates="user")
    assigned_contacts: Mapped[list[CampaignContact]] = relationship("CampaignContact", back_populates="assigned_user")
    edited_drafts: Mapped[list[Draft]] = relationship("Draft", back_populates="edited_by")
    approvals: Mapped[list[Approval]] = relationship("Approval", back_populates="reviewer")
    sent_messages: Mapped[list[Message]] = relationship("Message", back_populates="sent_by")
    prompt_versions: Mapped[list[PromptVersion]] = relationship("PromptVersion", back_populates="created_by")
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="actor")
    suppressions: Mapped[list[SuppressionEntry]] = relationship("SuppressionEntry", back_populates="added_by")
    settings_changed: Mapped[list[SystemSetting]] = relationship("SystemSetting", back_populates="updated_by")


# ───────────────────────── CAMPAIGNS ─────────────────────────


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[CampaignStatus] = mapped_column(sa_campaign_status, nullable=False, default=CampaignStatus.DRAFT, server_default="DRAFT", index=True)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icp: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    geography: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    exclusion_criteria: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    reference_profiles: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    outreach_policy: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    chroma_collection: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    owner: Mapped[User] = relationship("User", back_populates="owned_campaigns")
    members: Mapped[list[CampaignMember]] = relationship("CampaignMember", back_populates="campaign", cascade="all, delete-orphan")
    contacts: Mapped[list[CampaignContact]] = relationship("CampaignContact", back_populates="campaign", cascade="all, delete-orphan")
    agents: Mapped[list[CampaignAgent]] = relationship("CampaignAgent", back_populates="campaign", cascade="all, delete-orphan")
    channels: Mapped[list[CampaignChannel]] = relationship("CampaignChannel", back_populates="campaign", cascade="all, delete-orphan")
    prompt_versions: Mapped[list[PromptVersion]] = relationship("PromptVersion", back_populates="campaign", cascade="all, delete-orphan")
    agent_runs: Mapped[list[AgentRun]] = relationship("AgentRun", back_populates="campaign", cascade="all, delete-orphan")
    evaluations: Mapped[list[Evaluation]] = relationship("Evaluation", back_populates="campaign", cascade="all, delete-orphan")


class CampaignMember(Base):
    __tablename__ = "campaign_members"
    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_campaign_member"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role_in_campaign: Mapped[MemberRole] = mapped_column(sa_member_role, nullable=False, default=MemberRole.REP, server_default="REP")
    daily_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    use_as_sender_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="members")
    user: Mapped[User] = relationship("User", back_populates="memberships")


# ──────────────────── COMPANIES & CONTACTS ────────────────────


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website: Mapped[Optional[str]] = mapped_column(String(2048), unique=True, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_range: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    enrichment: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    contacts: Mapped[list[Contact]] = relationship("Contact", back_populates="company")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    company_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), unique=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(2048), unique=True, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    company: Mapped[Optional[Company]] = relationship("Company", back_populates="contacts")
    campaign_contacts: Mapped[list[CampaignContact]] = relationship("CampaignContact", back_populates="contact")


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),
        Index("ix_campaign_contacts_campaign_stage", "campaign_id", "stage"),
        Index("ix_campaign_contacts_contact", "contact_id"),
        Index("ix_campaign_contacts_assigned_user", "assigned_user_id"),
        Index("ix_campaign_contacts_next_action", "next_action_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    assigned_user_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    stage: Mapped[ContactStage] = mapped_column(sa_contact_stage, nullable=False, default=ContactStage.DISCOVERED, server_default="DISCOVERED")
    icp_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    icp_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="contacts")
    contact: Mapped[Contact] = relationship("Contact", back_populates="campaign_contacts")
    assigned_user: Mapped[Optional[User]] = relationship("User", back_populates="assigned_contacts")
    conversations: Mapped[list[Conversation]] = relationship("Conversation", back_populates="campaign_contact", cascade="all, delete-orphan")
    agent_runs: Mapped[list[AgentRun]] = relationship("AgentRun", back_populates="campaign_contact")


# ──────────────────────── COMMUNICATION ────────────────────────


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_campaign_contact_channel", "campaign_contact_id", "channel"),
        Index("ix_conversations_external_thread", "external_thread_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_contact_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaign_contacts.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[Channel] = mapped_column(sa_channel, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    campaign_contact: Mapped[CampaignContact] = relationship("CampaignContact", back_populates="conversations")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    drafts: Mapped[list[Draft]] = relationship("Draft", back_populates="conversation", cascade="all, delete-orphan")
    call_logs: Mapped[list[CallLog]] = relationship("CallLog", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_external_id", "external_message_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[Direction] = mapped_column(sa_direction, nullable=False)
    channel: Mapped[Channel] = mapped_column(sa_channel, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    draft_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("drafts.id"), nullable=True)
    sent_by_user_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
    draft: Mapped[Optional[Draft]] = relationship("Draft", back_populates="messages")
    sent_by: Mapped[Optional[User]] = relationship("User", back_populates="sent_messages")


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        Index("ix_drafts_status", "status"),
        Index("ix_drafts_conversation", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[Channel] = mapped_column(sa_channel, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    original_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[DraftStatus] = mapped_column(sa_draft_status, nullable=False, default=DraftStatus.PENDING_REVIEW, server_default="PENDING_REVIEW")
    created_by_agent_run_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    prompt_version_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    edited_by_user_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="drafts")
    created_by_run: Mapped[Optional[AgentRun]] = relationship("AgentRun", back_populates="drafts", foreign_keys=[created_by_agent_run_id])
    prompt_version: Mapped[Optional[PromptVersion]] = relationship("PromptVersion", back_populates="drafts")
    edited_by: Mapped[Optional[User]] = relationship("User", back_populates="edited_drafts", foreign_keys=[edited_by_user_id])
    approvals: Mapped[list[Approval]] = relationship("Approval", back_populates="draft", cascade="all, delete-orphan")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="draft")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_draft", "draft_id"),
        Index("ix_approvals_reviewer", "reviewer_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    draft_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(sa_approval_decision, nullable=False)
    final_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    draft: Mapped[Draft] = relationship("Draft", back_populates="approvals")
    reviewer: Mapped[User] = relationship("User", back_populates="approvals")


class CallLog(Base):
    __tablename__ = "call_logs"
    __table_args__ = (
        Index("ix_call_logs_conversation", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    external_call_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    direction: Mapped[Direction] = mapped_column(sa_direction, nullable=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[CallOutcome]] = mapped_column(sa_call_outcome, nullable=True)
    recording_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="call_logs")


# ─────────────────── AGENTS, PROMPTS, CONTROL ───────────────────


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    type: Mapped[AgentType] = mapped_column(sa_agent_type, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    campaign_agents: Mapped[list[CampaignAgent]] = relationship("CampaignAgent", back_populates="agent")
    prompt_versions: Mapped[list[PromptVersion]] = relationship("PromptVersion", back_populates="agent")
    agent_runs: Mapped[list[AgentRun]] = relationship("AgentRun", back_populates="agent")


class CampaignAgent(Base):
    __tablename__ = "campaign_agents"
    __table_args__ = (
        UniqueConstraint("campaign_id", "agent_id", name="uq_campaign_agent"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="agents")
    agent: Mapped[Agent] = relationship("Agent", back_populates="campaign_agents")


class CampaignChannel(Base):
    __tablename__ = "campaign_channels"
    __table_args__ = (
        UniqueConstraint("campaign_id", "channel", name="uq_campaign_channel"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[Channel] = mapped_column(sa_channel, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="channels")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "agent_id", "version", name="uq_prompt_version"),
        Index("ix_prompt_versions_campaign_agent_active", "campaign_id", "agent_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    parent_version_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="prompt_versions")
    agent: Mapped[Optional[Agent]] = relationship("Agent", back_populates="prompt_versions")
    created_by: Mapped[User] = relationship("User", back_populates="prompt_versions")
    parent: Mapped[Optional[PromptVersion]] = relationship("PromptVersion", remote_side=[id], back_populates="children")
    children: Mapped[list[PromptVersion]] = relationship("PromptVersion", back_populates="parent")
    agent_runs: Mapped[list[AgentRun]] = relationship("AgentRun", back_populates="prompt_version")
    drafts: Mapped[list[Draft]] = relationship("Draft", back_populates="prompt_version")


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_campaign_created", "campaign_id", "created_at"),
        Index("ix_agent_runs_contact", "campaign_contact_id"),
        Index("ix_agent_runs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    campaign_contact_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaign_contacts.id"), nullable=True)
    prompt_version_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(sa_agent_run_status, nullable=False, default=AgentRunStatus.QUEUED, server_default="QUEUED")
    input: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    retrieved_context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal(0), server_default="0")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="agent_runs")
    agent: Mapped[Agent] = relationship("Agent", back_populates="agent_runs")
    campaign_contact: Mapped[Optional[CampaignContact]] = relationship("CampaignContact", back_populates="agent_runs")
    prompt_version: Mapped[Optional[PromptVersion]] = relationship("PromptVersion", back_populates="agent_runs")
    drafts: Mapped[list[Draft]] = relationship("Draft", back_populates="created_by_run", foreign_keys="Draft.created_by_agent_run_id")


# ───────────────────── SAFETY & GOVERNANCE ─────────────────────


class SuppressionEntry(Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_suppression_type_value"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    type: Mapped[SuppressionType] = mapped_column(sa_suppression_type, nullable=False)
    value: Mapped[str] = mapped_column(String(2048), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_by_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    added_by: Mapped[Optional[User]] = relationship("User", back_populates="suppressions")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_by_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default, onupdate=now_default)

    # Relationships
    updated_by: Mapped[Optional[User]] = relationship("User", back_populates="settings_changed")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "actor_id"),
        Index("ix_audit_logs_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    actor_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    actor: Mapped[Optional[User]] = relationship("User", back_populates="audit_logs")


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_campaign_agent_type", "campaign_id", "agent_type"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=uuid_default)
    campaign_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True)
    agent_type: Mapped[AgentType] = mapped_column(sa_agent_type, nullable=False)
    prompt_version_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    test_case: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    judge: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=now_default)

    # Relationships
    campaign: Mapped[Optional[Campaign]] = relationship("Campaign", back_populates="evaluations")
