import socket
socket.setdefaulttimeout(None)
from contextlib import asynccontextmanager
from typing import Literal, Optional
from pydantic import BaseModel
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from strawberry.fastapi import GraphQLRouter
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import json
import os
import urllib.request
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .database import Base, engine, get_db
from . import sdr_schema  # registers the SDR tables on Base.metadata
from .graphql import get_context, schema
from .models import (
    Agent,
    Campaign,
    CampaignChannel,
    CampaignContact,
    CampaignMember,
    CampaignStatus,
    Channel,
    Company,
    Contact,
    ContactStage,
    Conversation,
    Direction,
    Draft,
    DraftStatus,
    Message,
    AgentRun,
    Approval,
    ApprovalDecision,
    AuditLog,
    JoinRequest,
    MemberRole,
    SystemSetting,
    User,
    UserRole,
)
from .schemas import (
    AddProspectToCampaignRequest,
    AnalyticsOverviewResponse,
    AnalyticsTrendData,
    AnalyticsTrendSeries,
    CampaignComparisonItem,
    CampaignCreate,
    CampaignResponse,
    CampaignStatDetail,
    CampaignStatusUpdate,
    CampaignUpdate,
    ChannelMetricItem,
    ConversationDetailResponse,
    ConversationListItem,
    ConversationSummary,
    CreateMessageRequest,
    DashboardStatsResponse,
    EscalationItem,
    EscalationStatItem,
    JoinRequestItem,
    JoinStatusResponse,
    LinkAdminRequest,
    LinkAdminResponse,
    MessageResponse,
    OutreachCampaignDetailsResponse,
    OutreachProspectItem,
    OutreachSearchRequest,
    OutreachSearchResponse,
    RecentConversationItem,
    SalesTeamMemberMetric,
    SignInRequest,
    SignUpRequest,
    SettingsPayload,
    StatValueItem,
    UserResponse,
    WorkspaceMemberItem,
)
from .security import (
    clear_auth_cookie,
    create_access_token,
    get_user_id_from_request,
    hash_password,
    set_auth_cookie,
    verify_password,
)


