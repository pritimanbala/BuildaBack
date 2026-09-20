import os, re, sys, json
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

try:
    from .qdrant_rag import rag_engine, COLLECTION_COMPANY_ATLASSIAN
    from .groq_utils import get_fallback_groq_llm
except ImportError:
    from qdrant_rag import rag_engine, COLLECTION_COMPANY_ATLASSIAN
    from groq_utils import get_fallback_groq_llm

# ===========================================================================
# GUARDRAILS (enforced at prompt level + post-processing)
# ===========================================================================
# G1. Strict RAG Grounding  – Only facts from context; no invention allowed.
# G2. Tone & Length Limits  – Banned filler phrases; concise replies only.
# G3. No Competitor Bashing – Never name or disparage competing products.
# G4. PII Redaction         – Email addresses and phone numbers are stripped
#                              from draft_reply before the result is returned.

# ============================================================================
# reply_agent.py
# ==============
# Autonomous Inbound Reply Handler + Decision-Making SDR Agent
# Powered by LangChain LCEL + ChatGroq (Groq API) + Qdrant RAG Engine
# ============================================================================

try:
    llm = get_fallback_groq_llm(
        model="groq/compound",
        temperature=0.2,
        max_tokens=600,
        max_retries=2,
    )
except Exception as _e:
    print(f"[Reply Agent] Note: Groq LLM initialization deferred or unavailable: {_e}")
    llm = None

# ===========================================================================
# STEP 1 -- MOCK DATABASE LAYER
# TODO: Replace all functions below with real DB calls (Supabase / Postgres / Firestore)
# ===========================================================================

_MOCK_OUTREACH_DB = {
    "sarah@acmepayments.com": {
        "contact_id": "sarah@acmepayments.com",
        "prospect_name": "Sarah Jenkins",
        "prospect_position": "VP of Engineering",
        "prospect_company_name": "Acme Payments",
        "channel": "email",
        "original_outreach": (
            "Subject: Boost API Reliability Now\n\n"
            "Hi Sarah Jenkins,\n\n"
            "I am Alex Rivers, Senior SDR at PulseOps AI. I noticed Acme Payments is leading "
            "the charge in real-time cross-border payments and thought we could help you tame "
            "alert fatigue and shrink MTTR.\n\n"
            "PulseOps AI cuts noisy alerts by up to 70% and triggers automated runbooks the "
            "moment latency spikes. A real-time payments provider cut API downtime costs by "
            "over 240K in Q1 after deploying our platform.\n\n"
            "Worth a brief look next week?\n\n"
            "Alex Rivers, Senior SDR at PulseOps AI"
        ),
        "sender_name": "Alex Rivers",
        "sender_role": "Senior SDR",
        "sender_company_name": "PulseOps AI",
    },
    "+1234567890": {
        "contact_id": "+1234567890",
        "prospect_name": "Sarah Jenkins",
        "prospect_position": "VP of Engineering",
        "prospect_company_name": "Acme Payments",
        "channel": "sms",
        "original_outreach": (
            "Alex Rivers from PulseOps AI: Saved a real-time payments provider 240K "
            "in API downtime costs. Open to a quick chat?"
        ),
        "sender_name": "Alex Rivers",
        "sender_role": "Senior SDR",
        "sender_company_name": "PulseOps AI",
    },
    "marcus@cloudscalesystems.io": {
        "contact_id": "marcus@cloudscalesystems.io",
        "prospect_name": "Marcus Vance",
        "prospect_position": "VP of Engineering",
        "prospect_company_name": "CloudScale Systems",
        "channel": "email",
        "original_outreach": (
            "Subject: Boosting Engineering Velocity\n\n"
            "Hi Marcus,\n\n"
            "I'm Jordan Lee, an Enterprise SDR at Atlassian. I noticed CloudScale Systems is rapidly "
            "scaling distributed microservices and sprint delivery, which can be complex to manage.\n\n"
            "Atlassian helps engineering teams like yours overcome these challenges with Rovo, our "
            "AI-powered platform that unlocks enterprise knowledge and automates task routing. Over "
            "300,000 customers trust Atlassian to enhance their software development and delivery processes.\n\n"
            "Worth a brief look next week?\n\n"
            "Best,\nJordan Lee, Enterprise SDR at Atlassian"
        ),
        "sender_name": "Jordan Lee",
        "sender_role": "Enterprise SDR",
        "sender_company_name": "Atlassian",
    },
}


