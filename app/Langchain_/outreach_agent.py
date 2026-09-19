"""
outreach_agent.py
=================
Autonomous Multi-Channel Outreach SDR Agent
Powered by LangChain LCEL + ChatGroq (Groq API) + Mock RAG Retrieval

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENT DESCRIPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This agent autonomously generates hyper-personalized, grounded cold
outreach messages for sales teams. It selects the correct outreach
channel (Email, SMS, or LinkedIn) based on the contact information
available for the prospect, retrieves relevant campaign playbooks and
customer case studies via mock RAG, and produces zero-hallucination
copy that explicitly names both the sender's company and the
prospect's company.

Optionally, a manager or SDR can supply a free-text "manager_notes"
field to steer the agent's tone, focus, or angle for that specific
outreach — without changing the core prompt constraints.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT PAYLOAD SCHEMA  (passed as a Python dict to generate_initial_outreach)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    # --- SENDER (REQUIRED) ---
    "sender_name"         : str,   # Full name of the SDR / sender
    "sender_role"         : str,   # Job title of the sender (e.g. "Senior SDR")
    "sender_company_name" : str,   # Name of the sender's company
    "sender_company_info" : str,   # 1-2 sentence description of sender's company

    # --- PROSPECT (REQUIRED) ---
    "prospect_name"         : str, # Full name of the target prospect
    "prospect_position"     : str, # Job title of the prospect
    "prospect_company_name" : str, # Name of the prospect's company
    "prospect_company_info" : str, # 1-2 sentence description of prospect's company

    # --- CAMPAIGN (REQUIRED) ---
    "campaign_name"    : str,      # Short label for the campaign (e.g. "US Fintech CTO Q3")
    "campaign_context" : str,      # Brief description of the campaign goal / value prop

    # --- CONTACT INFO (REQUIRED — at least one value must be non-empty) ---
    "contact_info": {
        "email"    : str,          # Prospect's email address (use "" if unavailable)
        "phone"    : str,          # Prospect's phone number  (use "" if unavailable)
        "linkedin" : str,          # Prospect's LinkedIn URL  (use "" if unavailable)
    },

    # --- MANAGER / SDR NOTES (OPTIONAL) ---
    "manager_notes" : str          # Free-text guidance from manager or SDR — e.g.
                                   # tone adjustments, angles to push, things to avoid.
                                   # Omit the key or set to "" to skip.
}

Channel selection priority:  email  >  phone (SMS)  >  linkedin

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA  (returned as a Python dict)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    "outreach_type" : str,         # Channel used: "email" | "sms" | "linkedin"
    "subject"       : str | None,  # Email subject line (None for SMS / LinkedIn)
    "body"          : str          # The generated outreach message body
}

Usage:
  python -X utf8 outreach_agent.py
"""

import os
import re
import sys
import json
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

# -----------------------------------------------------------------------
# Environment Setup (Strictly Groq API Key & ChatGroq)
# -----------------------------------------------------------------------
load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise EnvironmentError(
        "GROQ_API_KEY not found in .env file. Please ensure GROQ_API_KEY is defined."
    )

# Initialize ChatGroq LLM exclusively
llm = ChatGroq(
    model="groq/compound",
    api_key=GROQ_API_KEY,
    temperature=0.4,
    max_tokens=512,
)

# ===========================================================================
# STEP 1 -- MOCK RAG RETRIEVAL FUNCTIONS
# ===========================================================================

_CAMPAIGN_KNOWLEDGE_STORE = {
    "vp_engineering": """
SENDER COMPANY PLAYBOOK -- Persona: VP of Engineering / CTO
-----------------------------------------------------------
Sender Company Core Value Proposition:
  - Our platform (PulseOps AI) provides an AI-native API correlation engine that cuts noisy alerts by up to 70%.
  - Triggers automated incident runbooks the moment latency spikes or errors surface, slashing MTTR without paging on-call engineers.
  - Gives engineering leaders peace of mind regarding SLA compliance and revenue protection.

Target Persona Pain Points:
  - Alert fatigue from noisy, un-correlated monitoring tools.
  - Mean Time to Detect (MTTD) and Resolve (MTTR) directly harming SLA compliance.
  - Sprint capacity lost to manual incident triaging.
""",
    "default": """
SENDER COMPANY PLAYBOOK -- General Technology Leadership
--------------------------------------------------------------
Sender Company Core Value Proposition:
  - Predictive API health monitoring and automated root-cause resolution.
  - Reduces operational costs and prevents silent outage-related revenue loss.
""",
}

