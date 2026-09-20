"""Compatibility module re-exporting all Autonomous SDR SQLAlchemy models and tables.

All models are defined as SQLAlchemy 2.0 Declarative ORM classes in `app.models`.
This file preserves backwards compatibility for imports referencing `sdr_schema`.
"""

from .models import (  # noqa: F401
    # Enums
    UserRole,
    CampaignStatus,
    MemberRole,
    ContactStage,
    Channel,
    Direction,
    DraftStatus,
    ApprovalDecision,
    AgentType,
    AgentRunStatus,
    CallOutcome,
    SuppressionType,
    # ORM Models
    User,
    Campaign,
    CampaignMember,
    Company,
    Contact,
    CampaignContact,
    Conversation,
    Message,
    Draft,
    Approval,
    CallLog,
    Agent,
    CampaignAgent,
    CampaignChannel,
    PromptVersion,
    AgentRun,
    SuppressionEntry,
    SystemSetting,
    AuditLog,
    Evaluation,
)

# Table object aliases for code expecting SQLAlchemy Table objects
users = User.__table__
campaigns = Campaign.__table__
campaign_members = CampaignMember.__table__
companies = Company.__table__
contacts = Contact.__table__
campaign_contacts = CampaignContact.__table__
conversations = Conversation.__table__
messages = Message.__table__
drafts = Draft.__table__
approvals = Approval.__table__
call_logs = CallLog.__table__
agents = Agent.__table__
campaign_agents = CampaignAgent.__table__
campaign_channels = CampaignChannel.__table__
prompt_versions = PromptVersion.__table__
agent_runs = AgentRun.__table__
suppression_entries = SuppressionEntry.__table__
system_settings = SystemSetting.__table__
audit_logs = AuditLog.__table__
evaluations = Evaluation.__table__