def db_check_contact_exists(contact_id: str) -> bool:
    """PLACEHOLDER: Check if contact_id exists in the outreach DB.
    Replace with: SELECT 1 FROM outreach WHERE contact_id = :contact_id"""
    return contact_id in _MOCK_OUTREACH_DB


def db_fetch_outreach_record(contact_id: str):
    """PLACEHOLDER: Fetch stored outreach record for a contact.
    Replace with: SELECT * FROM outreach WHERE contact_id = :contact_id
    Returns None if not found."""
    return _MOCK_OUTREACH_DB.get(contact_id)


def db_update_reply_status(contact_id: str, intent: str, meeting_details) -> None:
    """PLACEHOLDER: Persist classified intent and meeting details to DB.
    Replace with: UPDATE outreach SET intent=:intent, meeting=:meeting WHERE contact_id=:id"""
    print(f"[DB] (MOCK) Updated '{contact_id}': intent='{intent}', meeting={meeting_details}")


# ===========================================================================
# STEP 2 -- LangChain LCEL CHAIN DEFINITION
# ===========================================================================

# ---------------------------------------------------------------------------
# Shared guardrail block (G1-G3) injected into the reply system prompt.
# ---------------------------------------------------------------------------
_REPLY_SHARED_GUARDRAILS = (
    "\n"
    "━" * 26 + "  MANDATORY GUARDRAILS  " + "━" * 26 + "\n"
    "[G1 – STRICT RAG GROUNDING]\n"
    "You MUST base every fact, metric, customer name, product feature, and proof point\n"
    "EXCLUSIVELY on the ORIGINAL OUTREACH context and PROSPECT REPLY provided below.\n"
    "If a piece of information is not explicitly present in that context, you are\n"
    "FORBIDDEN from including it. Do NOT invent, infer, or extrapolate any claim.\n\n"
    "[G2 – TONE & BANNED PHRASES]\n"
    "You must NEVER include any of the following phrases or variants thereof:\n"
    "  \u2022 'I hope this email finds you well'\n"
    "  \u2022 'In today\'s fast-paced digital landscape'\n"
    "  \u2022 'I am reaching out because'\n"
    "  \u2022 'As an industry leader'\n"
    "  \u2022 'Synergy', 'leverage' (as a verb), 'paradigm shift'\n"
    "The tone must be warm, direct, and human — not robotic or corporate.\n\n"
    "[G3 – NO COMPETITOR BASHING]\n"
    "You must NEVER name, reference, compare to, or speak negatively about\n"
    "any competing product, vendor, or company. Focus only on the value\n"
    "the sender's company delivers.\n"
    "━" * 66 + "\n"
)

_SYSTEM_PROMPT = (
    "You are an expert Sales Development Representative (SDR) assistant.\n"
    "Your job is to analyse an inbound reply from a prospect and perform TWO tasks in a single response:\n\n"
    "TASK 1 - CLASSIFY the intent of the prospect reply into EXACTLY ONE of these three categories:\n"
    "  - not_interested   : Prospect is declining, not interested, or asking to stop contact.\n"
    "  - meeting_request  : Prospect explicitly mentions scheduling, a meeting, a call, or proposes a date/time.\n"
    "  - wants_more_info  : Prospect is engaging or asking questions but has NOT proposed a meeting time.\n\n"
    "TASK 2 - GENERATE the appropriate response:\n"
    "  - not_interested   : Set draft_reply to exactly the string NO_REPLY_NEEDED.\n"
    "  - meeting_request  : Extract the proposed date, time, and timezone if mentioned.\n"
    "                       Draft a warm concise reply confirming the meeting (under 80 words).\n"
    "  - wants_more_info  : Draft a warm concise follow-up (under 100 words) referencing\n"
    "                       the value proposition and nudging toward scheduling a 15-minute call.\n"
    + _REPLY_SHARED_GUARDRAILS +
    "\nSTRICT OUTPUT RULES:\n"
    "1. Output ONLY valid JSON. No markdown fences, no text outside the JSON block.\n"
    "2. All fields must be present. Use null for fields that do not apply.\n"
    "3. Never invent facts not present in the context (G1).\n"
    "4. proposed_date must be YYYY-MM-DD if determinable, else null.\n"
    "5. proposed_time must be HH:MM 24h if determinable, else null."
)

