"""
outreach_agent.py
=================
Autonomous Multi-Channel Outreach SDR Agent
Powered by LangChain LCEL + ChatGroq (Groq API) + Qdrant Vector Retrieval Engine

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENT DESCRIPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This agent autonomously generates hyper-personalized, grounded cold
outreach messages for sales teams. It:
1. Dynamically connects to a Qdrant cluster holding 4 tables (collections):
     - Table 1 (company_atlassian)          : Atlassian value props, Jira, Confluence, JSM, Rovo capabilities
     - Table 2 (campaign_us_saas_cto)       : Campaign 1 - US SaaS Engineering Leaders (CTO, VP Eng)
     - Table 3 (campaign_india_bfsi)        : Campaign 2 - India BFSI Digital Transformation (CIO, CDO)
     - Table 4 (campaign_voice_ai_founders) : Campaign 3 - US AI & Voice Technology Founders (Founder, CEO, CTO)
2. Selects the correct outreach channel (Email, SMS, or LinkedIn) based on
   the contact information available for the prospect.
3. Retrieves relevant vectors from Table 1 and the target Campaign Table using
   FastEmbed local embeddings (zero external API keys needed).
4. Produces zero-hallucination copy that explicitly names both the sender's
   company and the prospect's company.
5. Supports human-in-the-loop review: If a sales rep rejects the initial draft,
   review_and_revise_outreach() refines the copy based on rep feedback.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GUARDRAILS (enforced at prompt level + post-processing)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G1. Strict RAG Grounding  – Any fact, metric, or customer name not
    explicitly present in the retrieved RAG context is FORBIDDEN.
G2. Tone & Length Limits  – Banned openers / filler phrases are listed
    in the prompt. Hard caps: Email ≤ 125 words, SMS ≤ 30 words,
    LinkedIn ≤ 75 words.
G3. No Competitor Bashing – The agent may not name, compare to, or
    speak negatively about any third-party competing product.
G4. PII Redaction         – _redact_pii() strips email addresses and
    phone numbers from all generated output before returning.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT PAYLOAD SCHEMA  (passed as a Python dict to generate_initial_outreach)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    # --- SENDER (REQUIRED) ---
    "sender_name"         : str,   # Full name of the SDR / sender
    "sender_role"         : str,   # Job title of the sender (e.g. "Senior SDR")
    "sender_company_name" : str,   # Name of the sender's company (e.g. "Atlassian")
                                   # NOTE: All company details (value props, case studies,
                                   # proof points) are retrieved from Qdrant via RAG.
                                   # Do NOT pass sender_company_info — RAG owns that.

    # --- PROSPECT (REQUIRED) ---
    "prospect_name"         : str, # Full name of the target prospect
    "prospect_position"     : str, # Job title of the prospect
    "prospect_company_name" : str, # Name of the prospect's company
    "prospect_company_info" : str, # 1-2 sentence description of prospect's company

    # --- CAMPAIGN (REQUIRED) ---
    "campaign_name"        : str,  # Label for the campaign (e.g. "US SaaS Engineering Leaders")
                                   # Used to auto-select the correct Qdrant campaign table.
    "campaign_context"     : str,  # Brief description of the campaign goal / value prop
    "campaign_collection"  : str,  # (OPTIONAL) Explicit Qdrant table name:
                                   #   "campaign_us_saas_cto" | "campaign_india_bfsi" | "campaign_voice_ai_founders"
                                   # If omitted, agent auto-selects via semantic match on campaign_name.

    # --- CONTACT INFO (REQUIRED — at least one value must be non-empty) ---
    "contact_info": {
        "email"    : str,          # Prospect's email address (use "" if unavailable)
        "phone"    : str,          # Prospect's phone number  (use "" if unavailable)
        "linkedin" : str,          # Prospect's LinkedIn URL  (use "" if unavailable)
    },

    # --- MANAGER / SDR NOTES (OPTIONAL) ---
    "manager_notes" : str          # Free-text guidance from manager or SDR
}

Channel selection priority:  email  >  phone (SMS)  >  linkedin

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA  (returned as a Python dict)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    "outreach_type"            : str,         # Channel: "email" | "sms" | "linkedin"
    "subject"                  : str | None,  # Email subject line (None for SMS/LinkedIn)
    "body"                     : str,         # The generated outreach copy
    "campaign_collection_used" : str          # Which Qdrant campaign table was queried
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

# Import Qdrant RAG engine
from qdrant_rag import rag_engine, CAMPAIGN_COLLECTIONS

from groq_utils import get_fallback_groq_llm

# Initialize ChatGroq LLM exclusively with multi-key failover resilience
llm = get_fallback_groq_llm(
    model="groq/compound",
    temperature=0.4,
    max_tokens=512,
    max_retries=3,
)

# ===========================================================================
# STEP 1 -- PROMPTS & LCEL CHAINS
# ===========================================================================

# ---------------------------------------------------------------------------
# GUARDRAIL G1-G3: Shared guardrail block injected into every system prompt.
# G1 = Strict RAG grounding | G2 = Tone & length | G3 = No competitor bashing
# ---------------------------------------------------------------------------
_SHARED_GUARDRAILS = """

