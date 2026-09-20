from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class SignUpRequest(BaseModel):
    email: EmailStr
    role: Literal["ADMIN", "EXE", "EXECUTIVE"] = "EXECUTIVE"
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=255)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str | None
    role: str
    is_active: bool = True
    admin_linked: bool = False
    daily_limit: int = 50
    access_token: Optional[str] = None
    token_type: Optional[str] = "bearer"
    model_config = {"from_attributes": True}


class GeneralSettings(BaseModel):
    workspace_name: str = "Autonomous SDR"
    workspace_description: str = "AI-powered autonomous sales development platform"
    timezone: str = "Asia/Kolkata (IST)"
    language: str = "English"


class NotificationSettings(BaseModel):
    email_notifications: bool = True
    escalation_alerts: bool = True
    daily_performance_summary: bool = True


class WorkspaceSettings(BaseModel):
    default_campaign_limit: int = 100
    data_retention_days: int = 90


class IntegrationsSettings(BaseModel):
    gmail_connected: bool = True
    linkedin_connected: bool = True
    sms_connected: bool = False


class PermissionsSettings(BaseModel):
    allow_rep_escalations: bool = True
    require_admin_approval: bool = True


class SecuritySettings(BaseModel):
    two_factor_auth: bool = False
    session_timeout_minutes: int = 60
    admin_code: Optional[str] = "helloguys"


class CollaborationSettings(BaseModel):
    auto_approve_members: bool = False
    invite_code_expiry_days: int = 7


class LinkAdminRequest(BaseModel):
    code: str


class LinkAdminResponse(BaseModel):
    status: str = "PENDING"
    message: str = "Join request submitted. Awaiting admin approval."
    admin_linked: bool = False
    user: Optional[UserResponse] = None
    id: Optional[UUID] = None
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


class JoinStatusResponse(BaseModel):
    status: str
    admin_linked: bool
    code_entered: Optional[str] = None
    created_at: Optional[datetime] = None
    message: Optional[str] = None


class JoinRequestItem(BaseModel):
    id: UUID
    user_id: UUID
    name: Optional[str] = ""
    email: str
    role: str
    code_entered: str
    status: str
    created_at: datetime
    time_ago: Optional[str] = None
    model_config = {"from_attributes": True}


class WorkspaceMemberItem(BaseModel):
    id: UUID
    name: Optional[str] = ""
    email: str
    role: str
    is_active: bool = True
    admin_linked: bool = True
    created_at: datetime
    status: str = "Online"
    model_config = {"from_attributes": True}


class SettingsPayload(BaseModel):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    integrations: IntegrationsSettings = Field(default_factory=IntegrationsSettings)
    permissions: PermissionsSettings = Field(default_factory=PermissionsSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    collaboration: CollaborationSettings = Field(default_factory=CollaborationSettings)


class ConversationSummary(BaseModel):
    active_conversations: int = 142
    needs_attention: int = 8
    ai_handling: int = 117
    human_takeover: int = 17


class RecentConversationItem(BaseModel):
    id: str
    prospect_name: str
    prospect_initials: str
    title: str
    company: str
    time_ago: str
    campaign_name: str
    channel: str
    status: str
    status_label: str
    latest_message: str
    action_type: str = "review"


class EscalationItem(BaseModel):
    id: str
    priority: str
    prospect_name: str
    campaign_name: str
    reason: str
    status: str


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    channel: str
    sender: str
    subject: Optional[str] = None
    body: str
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class CreateMessageRequest(BaseModel):
    body: str
    channel: Optional[str] = None


class ConversationListItem(BaseModel):
    id: UUID
    campaign_id: Optional[UUID] = None
    campaign_name: Optional[str] = None
    prospect_name: str
    prospect_initials: str
    title: Optional[str] = None
    company: Optional[str] = None
    channel: str
    status: str
    status_label: str
    latest_message: str
    time_ago: str
    messages_count: int = 0
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: UUID
    campaign_id: Optional[UUID] = None
    campaign_name: Optional[str] = None
    channel: str
    subject: Optional[str] = None
    is_open: bool = True
    status: str
    status_label: str
    prospect: dict
    messages: list[MessageResponse]
    draft: Optional[dict] = None
    created_at: datetime
    last_message_at: Optional[datetime] = None
    model_config = {"from_attributes": True}



class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    objective: Optional[str] = None
    target_roles: list[str] = Field(default_factory=list)
    company_size: Optional[str] = None
    geography: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=lambda: ["EMAIL", "LINKEDIN"])
    daily_limit: int = Field(default=100, ge=1, le=10000)
    requires_approval: bool = True
    status: Literal["DRAFT", "LIVE", "PAUSED", "COMPLETED", "ARCHIVED"] = "LIVE"


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    target_roles: Optional[list[str]] = None
    company_size: Optional[str] = None
    geography: Optional[list[str]] = None
    channels: Optional[list[str]] = None
    daily_limit: Optional[int] = None
    requires_approval: Optional[bool] = None
    status: Optional[Literal["DRAFT", "LIVE", "PAUSED", "COMPLETED", "ARCHIVED"]] = None