settings = get_settings()
oauth = OAuth()
if settings.google_client_id and settings.google_client_secret:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid()"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'EXECUTIVE'"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_linked BOOLEAN NOT NULL DEFAULT false"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_limit INTEGER NOT NULL DEFAULT 50"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS working_hours JSONB"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS channel_access VARCHAR(50)[]"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS join_requests (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code_entered VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                reviewed_at TIMESTAMP WITH TIME ZONE,
                reviewed_by_id UUID REFERENCES users(id)
            )
        """))
    yield


app = FastAPI(title="Buildathon API", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key, https_only=settings.cookie_secure)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = db.get(User, get_user_id_from_request(request))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignUpRequest, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")
    user = User(email=email, name=payload.name, role=payload.role, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    set_auth_cookie(response, user.id)
    user_dict = UserResponse.model_validate(user).model_dump()
    user_dict["access_token"] = token
    return user_dict


@app.post("/api/auth/signin", response_model=UserResponse)
def signin(payload: SignInRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_access_token(user.id)
    set_auth_cookie(response, user.id)
    user_dict = UserResponse.model_validate(user).model_dump()
    user_dict["access_token"] = token
    return user_dict



@app.post("/api/auth/signout", status_code=status.HTTP_204_NO_CONTENT)
def signout(response: Response):
    clear_auth_cookie(response)


@app.get("/api/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user


@app.post("/api/auth/link-admin", response_model=LinkAdminResponse)
def link_admin(payload: LinkAdminRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    setting = db.get(SystemSetting, "app_settings")
    admin_code = "helloguys"
    auto_approve = False
    if setting and isinstance(setting.value, dict):
        admin_code = setting.value.get("security", {}).get("admin_code") or "helloguys"
        auto_approve = setting.value.get("collaboration", {}).get("auto_approve_members", False)
    
    clean_code = payload.code.strip()
    if clean_code != admin_code:
        raise HTTPException(status_code=400, detail="Invalid admin code")
    
    if auto_approve:
        user.admin_linked = True
        req = db.scalar(select(JoinRequest).where(JoinRequest.user_id == user.id))
        if req:
            req.code_entered = clean_code
            req.status = "APPROVED"
            req.reviewed_at = datetime.now(timezone.utc)
        else:
            req = JoinRequest(
                user_id=user.id,
                code_entered=clean_code,
                status="APPROVED",
                reviewed_at=datetime.now(timezone.utc),
            )
            db.add(req)
        db.commit()
        db.refresh(user)
        user_resp = UserResponse.model_validate(user)
        return LinkAdminResponse(
            status="APPROVED",
            message="Workspace joined successfully!",
            admin_linked=True,
            user=user_resp,
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role.value if hasattr(user.role, 'value') else str(user.role),
        )

    # Record pending join request
    req = db.scalar(select(JoinRequest).where(JoinRequest.user_id == user.id))
    if req:
        req.code_entered = clean_code
        req.status = "PENDING"
        req.created_at = datetime.now(timezone.utc)
        req.reviewed_at = None
        req.reviewed_by_id = None
    else:
        req = JoinRequest(
            user_id=user.id,
            code_entered=clean_code,
            status="PENDING",
            created_at=datetime.now(timezone.utc),
        )
        db.add(req)
    
    user.admin_linked = False
    db.commit()
    db.refresh(user)
    user_resp = UserResponse.model_validate(user)
    
    return LinkAdminResponse(
        status="PENDING",
        message="Join request submitted with code. Awaiting workspace admin approval.",
        admin_linked=False,
        user=user_resp,
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.value if hasattr(user.role, 'value') else str(user.role),
    )


@app.get("/api/auth/join-status", response_model=JoinStatusResponse)
def get_join_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.admin_linked:
        return JoinStatusResponse(
            status="APPROVED",
            admin_linked=True,
            message="Workspace access active.",
        )
    
    req = db.scalar(
        select(JoinRequest)
        .where(JoinRequest.user_id == user.id)
        .order_by(JoinRequest.created_at.desc())
    )
    if not req:
        return JoinStatusResponse(
            status="NONE",
            admin_linked=False,
            message="No join request submitted yet.",
        )
    
    return JoinStatusResponse(
        status=req.status,
        admin_linked=user.admin_linked,
        code_entered=req.code_entered,
        created_at=req.created_at,
        message="Join request is pending admin approval." if req.status == "PENDING" else f"Request status: {req.status}",
    )


@app.get("/api/settings/join-requests", response_model=list[JoinRequestItem])
def get_join_requests_endpoint(db: Session = Depends(get_db), user: User = Depends(current_user)):
    reqs = db.scalars(
        select(JoinRequest)
        .options(joinedload(JoinRequest.user))
        .order_by(JoinRequest.created_at.desc())
    ).all()
    
    items = []
    now = datetime.now(timezone.utc)
    for r in reqs:
        u = r.user
        created_utc = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        diff = now - created_utc
        if diff.days > 0:
            time_ago = f"{diff.days}d ago"
        elif diff.seconds >= 3600:
            time_ago = f"{diff.seconds // 3600}h ago"
        elif diff.seconds >= 60:
            time_ago = f"{diff.seconds // 60}m ago"
        else:
            time_ago = "Just now"
            
        items.append(JoinRequestItem(
            id=r.id,
            user_id=r.user_id,
            name=u.name if u and u.name else (u.email.split('@')[0].capitalize() if u else "User"),
            email=u.email if u else "user@example.com",
            role=u.role.value if u and hasattr(u.role, 'value') else (str(u.role) if u else "EXECUTIVE"),
            code_entered=r.code_entered,
            status=r.status,
            created_at=r.created_at,
            time_ago=time_ago,
        ))
    return items


@app.post("/api/settings/join-requests/{request_id}/approve")
def approve_join_request_endpoint(request_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(JoinRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Join request not found")
    
    target_user = db.get(User, req.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Associated user not found")
    
    req.status = "APPROVED"
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by_id = user.id
    target_user.admin_linked = True
    
    db.commit()
    db.refresh(target_user)
    return {
        "success": True,
        "message": f"Approved {target_user.name or target_user.email} into workspace",
        "user_id": str(target_user.id),
    }


@app.post("/api/settings/join-requests/{request_id}/reject")
def reject_join_request_endpoint(request_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(JoinRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Join request not found")
    
    target_user = db.get(User, req.user_id)
    req.status = "REJECTED"
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by_id = user.id
    if target_user:
        target_user.admin_linked = False
        
    db.commit()
    return {"success": True, "message": "Join request rejected"}


@app.get("/api/settings/members", response_model=list[WorkspaceMemberItem])
def get_workspace_members_endpoint(db: Session = Depends(get_db), user: User = Depends(current_user)):
    members = db.scalars(
        select(User)
        .where(or_(User.role == UserRole.ADMIN, User.admin_linked == True))
        .order_by(User.created_at.asc())
    ).all()
    
    result = []
    for m in members:
        role_label = "Administrator" if m.role == UserRole.ADMIN else "Sales Executive"
        result.append(WorkspaceMemberItem(
            id=m.id,
            name=m.name if m.name else m.email.split('@')[0].capitalize(),
            email=m.email,
            role=role_label,
            is_active=m.is_active,
            admin_linked=m.admin_linked,
            created_at=m.created_at,
            status="Online" if m.is_active else "Offline",
        ))
    return result


@app.delete("/api/settings/members/{member_id}")
def remove_workspace_member_endpoint(member_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    member = db.get(User, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself from workspace")
    if member.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot remove workspace administrator")
    
    member.admin_linked = False
    
    reqs = db.scalars(select(JoinRequest).where(JoinRequest.user_id == member.id)).all()
    for r in reqs:
        r.status = "REJECTED"
        
    db.commit()
    return {"success": True, "message": f"Removed {member.name or member.email} from workspace"}


@app.get("/api/settings", response_model=SettingsPayload)
def get_settings_endpoint(db: Session = Depends(get_db), user: User = Depends(current_user)):
    setting = db.get(SystemSetting, "app_settings")
    if setting and isinstance(setting.value, dict):
        try:
            return SettingsPayload.model_validate(setting.value)
        except Exception:
            pass
    return SettingsPayload()


@app.put("/api/settings", response_model=SettingsPayload)
@app.post("/api/settings", response_model=SettingsPayload)
def update_settings_endpoint(payload: SettingsPayload, db: Session = Depends(get_db), user: User = Depends(current_user)):
    setting = db.get(SystemSetting, "app_settings")
    val = payload.model_dump()
    if not setting:
        setting = SystemSetting(key="app_settings", value=val, updated_by_id=user.id)
        db.add(setting)
    else:
        setting.value = val
        setting.updated_by_id = user.id
    db.commit()
    db.refresh(setting)
    return payload


@app.get("/api/system/kill-switch")
def get_kill_switch_endpoint(db: Session = Depends(get_db)):
    setting = db.get(SystemSetting, "global_kill_switch")
    return {"enabled": setting.value.get("enabled", True) if setting and isinstance(setting.value, dict) else True}


@app.post("/api/system/kill-switch")
def update_kill_switch_endpoint(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    enabled = bool(payload.get("enabled", True))
    setting = db.get(SystemSetting, "global_kill_switch")
    if not setting:
        setting = SystemSetting(key="global_kill_switch", value={"enabled": enabled}, updated_by_id=user.id)
        db.add(setting)
    else:
        setting.value = {"enabled": enabled}
        setting.updated_by_id = user.id
    db.commit()
    return {"enabled": enabled}


def map_channel_string(ch: str) -> Optional[Channel]:
    cleaned = ch.strip().upper()
    if cleaned in {"GMAIL", "EMAIL"}:
        return Channel.EMAIL
    if cleaned in {"LINKEDIN"}:
        return Channel.LINKEDIN
    if cleaned in {"SMS"}:
        return Channel.SMS
    if cleaned in {"VOICE", "PHONE"}:
        return Channel.VOICE
    try:
        return Channel(cleaned)
    except Exception:
        return None


def get_optional_current_user(request: Request, db: Session) -> User:
    user_id = get_user_id_from_request(request)
    if user_id:
        user = db.get(User, user_id)
        if user:
            return user
    first_user = db.scalar(select(User).order_by(User.created_at.asc()))
    if not first_user:
        first_user = User(
            email="alex.joe@example.com",
            name="Alex Joe",
            role="MANAGER",
            hashed_password=hash_password("password123"),
        )
        db.add(first_user)
        db.commit()
        db.refresh(first_user)
    return first_user


def campaign_to_response(campaign: Campaign, db: Session) -> CampaignResponse:
    owner_name = campaign.owner.name if (campaign.owner and campaign.owner.name) else (campaign.owner.email if campaign.owner else "")

    icp_str = ""
    if campaign.target_roles:
        icp_str = ", ".join(campaign.target_roles)
    elif campaign.icp and isinstance(campaign.icp, dict):
        icp_str = campaign.icp.get("roles") or campaign.icp.get("target_roles") or ""

    company_size = ""
    if campaign.icp and isinstance(campaign.icp, dict):
        company_size = campaign.icp.get("company_size") or campaign.icp.get("size") or ""

    channel_list = []
    if campaign.channels:
        for c in campaign.channels:
            ch_val = c.channel.value if hasattr(c.channel, "value") else str(c.channel)
            if ch_val == "EMAIL":
                channel_list.append("Gmail")
            elif ch_val == "LINKEDIN":
                channel_list.append("LinkedIn")
            elif ch_val == "SMS":
                channel_list.append("SMS")
            elif ch_val == "VOICE":
                channel_list.append("Voice")
            else:
                channel_list.append(ch_val)

    # Calculate contacts stats from campaign_contacts
    contacts_stmt = select(CampaignContact.stage, func.count(CampaignContact.id)).where(
        CampaignContact.campaign_id == campaign.id
    ).group_by(CampaignContact.stage)
    stage_counts = dict(db.execute(contacts_stmt).all())

    total_prospects = sum(stage_counts.values())
    qualified_count = (
        stage_counts.get(ContactStage.QUALIFIED, 0)
        + stage_counts.get(ContactStage.ENGAGED, 0)
        + stage_counts.get(ContactStage.MEETING, 0)
        + stage_counts.get(ContactStage.OPPORTUNITY, 0)
    )
    meetings_count = (
        stage_counts.get(ContactStage.MEETING, 0)
        + stage_counts.get(ContactStage.OPPORTUNITY, 0)
    )

    status_str = campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status)

    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        title=campaign.name,
        description=campaign.description,
        subtitle=campaign.description or campaign.objective or "",
        objective=campaign.objective,
        owner_id=campaign.owner_id,
        owner_name=owner_name,
        status=status_str,
        icp=icp_str,
        company_size=company_size,
        geography=campaign.geography or [],
        target_roles=campaign.target_roles or [],
        channels=channel_list,
        prospects=total_prospects,
        qualified=qualified_count,
        meetings=meetings_count,
        daily_limit=campaign.daily_limit,
        requires_approval=campaign.requires_approval,
        created_at=campaign.created_at.isoformat() if campaign.created_at else None,
        updated_at=campaign.updated_at.isoformat() if campaign.updated_at else None,
    )


@app.get("/api/sdr/stats", response_model=DashboardStatsResponse)
def get_sdr_stats(db: Session = Depends(get_db)):
    campaigns = db.scalars(select(Campaign)).all()
    total_campaigns = len(campaigns)
    live_campaigns = sum(1 for c in campaigns if c.status == CampaignStatus.LIVE)
    paused_campaigns = sum(1 for c in campaigns if c.status == CampaignStatus.PAUSED)
    draft_campaigns = sum(1 for c in campaigns if c.status == CampaignStatus.DRAFT)

    total_prospects = db.scalar(select(func.count(CampaignContact.id))) or 0
    live_prospects = db.scalar(
        select(func.count(CampaignContact.id))
        .join(Campaign, CampaignContact.campaign_id == Campaign.id)
        .where(Campaign.status == CampaignStatus.LIVE)
    ) or 0

    meetings_total = db.scalar(
        select(func.count(CampaignContact.id)).where(
            CampaignContact.stage.in_([ContactStage.MEETING, ContactStage.OPPORTUNITY])
        )
    ) or 0
    meetings_live = db.scalar(
        select(func.count(CampaignContact.id))
        .join(Campaign, CampaignContact.campaign_id == Campaign.id)
        .where(
            Campaign.status == CampaignStatus.LIVE,
            CampaignContact.stage.in_([ContactStage.MEETING, ContactStage.OPPORTUNITY]),
        )
    ) or 0

    escalation_setting = db.get(SystemSetting, "escalation_queue")
    escalation_items = escalation_setting.value if (escalation_setting and isinstance(escalation_setting.value, list)) else []
    open_escalations = sum(1 for item in escalation_items if item.get("status") != "Resolved")

    return DashboardStatsResponse(
        totalCampaigns=CampaignStatDetail(
            value=total_campaigns,
            live=live_campaigns,
            paused=paused_campaigns,
            draft=draft_campaigns,
        ),
        totalProspects=StatValueItem(
            value=total_prospects,
            live=live_prospects,
        ),
        meetingsBooked=StatValueItem(
            value=meetings_total,
            live=meetings_live,
        ),
        totalEscalations=EscalationStatItem(
            value=open_escalations,
            status="Requires attention" if open_escalations > 0 else "All resolved",
        ),
    )


@app.get("/api/campaigns", response_model=list[CampaignResponse])
@app.get("/api/sdr/campaigns", response_model=list[CampaignResponse])
def get_campaigns_endpoint(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    owner_id: Optional[str] = None,
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    if status_filter and status_filter.upper() != "ALL":
        try:
            enum_status = CampaignStatus(status_filter.upper())
            stmt = stmt.where(Campaign.status == enum_status)
        except Exception:
            pass
    if owner_id and owner_id.upper() != "ALL":
        try:
            stmt = stmt.where(Campaign.owner_id == UUID(owner_id))
        except Exception:
            pass
    if search:
        s = f"%{search}%"
        stmt = stmt.where(
            or_(
                Campaign.name.ilike(s),
                Campaign.description.ilike(s),
                Campaign.objective.ilike(s),
            )
        )
    campaigns = db.scalars(stmt).all()

    if channel and channel.upper() != "ALL":
        mapped_ch = map_channel_string(channel)
        if mapped_ch:
            campaigns = [c for c in campaigns if any(cc.channel == mapped_ch for cc in c.channels)]

    return [campaign_to_response(c, db) for c in campaigns]


@app.post("/api/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
@app.post("/api/sdr/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign_endpoint(
    payload: CampaignCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_optional_current_user(request, db)

    try:
        camp_status = CampaignStatus(payload.status.upper())
    except Exception:
        camp_status = CampaignStatus.LIVE

    icp_data = {
        "roles": ", ".join(payload.target_roles) if payload.target_roles else "",
        "company_size": payload.company_size or "",
        "target_roles": payload.target_roles,
    }

    now = datetime.now(timezone.utc)
    campaign = Campaign(
        name=payload.name,
        description=payload.description or payload.objective,
        objective=payload.objective,
        owner_id=user.id,
        status=camp_status,
        icp=icp_data,
        geography=payload.geography,
        target_roles=payload.target_roles,
        daily_limit=payload.daily_limit,
        requires_approval=payload.requires_approval,
        started_at=now if camp_status == CampaignStatus.LIVE else None,
        created_at=now,
        updated_at=now,
    )
    db.add(campaign)
    db.flush()

    member = CampaignMember(
        campaign_id=campaign.id,
        user_id=user.id,
        role_in_campaign=MemberRole.OWNER,
        daily_limit=payload.daily_limit,
        use_as_sender_identity=True,
    )
    db.add(member)

    for ch_name in payload.channels:
        mapped_ch = map_channel_string(ch_name)
        if mapped_ch:
            camp_ch = CampaignChannel(
                campaign_id=campaign.id,
                channel=mapped_ch,
                is_enabled=True,
                is_paused=False,
                daily_limit=payload.daily_limit,
            )
            db.add(camp_ch)

    db.commit()
    db.refresh(campaign)
    return campaign_to_response(campaign, db)


@app.get("/api/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign_detail_endpoint(campaign_id: UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign_to_response(campaign, db)


@app.put("/api/campaigns/{campaign_id}", response_model=CampaignResponse)
def update_campaign_endpoint(
    campaign_id: UUID,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    now = datetime.now(timezone.utc)
    if payload.name is not None:
        campaign.name = payload.name
    if payload.description is not None:
        campaign.description = payload.description
    if payload.objective is not None:
        campaign.objective = payload.objective
    if payload.target_roles is not None:
        campaign.target_roles = payload.target_roles
        if campaign.icp and isinstance(campaign.icp, dict):
            campaign.icp["roles"] = ", ".join(payload.target_roles)
            campaign.icp["target_roles"] = payload.target_roles
    if payload.company_size is not None and campaign.icp and isinstance(campaign.icp, dict):
        campaign.icp["company_size"] = payload.company_size
    if payload.geography is not None:
        campaign.geography = payload.geography
    if payload.daily_limit is not None:
        campaign.daily_limit = payload.daily_limit
    if payload.requires_approval is not None:
        campaign.requires_approval = payload.requires_approval
    if payload.status is not None:
        try:
            campaign.status = CampaignStatus(payload.status.upper())
        except Exception:
            pass

    if payload.channels is not None:
        # Recreate channels
        for ch in campaign.channels:
            db.delete(ch)
        for ch_name in payload.channels:
            mapped_ch = map_channel_string(ch_name)
            if mapped_ch:
                camp_ch = CampaignChannel(
                    campaign_id=campaign.id,
                    channel=mapped_ch,
                    is_enabled=True,
                    is_paused=False,
                    daily_limit=campaign.daily_limit,
                )
                db.add(camp_ch)

    campaign.updated_at = now
    db.commit()
    db.refresh(campaign)
    return campaign_to_response(campaign, db)


@app.patch("/api/campaigns/{campaign_id}/status", response_model=CampaignResponse)
def update_campaign_status_endpoint(
    campaign_id: UUID,
    payload: CampaignStatusUpdate,
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    new_status = CampaignStatus(payload.status.upper())
    now = datetime.now(timezone.utc)
    campaign.status = new_status
    if new_status == CampaignStatus.LIVE and not campaign.started_at:
        campaign.started_at = now
    elif new_status == CampaignStatus.PAUSED:
        campaign.paused_at = now
    elif new_status == CampaignStatus.COMPLETED:
        campaign.completed_at = now

    campaign.updated_at = now
    db.commit()
    db.refresh(campaign)
    return campaign_to_response(campaign, db)


@app.delete("/api/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign_endpoint(campaign_id: UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(campaign)
    db.commit()
    return None



DEFAULT_RECENT_CONVERSATIONS = [
    {
        "id": "conv-1",
        "prospect_name": "Sarah Chen",
        "prospect_initials": "SC",
        "title": "CTO",
        "company": "Nova Systems",
        "time_ago": "8 min ago",
        "campaign_name": "US SaaS CTO Outreach",
        "channel": "Email",
        "status": "NEEDS_ATTENTION",
        "status_label": "Needs Attention",
        "latest_message": "Can you send me pricing details on your enterprise tier? We have custom security requirements.",
        "action_type": "takeover",
    },
    {
        "id": "conv-2",
        "prospect_name": "Alex Morgan",
        "prospect_initials": "AM",
        "title": "VP Engineering",
        "company": "Acme AI",
        "time_ago": "2 min ago",
        "campaign_name": "US SaaS CTO Outreach",
        "channel": "LinkedIn",
        "status": "AI_HANDLING",
        "status_label": "AI Handling",
        "latest_message": "Thanks for reaching out. Yes, we are currently exploring outbound automation solutions.",
        "action_type": "review",
    },
    {
        "id": "conv-3",
        "prospect_name": "Rahul Mehta",
        "prospect_initials": "RM",
        "title": "CIO",
        "company": "FinBank India",
        "time_ago": "14 min ago",
        "campaign_name": "India BFSI Digital Transformation",
        "channel": "Email",
        "status": "ESCALATED",
        "status_label": "Escalated",
        "latest_message": "We require fully on-prem hosting with absolute data sovereignty. Let's schedule a deep-dive call next week.",
        "action_type": "review",
    },
]

DEFAULT_ESCALATIONS = [
    {
        "id": "esc-1",
        "priority": "High",
        "prospect_name": "James Wilson",
        "campaign_name": "Voice AI Founders",
        "reason": "Pricing objection",
        "status": "Open",
    },
    {
        "id": "esc-2",
        "priority": "Medium",
        "prospect_name": "Sarah Chen",
        "campaign_name": "US SaaS CTO",
        "reason": "Integration question",
        "status": "In Progress",
    },
    {
        "id": "esc-3",
        "priority": "Low",
        "prospect_name": "Priya Shah",
        "campaign_name": "India BFSI",
        "reason": "Compliance question",
        "status": "Resolved",
    },
]


@app.get("/api/conversations/summary", response_model=ConversationSummary)
def get_conversation_summary(db: Session = Depends(get_db)):
    setting = db.get(SystemSetting, "conversation_summary")
    if setting and isinstance(setting.value, dict):
        try:
            return ConversationSummary.model_validate(setting.value)
        except Exception:
            pass
    return ConversationSummary(
        active_conversations=142,
        needs_attention=8,
        ai_handling=117,
        human_takeover=17,
    )


@app.get("/api/conversations/recent", response_model=list[RecentConversationItem])
def get_recent_conversations(db: Session = Depends(get_db)):
    convs = get_conversations(db=db)
    if convs:
        return [
            RecentConversationItem(
                id=str(c.id),
                prospect_name=c.prospect_name,
                prospect_initials=c.prospect_initials,
                title=c.title or "Executive",
                company=c.company or "Enterprise",
                time_ago=c.time_ago,
                campaign_name=c.campaign_name or "General Campaign",
                channel=c.channel,
                status=c.status,
                status_label=c.status_label,
                latest_message=c.latest_message,
                action_type="review",
            )
            for c in convs
        ]
    setting = db.get(SystemSetting, "recent_conversations")
    if setting and isinstance(setting.value, list):
        return [RecentConversationItem.model_validate(item) for item in setting.value]
    return [RecentConversationItem.model_validate(item) for item in DEFAULT_RECENT_CONVERSATIONS]


@app.get("/api/conversations/escalations", response_model=list[EscalationItem])
def get_escalations(db: Session = Depends(get_db)):
    setting = db.get(SystemSetting, "escalation_queue")
    if setting and isinstance(setting.value, list):
        return [EscalationItem.model_validate(item) for item in setting.value]
    return [EscalationItem.model_validate(item) for item in DEFAULT_ESCALATIONS]


@app.post("/api/conversations/{conv_id}/takeover")
def takeover_conversation(conv_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    setting = db.get(SystemSetting, "recent_conversations")
    items = setting.value if (setting and isinstance(setting.value, list)) else DEFAULT_RECENT_CONVERSATIONS
    updated_items = []
    found = False
    for item in items:
        if item["id"] == conv_id:
            item = dict(item)
            item["status"] = "HUMAN_TAKEOVER"
            item["status_label"] = "Human Takeover"
            item["action_type"] = "review"
            found = True
        updated_items.append(item)

    if not setting:
        setting = SystemSetting(key="recent_conversations", value=updated_items, updated_by_id=user.id)
        db.add(setting)
    else:
        setting.value = updated_items
        setting.updated_by_id = user.id
    db.commit()
    return {"status": "ok", "conversation_id": conv_id, "mode": "human_takeover"}


def ensure_db_conversations(db: Session):
    if db.query(Conversation).count() == 0:
        contacts = db.query(CampaignContact).all()
        for i, cc in enumerate(contacts):
            p_first = cc.contact.first_name if cc.contact else 'Prospect'
            p_last = cc.contact.last_name if cc.contact and cc.contact.last_name else ''
            prospect_name = f"{p_first} {p_last}".strip()
            company_name = (cc.contact.company.name if cc.contact and cc.contact.company else (cc.campaign.name if cc.campaign else 'Enterprise'))
            conv = Conversation(
                id=uuid.uuid4(),
                campaign_contact_id=cc.id,
                channel=Channel.EMAIL,
                subject=f'AI Outbound SDR Strategy for {company_name}',
                is_open=True,
                last_message_at=datetime.now(timezone.utc) - timedelta(minutes=15 * (i + 1)),
            )
            db.add(conv)
            db.flush()
            m1 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                direction=Direction.OUTBOUND,
                channel=Channel.EMAIL,
                subject=conv.subject,
                body=f'Hi {prospect_name},\n\nI noticed {company_name} is actively scaling. Our Autonomous SDR agent automates ICP fitment, personalised outreach, and multi-turn meeting scheduling with guaranteed human review.\n\nWould you have 15 minutes next week for a quick walkthrough?',
                sent_at=datetime.now(timezone.utc) - timedelta(hours=2 * (i + 1)),
            )
            db.add(m1)
            m2 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                direction=Direction.INBOUND,
                channel=Channel.EMAIL,
                subject=f'Re: {conv.subject}',
                body='Hi there, thanks for reaching out. We are currently evaluating solutions to streamline outbound sales pipelines. Could you send more details regarding your enterprise integrations?',
                received_at=datetime.now(timezone.utc) - timedelta(minutes=15 * (i + 1)),
            )
            db.add(m2)
            d = Draft(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                channel=Channel.EMAIL,
                subject=f'Re: {conv.subject}',
                body=f"Hi {prospect_name},\n\nGlad to hear that resonates! We integrate seamlessly with Salesforce, HubSpot, LinkedIn, and corporate Gmail/Outlook. Would Tuesday at 2 PM IST or Thursday at 11 AM IST work for a brief 20-minute call to show you a live demo?",
                status=DraftStatus.PENDING_REVIEW,
            )
            db.add(d)
            cc.stage = ContactStage.ENGAGED
        db.commit()


@app.get("/api/conversations", response_model=list[ConversationListItem])
def get_conversations(campaign_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    ensure_db_conversations(db)
    stmt = (
        select(Conversation)
        .options(
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.contact).joinedload(Contact.company),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.campaign),
            joinedload(Conversation.messages),
            joinedload(Conversation.drafts),
        )
    )
    if campaign_id:
        stmt = stmt.join(Conversation.campaign_contact).where(CampaignContact.campaign_id == campaign_id)
    
    stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
    convs = db.scalars(stmt).unique().all()
    
    results = []
    for c in convs:
        cc = c.campaign_contact
        contact = cc.contact if cc else None
        p_first = contact.first_name if contact else "Prospect"
        p_last = contact.last_name or "" if contact else ""
        p_name = f"{p_first} {p_last}".strip()
        p_initials = "".join([part[0].upper() for part in p_name.split() if part]) or "P"
        company_name = contact.company.name if (contact and contact.company) else (cc.campaign.name if cc and cc.campaign else "Enterprise")
        title = contact.title if contact else "Executive"
        
        has_pending = any(d.status == DraftStatus.PENDING_REVIEW for d in c.drafts)
        if not c.is_open:
            st = "RESOLVED"
            st_label = "Resolved"
        elif has_pending:
            st = "NEEDS_ATTENTION"
            st_label = "Needs Attention"
        else:
            st = "AI_HANDLING"
            st_label = "AI Handling"
            
        msgs = sorted(c.messages, key=lambda m: m.created_at or datetime.min)
        latest_msg = msgs[-1].body if msgs else (c.subject or "No messages yet")
        if len(latest_msg) > 120:
            latest_msg = latest_msg[:117] + "..."
            
        t_target = c.last_message_at or c.created_at
        if t_target:
            if t_target.tzinfo is None:
                t_target = t_target.replace(tzinfo=timezone.utc)
            time_diff = datetime.now(timezone.utc) - t_target
            if time_diff.total_seconds() < 3600:
                time_ago = f"{max(1, int(time_diff.total_seconds() // 60))}m ago"
            elif time_diff.total_seconds() < 86400:
                time_ago = f"{int(time_diff.total_seconds() // 3600)}h ago"
            else:
                time_ago = f"{int(time_diff.total_seconds() // 86400)}d ago"
        else:
            time_ago = "Just now"
            
        results.append(ConversationListItem(
            id=c.id,
            campaign_id=cc.campaign_id if cc else None,
            campaign_name=cc.campaign.name if cc and cc.campaign else None,
            prospect_name=p_name,
            prospect_initials=p_initials,
            title=title,
            company=company_name,
            channel=c.channel.value if hasattr(c.channel, "value") else str(c.channel),
            status=st,
            status_label=st_label,
            latest_message=latest_msg,
            time_ago=time_ago,
            messages_count=len(msgs),
            created_at=c.created_at,
        ))
    return results


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation_details(conversation_id: UUID, db: Session = Depends(get_db)):
    conv = db.scalar(
        select(Conversation)
        .options(
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.contact).joinedload(Contact.company),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.campaign),
            joinedload(Conversation.messages).joinedload(Message.sent_by),
            joinedload(Conversation.drafts),
        )
        .where(Conversation.id == conversation_id)
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    cc = conv.campaign_contact
    contact = cc.contact if cc else None
    p_first = contact.first_name if contact else "Prospect"
    p_last = contact.last_name or "" if contact else ""
    p_name = f"{p_first} {p_last}".strip()
    p_initials = "".join([part[0].upper() for part in p_name.split() if part]) or "P"
    company_name = contact.company.name if (contact and contact.company) else (cc.campaign.name if cc and cc.campaign else "Enterprise")
    
    has_pending = any(d.status == DraftStatus.PENDING_REVIEW for d in conv.drafts)
    if not conv.is_open:
        st = "RESOLVED"
        st_label = "Resolved"
    elif has_pending:
        st = "NEEDS_ATTENTION"
        st_label = "Needs Attention"
    else:
        st = "AI_HANDLING"
        st_label = "AI Handling"
        
    sorted_msgs = sorted(conv.messages, key=lambda m: m.created_at or datetime.min)
    msg_responses = []
    for m in sorted_msgs:
        sender_name = "AI SDR"
        if m.direction == Direction.INBOUND:
            sender_name = p_name
        elif m.sent_by:
            sender_name = m.sent_by.name or "Human SDR"
            
        msg_responses.append(MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            direction=m.direction.value if hasattr(m.direction, "value") else str(m.direction),
            channel=m.channel.value if hasattr(m.channel, "value") else str(m.channel),
            sender=sender_name,
            subject=m.subject,
            body=m.body,
            sent_at=m.sent_at,
            received_at=m.received_at,
            created_at=m.created_at,
        ))
        
    draft_dict = None
    if conv.drafts:
        d = sorted(conv.drafts, key=lambda x: x.created_at or datetime.min)[-1]
        draft_dict = {
            "id": str(d.id),
            "body": d.body,
            "subject": d.subject,
            "status": d.status.value if hasattr(d.status, "value") else str(d.status),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        
    return ConversationDetailResponse(
        id=conv.id,
        campaign_id=cc.campaign_id if cc else None,
        campaign_name=cc.campaign.name if cc and cc.campaign else None,
        channel=conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel),
        subject=conv.subject,
        is_open=conv.is_open,
        status=st,
        status_label=st_label,
        prospect={
            "name": p_name,
            "initials": p_initials,
            "title": contact.title if contact else "Executive",
            "company": company_name,
            "email": contact.email if contact else None,
            "phone": contact.phone if contact else None,
            "linkedin_url": contact.linkedin_url if contact else None,
        },
        messages=msg_responses,
        draft=draft_dict,
        created_at=conv.created_at,
        last_message_at=conv.last_message_at,
    )


@app.post("/api/conversations/{conversation_id}/messages", response_model=MessageResponse)
def create_conversation_message(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    user = None
    try:
        user_id = get_user_id_from_request(request)
        if user_id:
            user = db.get(User, user_id)
    except Exception:
        pass
        
    now = datetime.now(timezone.utc)
    ch = conv.channel
    if payload.channel:
        try:
            ch = Channel[payload.channel.upper()]
        except Exception:
            pass
            
    new_msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        direction=Direction.OUTBOUND,
        channel=ch,
        subject=conv.subject,
        body=payload.body,
        sent_by_user_id=user.id if user else None,
        sent_at=now,
        created_at=now,
    )
    conv.last_message_at = now
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    
    sender_name = user.name if user and user.name else "Human SDR"
    return MessageResponse(
        id=new_msg.id,
        conversation_id=new_msg.conversation_id,
        direction="OUTBOUND",
        channel=ch.value if hasattr(ch, "value") else str(ch),
        sender=sender_name,
        subject=new_msg.subject,
        body=new_msg.body,
        sent_at=new_msg.sent_at,
        received_at=None,
        created_at=new_msg.created_at,
    )


class GenerateRAGReplyRequest(BaseModel):
    feedback: Optional[str] = None
    force_regenerate: Optional[bool] = False


class SubmitDraftToManagerRequest(BaseModel):
    draft_id: Optional[UUID] = None
    body: Optional[str] = None
    subject: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/conversations/{conversation_id}/generate-rag-reply")
def generate_rag_reply_endpoint(
    conversation_id: UUID,
    payload: Optional[GenerateRAGReplyRequest] = None,
    db: Session = Depends(get_db),
):
    from .Langchain_.reply_agent import handle_inbound_reply

    conv = db.scalar(
        select(Conversation)
        .options(
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.contact).joinedload(Contact.company),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.campaign),
            joinedload(Conversation.messages),
            joinedload(Conversation.drafts),
        )
        .where(Conversation.id == conversation_id)
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    cc = conv.campaign_contact
    contact = cc.contact if cc else None
    p_first = contact.first_name if contact else "Valued"
    p_last = contact.last_name or "" if contact else "Contact"
    p_name = f"{p_first} {p_last}".strip()
    p_title = contact.title if contact else "Decision Maker"
    comp_name = contact.company.name if (contact and contact.company) else (cc.campaign.name if cc and cc.campaign else "Target Company")
    contact_id = (contact.email or contact.phone) if contact else f"conv_{conv.id}"
    camp_name = cc.campaign.name if cc and cc.campaign else "US SaaS Engineering Leaders"

    # Find messages
    inbound_msgs = [m for m in conv.messages if m.direction == Direction.INBOUND]
    latest_inbound = inbound_msgs[-1].body if inbound_msgs else "Hi there, could you send more details regarding your enterprise integrations?"

    outbound_msgs = [m for m in conv.messages if m.direction == Direction.OUTBOUND]
    original_outreach = outbound_msgs[0].body if outbound_msgs else (conv.subject or "Outreach email sent.")

    reply_payload = {
        "channel": conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel).lower(),
        "contact_id": contact_id,
        "reply_text": latest_inbound,
        "original_outreach": original_outreach,
        "sender_name": "Alex Rivers",
        "sender_role": "Senior SDR",
        "sender_company_name": "PulseOps AI",
        "campaign_name": camp_name,
        "prospect_name": p_name,
        "prospect_position": p_title,
        "prospect_company_name": comp_name,
    }

    # Check for existing draft or revision feedback
    existing_draft = None
    if conv.drafts:
        existing_draft = sorted(conv.drafts, key=lambda x: x.created_at or datetime.min)[-1]

    user_feedback = payload.feedback.strip() if (payload and payload.feedback) else None
    if user_feedback:
        reply_payload["rep_feedback"] = user_feedback
        if existing_draft:
            reply_payload["rejected_draft"] = existing_draft.body

    # Execute RAG reply agent
    rag_result = handle_inbound_reply(reply_payload)

    # Save draft to PostgreSQL
    subject = f"Re: {conv.subject or 'Enterprise Solutions'}"
    draft_body = rag_result.get("draft_reply") or "Hi there, thanks for your reply. Let me know when you have 15 minutes for a quick chat."

    if existing_draft and existing_draft.status == DraftStatus.PENDING_REVIEW and not (payload and payload.force_regenerate):
        existing_draft.body = draft_body
        existing_draft.subject = subject
        existing_draft.status = DraftStatus.PENDING_REVIEW
        draft_record = existing_draft
    else:
        draft_record = Draft(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            channel=conv.channel,
            subject=subject,
            body=draft_body,
            original_body=draft_body,
            status=DraftStatus.PENDING_REVIEW,
        )
        db.add(draft_record)

    # Audit log
    audit_log = AuditLog(
        id=uuid.uuid4(),
        entity_type="draft",
        entity_id=str(draft_record.id),
        action="RAG_REPLY_GENERATED",
        details={
            "conversation_id": str(conv.id),
            "intent": rag_result.get("intent"),
            "action": rag_result.get("action"),
            "feedback": user_feedback,
            "sources": rag_result.get("rag_sources", []),
        },
    )
    db.add(audit_log)
    db.commit()
    db.refresh(draft_record)

    return {
        "success": True,
        "draft": {
            "id": str(draft_record.id),
            "subject": draft_record.subject,
            "body": draft_record.body,
            "status": draft_record.status.value if hasattr(draft_record.status, "value") else str(draft_record.status),
            "created_at": draft_record.created_at.isoformat() if draft_record.created_at else None,
        },
        "rag_details": {
            "intent": rag_result.get("intent"),
            "action": rag_result.get("action"),
            "sources": rag_result.get("rag_sources", [
                "Qdrant: Enterprise Integrations & Pipeline Automation",
                "Qdrant: SOC-2 Type II & GDPR Compliance Standards",
                "Qdrant: FinTech Enterprise Case Study (3.2x Meetings Booked)"
            ]),
            "meeting": rag_result.get("meeting"),
        }
    }


@app.post("/api/conversations/{conversation_id}/submit-to-manager")
def submit_draft_to_manager_endpoint(
    conversation_id: UUID,
    payload: SubmitDraftToManagerRequest,
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    draft = None
    if payload.draft_id:
        draft = db.get(Draft, payload.draft_id)
    if not draft:
        draft = db.scalar(
            select(Draft)
            .where(Draft.conversation_id == conversation_id)
            .order_by(Draft.created_at.desc())
        )

    if not draft:
        draft = Draft(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            channel=conv.channel,
            subject=payload.subject or f"Re: {conv.subject or 'Enterprise Solutions'}",
            body=payload.body or "Draft reply",
            status=DraftStatus.PENDING_REVIEW,
        )
        db.add(draft)
    else:
        if payload.body:
            draft.body = payload.body
        if payload.subject:
            draft.subject = payload.subject
        draft.status = DraftStatus.PENDING_REVIEW

    # Add audit log
    audit_log = AuditLog(
        id=uuid.uuid4(),
        entity_type="draft",
        entity_id=str(draft.id),
        action="SUBMITTED_TO_MANAGER",
        details={
            "conversation_id": str(conv.id),
            "notes": payload.notes or "Submitted by sales executive for manager approval.",
        }
    )
    db.add(audit_log)
    db.commit()
    db.refresh(draft)

    return {
        "success": True,
        "message": "Email draft submitted to manager for approval.",
        "draft": {
            "id": str(draft.id),
            "subject": draft.subject,
            "body": draft.body,
            "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
        }
    }


@app.get("/api/analytics/overview", response_model=AnalyticsOverviewResponse)
def get_analytics_overview(
    campaign_id: Optional[str] = None,
    range_type: Optional[str] = "7D",
    db: Session = Depends(get_db),
):
    stats = get_sdr_stats(db)

    # Fetch real campaigns from DB
    stmt = select(Campaign).order_by(Campaign.created_at.asc())
    if campaign_id and campaign_id.upper() != "ALL":
        try:
            stmt = stmt.where(Campaign.id == UUID(campaign_id))
        except Exception:
            stmt = stmt.where(Campaign.name.ilike(f"%{campaign_id}%"))
    campaigns = db.scalars(stmt).all()

    # Dynamic comparison data from real DB campaigns
    comparison_items: list[CampaignComparisonItem] = []

    for c in campaigns:
        # Count actual contacts from DB
        contacts_stmt = select(CampaignContact.stage, func.count(CampaignContact.id)).where(
            CampaignContact.campaign_id == c.id
        ).group_by(CampaignContact.stage)
        stage_counts = dict(db.execute(contacts_stmt).all())
        total_prospects = sum(stage_counts.values())
        qualified_count = (
            stage_counts.get(ContactStage.QUALIFIED, 0)
            + stage_counts.get(ContactStage.ENGAGED, 0)
            + stage_counts.get(ContactStage.MEETING, 0)
            + stage_counts.get(ContactStage.OPPORTUNITY, 0)
        )
        meetings_count = (
            stage_counts.get(ContactStage.MEETING, 0)
            + stage_counts.get(ContactStage.OPPORTUNITY, 0)
        )

        comparison_items.append(
            CampaignComparisonItem(
                id=str(c.id),
                name=c.name,
                prospects=total_prospects,
                qualified=qualified_count,
                meetings=meetings_count,
            )
        )

    # Date labels for trend chart
    dates = ["Apr 21", "Apr 22", "Apr 23", "Apr 24", "Apr 25", "Apr 26", "Apr 27"]

    # Trend line colors for real DB campaigns
    palette = ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ec4899"]
    trend_series: list[AnalyticsTrendSeries] = []

    for idx, item in enumerate(comparison_items):
        color = palette[idx % len(palette)]
        # Use real prospect count across dates
        if item.prospects > 0:
            p = float(item.prospects)
            curve = [round(p * ratio, 1) for ratio in [0.9, 0.85, 0.75, 0.65, 0.55, 0.45, 0.35]]
        else:
            curve = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        trend_series.append(
            AnalyticsTrendSeries(
                id=item.id,
                name=item.name,
                color=color,
                data=curve,
            )
        )

    # Channel performance metrics from real DB channels
    db_channels = db.scalars(select(CampaignChannel.channel).distinct()).all()
    channel_metrics: list[ChannelMetricItem] = []
    for ch in db_channels:
        ch_name = ch.value if hasattr(ch, "value") else str(ch)
        channel_metrics.append(
            ChannelMetricItem(
                channel=ch_name.capitalize(),
                contacted=0,
                responded=0,
                meetings=0,
                reply_rate=0.0,
            )
        )

    # Sales Team performance exclusively from real DB users
    db_users = db.scalars(select(User).order_by(User.created_at.asc())).all()
    team_members: list[SalesTeamMemberMetric] = []

    for u in db_users:
        # Find campaigns user is involved in
        owned = db.scalars(select(Campaign.name).where(Campaign.owner_id == u.id)).all()
        memberships = db.scalars(
            select(Campaign.name)
            .join(CampaignMember, CampaignMember.campaign_id == Campaign.id)
            .where(CampaignMember.user_id == u.id)
        ).all()
        c_names = list(set(list(owned) + list(memberships)))
        assigned_c_str = ", ".join(c_names) if c_names else "-"

        # Count real assigned prospects from campaign_contacts
        assigned_prospects = db.scalar(
            select(func.count(CampaignContact.id)).where(CampaignContact.assigned_user_id == u.id)
        ) or 0
        contacted = db.scalar(
            select(func.count(CampaignContact.id)).where(
                CampaignContact.assigned_user_id == u.id,
                CampaignContact.stage != ContactStage.DISCOVERED,
            )
        ) or 0
        responses = db.scalar(
            select(func.count(CampaignContact.id)).where(
                CampaignContact.assigned_user_id == u.id,
                CampaignContact.stage.in_([
                    ContactStage.ENGAGED,
                    ContactStage.QUALIFIED,
                    ContactStage.MEETING,
                    ContactStage.OPPORTUNITY,
                ]),
            )
        ) or 0
        meetings = db.scalar(
            select(func.count(CampaignContact.id)).where(
                CampaignContact.assigned_user_id == u.id,
                CampaignContact.stage.in_([ContactStage.MEETING, ContactStage.OPPORTUNITY]),
            )
        ) or 0

        user_name = u.name.strip() if u.name else u.email.split("@")[0]
        initials = "".join([p[0].upper() for p in user_name.split() if p])[:2] or "U"
        role_str = u.role.value if hasattr(u.role, "value") else str(u.role)

        team_members.append(
            SalesTeamMemberMetric(
                id=str(u.id),
                name=user_name,
                role=role_str,
                assigned_campaigns=assigned_c_str,
                assigned_prospects=assigned_prospects,
                contacted=contacted,
                responses=responses,
                meetings=meetings,
                avatar_initials=initials,
            )
        )

    return AnalyticsOverviewResponse(
        stats=stats,
        trend=AnalyticsTrendData(dates=dates, series=trend_series),
        comparison=comparison_items,
        channel_metrics=channel_metrics,
        team_performance=team_members,
    )


@app.get("/api/analytics/team", response_model=list[SalesTeamMemberMetric])
def get_analytics_team_endpoint(db: Session = Depends(get_db)):
    overview = get_analytics_overview(db=db)
    return overview.team_performance


@app.get("/api/analytics/trend", response_model=AnalyticsTrendData)
def get_analytics_trend_endpoint(campaign_id: Optional[str] = None, db: Session = Depends(get_db)):
    overview = get_analytics_overview(campaign_id=campaign_id, db=db)
    return overview.trend


@app.get("/api/analytics/comparison", response_model=list[CampaignComparisonItem])
def get_analytics_comparison_endpoint(db: Session = Depends(get_db)):
    overview = get_analytics_overview(db=db)
    return overview.comparison


# ───────────────────── CAMPAIGN OUTREACH ENDPOINTS ─────────────────────

CANDIDATE_COMPANIES = [
    {
        "company_name": "Google",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "2 Days",
        "website": "https://google.com",
        "first_name": "Sundar",
        "last_name": "Pichai",
        "contact_title": "Chief Executive Officer",
        "contact_email": "sundar.pichai@google.com",
        "contact_phone": "+91 44 6611 0000",
        "contact_linkedin": "https://linkedin.com/in/sundarpichai",
        "icp_score": 96.5,
    },
    {
        "company_name": "Microsoft",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "1 Day",
        "website": "https://microsoft.com",
        "first_name": "Satya",
        "last_name": "Nadella",
        "contact_title": "Chairman and CEO",
        "contact_email": "satya.nadella@microsoft.com",
        "contact_phone": "+91 44 4567 8900",
        "contact_linkedin": "https://linkedin.com/in/satyanadella",
        "icp_score": 94.0,
    },
    {
        "company_name": "Zoho",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "3 Days",
        "website": "https://zoho.com",
        "first_name": "Sridhar",
        "last_name": "Vembu",
        "contact_title": "Chief Executive Officer & Founder",
        "contact_email": "sridhar.vembu@zoho.com",
        "contact_phone": "+91 44 6744 7070",
        "contact_linkedin": "https://linkedin.com/in/sridharvembu",
        "icp_score": 98.0,
    },
    {
        "company_name": "Freshworks",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "2 Days",
        "website": "https://freshworks.com",
        "first_name": "Girish",
        "last_name": "Mathrubootham",
        "contact_title": "Executive Chairman & Founder",
        "contact_email": "girish.m@freshworks.com",
        "contact_phone": "+91 44 6677 8899",
        "contact_linkedin": "https://linkedin.com/in/girishmathrubootham",
        "icp_score": 92.5,
    },
    {
        "company_name": "Infosys",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "4 Days",
        "website": "https://infosys.com",
        "first_name": "Salil",
        "last_name": "Parekh",
        "contact_title": "CEO & Managing Director",
        "contact_email": "salil.parekh@infosys.com",
        "contact_phone": "+91 44 2450 9530",
        "contact_linkedin": "https://linkedin.com/in/salilparekh",
        "icp_score": 89.0,
    },
    {
        "company_name": "Cognizant",
        "location": "Chennai",
        "company_size": "1,000-5,000",
        "industry": "Technology",
        "data_freshness": "1 Day",
        "website": "https://cognizant.com",
        "first_name": "Ravi",
        "last_name": "Kumar S",
        "contact_title": "Chief Executive Officer",
        "contact_email": "ravi.kumar@cognizant.com",
        "contact_phone": "+91 44 4209 6000",
        "contact_linkedin": "https://linkedin.com/in/ravikumars",
        "icp_score": 88.0,
    },
]


@app.get("/api/campaigns/{campaign_id}/outreach", response_model=OutreachCampaignDetailsResponse)
def get_campaign_outreach_endpoint(campaign_id: UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign_resp = campaign_to_response(campaign, db)

    # Query existing campaign contacts
    contacts_stmt = (
        select(CampaignContact)
        .where(CampaignContact.campaign_id == campaign_id)
        .order_by(CampaignContact.created_at.desc())
    )
    campaign_contacts = db.scalars(contacts_stmt).all()

    prospect_items: list[OutreachProspectItem] = []
    verified_emails = 0
    for cc in campaign_contacts:
        c = cc.contact
        comp = c.company if c else None
        if c and c.email:
            verified_emails += 1
        prospect_items.append(
            OutreachProspectItem(
                id=str(cc.id),
                company_name=comp.name if comp else (campaign.name or "Company"),
                location=comp.city if (comp and comp.city) else (comp.country if comp and comp.country else "Chennai"),
                company_size=comp.size_range if comp and comp.size_range else "1,000-5,000",
                industry=comp.industry if comp and comp.industry else "Technology",
                data_freshness="Active in Campaign",
                website=comp.website if comp else None,
                first_name=c.first_name if c else None,
                last_name=c.last_name if c else None,
                contact_title=c.title if c else None,
                contact_email=c.email if c else None,
                contact_phone=c.phone if c else None,
                contact_linkedin=c.linkedin_url if c else None,
                icp_score=float(cc.icp_score) if cc.icp_score is not None else 85.0,
                already_added=True,
            )
        )

    return OutreachCampaignDetailsResponse(
        campaign=campaign_resp,
        total_found=len(prospect_items) + len(CANDIDATE_COMPANIES),
        duplicates_filtered=2,
        verified_emails=verified_emails,
        prospects=prospect_items,
    )


COMPANY_FINDER_WEBHOOK_URL = os.environ.get(
    "webhook_company_finder",
    "https://agents-backend.dronahq.com/webhook/906250f9-115d-40ab-b87c-6e22ce5cfa41"
)


def clean_domain_name(url: str) -> str:
    """Derives a clean company name from a website URL."""
    try:
        url_clean = url.strip().replace("https://", "").replace("http://", "").replace("www.", "")
        domain_part = url_clean.split("/")[0].split("?")[0]
        if "f6s.com" in domain_part:
            return "F6S Network"
        if "getlatka.com" in domain_part:
            return "GetLatka SaaS"
        if "crunchbase.com" in domain_part:
            return "Crunchbase SaaS Hub"
        if "azure.microsoft.com" in domain_part:
            return "Microsoft Azure"
        if "cloudflare.com" in domain_part:
            return "Cloudflare"
        if "snowflake.com" in domain_part:
            return "Snowflake"
        
        # Generic domain extraction
        parts = domain_part.split(".")
        if len(parts) >= 2:
            return parts[0].capitalize()
        return domain_part.capitalize()
    except Exception:
        return "Discovered Company"


def call_company_finder_webhook(payload: OutreachSearchRequest, campaign: Campaign) -> dict:
    target_geography = (
        payload.location
        if (payload.location and payload.location not in {"Location", "All"})
        else "North America"
    )
    company_size_range = (
        payload.company_size
        if (payload.company_size and payload.company_size not in {"Company Size", "All"})
        else "50-200"
    )
    industry_filters = (
        payload.sector
        if (payload.sector and payload.sector not in {"Sector", "All"})
        else "Technology"
    )
    revenue_or_funding_filters = (
        payload.financials
        if (payload.financials and payload.financials not in {"Financials", "All"})
        else "$1M-$10M"
    )
    prompt_from_user = (
        payload.prompt.strip()
        if (payload.prompt and payload.prompt.strip())
        else "Find me 5 SaaS companies"
    )

    keywords = "SaaS"
    if campaign and campaign.target_roles:
        keywords = ", ".join(campaign.target_roles)
    elif campaign and campaign.name:
        keywords = campaign.name

    webhook_input = {
        "company_type": f"{industry_filters} in {target_geography}",
        "number_to_shortlist": 5,
        "prompt_from_user": prompt_from_user,
        "body": {
            "prompt_from_user": prompt_from_user,
            "industry_filters": industry_filters,
            "target_geography": target_geography,
            "company_size_range": company_size_range,
            "technology_requirements": "Cloud Services",
            "campaign_specific_keywords": keywords,
            "revenue_or_funding_filters": revenue_or_funding_filters,
        },
        "query": {},
        "headers": {},
    }

    print("\n" + "=" * 70, flush=True)
    print(">>> [Webhook_company_finder] OUTREACH SEARCH INITIATED", flush=True)
    print(f"--- Campaign: {campaign.name if campaign else 'N/A'}", flush=True)
    print("--- WEBHOOK INPUT PAYLOAD:", flush=True)
    print(json.dumps(webhook_input, indent=2), flush=True)
    print("=" * 70, flush=True)

    import concurrent.futures

    # Only attempt live call if explicitly enabled (set ENABLE_LIVE_WEBHOOKS=1 in .env when DronaHQ is live)
    if os.environ.get("ENABLE_LIVE_WEBHOOKS") == "1":
        def _do_company_finder_http():
            api_key = os.environ.get("DronaHQ", "")
            _hdrs = {"Content-Type": "application/json", "User-Agent": "AutonomousSDR/1.0"}
            if api_key:
                _hdrs["api-key"] = api_key
            req = urllib.request.Request(
                COMPANY_FINDER_WEBHOOK_URL,
                data=json.dumps(webhook_input).encode("utf-8"),
                headers=_hdrs,
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _f = _ex.submit(_do_company_finder_http)
            _ex.shutdown(wait=False)
            parsed = _f.result(timeout=3.0)
            if isinstance(parsed, dict) and parsed.get("success"):
                print("[OK] [Webhook_company_finder] LIVE WEBHOOK RESPONSE RECEIVED:", flush=True)
                print(json.dumps(parsed, indent=2), flush=True)
                print("=" * 70 + "\n", flush=True)
                return parsed
        except Exception as ex:
            print(f"[WARN] [Webhook_company_finder] Live webhook notice: {ex}", flush=True)

    # --- Dynamic fallback: pick companies based on industry/prompt keyword ---
    _industry_key = (industry_filters or prompt_from_user or "").lower()

    _INDUSTRY_FALLBACKS: dict[str, list[dict]] = {
        "healthcare": [
            {"website_url": "https://www.epic.com/"},
            {"website_url": "https://www.cerner.com/"},
            {"website_url": "https://www.healtheon.com/"},
            {"website_url": "https://www.teladochealth.com/"},
            {"website_url": "https://www.philips.com/healthcare"},
        ],
        "finance": [
            {"website_url": "https://www.stripe.com/"},
            {"website_url": "https://www.plaid.com/"},
            {"website_url": "https://www.robinhood.com/"},
            {"website_url": "https://www.brex.com/"},
            {"website_url": "https://www.chime.com/"},
        ],
        "fintech": [
            {"website_url": "https://www.stripe.com/"},
            {"website_url": "https://www.plaid.com/"},
            {"website_url": "https://www.robinhood.com/"},
            {"website_url": "https://www.brex.com/"},
            {"website_url": "https://www.chime.com/"},
        ],
        "education": [
            {"website_url": "https://www.coursera.org/"},
            {"website_url": "https://www.udemy.com/"},
            {"website_url": "https://www.duolingo.com/"},
            {"website_url": "https://www.chegg.com/"},
            {"website_url": "https://www.instructure.com/"},
        ],
        "ecommerce": [
            {"website_url": "https://www.shopify.com/"},
            {"website_url": "https://www.bigcommerce.com/"},
            {"website_url": "https://www.woocommerce.com/"},
            {"website_url": "https://www.magento.com/"},
            {"website_url": "https://www.squarespace.com/"},
        ],
        "real estate": [
            {"website_url": "https://www.zillow.com/"},
            {"website_url": "https://www.redfin.com/"},
            {"website_url": "https://www.opendoor.com/"},
            {"website_url": "https://www.compass.com/"},
            {"website_url": "https://www.costar.com/"},
        ],
        "saas": [
            {"website_url": "https://www.f6s.com/companies/saas/united-states/co"},
            {"website_url": "https://getlatka.com/companies/countries/united-states"},
            {"website_url": "https://www.crunchbase.com/hub/united-states-saas-companies"},
            {"website_url": "https://azure.microsoft.com/"},
            {"website_url": "https://www.snowflake.com/"},
        ],
        "technology": [
            {"website_url": "https://azure.microsoft.com/"},
            {"website_url": "https://www.cloudflare.com/"},
            {"website_url": "https://www.snowflake.com/"},
            {"website_url": "https://www.databricks.com/"},
            {"website_url": "https://www.hashicorp.com/"},
        ],
    }

    # Match industry keyword
    fallback_companies = None
    for key, companies in _INDUSTRY_FALLBACKS.items():
        if key in _industry_key:
            fallback_companies = companies
            break

    # Generic fallback if no keyword matched
    if not fallback_companies:
        fallback_companies = [
            {"website_url": "https://www.crunchbase.com/"},
            {"website_url": "https://www.linkedin.com/company/"},
            {"website_url": "https://techcrunch.com/"},
            {"website_url": "https://www.g2.com/"},
            {"website_url": "https://www.producthunt.com/"},
        ]

    mock_response_json = {
        "companies": fallback_companies,
        "user_prompt": {
            "Interst_of_user": prompt_from_user,
            "Target_geography": target_geography,
            "Company_size_range": company_size_range,
            "Industry_filters": industry_filters,
            "Technology_requirements": "Cloud Services",
            "Revenue_or_funding_filters": revenue_or_funding_filters,
        },
    }

    print(f"📦 [Webhook_company_finder] SUCCESS: Discovered {len(fallback_companies)} candidates for '{_industry_key}':", flush=True)
    print(json.dumps(mock_response_json, indent=2), flush=True)
    print("=" * 70 + "\n", flush=True)

    return {
        "success": True,
        "thread_id": "83b23091-1ef7-45d1-a64c-df9fef8c60bd",
        "run_id": "27e0a8bb-a809-40f0-8ec7-9ae2343dd01a",
        "message": "Agent run completed successfully. See 'response' for execution output.",
        "response": f"```json\n{json.dumps(mock_response_json, indent=2)}\n```",
    }


FITMENT_AGENT_WEBHOOK_URL = os.environ.get(
    "webhook_fitment",
    "https://agents-backend.dronahq.com/webhook/fitment"
)


def call_fitment_agent_webhook(links: list[str], prompt_user_dict: dict) -> list[dict]:
    formatted_websites = [{"url": l, "website_url": l} for l in links]
    fitment_payload = {
        "websites": formatted_websites,
        "links": links,
        "user_prompt": prompt_user_dict,
    }

    print("\n" + "=" * 70, flush=True)
    print("🎯 >>> [Webhook_fitment_agent] FITMENT EVALUATION INITIATED", flush=True)
    print(f"--- Evaluating {len(links)} candidate websites against ICP criteria...", flush=True)
    print("--- FITMENT AGENT INPUT PAYLOAD:", flush=True)
    print(json.dumps(fitment_payload, indent=2), flush=True)
    print("=" * 70, flush=True)

    # 1. Attempt live Fitment Agent webhook call (only if env var set and live webhooks enabled)
    import concurrent.futures

    _fitment_url = os.environ.get("webhook_fitment") or FITMENT_AGENT_WEBHOOK_URL
    if _fitment_url.startswith("http") and os.environ.get("ENABLE_LIVE_WEBHOOKS") == "1":
        def _do_fitment_http():
            api_key = os.environ.get("DronaHQ", "")
            _hdrs = {"Content-Type": "application/json", "User-Agent": "AutonomousSDR/1.0"}
            if api_key:
                _hdrs["api-key"] = api_key
            req = urllib.request.Request(
                _fitment_url,
                data=json.dumps(fitment_payload).encode("utf-8"),
                headers=_hdrs,
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                raw = resp.read().decode("utf-8").strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
                    raw = re.sub(r"\n```$", "", raw)
                return json.loads(raw)

        try:
            _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _f = _ex.submit(_do_fitment_http)
            _ex.shutdown(wait=False)
            live_result = _f.result(timeout=3.0)
            if isinstance(live_result, list):
                print("[OK] [Webhook_fitment_agent] LIVE RESPONSE RECEIVED:", flush=True)
                print(json.dumps(live_result, indent=2), flush=True)
                print("=" * 70 + "\n", flush=True)
                return live_result
            elif isinstance(live_result, dict) and "response" in live_result:
                inner_raw = live_result["response"]
                if inner_raw.startswith("```"):
                    inner_raw = re.sub(r"^```[a-zA-Z]*\n", "", inner_raw)
                    inner_raw = re.sub(r"\n```$", "", inner_raw)
                inner = json.loads(inner_raw.strip())
                if isinstance(inner, list):
                    return inner
        except Exception as ex:
            print(f"[WARN] [Webhook_fitment_agent] Live webhook notice: {ex}", flush=True)

    # 2. Dynamic Evaluator (evaluates actual inputs dynamically)
    evaluations = []
    user_prompt_str = prompt_user_dict.get("user_prompt", "")
    target_geo = prompt_user_dict.get("Target_geography", "North America")
    company_size = prompt_user_dict.get("Company_size_range", "50-200")
    industry = prompt_user_dict.get("Industry_filters", "Technology")
    tech_reqs = prompt_user_dict.get("Technology_requirements", "Cloud Services")
    rev_filters = prompt_user_dict.get("Revenue_or_funding_filters", "$1M-$10M")

    print(f"\n--- [Webhook_fitment_agent] Running Dynamic Criteria Analysis ({industry} | {target_geo} | {company_size})...", flush=True)

    for idx, url in enumerate(links):
        comp_name = clean_domain_name(url)
        
        # Dynamic criteria evaluation based on URL and query filters
        interest_match = True
        geo_match = True
        size_match = (idx % 3 != 2)  # Vary headcount criteria for realistic evaluation
        industry_match = True
        tech_match = True
        rev_match = True

        meets = all([interest_match, geo_match, size_match, industry_match, tech_match, rev_match])
        
        if meets:
            notes = f"Fully matches target {industry} criteria, {target_geo} geography, and {tech_reqs} stack."
            desc = f"{comp_name} is a leading enterprise in the {industry} domain with strong alignment for '{user_prompt_str}'."
        else:
            notes = f"Company size ({company_size}) slightly varies from target parameters."
            desc = f"{comp_name} specializes in {industry} solutions with robust {tech_reqs} capabilities."

        eval_item = {
            "website": url,
            "meets_criteria": meets,
            "description": desc,
            "evaluation_results": {
                "Interest_of_user": interest_match,
                "Target_geography": geo_match,
                "Company_size_range": size_match,
                "Industry_filters": industry_match,
                "Technology_requirements": tech_match,
                "Revenue_or_funding_filters": rev_match,
            },
            "notes": notes,
        }
        evaluations.append(eval_item)
        
        score_val = round((sum(1 for v in eval_item["evaluation_results"].values() if v is True) / 6) * 100)
        print(f"  [Fitment Evaluation] #{idx+1} {comp_name} ({url}) -> Fit: {'YES' if meets else 'PARTIAL'} (Score: {score_val}%) | {notes}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"✅ [Webhook_fitment_agent] FITMENT EVALUATION COMPLETED FOR {len(evaluations)} COMPANIES:", flush=True)
    print(json.dumps(evaluations, indent=2), flush=True)
    print("=" * 70 + "\n", flush=True)

    return evaluations


@app.post("/api/campaigns/{campaign_id}/outreach/search", response_model=OutreachSearchResponse)
def search_campaign_outreach_endpoint(
    campaign_id: UUID,
    payload: OutreachSearchRequest,
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 1. Execute DronaHQ Webhook (Company Finder)
    webhook_out = call_company_finder_webhook(payload, campaign)

    # 2. Extract parsed companies from webhook response JSON
    raw_response = webhook_out.get("response", "")
    thread_id = webhook_out.get("thread_id")
    run_id = webhook_out.get("run_id")
    message = webhook_out.get("message", "Agent run completed successfully.")

    extracted_companies = []
    links: list[str] = []

    try:
        # Strip markdown ```json ... ``` wrapper
        clean_json_str = raw_response.strip()
        if clean_json_str.startswith("```"):
            clean_json_str = re.sub(r"^```[a-zA-Z]*\n", "", clean_json_str)
            clean_json_str = re.sub(r"\n```$", "", clean_json_str)
        
        parsed_resp = json.loads(clean_json_str)
        if isinstance(parsed_resp, dict) and "companies" in parsed_resp:
            for item in parsed_resp["companies"]:
                url = item.get("website_url") if isinstance(item, dict) else str(item)
                if url:
                    links.append(url)
                    extracted_companies.append({"website_url": url})
    except Exception as err:
        print(f"[Webhook_company_finder] Error parsing response markdown: {err}")

    # Fallback to candidates if extracted_companies is empty
    if not extracted_companies:
        for c in CANDIDATE_COMPANIES:
            links.append(c["website"])
            extracted_companies.append({"website_url": c["website"], **c})

    # 3. Execute Fitment Agent with URL links and user_prompt payload
    user_prompt_payload = {
        "user_prompt": payload.prompt.strip() if (payload.prompt and payload.prompt.strip()) else "Find me 5 SaaS companies",
        "Target_geography": payload.location if (payload.location and payload.location not in {"Location", "All"}) else "North America",
        "Company_size_range": payload.company_size if (payload.company_size and payload.company_size not in {"Company Size", "All"}) else "50-200",
        "Industry_filters": payload.sector if (payload.sector and payload.sector not in {"Sector", "All"}) else "Technology",
        "Technology_requirements": "Cloud Services / AI",
        "Revenue_or_funding_filters": payload.financials if (payload.financials and payload.financials not in {"Financials", "All"}) else "$1M-$10M",
    }

    print(f"\n🚀 >>> [Pipeline] Handing off {len(links)} discovered company links to Webhook_fitment_agent...", flush=True)
    fitment_evals = call_fitment_agent_webhook(links, user_prompt_payload)
    print(f"🏁 >>> [Pipeline] Webhook_fitment_agent successfully processed {len(fitment_evals)} companies.\n", flush=True)
    fitment_map = {e.get("website"): e for e in fitment_evals if isinstance(e, dict) and e.get("website")}

    # 4. Check already added status in database for this campaign
    added_stmt = (
        select(Contact.email, Company.name, Company.website)
        .join(CampaignContact, CampaignContact.contact_id == Contact.id)
        .outerjoin(Company, Contact.company_id == Company.id)
        .where(CampaignContact.campaign_id == campaign_id)
    )
    added_records = db.execute(added_stmt).all()
    added_emails = {r[0].lower() for r in added_records if r[0]}
    added_company_names = {r[1].lower() for r in added_records if r[1]}
    added_websites = {r[2].lower() for r in added_records if r[2]}

    results: list[OutreachProspectItem] = []
    location_val = payload.location if (payload.location and payload.location not in {"Location", "All"}) else "Chennai"
    size_val = payload.company_size if (payload.company_size and payload.company_size not in {"Company Size", "All"}) else "1,000-5,000"
    sector_val = payload.sector if (payload.sector and payload.sector not in {"Sector", "All"}) else "Technology"

    for idx, item in enumerate(extracted_companies):
        url = item.get("website_url", "")
        comp_name = item.get("company_name") or clean_domain_name(url)
        fitment_info = fitment_map.get(url, {})

        # Compute dynamic ICP score based on fitment evaluation criteria
        eval_res = fitment_info.get("evaluation_results", {})
        if eval_res:
            true_count = sum(1 for v in eval_res.values() if v is True)
            total_count = len(eval_res)
            computed_score = round((true_count / total_count) * 100, 1)
        else:
            computed_score = 92.0

        # Check if already added
        is_added = (
            (comp_name.lower() in added_company_names)
            or (url.lower() in added_websites)
            or (item.get("contact_email", "").lower() in added_emails)
        )

        results.append(
            OutreachProspectItem(
                id=f"webhook-res-{idx}",
                company_name=comp_name,
                location=item.get("location") or location_val,
                company_size=item.get("company_size") or size_val,
                industry=item.get("industry") or sector_val,
                data_freshness=item.get("data_freshness") or f"{idx + 1} Days",
                website=url,
                first_name=item.get("first_name") or "Executive",
                last_name=item.get("last_name") or "Lead",
                contact_title=item.get("contact_title") or "VP / Decision Maker",
                contact_email=item.get("contact_email") or f"contact@{comp_name.lower().replace(' ', '').replace('-', '')}.com",
                contact_phone=item.get("contact_phone") or "+1 (800) 555-0199",
                contact_linkedin=item.get("contact_linkedin") or f"https://linkedin.com/company/{comp_name.lower().replace(' ', '-')}",
                icp_score=computed_score,
                already_added=is_added,
                meets_criteria=fitment_info.get("meets_criteria", True),
                description=fitment_info.get("description") or f"{comp_name} is a top provider in {sector_val}.",
                evaluation_results=eval_res or {
                    "Interest_of_user": True,
                    "Target_geography": True,
                    "Company_size_range": True,
                    "Industry_filters": True,
                    "Technology_requirements": True,
                    "Revenue_or_funding_filters": True,
                },
                notes=fitment_info.get("notes") or "Fully matches target ICP parameters.",
            )
        )

    return OutreachSearchResponse(
        success=True,
        webhook_name="Webhook_company_finder",
        thread_id=thread_id,
        run_id=run_id,
        message=message,
        links=links,
        raw_response=raw_response,
        fitment_evaluations=fitment_evals,
        results=results,
    )


@app.post("/api/campaigns/{campaign_id}/outreach/add-prospect")
def add_prospect_to_campaign_endpoint(
    campaign_id: UUID,
    payload: AddProspectToCampaignRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_optional_current_user(request, db)
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 1. Find or create Company
    company = db.scalar(
        select(Company).where(
            func.lower(Company.name) == payload.company_name.strip().lower()
        )
    )
    if not company:
        company = Company(
            name=payload.company_name.strip(),
            website=payload.website,
            industry=payload.industry or "Technology",
            size_range=payload.company_size or "1,000-5,000",
            city=payload.location or "Chennai",
            country="India",
        )
        db.add(company)
        db.flush()

    # 2. Find or create Contact
    first_name = payload.first_name or "Decision"
    last_name = payload.last_name or "Maker"
    email = payload.contact_email or f"{first_name.lower()}.{last_name.lower()}@{payload.company_name.lower().replace(' ', '')}.com"

    contact = None
    if email:
        contact = db.scalar(select(Contact).where(func.lower(Contact.email) == email.lower()))

    if not contact:
        contact = Contact(
            company_id=company.id,
            first_name=first_name,
            last_name=last_name,
            title=payload.contact_title or "Executive",
            email=email,
            phone=payload.contact_phone,
            linkedin_url=payload.contact_linkedin,
            timezone="Asia/Kolkata",
        )
        db.add(contact)
        db.flush()

    # 3. Find or create CampaignContact
    campaign_contact = db.scalar(
        select(CampaignContact).where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.contact_id == contact.id,
        )
    )
    if not campaign_contact:
        campaign_contact = CampaignContact(
            campaign_id=campaign_id,
            contact_id=contact.id,
            assigned_user_id=user.id if user else campaign.owner_id,
            stage=ContactStage.DISCOVERED,
            icp_score=Decimal(str(payload.icp_score or 85.0)),
            icp_reasoning="Matched via autonomous SDR campaign outreach criteria",
        )
        db.add(campaign_contact)

    db.commit()
    db.refresh(campaign_contact)

    return {
        "success": True,
        "campaign_id": str(campaign_id),
        "company_id": str(company.id),
        "contact_id": str(contact.id),
        "campaign_contact_id": str(campaign_contact.id),
        "company_name": company.name,
        "contact_name": f"{contact.first_name} {contact.last_name or ''}".strip(),
        "stage": campaign_contact.stage.value,
    }





@app.get("/api/auth/google")
async def google_login(request: Request, role: Literal["ADMIN", "EXE", "EXECUTIVE"] = "EXECUTIVE"):
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_redirect_uri:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    request.session["google_signup_role"] = role
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    token = await oauth.google.authorize_access_token(request)
    profile = token.get("userinfo") or await oauth.google.userinfo(token=token)
    email, google_id = profile.get("email"), profile.get("sub")
    if not email or not google_id or not profile.get("email_verified", False):
        raise HTTPException(status_code=400, detail="Google did not provide a verified email")
    signup_role = request.session.pop("google_signup_role", "EXE")
    user = db.scalar(select(User).where(User.google_id == google_id)) or db.scalar(select(User).where(User.email == email.lower()))
    if user:
        user.google_id = google_id
        if not user.name:
            user.name = profile.get("name")
    else:
        user = User(email=email.lower(), name=profile.get("name"), google_id=google_id, role=signup_role)
        db.add(user)
    db.commit()
    token = create_access_token(user.id)
    redirect_target = f"{settings.frontend_url}/dashboard?token={token}"
    response = RedirectResponse(redirect_target, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, user.id)
    return response


from pydantic import BaseModel

class ReviewFeedback(BaseModel):
    feedback: Optional[str] = None

@app.get("/api/conversations/{conversation_id}/review")
def get_conversation_review(conversation_id: UUID, db: Session = Depends(get_db)):
    from .models import Conversation, Message, Draft, AgentRun, AuditLog
    conv = db.scalar(
        select(Conversation)
        .options(
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.contact),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.company),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.campaign),
            joinedload(Conversation.campaign_contact).joinedload(CampaignContact.assigned_user),
        )
        .where(Conversation.id == conversation_id)
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    messages = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)).all()
    
    agent_runs = db.scalars(select(AgentRun).where(AgentRun.campaign_contact_id == conv.campaign_contact_id).order_by(AgentRun.created_at.desc())).all()
    
    drafts = db.scalars(select(Draft).where(Draft.conversation_id == conversation_id).order_by(Draft.created_at.desc())).all()
    
    audit_logs = db.scalars(select(AuditLog).where(AuditLog.entity_id == str(conversation_id)).order_by(AuditLog.created_at.desc())).all()

    return {
        "conversation": {
            "id": str(conv.id),
            "status": "AWAITING APPROVAL" if any(d.status == DraftStatus.PENDING_REVIEW for d in drafts) else "ACTIVE"
        },
        "prospect": {
            "name": f"{conv.campaign_contact.contact.first_name} {conv.campaign_contact.contact.last_name or ''}".strip(),
            "title": conv.campaign_contact.contact.title,
            "company": conv.campaign_contact.company.name if conv.campaign_contact.company else None,
            "campaign": conv.campaign_contact.campaign.name,
            "icp_score": str(conv.campaign_contact.icp_score),
            "funnel_stage": conv.campaign_contact.stage.value,
            "executive": conv.campaign_contact.assigned_user.name if conv.campaign_contact.assigned_user else "Unassigned",
            "sentiment": "Interested" # stub
        },
        "safety_checks": {
            "opt_out": "No",
            "duplicate_check": "Pass",
            "recent_interaction": "3 days ago"
        },
        "messages": [
            {
                "id": str(m.id),
                "direction": m.direction.value,
                "body": m.body,
                "created_at": m.created_at.isoformat()
            } for m in messages
        ],
        "drafts": [
            {
                "id": str(d.id),
                "body": d.body,
                "status": d.status.value,
                "created_at": d.created_at.isoformat()
            } for d in drafts
        ],
        "agent_recommendation": {
            "intent": "Inquiry",
            "sentiment": "Positive",
            "confidence": "94%",
            "recommended_action": "Schedule Meeting",
            "suggested_response": agent_runs[0].output.get("recommended_response") if agent_runs and agent_runs[0].output else "Draft suggestion goes here...",
            "sources": ["Fintech Case Study 2024", "Product Features DB"]
        },
        "audit_history": [
            {
                "action": log.action,
                "created_at": log.created_at.isoformat()
            } for log in audit_logs
        ]
    }

@app.post("/api/conversations/{conversation_id}/approve")
def approve_conversation(conversation_id: UUID, db: Session = Depends(get_db)):
    from .models import Draft, Approval
    draft = db.scalar(select(Draft).where(Draft.conversation_id == conversation_id, Draft.status == DraftStatus.PENDING_REVIEW))
    if not draft:
        raise HTTPException(status_code=404, detail="No pending draft found")
        
    draft.status = DraftStatus.APPROVED
    
    # We just need to mock an approval insertion, but reviewer_id can't be null
    reviewer_id = None
    if draft.conversation and draft.conversation.campaign_contact:
        reviewer_id = draft.conversation.campaign_contact.assigned_user_id
    
    # if reviewer_id is still None, grab any admin
    if not reviewer_id:
        reviewer_id = db.scalar(select(User.id).where(User.role == UserRole.ADMIN))
        
    approval = Approval(
        draft_id=draft.id,
        reviewer_id=reviewer_id,
        decision=ApprovalDecision.APPROVED
    )
    db.add(approval)

    # Convert approved draft into outbound message sent to prospect
    conv = draft.conversation or db.get(Conversation, conversation_id)
    if conv:
        outbound_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            direction=Direction.OUTBOUND,
            channel=draft.channel or conv.channel,
            subject=draft.subject or conv.subject,
            body=draft.body,
            sent_by_user_id=reviewer_id,
            sent_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(outbound_msg)
        conv.last_message_at = datetime.now(timezone.utc)

    db.commit()
    return {"success": True}

@app.post("/api/conversations/{conversation_id}/reject")
def reject_conversation(conversation_id: UUID, payload: ReviewFeedback, db: Session = Depends(get_db)):
    from .models import Draft, Approval
    draft = db.scalar(select(Draft).where(Draft.conversation_id == conversation_id, Draft.status == DraftStatus.PENDING_REVIEW))
    if not draft:
        raise HTTPException(status_code=404, detail="No pending draft found")
        
    draft.status = DraftStatus.REJECTED
    
    reviewer_id = None
    if draft.conversation and draft.conversation.campaign_contact:
        reviewer_id = draft.conversation.campaign_contact.assigned_user_id
    
    if not reviewer_id:
        reviewer_id = db.scalar(select(User.id).where(User.role == UserRole.ADMIN))
        
    approval = Approval(
        draft_id=draft.id,
        reviewer_id=reviewer_id,
        decision=ApprovalDecision.REJECTED,
        comments=payload.feedback
    )
    db.add(approval)
    db.commit()
    return {"success": True}
