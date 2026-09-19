import os, re, sys, json
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

# ============================================================================
# reply_agent.py
# ==============
# Autonomous Inbound Reply Handler + Decision-Making SDR Agent
# Powered by LangChain LCEL + ChatGroq (Groq API) + Mock DB Lookups
#
# AGENT DESCRIPTION
# -----------------
# Activates on a new inbound reply (Email, LinkedIn, SMS).
# Steps:
#   1. DB LOOKUP   - Checks if contact_id exists in the outreach database.
#   2. FETCH       - Retrieves original outreach sent and the prospect reply.
#   3. CLASSIFY    - LLM classifies reply intent into one of three cases:
#                      not_interested  | meeting_request | wants_more_info
#   4. RESPOND     - Generates the appropriate draft reply or action.
#
# INPUT PAYLOAD SCHEMA  (dict passed to handle_inbound_reply)
# -----------------------------------------------------------
#   channel             : str  - "email" | "sms" | "linkedin"
#   contact_id          : str  - email address / phone number / LinkedIn URL
#   reply_text          : str  - full text of the prospect reply
#   sender_name         : str  - SDR full name
#   sender_role         : str  - SDR job title
#   sender_company_name : str  - sender company name
#
# OUTPUT SCHEMA  (returned dict)
# -------------------------------
#   contact_id    : str
#   channel       : str
#   intent        : "not_interested" | "meeting_request" | "wants_more_info"
#   meeting:
#     proposed_date : str or None  (YYYY-MM-DD)
#     proposed_time : str or None  (HH:MM 24h)
#     timezone      : str or None
#     raw_datetime  : str or None  (original text snippet from reply)
#   draft_reply   : str or None   (None when not_interested)
#   action        : str           (human-readable summary of agent decision)
#
# Usage:
#   python -X utf8 reply_agent.py
# ============================================================================

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise EnvironmentError("GROQ_API_KEY not found in .env file.")

llm = ChatGroq(
    model="groq/compound",
    api_key=GROQ_API_KEY,
    temperature=0.2,
    max_tokens=600,
)

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
    "                       the value proposition and nudging toward scheduling a 15-minute call.\n\n"
    "STRICT RULES:\n"
    "1. Output ONLY valid JSON. No markdown fences, no text outside the JSON block.\n"
    "2. All fields must be present. Use null for fields that do not apply.\n"
    "3. Never invent facts not present in the context.\n"
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
_reply_chain = _prompt | llm | _output_parser


# ===========================================================================
# STEP 3 -- OUTPUT PARSER
# ===========================================================================

def _parse_llm_output(raw: str, contact_id: str, channel: str) -> dict:
    """Strips markdown fences and parses LLM JSON into structured dict."""
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
    draft_reply     = None if draft_reply_raw.strip().upper() == "NO_REPLY_NEEDED" else draft_reply_raw.strip()

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


# ===========================================================================
# STEP 4 -- MAIN ENTRY POINT
# ===========================================================================

def handle_inbound_reply(payload: dict) -> dict:
    """Main entry point for the reply handler agent.

    Accepts an inbound reply payload, looks up the outreach record from the DB,
    classifies the intent via LLM, and returns a structured action dictionary.
    """
    required_keys = ["channel", "contact_id", "reply_text",
                     "sender_name", "sender_role", "sender_company_name"]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"Payload is missing required keys: {missing}")

    contact_id = payload["contact_id"]
    channel    = payload["channel"]

    # Step 1: DB Lookup
    print(f"[Reply Agent] Checking DB for contact: '{contact_id}'...")
    if not db_check_contact_exists(contact_id):
        print("[Reply Agent] Contact not found in outreach DB. Ignoring reply.")
        return {
            "contact_id":  contact_id,
            "channel":     channel,
            "intent":      "unknown_contact",
            "meeting":     {"proposed_date": None, "proposed_time": None,
                            "timezone": None, "raw_datetime": None},
            "draft_reply": None,
            "action":      "Contact not in outreach DB. Reply ignored.",
        }

    record = db_fetch_outreach_record(contact_id)
    print(f"[Reply Agent] Record found: {record['prospect_name']} at {record['prospect_company_name']}.")

    # Step 2: Build LLM Input
    chain_input = {
        "original_outreach":     record["original_outreach"],
        "reply_text":            payload["reply_text"],
        "channel":               channel,
        "sender_name":           payload["sender_name"],
        "sender_role":           payload["sender_role"],
        "sender_company_name":   payload["sender_company_name"],
        "prospect_name":         record["prospect_name"],
        "prospect_position":     record["prospect_position"],
        "prospect_company_name": record["prospect_company_name"],
    }

    # Step 3: Run LLM Chain
    print("[Reply Agent] Classifying reply intent via ChatGroq...")
    raw_output = _reply_chain.invoke(chain_input)

    # Step 4: Parse Output
    result = _parse_llm_output(raw_output, contact_id, channel)
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
        "sender_company_name": "PulseOps AI",
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