class CampaignStatusUpdate(BaseModel):
    status: Literal["DRAFT", "LIVE", "PAUSED", "COMPLETED", "ARCHIVED"]


class CampaignResponse(BaseModel):
    id: UUID
    name: str
    title: str
    description: Optional[str] = None
    subtitle: Optional[str] = None
    objective: Optional[str] = None
    owner_id: UUID
    owner_name: str
    status: str
    icp: str
    company_size: str
    geography: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    prospects: int = 0
    qualified: int = 0
    meetings: int = 0
    daily_limit: int = 100
    requires_approval: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = {"from_attributes": True}


class CampaignStatDetail(BaseModel):
    value: int = 0
    live: int = 0
    paused: int = 0
    draft: int = 0


class StatValueItem(BaseModel):
    value: int = 0
    live: int = 0


class EscalationStatItem(BaseModel):
    value: int = 0
    status: str = "All resolved"


class DashboardStatsResponse(BaseModel):
    totalCampaigns: CampaignStatDetail = Field(default_factory=CampaignStatDetail)
    totalProspects: StatValueItem = Field(default_factory=StatValueItem)
    meetingsBooked: StatValueItem = Field(default_factory=StatValueItem)
    totalEscalations: EscalationStatItem = Field(default_factory=EscalationStatItem)


class AnalyticsTrendSeries(BaseModel):
    id: Optional[str] = None
    name: str
    color: str = "#4361ee"
    data: list[float] = Field(default_factory=list)


class AnalyticsTrendData(BaseModel):
    dates: list[str] = Field(default_factory=list)
    series: list[AnalyticsTrendSeries] = Field(default_factory=list)


class CampaignComparisonItem(BaseModel):
    id: Optional[str] = None
    name: str
    prospects: int = 0
    qualified: int = 0
    meetings: int = 0


class ChannelMetricItem(BaseModel):
    channel: str
    contacted: int = 0
    responded: int = 0
    meetings: int = 0
    reply_rate: float = 0.0


class SalesTeamMemberMetric(BaseModel):
    id: str
    name: str
    role: str = "Sales Executive"
    assigned_campaigns: str = ""
    assigned_prospects: int = 0
    contacted: int = 0
    responses: int = 0
    meetings: int = 0
    avatar_initials: Optional[str] = None


class AnalyticsOverviewResponse(BaseModel):
    stats: DashboardStatsResponse
    trend: AnalyticsTrendData
    comparison: list[CampaignComparisonItem] = Field(default_factory=list)
    channel_metrics: list[ChannelMetricItem] = Field(default_factory=list)
    team_performance: list[SalesTeamMemberMetric] = Field(default_factory=list)


class OutreachSearchRequest(BaseModel):
    prompt: Optional[str] = ""
    location: Optional[str] = None
    company_size: Optional[str] = None
    financials: Optional[str] = None
    sector: Optional[str] = None
    channels: Optional[list[str]] = Field(default_factory=lambda: ["Email", "LinkedIn", "Messages"])


class OutreachProspectItem(BaseModel):
    id: str
    company_name: str
    location: str
    company_size: str
    industry: str
    data_freshness: str
    website: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_linkedin: Optional[str] = None
    icp_score: Optional[float] = 85.0
    already_added: bool = False
    # Fitment Agent fields
    meets_criteria: bool = True
    description: Optional[str] = None
    evaluation_results: Optional[dict[str, bool]] = Field(default_factory=dict)
    notes: Optional[str] = None


class AddProspectToCampaignRequest(BaseModel):
    company_name: str
    location: Optional[str] = "Chennai"
    company_size: Optional[str] = "1,000-5,000"
    industry: Optional[str] = "Technology"
    website: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_linkedin: Optional[str] = None
    icp_score: Optional[float] = 85.0


class OutreachCampaignDetailsResponse(BaseModel):
    campaign: CampaignResponse
    total_found: int = 0
    duplicates_filtered: int = 0
    verified_emails: int = 0
    prospects: list[OutreachProspectItem] = Field(default_factory=list)


class OutreachSearchResponse(BaseModel):
    success: bool = True
    webhook_name: str = "Webhook_company_finder"
    thread_id: Optional[str] = None
    run_id: Optional[str] = None
    message: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    raw_response: Optional[str] = None
    fitment_evaluations: list[dict] = Field(default_factory=list)
    results: list[OutreachProspectItem] = Field(default_factory=list)