_CASE_STUDY_STORE = {
    "fintech": """
SENDER COMPANY CASE STUDY -- Real-Time Fintech & Payments
-------------------------------------------------------------
Client Outcome with PulseOps AI:
  - Cut API downtime costs by over $240K in the first quarter of deployment.
  - Reduced MTTd from 3.5 hours down to 4 minutes during peak transaction windows.
  - 60% of recurring incident patterns auto-resolved without engineer intervention.

Proof Point to Cite:
  "A real-time payments provider cut API downtime costs by over $240K in Q1 after deploying PulseOps AI."
""",
    "saas": """
SENDER COMPANY CASE STUDY -- B2B SaaS Cloud Infrastructure
-------------------------------------------------------------
Client Outcome with PulseOps AI:
  - Maintained 99.98% API uptime across 200+ microservices.
  - Reduced on-call escalations by 55% within 90 days.

Proof Point to Cite:
  "A B2B SaaS platform achieved 99.98% API uptime and reduced on-call escalations by 55% in 90 days with PulseOps AI."
""",
    "default": """
SENDER COMPANY CASE STUDY -- General Tech Enterprise
-------------------------------------------------------------
Proof Point to Cite:
  "Engineering teams using PulseOps AI achieve 60-80% reductions in MTTD and cut on-call workload within 60 days."
""",
}


def retrieve_campaign_knowledge(campaign_context: str, prospect_position: str, sender_company_name: str = "PulseOps AI") -> str:
    """
    Simulates vector similarity search for campaign playbook & sender company value propositions.
    """
    position_lower = prospect_position.lower()
    if any(kw in position_lower for kw in ("vp", "vice president", "cto", "engineering", "technical")):
        key = "vp_engineering"
    else:
        key = "default"

    return _CAMPAIGN_KNOWLEDGE_STORE[key].strip()


def retrieve_case_studies(company_info: str, sender_company_name: str = "PulseOps AI") -> str:
    """
    Simulates vector similarity search for customer success stories and metrics achieved by sender company.
    """
    info_lower = company_info.lower()
    if any(kw in info_lower for kw in ("fintech", "payment", "finance", "banking", "transaction")):
        key = "fintech"
    elif any(kw in info_lower for kw in ("saas", "software", "platform", "cloud")):
        key = "saas"
    else:
        key = "default"

    return _CASE_STUDY_STORE[key].strip()


# ===========================================================================
# STEP 2 -- LangChain LCEL CHAIN DEFINITION
# ===========================================================================

_EMAIL_SYSTEM_PROMPT = """You are an expert Sales Development Representative (SDR) writing an initial cold outreach email.

STRICT CONSTRAINTS & GUARDRAILS:
1. GROUNDED FACTS ONLY: Never invent metrics, client names, features, or integrations not present in the RAG context.
2. NO GENERIC FLUFF: Never use generic openers like "I hope this email finds you well", "My name is... and I wanted to reach out", or vague corporate jargon.
3. SENDER & COMPANY INTEGRATION: You MUST explicitly state who you are ({sender_name}, {sender_role} at {sender_company_name}) and state how {sender_company_name} helps {prospect_company_name}.
4. LENGTH & FORMAT: The email body MUST be under 125 words, formatted with clean paragraph breaks (no bullet points inside the body).
5. SIGN-OFF: Conclude with a low-friction call to action and a sign-off as {sender_name}, {sender_role} at {sender_company_name}."""

_SMS_SYSTEM_PROMPT = """You are an expert Sales Development Representative (SDR) writing a concise cold outreach SMS text message.

STRICT CONSTRAINTS & GUARDRAILS:
1. GROUNDED FACTS ONLY: Never invent metrics or client names.
2. EXTREMELY CONCISE: SMS must be under 30 words.
3. SENDER & COMPANY INTEGRATION: State who you are ({sender_name} from {sender_company_name}) and quickly reference value.
4. FORMAT: Single paragraph, no subject line, highly conversational.
5. SIGN-OFF: End with a simple CTA (e.g. "Open to a quick chat?")."""

_LINKEDIN_SYSTEM_PROMPT = """You are an expert Sales Development Representative (SDR) writing a LinkedIn connection request / direct message.

STRICT CONSTRAINTS & GUARDRAILS:
1. GROUNDED FACTS ONLY: Never invent metrics or client names.
2. CONCISE: LinkedIn message must be under 75 words.
3. SENDER & COMPANY INTEGRATION: Introduce yourself ({sender_name} at {sender_company_name}) and connect the value prop to their role.
4. FORMAT: Friendly and professional, no subject line.
5. SIGN-OFF: Conclude with a soft CTA and a sign-off as {sender_name}, {sender_role} at {sender_company_name}."""