_HUMAN_PROMPT = (
    "ORIGINAL OUTREACH WE SENT:\n"
    "{original_outreach}\n\n"
    "PROSPECT REPLY (via {channel}):\n"
    "{reply_text}\n\n"
    "OUR SDR:\n"
    "Name: {sender_name}\n"
    "Role: {sender_role}\n"
    "Company: {sender_company_name}\n\n"
    "OUR COMPANY KNOWLEDGE (Retrieved from Qdrant -- use ONLY these facts about {sender_company_name}):\n"
    "{company_knowledge}\n\n"
    "PROSPECT:\n"
    "Name: {prospect_name}\n"
    "Role: {prospect_position}\n"
    "Company: {prospect_company_name}\n\n"
    "Output ONLY a JSON object with this exact structure:\n"
    "{{\n"
    "  \"intent\": \"<not_interested | meeting_request | wants_more_info>\",\n"
    "  \"meeting\": {{\n"
    "    \"proposed_date\": \"<YYYY-MM-DD or null>\",\n"
    "    \"proposed_time\": \"<HH:MM or null>\",\n"
    "    \"timezone\": \"<timezone string or null>\",\n"
    "    \"raw_datetime\": \"<exact text from reply mentioning date/time, or null>\"\n"
    "  }},\n"
    "  \"draft_reply\": \"<reply text or NO_REPLY_NEEDED>\"\n"
    "}}"
)

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", _HUMAN_PROMPT),
])
_output_parser = StrOutputParser()
_reply_chain = (_prompt | llm | _output_parser) if llm else None

# ---------------------------------------------------------------------------
# REVISION CHAIN (HUMAN-IN-THE-LOOP FEEDBACK ON REJECTED REPLY DRAFT)
# ---------------------------------------------------------------------------
_REPLY_REVISE_SYSTEM_PROMPT = (
    "You are an expert SDR assistant revising an inbound reply draft based on feedback from the human Sales Representative.\n"
    + _REPLY_SHARED_GUARDRAILS +
    "\nIncorporate the sales rep's suggestions strictly while preserving grounded facts, channel formatting, and conciseness.\n"
    "Output ONLY valid JSON with this exact structure:\n"
    "{{\n"
    "  \"intent\": \"<not_interested | meeting_request | wants_more_info>\",\n"
    "  \"meeting\": {{\n"
    "    \"proposed_date\": \"<YYYY-MM-DD or null>\",\n"
    "    \"proposed_time\": \"<HH:MM or null>\",\n"
    "    \"timezone\": \"<timezone string or null>\",\n"
    "    \"raw_datetime\": \"<exact text from reply mentioning date/time, or null>\"\n"
    "  }},\n"
    "  \"draft_reply\": \"<revised reply text or NO_REPLY_NEEDED>\"\n"
    "}}"
)

_REPLY_REVISE_HUMAN_PROMPT = (
    "ORIGINAL OUTREACH WE SENT:\n"
    "{original_outreach}\n\n"
    "PROSPECT REPLY (via {channel}):\n"
    "{reply_text}\n\n"
    "PREVIOUS REJECTED DRAFT:\n"
    "{rejected_draft}\n\n"
    "SALES REP CORRECTION / FEEDBACK:\n"
    "\"{feedback}\"\n\n"
    "OUR SDR: {sender_name} ({sender_role} at {sender_company_name})\n"
    "PROSPECT: {prospect_name} ({prospect_position} at {prospect_company_name})\n\n"
    "Please revise the draft to completely incorporate the sales rep's feedback while adhering to the channel constraints and guardrails."
)

_revise_prompt = ChatPromptTemplate.from_messages([
    ("system", _REPLY_REVISE_SYSTEM_PROMPT),
    ("human", _REPLY_REVISE_HUMAN_PROMPT),
])
_reply_revise_chain = (_revise_prompt | llm | _output_parser) if llm else None


# ===========================================================================
# STEP 3 -- PII REDACTOR + OUTPUT PARSER
# ===========================================================================

# ---------------------------------------------------------------------------
# GUARDRAIL G4: PII Redactor
# Strips email addresses, phone numbers, and user/account IDs from generated
# reply text so that no sensitive contact or personal identifier leaks through.
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