━━━━━━━━━━━━━━━━━━━━━━━━  MANDATORY GUARDRAILS  ━━━━━━━━━━━━━━━━━━━━━━━━
[G1 – STRICT RAG GROUNDING]
You MUST base every fact, metric, customer name, product feature, and
integration claim EXCLUSIVELY on the RAG context sections provided below
(OUR COMPANY KNOWLEDGE and CAMPAIGN PLAYBOOK & PROOF POINTS).
If a piece of information is not explicitly stated in those sections,
you are FORBIDDEN from including it. Do NOT invent, infer, or extrapolate
any data point that is absent from the retrieved context.

[G2 – TONE & BANNED PHRASES]
You must NEVER open with or include any of the following phrases or
variants thereof:
  • "I hope this email finds you well"
  • "I hope this message finds you well"
  • "In today's fast-paced digital landscape"
  • "In today's rapidly evolving world"
  • "My name is X and I wanted to reach out"
  • "I am reaching out because"
  • "As an industry leader"
  • "Synergy", "leverage" (as a verb), "paradigm shift"
  • Any variation of the above.
The tone must be direct, specific, and conversational — not corporate.

[G3 – NO COMPETITOR BASHING]
You must NEVER name, reference, compare to, or speak negatively about
any competing product, vendor, or company. Focus only on the value
{sender_company_name} delivers.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

_EMAIL_SYSTEM_PROMPT = (
    "You are an expert Sales Development Representative (SDR) writing an initial cold outreach email."
    + _SHARED_GUARDRAILS +
    """CHANNEL-SPECIFIC CONSTRAINTS (EMAIL):
1. GROUNDED FACTS ONLY: Every metric, feature, and customer name must come from the RAG context.
2. NO GENERIC FLUFF: Do not use any banned phrases listed in the guardrails above.
3. SENDER & COMPANY INTEGRATION: You MUST explicitly state who you are ({sender_name}, {sender_role} at {sender_company_name}) and explain how {sender_company_name} helps {prospect_company_name}.
4. LENGTH HARD CAP: The email body MUST be 125 words or fewer. Count every word. If you exceed 125 words, trim before outputting.
5. FORMAT: Clean paragraph breaks — no bullet points inside the body.
6. SIGN-OFF: Low-friction CTA followed by {sender_name}, {sender_role} at {sender_company_name}."""
)

_SMS_SYSTEM_PROMPT = (
    "You are an expert Sales Development Representative (SDR) writing a concise cold outreach SMS text message."
    + _SHARED_GUARDRAILS +
    """CHANNEL-SPECIFIC CONSTRAINTS (SMS):
1. GROUNDED FACTS ONLY: Every metric or customer name must come from the RAG context.
2. EXTREMELY CONCISE: SMS body MUST be 30 words or fewer.
3. SENDER & COMPANY INTEGRATION: State {sender_name} from {sender_company_name} and reference one value point.
4. FORMAT: Single paragraph, no subject line, highly conversational.
5. SIGN-OFF: Simple CTA (e.g. "Open to a quick chat?")."""
)

_LINKEDIN_SYSTEM_PROMPT = (
    "You are an expert Sales Development Representative (SDR) writing a LinkedIn connection request / direct message."
    + _SHARED_GUARDRAILS +
    """CHANNEL-SPECIFIC CONSTRAINTS (LINKEDIN):
1. GROUNDED FACTS ONLY: Every metric or customer name must come from the RAG context.
2. CONCISE: LinkedIn message MUST be 75 words or fewer.
3. SENDER & COMPANY INTEGRATION: Introduce yourself ({sender_name} at {sender_company_name}) and tie the value prop to {prospect_position}.
4. FORMAT: Friendly and professional, no subject line.
5. SIGN-OFF: Soft CTA and sign-off as {sender_name}, {sender_role} at {sender_company_name}."""
)