_BASE_HUMAN_DATA = """SENDER INFORMATION:
Sender Name: {sender_name}
Sender Role: {sender_role}
Sender Company: {sender_company_name}
Sender Company Summary: {sender_company_info}

TARGET RECIPIENT:
Name: {prospect_name}
Role: {prospect_position}
Company: {prospect_company_name}
Company Summary: {prospect_company_info}

CAMPAIGN PLAYBOOK & SENDER VALUE PROPOSITION (RAG Context):
{campaign_knowledge}

RELEVANT SOCIAL PROOF & CASE STUDIES (RAG Context):
{case_studies}

MANAGER / SDR NOTES (High-priority guidance — incorporate if present, ignore section if empty):
{manager_notes}
"""

_EMAIL_INSTRUCTIONS = """
INSTRUCTIONS:
1. Write a 3-5 word subject line relevant to the prospect's priorities.
2. Draft a cold email under 125 words following this flow:
   - Introduce yourself ({sender_name}, {sender_role} at {sender_company_name}) and note a specific observation about {prospect_company_name}'s profile.
   - Articulate how {sender_company_name} solves {prospect_position}'s pain points using the RAG campaign context.
   - Include one concrete proof point or metric from {sender_company_name}'s case study context.
   - End with a low-friction, conversational call to action (e.g. "Worth a brief look next week?").
   - Sign off with {sender_name}, {sender_role} at {sender_company_name}.
3. Adhere strictly to the RAG facts provided.

OUTPUT FORMAT (Follow exactly):
Subject: <Subject line>

<Email Body>"""

_SMS_INSTRUCTIONS = """
INSTRUCTIONS:
1. Write a cold SMS text message under 30 words.
2. Introduce yourself briefly ({sender_name} from {sender_company_name}).
3. Touch on {prospect_company_name}'s pain point using the RAG campaign context or cite a short metric.
4. End with a conversational CTA.
5. NO subject line. Just the message body.

OUTPUT FORMAT (Follow exactly):
Message: <SMS Body>"""

_LINKEDIN_INSTRUCTIONS = """
INSTRUCTIONS:
1. Draft a cold LinkedIn message under 75 words.
2. Introduce yourself ({sender_name} at {sender_company_name}) and mention a relevant point about {prospect_company_name}.
3. Briefly mention the value from the RAG campaign context.
4. Include a soft call to action (e.g., "Would love to connect").
5. NO subject line. Just the message body.

OUTPUT FORMAT (Follow exactly):
Message: <LinkedIn Body>"""


def get_chain_for_channel(channel: str):
    """
    Returns the configured LCEL chain for the specified outreach channel (email, sms, linkedin).
    """
    if channel == "email":
        sys_prompt = _EMAIL_SYSTEM_PROMPT
        human_prompt = _BASE_HUMAN_DATA + _EMAIL_INSTRUCTIONS
    elif channel == "sms":
        sys_prompt = _SMS_SYSTEM_PROMPT
        human_prompt = _BASE_HUMAN_DATA + _SMS_INSTRUCTIONS
    elif channel == "linkedin":
        sys_prompt = _LINKEDIN_SYSTEM_PROMPT
        human_prompt = _BASE_HUMAN_DATA + _LINKEDIN_INSTRUCTIONS
    else:
        raise ValueError(f"Unsupported channel: {channel}")

    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_prompt),
        ("human", human_prompt),
    ])
    output_parser = StrOutputParser()
    return prompt | llm | output_parser


# ======================================================================
# STEP 3 & 4 -- RUNNABLE WRAPPER & PARSER
# ======================================================================