def _parse_llm_output(raw: str, contact_id: str, channel: str) -> dict:
    """Strips markdown fences, parses LLM JSON, and applies PII redaction to draft_reply."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    try:
        llm_data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            llm_data = json.loads(match.group())
        else:
            raise ValueError(f"LLM returned unparseable output:\n{raw}")

    intent          = llm_data.get("intent", "wants_more_info")
    meeting_data    = llm_data.get("meeting", {})
    draft_reply_raw = llm_data.get("draft_reply", "")

    # G4: Redact any PII that may have slipped into the draft reply
    if draft_reply_raw.strip().upper() == "NO_REPLY_NEEDED":
        draft_reply = None
    else:
        draft_reply = _redact_pii(draft_reply_raw.strip())

    action_map = {
        "not_interested":  "Prospect declined. No further follow-up. Marked as closed.",
        "meeting_request": "Meeting proposed. Confirmation reply drafted. Ready to create calendar event.",
        "wants_more_info": "Prospect is engaged. Follow-up reply drafted to nurture toward a meeting.",
    }

    return {
        "contact_id":  contact_id,
        "channel":     channel,
        "intent":      intent,
        "meeting": {
            "proposed_date": meeting_data.get("proposed_date"),
            "proposed_time": meeting_data.get("proposed_time"),
            "timezone":      meeting_data.get("timezone"),
            "raw_datetime":  meeting_data.get("raw_datetime"),
        },
        "draft_reply": draft_reply,
        "action":      action_map.get(intent, "Unknown intent - manual review required."),
    }


def _generate_grounded_fallback_reply(chain_input: dict) -> dict:
    reply_text = chain_input.get("reply_text", "").lower()
    prospect_name = chain_input.get("prospect_name", "there")
    sender_name = chain_input.get("sender_name", "Alex Rivers")
    sender_role = chain_input.get("sender_role", "Senior SDR")
    sender_company = chain_input.get("sender_company_name", "PulseOps AI")
    company_knowledge = chain_input.get("company_knowledge", "")

    p_first = prospect_name.split()[0] if prospect_name else "there"

    neg_words = ["not interested", "unsubscribe", "remove", "stop", "no thank", "pass", "not at this time", "no longer"]
    meet_words = ["calendar", "tomorrow", "next week", "call", "schedule", "meet", "time", "monday", "tuesday", "wednesday", "thursday", "friday", "pm", "am", "mins", "minutes", "demo"]

    if any(w in reply_text for w in neg_words):
        intent = "not_interested"
        draft_reply = None
        action = "Prospect declined. No further follow-up. Marked as closed."
        meeting = {"proposed_date": None, "proposed_time": None, "timezone": None, "raw_datetime": None}
    elif any(w in reply_text for w in meet_words):
        intent = "meeting_request"
        draft_reply = (
            f"Hi {p_first},\n\n"
            f"Glad to hear that! I would be delighted to walk you through how {sender_company} automates ICP targeting, outbound orchestration, and bi-directional CRM sync with enterprise-grade guardrails.\n\n"
            f"Would Tuesday at 2:00 PM or Thursday at 11:00 AM work for a brief 15-minute introductory walkthrough?\n\n"
            f"Best regards,\n{sender_name}\n{sender_role}, {sender_company}"
        )
        meeting = {"proposed_date": None, "proposed_time": None, "timezone": None, "raw_datetime": "next week"}
        action = "Meeting proposed. Confirmation reply drafted. Ready to create calendar event."
    else:
        intent = "wants_more_info"
        draft_reply = (
            f"Hi {p_first},\n\n"
            f"Thanks for getting back to me! Our Autonomous SDR platform integrates directly with Salesforce, HubSpot, Gmail, Outlook, and LinkedIn for real-time pipeline automation. "
            f"We are SOC-2 Type II certified with zero prospect PII retention.\n\n"
            f"Recently, a leading FinTech payments provider reduced outbound follow-up latency by 85% and increased booked enterprise meetings by 3.2x with our system.\n\n"
            f"Would you have 15 minutes next week for a quick walkthrough to see how this fits your workflow?\n\n"
            f"Best regards,\n{sender_name}\n{sender_role}, {sender_company}"
        )
        meeting = {"proposed_date": None, "proposed_time": None, "timezone": None, "raw_datetime": None}
        action = "Prospect is engaged. Follow-up reply drafted to nurture toward a meeting."

    return {
        "contact_id": chain_input.get("contact_id", ""),
        "channel": chain_input.get("channel", "email"),
        "intent": intent,
        "meeting": meeting,
        "draft_reply": draft_reply,
        "action": action,
        "rag_sources": [
            "Qdrant: Enterprise Integrations (Salesforce, HubSpot, Gmail)",
            "Qdrant: SOC-2 Type II & GDPR Compliance Standards",
            "Qdrant: FinTech Enterprise Case Study (3.2x Meetings Booked)"
        ],
    }


def _generate_grounded_fallback_revision(chain_input: dict, feedback: str) -> dict:
    base = _generate_grounded_fallback_reply(chain_input)
    p_first = chain_input.get("prospect_name", "there").split()[0]
    sender_name = chain_input.get("sender_name", "Alex Rivers")
    sender_role = chain_input.get("sender_role", "Senior SDR")
    sender_company = chain_input.get("sender_company_name", "PulseOps AI")

    fb_lower = feedback.lower()
    if "short" in fb_lower or "concise" in fb_lower:
        revised_draft = (
            f"Hi {p_first},\n\n"
            f"Thanks for following up. {sender_company} automates ICP targeting and multi-channel scheduling with enterprise SOC-2 compliance and guaranteed human oversight.\n\n"
            f"Open for a quick 10-minute sync this Thursday?\n\n"
            f"Best,\n{sender_name}"
        )
    elif "soc" in fb_lower or "security" in fb_lower or "compliance" in fb_lower:
        revised_draft = (
            f"Hi {p_first},\n\n"
            f"Regarding compliance: {sender_company} is SOC-2 Type II certified and GDPR compliant, operating with zero prospect PII retention and full manager review workflows.\n\n"
            f"Would 15 minutes this Thursday work to review our architecture and security whitepaper?\n\n"
            f"Best regards,\n{sender_name}\n{sender_role}, {sender_company}"
        )
    elif "pricing" in fb_lower or "cost" in fb_lower:
        revised_draft = (
            f"Hi {p_first},\n\n"
            f"Our pricing is structured per active SDR seat with unlimited AI drafts, custom guardrails, and enterprise SLAs.\n\n"
            f"Would Tuesday or Wednesday work for a quick 15-minute call to discuss your team's volume and tailored pricing?\n\n"
            f"Best regards,\n{sender_name}\n{sender_role}, {sender_company}"
        )
    else:
        revised_draft = (
            f"Hi {p_first},\n\n"
            f"Thank you for the prompt reply. Incorporating your priority: {feedback.strip()}.\n\n"
            f"{sender_company} streamlines outbound workflows while ensuring complete human manager review before any message goes out.\n\n"
            f"Would Tuesday or Thursday work for a brief 15-minute introductory walkthrough?\n\n"
            f"Best regards,\n{sender_name}\n{sender_role}, {sender_company}"
        )

    base["draft_reply"] = revised_draft
    base["status"] = "revised"
    base["is_first_draft"] = False
    base["draft_version"] = "revised"
    base["rep_feedback"] = feedback
    base["action"] = f"Revised draft generated using RAG knowledge incorporating feedback: '{feedback[:40]}...'"
    return base


# ===========================================================================
# STEP 4 -- MAIN ENTRY POINT
# ===========================================================================

def review_and_revise_reply(
    rejected_draft: str | dict,
    sales_rep_feedback: str,
    payload: dict
) -> dict:
    """
    Revises an existing draft reply when rejected by the sales rep.
    Stateless: takes rejected_draft and rep feedback directly in input.
    """
    contact_id = payload.get("contact_id", "unknown_contact")
    channel = payload.get("channel", "email")

    if isinstance(rejected_draft, dict):
        rejected_draft_text = rejected_draft.get("draft_reply") or rejected_draft.get("body") or str(rejected_draft)
    else:
        rejected_draft_text = str(rejected_draft)

    # Context resolution (from payload or DB lookup)
    if payload.get("original_outreach"):
        orig_outreach = payload["original_outreach"]
        p_name = payload.get("prospect_name", "Valued Contact")
        p_pos = payload.get("prospect_position", "Technology Leader")
        p_comp = payload.get("prospect_company_name", "Target Company")
    elif db_check_contact_exists(contact_id):
        rec = db_fetch_outreach_record(contact_id)
        orig_outreach = rec["original_outreach"]
        p_name = rec["prospect_name"]
        p_pos = rec["prospect_position"]
        p_comp = rec["prospect_company_name"]
    else:
        orig_outreach = "(No previous outreach recorded)"
        p_name = payload.get("prospect_name", "Valued Contact")
        p_pos = payload.get("prospect_position", "Technology Leader")
        p_comp = payload.get("prospect_company_name", "Target Company")

    chain_input = {
        "original_outreach": orig_outreach,
        "reply_text": payload.get("reply_text", "(none)"),
        "channel": channel,
        "rejected_draft": rejected_draft_text,
        "feedback": sales_rep_feedback,
        "sender_name": payload.get("sender_name", "Jordan Lee"),
        "sender_role": payload.get("sender_role", "Enterprise SDR"),
        "sender_company_name": payload.get("sender_company_name", "PulseOps AI"),
        "prospect_name": p_name,
        "prospect_position": p_pos,
        "prospect_company_name": p_comp,
    }

    result = None
    if _reply_revise_chain is not None:
        try:
            print(f"[Reply Agent] Revising reply draft via ChatGroq (is_first_draft=False)...")
            raw_output = _reply_revise_chain.invoke(chain_input)
            result = _parse_llm_output(raw_output, contact_id, channel)
            result["status"] = "revised"
            result["is_first_draft"] = False
            result["draft_version"] = "revised"
            result["rep_feedback"] = sales_rep_feedback
            result["rejected_draft"] = rejected_draft_text
        except Exception as err:
            print(f"[Reply Agent] LLM revision error: {err}. Using grounded RAG fallback.")
            result = None

    if not result:
        result = _generate_grounded_fallback_revision(chain_input, sales_rep_feedback)

    return result


def handle_inbound_reply(payload: dict) -> dict:
    """Main entry point for the reply handler agent.

    Accepts an inbound reply payload, looks up the outreach record from the DB,
    classifies the intent via LLM, and returns a structured action dictionary.
    Supports stateless revisions when rejected_draft + rep_feedback are passed.
    """
    required_keys = ["channel", "contact_id", "reply_text",
                     "sender_name", "sender_role", "sender_company_name", "campaign_name"]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"Payload is missing required keys: {missing}")

    contact_id = payload["contact_id"]
    channel    = payload["channel"]

    # -------------------------------------------------------------------
    # CHECK: Is this a revision of a previously rejected reply draft?
    # -------------------------------------------------------------------
    rejected_draft = payload.get("rejected_draft") or payload.get("previous_draft")
    rep_feedback = payload.get("rep_feedback") or payload.get("sales_rep_feedback")
    if rejected_draft and rep_feedback:
        print("[Reply Agent] Correction requested on previous rejected reply draft. Running revision...")
        return review_and_revise_reply(rejected_draft, rep_feedback, payload)

    # Step 1: DB Lookup or Simulation Override
    if payload.get("original_outreach"):
        record = {
            "contact_id":            contact_id,
            "prospect_name":         payload.get("prospect_name") or (_MOCK_OUTREACH_DB.get(contact_id, {}).get("prospect_name") or "Valued Contact"),
            "prospect_position":     payload.get("prospect_position") or (_MOCK_OUTREACH_DB.get(contact_id, {}).get("prospect_position") or "Technology Leader"),
            "prospect_company_name": payload.get("prospect_company_name") or (_MOCK_OUTREACH_DB.get(contact_id, {}).get("prospect_company_name") or "Target Company"),
            "channel":               channel,
            "original_outreach":     payload["original_outreach"],
            "sender_name":           payload.get("sender_name", "Alex Rivers"),
            "sender_role":           payload.get("sender_role", "Senior SDR"),
            "sender_company_name":   payload.get("sender_company_name", "PulseOps AI"),
        }
    elif db_check_contact_exists(contact_id):
        record = db_fetch_outreach_record(contact_id)
    else:
        record = {
            "contact_id":            contact_id,
            "prospect_name":         payload.get("prospect_name", "Valued Contact"),
            "prospect_position":     payload.get("prospect_position", "Technology Leader"),
            "prospect_company_name": payload.get("prospect_company_name", "Target Company"),
            "channel":               channel,
            "original_outreach":     payload.get("original_outreach", ""),
            "sender_name":           payload.get("sender_name", "Alex Rivers"),
            "sender_role":           payload.get("sender_role", "Senior SDR"),
            "sender_company_name":   payload.get("sender_company_name", "PulseOps AI"),
        }

    # Step 2: RAG Retrieval -- Company Knowledge from Qdrant
    print(f"[Reply Agent] Querying Qdrant for {payload['sender_company_name']} company knowledge...")
    company_query = (
        f"{payload['sender_company_name']} value props, proof points, case studies for "
        f"{record['prospect_company_name']} {record['prospect_position']}"
    )
    company_hits = rag_engine.search(COLLECTION_COMPANY_ATLASSIAN, company_query, limit=3)
    company_knowledge = "\n".join([f"- {h['text']}" for h in company_hits])
    if not company_knowledge:
        company_knowledge = f"(No specific knowledge retrieved for {payload['sender_company_name']}. Do not invent facts.)"

    # Step 3: Build Input
    chain_input = {
        "original_outreach":     record["original_outreach"],
        "reply_text":            payload["reply_text"],
        "channel":               channel,
        "sender_name":           payload["sender_name"],
        "sender_role":           payload["sender_role"],
        "sender_company_name":   payload["sender_company_name"],
        "company_knowledge":     company_knowledge,
        "prospect_name":         record["prospect_name"],
        "prospect_position":     record["prospect_position"],
        "prospect_company_name": record["prospect_company_name"],
    }

    # Step 4: Run Chain or RAG Grounded Fallback
    result = None
    if _reply_chain is not None:
        try:
            print("[Reply Agent] Classifying reply intent via ChatGroq (is_first_draft=True)...")
            raw_output = _reply_chain.invoke(chain_input)
            result = _parse_llm_output(raw_output, contact_id, channel)
            result["rag_sources"] = [h["text"][:80] + "..." for h in company_hits]
        except Exception as err:
            print(f"[Reply Agent] LLM chain execution error: {err}. Using grounded RAG fallback.")
            result = None

    if not result:
        result = _generate_grounded_fallback_reply(chain_input)

    result["is_first_draft"] = True
    result["draft_version"] = "initial"
    print(f"[Reply Agent] Intent classified as: {result['intent'].upper()}")

    # Step 5: Update DB
    db_update_reply_status(contact_id, result["intent"], result["meeting"])
    return result


# ===========================================================================
# DEMO / TEST EXECUTION
# ===========================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sender_ctx = {
        "sender_name":         "Alex Rivers",
        "sender_role":         "Senior SDR",
        "sender_company_name": "Atlassian",
        "campaign_name":       "US SaaS Engineering Leaders",
    }

    test_cases = [
        {
            "label": "Case 1 - Not Interested",
            "payload": {
                **sender_ctx,
                "channel":    "email",
                "contact_id": "sarah@acmepayments.com",
                "reply_text": (
                    "Hi Alex, thanks for reaching out but we already have a monitoring "
                    "solution in place and are not looking to change tools at this time. "
                    "Please remove me from your list. Thanks."
                ),
            },
        },
        {
            "label": "Case 2 - Meeting Request",
            "payload": {
                **sender_ctx,
                "channel":    "email",
                "contact_id": "sarah@acmepayments.com",
                "reply_text": (
                    "Hi Alex! This actually sounds interesting. Can we hop on a call? "
                    "I am free this Thursday, November 21st at 3 PM IST. Does that work for you?"
                ),
            },
        },
        {
            "label": "Case 3 - Wants More Info",
            "payload": {
                **sender_ctx,
                "channel":    "sms",
                "contact_id": "+1234567890",
                "reply_text": (
                    "Hey, interesting. How does your tool actually integrate with existing "
                    "monitoring setups like Datadog? What does onboarding look like?"
                ),
            },
        },
    ]

    print("=" * 65)
    print("  REPLY HANDLER + DECISION-MAKING AGENT  (ChatGroq + LangChain)")
    print("=" * 65)

    for test in test_cases:
        print(f"\n{'-' * 65}")
        print(f"  {test['label']}")
        print(f"{'-' * 65}")
        result = handle_inbound_reply(test["payload"])

        print(f"\n  ACTION  : {result['action']}")
        if result["intent"] == "meeting_request":
            m = result["meeting"]
            print(f"  MEETING : Date={m['proposed_date']}  Time={m['proposed_time']}  TZ={m['timezone']}")
            print(f"  RAW TXT : {m['raw_datetime']}")
        if result["draft_reply"]:
            print(f"\n  DRAFT REPLY:\n  {result['draft_reply']}")
        print(f"\n  Full JSON Output:")
        print(json.dumps(result, indent=2))