_REVISE_SYSTEM_PROMPT = (
    "You are an expert SDR assistant revising an outreach draft based on feedback from the human Sales Representative."
    + _SHARED_GUARDRAILS +
    "Incorporate the sales rep's suggestions strictly while preserving grounded facts "
    "and staying within channel word-count limits."
)

_BASE_HUMAN_DATA = """SENDER INFORMATION:
Sender Name: {sender_name}
Sender Role: {sender_role}
Sender Company: {sender_company_name}

TARGET RECIPIENT:
Name: {prospect_name}
Role: {prospect_position}
Company: {prospect_company_name}
Company Summary: {prospect_company_info}

OUR COMPANY KNOWLEDGE (Retrieved from Qdrant — use ONLY these facts about {sender_company_name}):
{company_knowledge}

CAMPAIGN PLAYBOOK & PROOF POINTS (Retrieved from Qdrant Table '{campaign_collection}'):
{campaign_knowledge}

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
    """Returns the configured LCEL chain for the specified outreach channel."""
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
    return prompt | llm | StrOutputParser()


# ======================================================================
# STEP 2 -- OUTPUT PARSERS, PII REDACTOR & HELPERS
# ======================================================================

# ---------------------------------------------------------------------------
# GUARDRAIL G4: PII Redactor
# Strips email addresses, phone numbers, and user/account IDs from generated
# text so that no sensitive contact or personal identifier leaks through.
# ---------------------------------------------------------------------------
_PII_PATTERNS = [
    # Email addresses  (e.g. user@example.com)
    (re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"), "[EMAIL REDACTED]"),
    # User / Account / Customer IDs (e.g. user_id: 12345, User ID usr_98124, Account ID: 89712)
    (re.compile(r"(?i)\b(?:user|account|customer|client|member)[-_ ]?id\s*[:=#]?\s*([a-zA-Z0-9_\-]+)\b"), "[USER ID REDACTED]"),
    # UUIDs (e.g. 123e4567-e89b-12d3-a456-426614174000)
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "[ID REDACTED]"),
    # International / US phone numbers  (+1-800-555-1234, +91 9876543210, (415) 555-2671)
    (re.compile(
        r"(?:\+?\d{1,3}[\s.\-]?)?"          # country code (+1, +91, etc.)
        r"(?:\(?\d{2,4}\)?[\s.\-]?)?"       # area code ((415), 022, etc.)
        r"\d{3,4}[\s.\-]\d{3,4}"            # standard phone number with separators
        r"(?:[\s.\-]?\d{1,4})?",            # optional extension
        re.VERBOSE
    ), "[PHONE REDACTED]"),
    # Standalone 10-12 digit phone numbers with leading + or country code
    (re.compile(r"\+\d{10,13}\b"), "[PHONE REDACTED]"),
]


def _redact_pii(text: str) -> str:
    """[Guardrail G4] Redacts emails, phone numbers, and user IDs from text.

    Applies all patterns in _PII_PATTERNS sequentially. Returns the
    sanitised string with placeholder tokens in place of any PII found.
    A console warning is emitted whenever a redaction is performed.
    """
    if not text:
        return text
    redacted = text
    for pattern, placeholder in _PII_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            print(
                f"[Guardrail G4 - PII Redactor] Redacted {len(matches)} instance(s) "
                f"matching '{pattern.pattern[:35]}...' -> '{placeholder}'"
            )
            redacted = pattern.sub(placeholder, redacted)
    return redacted


def _parse_outreach_output(raw_output: str, channel: str) -> dict:
    """Parses LLM string output into structured dict and applies PII redaction."""
    raw_output = raw_output.strip()
    result = {"outreach_type": channel, "subject": None, "body": raw_output}

    if channel == "email":
        subject_match = re.search(r"^Subject:\s*(.+)", raw_output, re.IGNORECASE | re.MULTILINE)
        if subject_match:
            result["subject"] = _redact_pii(subject_match.group(1).strip())
            result["body"] = _redact_pii(raw_output[subject_match.end():].strip())
        else:
            result["body"] = _redact_pii(raw_output)
    else:
        message_match = re.search(r"^Message:\s*(.+)", raw_output, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if message_match:
            result["body"] = _redact_pii(message_match.group(1).strip())
        else:
            result["body"] = _redact_pii(raw_output)

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


# ======================================================================
# STEP 3 -- CORE GENERATE FUNCTION (BACKED BY QDRANT 4 TABLES)
# ======================================================================

def generate_initial_outreach(payload: dict) -> dict:
    """
    Accepts prospect & sender payload.
    1. Determines channel (email/sms/linkedin)
    2. Queries Qdrant Table 1 (company_info) for our company's capabilities & case studies
    3. Queries Qdrant Campaign Table (from the 3 campaign tables) based on campaign context
    4. Executes LCEL chain via ChatGroq
    5. Returns {"outreach_type": ..., "subject": ..., "body": ..., "campaign_collection_used": ...}
    """
    required_keys = [
        "sender_name", "sender_role", "sender_company_name",
        "prospect_name", "prospect_position", "prospect_company_name", "prospect_company_info",
        "campaign_name", "campaign_context", "contact_info"
    ]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"Payload is missing required keys: {missing}")

    channel = determine_channel(payload["contact_info"])
    print(f"[SDR Agent] Target channel: {channel.upper()}")

    manager_notes = payload.get("manager_notes", "").strip()
    if manager_notes:
        print(f"[SDR Agent] Incorporating manager notes into generation.")

    # -------------------------------------------------------------------
    # QDRANT 4-TABLE RAG RETRIEVAL
    # -------------------------------------------------------------------
    print(f"[SDR Agent] Querying Qdrant for company info and campaign playbook...")
    rag_data = rag_engine.retrieve_context(
        sender_company_name=payload["sender_company_name"],
        prospect_company_info=payload["prospect_company_info"],
        prospect_position=payload["prospect_position"],
        campaign_name=payload["campaign_name"],
        campaign_context=payload["campaign_context"]
    )

    campaign_collection_used = payload.get("campaign_collection") or rag_data["campaign_collection_used"]
    print(f"[SDR Agent] Retrived RAG context from Table 1 ('company_info') and Campaign Table ('{campaign_collection_used}').")

    # -------------------------------------------------------------------
    # CHECK: Is this a revision of a previously rejected draft?
    # Stateless check: if rejected_draft + feedback are passed in payload,
    # the agent automatically recognizes it as a revision / correction.
    # -------------------------------------------------------------------
    rejected_draft = payload.get("rejected_draft") or payload.get("previous_draft")
    rep_feedback = payload.get("rep_feedback") or payload.get("sales_rep_feedback")
    if rejected_draft and rep_feedback:
        print("[SDR Agent] Correction requested on previous rejected draft. Running revision...")
        if isinstance(rejected_draft, str):
            rejected_draft = {"outreach_type": channel, "subject": None, "body": rejected_draft}
        return review_and_revise_outreach(rejected_draft, rep_feedback, payload)

    # -------------------------------------------------------------------
    # LCEL GENERATION (INITIAL DRAFT)
    # -------------------------------------------------------------------
    chain_input = {
        "sender_name": payload["sender_name"],
        "sender_role": payload["sender_role"],
        "sender_company_name": payload["sender_company_name"],
        "prospect_name": payload["prospect_name"],
        "prospect_position": payload["prospect_position"],
        "prospect_company_name": payload["prospect_company_name"],
        "prospect_company_info": payload["prospect_company_info"],
        "company_knowledge": rag_data["company_knowledge"],
        "campaign_knowledge": rag_data["campaign_knowledge"],
        "campaign_collection": campaign_collection_used,
        "manager_notes": manager_notes if manager_notes else "(none)",
    }

    sdr_chain = get_chain_for_channel(channel)
    print(f"[SDR Agent] Generating initial grounded copy via Groq LLM (is_first_draft=True)...")
    raw_output = sdr_chain.invoke(chain_input)

    result = _parse_outreach_output(raw_output, channel)
    result["campaign_collection_used"] = campaign_collection_used
    result["is_first_draft"] = True
    result["draft_version"] = "initial"
    return result


# ======================================================================
# STEP 4 -- HUMAN-IN-THE-LOOP REVISION FUNCTION
# ======================================================================

def review_and_revise_outreach(
    original_draft: dict,
    sales_rep_feedback: str,
    original_payload: dict
) -> dict:
    """
    Revises an existing outreach draft when rejected by the sales rep.
    Takes the sales rep's suggestions and regenerates the copy, respecting original RAG constraints.
    """
    channel = original_draft["outreach_type"]

    revise_prompt = ChatPromptTemplate.from_messages([
        ("system", _REVISE_SYSTEM_PROMPT),
        ("human", (
            "ORIGINAL RECIPIENT: {prospect_name} ({prospect_position} at {prospect_company_name})\n"
            "SENDER: {sender_name} ({sender_role} at {sender_company_name})\n"
            "CHANNEL: {channel}\n\n"
            "ORIGINAL DRAFT:\n"
            "Subject: {original_subject}\n"
            "Body:\n{original_body}\n\n"
            "SALES REP REJECTION FEEDBACK / SUGGESTIONS:\n"
            "\"{feedback}\"\n\n"
            "Please revise the draft to incorporate the sales rep's feedback completely. "
            "Keep the response grounded, professional, and matching the channel format ({channel}).\n\n"
            + (_EMAIL_INSTRUCTIONS if channel == "email" else _SMS_INSTRUCTIONS if channel == "sms" else _LINKEDIN_INSTRUCTIONS)
        ))
    ])

    chain = revise_prompt | llm | StrOutputParser()
    raw_output = chain.invoke({
        "prospect_name": original_payload["prospect_name"],
        "prospect_position": original_payload["prospect_position"],
        "prospect_company_name": original_payload["prospect_company_name"],
        "sender_name": original_payload["sender_name"],
        "sender_role": original_payload["sender_role"],
        "sender_company_name": original_payload["sender_company_name"],
        "channel": channel.upper(),
        "original_subject": original_draft.get("subject") or "(None)",
        "original_body": original_draft["body"],
        "feedback": sales_rep_feedback,
    })

    revised = _parse_outreach_output(raw_output, channel)
    revised["campaign_collection_used"] = original_draft.get("campaign_collection_used", "campaign_fintech")
    revised["status"] = "revised"
    revised["is_first_draft"] = False
    revised["draft_version"] = "revised"
    revised["rep_feedback"] = sales_rep_feedback
    return revised


# =======================================================================
# DEMO / TEST EXECUTION
# =======================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  AUTONOMOUS SDR AGENT (Qdrant 4-Table RAG + ChatGroq + Multi-Channel)")
    print("=" * 70)

    # Test Payload 1: US SaaS CTO Prospect -> Triggers Table 1 (company_atlassian) + Table 2 (campaign_us_saas_cto)
    atlassian_payload = {
        "sender_name": "Jordan Lee",
        "sender_role": "Enterprise SDR",
        "sender_company_name": "Atlassian",
        "sender_company_info": "Global work management and software development platform (Jira, Confluence, JSM, Rovo).",
        "prospect_name": "Marcus Vance",
        "prospect_position": "VP of Engineering",
        "prospect_company_name": "CloudScale Systems",
        "prospect_company_info": "Series B B2B SaaS platform scaling distributed microservices and sprint delivery.",
        "campaign_name": "US SaaS Engineering Leaders",
        "campaign_context": "Targeting agile sprint velocity, cross-functional roadmap alignment, and developer tracking.",
        "contact_info": {
            "email": "marcus@cloudscalesystems.io",
            "phone": "+14155552671",
            "linkedin": "linkedin.com/in/marcusvance"
        }
    }

    print("\n--- TEST 1: Generating Initial Email via Qdrant RAG ---")
    draft = generate_initial_outreach(atlassian_payload)
    print(f"\n[Generated Output - Channel: {draft['outreach_type'].upper()}]")
    print(f"[Qdrant Campaign Table Used]: {draft['campaign_collection_used']}")
    print(f"Subject: {draft['subject']}")
    print(f"Body:\n{draft['body']}")

    print("\n" + "-" * 70)
    print("--- TEST 2: Human-in-the-Loop Rejection & Revision Cycle ---")
    rep_feedback = "Highlight Jira and Rovo AI agents for sprint tracking, and keep it under 100 words."
    print(f"Sales Rep Feedback: \"{rep_feedback}\"")
    revised_draft = review_and_revise_outreach(draft, rep_feedback, atlassian_payload)
    print(f"\n[Revised Output - Subject: {revised_draft['subject']}]")
    print(f"Revised Body:\n{revised_draft['body']}")

    print("\n" + "=" * 70)
    print("Tests completed successfully!")