def _parse_outreach_output(raw_output: str, channel: str) -> dict:
    """
    Parses the LLM string output.
    Returns {"channel": channel, "subject": subject, "body": body}.
    For SMS and LinkedIn, subject will be None.
    """
    raw_output = raw_output.strip()
    result = {"outreach_type": channel, "subject": None, "body": raw_output}

    if channel == "email":
        subject_match = re.search(r"^Subject:\s*(.+)", raw_output, re.IGNORECASE | re.MULTILINE)
        if subject_match:
            result["subject"] = subject_match.group(1).strip()
            result["body"] = raw_output[subject_match.end():].strip()
    else:
        message_match = re.search(r"^Message:\s*(.+)", raw_output, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if message_match:
            result["body"] = message_match.group(1).strip()

    return result


def determine_channel(contact_info: dict) -> str:
    """
    Determines the appropriate outreach channel based on available contact info.
    Priority: Email -> Phone (SMS) -> LinkedIn
    """
    if contact_info.get("email"):
        return "email"
    elif contact_info.get("phone"):
        return "sms"
    elif contact_info.get("linkedin"):
        return "linkedin"
    else:
        raise ValueError("No valid contact information provided (email, phone, or linkedin).")


def generate_initial_outreach(payload: dict) -> dict:
    """
    Accepts a Python dictionary payload containing both sender and prospect details,
    as well as 'contact_info'. Fetches RAG knowledge for both companies, executes the LCEL chain 
    via ChatGroq, and returns:
    {"channel": "...", "subject": "...", "body": "..."}
    """
    required_keys = [
        "sender_name", "sender_role", "sender_company_name", "sender_company_info",
        "prospect_name", "prospect_position", "prospect_company_name", "prospect_company_info",
        "campaign_name", "campaign_context", "contact_info"
    ]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"Payload is missing required keys: {missing}")

    channel = determine_channel(payload["contact_info"])
    print(f"[SDR Agent] Target channel determined as: {channel.upper()}")

    # Optional manager/SDR notes — defaults to empty string if not provided
    manager_notes = payload.get("manager_notes", "").strip()
    if manager_notes:
        print(f"[SDR Agent] Manager notes detected — will incorporate into outreach.")

    # Step 1: Mock RAG Retrieval
    print(f"[SDR Agent] Retrieving campaign knowledge for sender '{payload['sender_company_name']}' & campaign '{payload['campaign_name']}'...")
    campaign_knowledge = retrieve_campaign_knowledge(
        campaign_context=payload["campaign_context"],
        prospect_position=payload["prospect_position"],
        sender_company_name=payload["sender_company_name"]
    )

    print(f"[SDR Agent] Retrieving case study RAG data for prospect '{payload['prospect_company_name']}'...")
    case_studies = retrieve_case_studies(
        company_info=payload["prospect_company_info"],
        sender_company_name=payload["sender_company_name"]
    )

    # Step 2: Inject context into LCEL pipeline
    chain_input = {
        "sender_name": payload["sender_name"],
        "sender_role": payload["sender_role"],
        "sender_company_name": payload["sender_company_name"],
        "sender_company_info": payload["sender_company_info"],
        "prospect_name": payload["prospect_name"],
        "prospect_position": payload["prospect_position"],
        "prospect_company_name": payload["prospect_company_name"],
        "prospect_company_info": payload["prospect_company_info"],
        "campaign_knowledge": campaign_knowledge,
        "case_studies": case_studies,
        "manager_notes": manager_notes if manager_notes else "(none)",
    }

    # Step 3: Run Chain
    sdr_chain = get_chain_for_channel(channel)
    print(f"[SDR Agent] Executing LCEL Chain via ChatGroq for {channel.upper()}...")
    raw_output = sdr_chain.invoke(chain_input)

    # Step 4: Parse & Return
    result = _parse_outreach_output(raw_output, channel)
    print(f"[SDR Agent] {channel.upper()} outreach generated successfully.\n")
    return result


# =======================================================================
# DEMO / TEST EXECUTION
# =======================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    base_payload = {
        "sender_name": "Alex Rivers",
        "sender_role": "Senior SDR",
        "sender_company_name": "PulseOps AI",
        "sender_company_info": "AI-native automated API monitoring and incident resolution platform.",
        "prospect_name": "Sarah Jenkins",
        "prospect_position": "VP of Engineering",
        "prospect_company_name": "Acme Payments",
        "prospect_company_info": "Series B fintech providing real-time cross-border payment APIs.",
        "campaign_name": "US Fintech CTO Outreach",
        "campaign_context": "Selling PulseOps AI automated API monitoring & incident resolution. Target reducing downtime and alerting latency."
    }

    # Test Cases for Routing (last case includes manager_notes)
    test_contacts = [
        {"contact_info": {"email": "sarah@acmepayments.com", "phone": "+1234567890", "linkedin": "linkedin.com/in/sarahj"}},
        {"contact_info": {"email": "", "phone": "+1234567890", "linkedin": "linkedin.com/in/sarahj"},
         "manager_notes": "Keep it very brief. Lead with the $240K savings stat. Don't mention MTTR."},
        {"contact_info": {"email": "", "phone": "", "linkedin": "linkedin.com/in/sarahj"},
         "manager_notes": "She's a warm lead — we met her at FinTech Summit. Be friendly, not salesy."},
    ]

    print("=" * 65)
    print("  AUTONOMOUS SDR AGENT (LangChain LCEL + ChatGroq + Multi-Channel)")
    print("=" * 65)

    for i, test_contact in enumerate(test_contacts):
        print(f"\\n--- RUNNING TEST CASE {i+1} ---")
        payload = {**base_payload, **test_contact}
        outreach = generate_initial_outreach(payload)
        
        print("\n  GENERATED OUTREACH")
        print("=" * 65)
        print(f"Outreach Type: {outreach['outreach_type'].upper()}")
        if outreach.get('subject'):
            print(f"Subject: {outreach['subject']}")
        print(f"Body:\n{outreach['body']}")
        print("=" * 65)
        print("Parsed JSON Result:")
        print(json.dumps(outreach, indent=2))
