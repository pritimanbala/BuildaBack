"""
followup_agent.py
=================
Autonomous Follow-Up SDR Agent
Powered by LangChain LCEL + ChatGroq (Groq API) + Qdrant RAG

PURPOSE
-------
Generates a short, grounded follow-up message for a prospect who has
not replied to previous outreach. Fire and forget -- no revision loop.

FOLLOW-UP STAGES (auto-selected from followup_count)
-----------------------------------------------------
  followup_count = 0  ->  1st Follow-Up: Short nudge, fresh angle
  followup_count = 1  ->  2nd Follow-Up: Address a likely objection
  followup_count >= 2 ->  Final Follow-Up: Respectful break-up

GUARDRAILS
----------
G1. Strict RAG Grounding  - Only facts from Qdrant company context.
G2. Tone & Length Limits  - No filler phrases; Email<=80w, SMS<=25w.
G3. No Competitor Bashing - Never name or disparage competitors.
G4. PII Redaction         - Emails and phone numbers stripped from output.

INPUT SCHEMA  (dict passed to generate_followup)
-------------------------------------------------
{
    "sender_name"         : str,   # SDR full name
    "sender_role"         : str,   # SDR job title
    "sender_company_name" : str,   # Sender company -- RAG fetches all details
    "campaign_name"       : str,   # Campaign label -- used to query Qdrant

    "prospect_name"         : str, # Prospect full name
    "prospect_position"     : str, # Prospect job title
    "prospect_company_name" : str, # Prospect company name
    "prospect_company_info" : str, # 1-2 sentence description of prospect company

    "original_outreach" : str,     # The exact body of the mail we already sent
    "followup_count"    : int,     # How many follow-ups already sent (0 = first time)

    "contact_info": {
        "email" : str,             # Prospect email ("" if unavailable)
        "phone" : str,             # Prospect phone ("" if unavailable)
    },

    "manager_notes" : str,         # Optional extra guidance ("" to skip)
}

Channel priority: email > phone (SMS)

OUTPUT SCHEMA  (returned dict)
------------------------------
{
    "outreach_type"  : str,        # "email" | "sms"
    "subject"        : str | None, # Subject line (None for SMS)
    "body"           : str,        # Generated follow-up copy -- ready to send
    "followup_number": int,        # followup_count + 1
    "followup_stage" : str,        # "nudge" | "objection_reframe" | "breakup"
    "stage_label"    : str,        # Human-readable stage label
    "rag_collection" : str,        # Qdrant collection used
}
"""

import os
import re
import sys
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

from qdrant_rag import rag_engine, COLLECTION_COMPANY_ATLASSIAN

# -----------------------------------------------------------------------
# Environment Setup
# -----------------------------------------------------------------------
from groq_utils import get_fallback_groq_llm

llm = get_fallback_groq_llm(
    model="groq/compound",
    temperature=0.3,
    max_tokens=512,
    max_retries=3,
)

# ===========================================================================
# STEP 1 -- GUARDRAILS
# ===========================================================================

_FOLLOWUP_GUARDRAILS = """

==========================  MANDATORY GUARDRAILS  ==========================
[G1 - STRICT RAG GROUNDING]
You MUST base every fact, metric, customer name, product feature, and
integration claim EXCLUSIVELY on the OUR COMPANY KNOWLEDGE section below.
If information is not explicitly stated there, you are FORBIDDEN from
including it. Do NOT invent, infer, or extrapolate any claim.

[G2 - TONE & BANNED PHRASES]
You must NEVER include any of the following phrases or variants thereof:
  - "I hope this email finds you well"
  - "I hope this message finds you well"
  - "Just following up" (as an opener)
  - "Checking in" (as an opener)
  - "In today's fast-paced digital landscape"
  - "I am reaching out because"
  - "As per my last email"
  - "Synergy", "leverage" (as a verb), "paradigm shift"
The tone must be warm, direct, and human -- not robotic or corporate.
The message must feel like a fresh angle, NOT a repeat of the first email.

[G3 - NO COMPETITOR BASHING]
You must NEVER name, reference, compare to, or speak negatively about
any competing product, vendor, or company.
===========================================================================
"""

# ===========================================================================
# STEP 2 -- FOLLOW-UP STAGE LOGIC
# ===========================================================================

def get_followup_stage(followup_count: int) -> tuple:
    """
    Returns (stage_name, stage_label, stage_instruction) based on
    how many follow-ups have already been sent.

    followup_count = 0  ->  1st follow-up (gentle nudge)
    followup_count = 1  ->  2nd follow-up (objection reframe)
    followup_count >= 2 ->  3rd+ follow-up (break-up message)
    """
    if followup_count == 0:
        return (
            "nudge",
            "1st Follow-Up: Gentle Nudge",
            (
                "FOLLOW-UP APPROACH: GENTLE NUDGE (1st follow-up)\n"
                "- The prospect has not replied to the original outreach.\n"
                "- Do NOT repeat the same pitch. Offer a NEW proof point or a different value angle "
                "from the RAG context that was NOT in the original outreach.\n"
                "- Be brief, warm, and conversational. Acknowledge they may be busy.\n"
                "- End with a very low-friction CTA (e.g. 'Would a 10-minute call work this week?').\n"
            ),
        )
    elif followup_count == 1:
        return (
            "objection_reframe",
            "2nd Follow-Up: Objection Reframe",
            (
                "FOLLOW-UP APPROACH: OBJECTION REFRAME (2nd follow-up)\n"
                "- Two messages have gone unanswered. The prospect may have a concern.\n"
                "- Tactfully acknowledge the silence without being passive-aggressive.\n"
                "- Surface and directly address ONE likely objection for their role/company type "
                "(e.g. 'Already have a solution', 'No budget right now', 'Not the right time').\n"
                "- Use a concrete proof point from the RAG context to counter the objection.\n"
                "- Offer a no-commitment, easy next step.\n"
            ),
        )
    else:
        ordinal = f"{followup_count + 1}th"
        return (
            "breakup",
            f"{ordinal} Follow-Up: Break-Up / Last Chance",
            (
                f"FOLLOW-UP APPROACH: BREAK-UP MESSAGE ({ordinal} follow-up)\n"
                "- Multiple messages have gone unanswered. This is the final outreach.\n"
                "- Use a respectful, low-pressure 'break-up' framing that leaves the door open.\n"
                "- Tone example: 'I won't keep filling your inbox -- but if timing ever changes, "
                "I'd love to reconnect. Here is one last thought...'\n"
                "- Include ONE compelling final proof point or insight from the RAG context.\n"
                "- Do NOT be emotional, guilt-tripping, or desperate.\n"
            ),
        )


# ===========================================================================
# STEP 3 -- PROMPTS
# ===========================================================================

def _build_system_prompt(channel: str, stage_instruction: str) -> str:
    """Assembles the system prompt for the given channel and stage."""
    channel_label = "email" if channel == "email" else "SMS text message"
    base = (
        f"You are an expert Sales Development Representative (SDR) writing a follow-up "
        f"{channel_label} to a prospect who has not replied to previous outreach.\n"
    )
    base += _FOLLOWUP_GUARDRAILS

    if channel == "email":
        base += (
            "\nCHANNEL-SPECIFIC CONSTRAINTS (EMAIL):\n"
            "1. Every fact must come from OUR COMPANY KNOWLEDGE below.\n"
            "2. Do NOT use any banned phrases listed in the guardrails above.\n"
            "3. The email body MUST be 100 words or fewer. Trim if needed.\n"
            "4. Clean paragraph breaks -- no bullet points inside the body.\n"
            "5. SIGN-OFF: Low-friction CTA followed by {sender_name}, {sender_role} at {sender_company_name}.\n"
            "6. SUBJECT LINE: 3-5 words. Do NOT say 'Follow Up' or 'Checking In'.\n\n"
        )
    else:
        base += (
            "\nCHANNEL-SPECIFIC CONSTRAINTS (SMS):\n"
            "1. Every fact must come from OUR COMPANY KNOWLEDGE below.\n"
            "2. SMS body MUST be 30 words or fewer.\n"
            "3. Single paragraph, no subject line, conversational.\n"
            "4. End with a soft CTA.\n\n"
        )

    base += stage_instruction
    return base


def _build_human_prompt(channel: str) -> str:
    """Assembles the human turn prompt template."""
    base = (
        "SENDER INFORMATION:\n"
        "  Name    : {sender_name}\n"
        "  Role    : {sender_role}\n"
        "  Company : {sender_company_name}\n"
        "  Summary : {sender_company_info}\n\n"
        "TARGET PROSPECT:\n"
        "  Name    : {prospect_name}\n"
        "  Role    : {prospect_position}\n"
        "  Company : {prospect_company_name}\n"
        "  Summary : {prospect_company_info}\n\n"
        "ORIGINAL OUTREACH WE SENT (do NOT repeat this -- use a fresh angle):\n"
        "---\n"
        "{original_outreach}\n"
        "---\n\n"
        "OUR COMPANY KNOWLEDGE (Retrieved from Qdrant -- ONLY use facts from here):\n"
        "{company_knowledge}\n\n"
        "MANAGER / SDR NOTES (incorporate if present, ignore if empty):\n"
        "{manager_notes}\n\n"
    )

    if channel == "email":
        base += (
            "OUTPUT FORMAT (Follow exactly):\n"
            "Subject: <Subject line>\n\n"
            "<Email Body>"
        )
    else:
        base += (
            "OUTPUT FORMAT (Follow exactly):\n"
            "Message: <SMS Body>"
        )

    return base


# ===========================================================================
# STEP 4 -- PII REDACTOR (Guardrail G4)
# ===========================================================================

_PII_PATTERNS = [
    # Email addresses
    (re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"), "[EMAIL REDACTED]"),
    # User / Account IDs
    (re.compile(r"(?i)\b(?:user|account|customer|client|member)[-_ ]?id\s*[:=#]?\s*[a-zA-Z0-9_\-]+\b"), "[USER ID REDACTED]"),
    # UUIDs
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "[ID REDACTED]"),
    # Phone numbers with separators (e.g. 415-555-1234, (415) 555-1234)
    (re.compile(r"(?:\+?1[\s.\-]?)?\(?[2-9]\d{2}\)?[\s.\-]\d{3}[\s.\-]\d{4}"), "[PHONE REDACTED]"),
    # International E.164 phones
    (re.compile(r"\+\d{10,13}\b"), "[PHONE REDACTED]"),
]


def _redact_pii(text: str) -> str:
    """[Guardrail G4] Strips email addresses, phone numbers, and user IDs from text."""
    if not text:
        return text
    redacted = text
    for pattern, placeholder in _PII_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            print(
                f"[Guardrail G4 - PII Redactor] Redacted {len(matches)} instance(s) -> {placeholder!r}"
            )
            redacted = pattern.sub(placeholder, redacted)
    return redacted


# ===========================================================================
# STEP 5 -- OUTPUT PARSER
# ===========================================================================

def _parse_followup_output(raw_output: str, channel: str) -> dict:
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


# ===========================================================================
# STEP 6 -- CHANNEL SELECTOR
# ===========================================================================

def _determine_channel(contact_info: dict) -> str:
    """Channel priority: email > phone (sms)."""
    if contact_info.get("email"):
        return "email"
    elif contact_info.get("phone"):
        return "sms"
    else:
        raise ValueError(
            "No valid contact info found. Provide at least 'email' or 'phone' in contact_info."
        )


# ===========================================================================
# STEP 7 -- MAIN ENTRY POINT
# ===========================================================================

def generate_followup(payload: dict) -> dict:
    """
    Main entry point for the Follow-Up Agent.

    Parameters
    ----------
    payload : dict
        Must contain: sender_name, sender_role, sender_company_name,
        sender_company_info, prospect_name, prospect_position,
        prospect_company_name, prospect_company_info, original_outreach,
        followup_count (int >= 0), contact_info (dict with email/phone).
        Optional: campaign_name, campaign_context, manager_notes.

    Returns
    -------
    dict
        outreach_type, subject, body, followup_number, followup_stage,
        stage_label, is_first_draft, draft_version, rag_collection.
    """
    required_keys = [
        "sender_name", "sender_role", "sender_company_name", "campaign_name",
        "prospect_name", "prospect_position", "prospect_company_name", "prospect_company_info",
        "original_outreach", "followup_count", "contact_info",
    ]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"[Follow-Up Agent] Missing required keys: {missing}")

    if not isinstance(payload["followup_count"], int) or payload["followup_count"] < 0:
        raise ValueError("[Follow-Up Agent] 'followup_count' must be a non-negative integer.")

    # --- Channel & Stage ---
    channel = _determine_channel(payload["contact_info"])
    print(f"[Follow-Up Agent] Channel selected: {channel.upper()}")

    followup_count = payload["followup_count"]
    stage_name, stage_label, stage_instruction = get_followup_stage(followup_count)
    followup_number = followup_count + 1
    print(f"[Follow-Up Agent] Stage: {stage_label} (follow-up #{followup_number})")

    # --- RAG Retrieval ---
    print("[Follow-Up Agent] Querying Qdrant for company knowledge...")
    company_query = (
        f"{payload['sender_company_name']} value props, proof points, case studies for "
        f"{payload['prospect_company_info']} {payload['prospect_position']}"
    )
    company_hits = rag_engine.search(COLLECTION_COMPANY_ATLASSIAN, company_query, limit=3)
    company_knowledge = "\n\n".join([f"- {h['text']}" for h in company_hits])

    if not company_knowledge:
        company_knowledge = (
            f"(No specific knowledge retrieved. Use general known value propositions "
            f"of {payload['sender_company_name']}.)"
        )
    print(f"[Follow-Up Agent] Retrieved {len(company_hits)} RAG chunk(s) from Qdrant.")

    # --- Build & Run Chain ---
    manager_notes = payload.get("manager_notes", "").strip() or "(none)"
    system_prompt = _build_system_prompt(channel, stage_instruction)
    human_prompt = _build_human_prompt(channel)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_prompt),
    ])
    chain = prompt | llm | StrOutputParser()

    print("[Follow-Up Agent] Generating follow-up copy via Groq LLM...")
    raw_output = chain.invoke({
        "sender_name":            payload["sender_name"],
        "sender_role":            payload["sender_role"],
        "sender_company_name":    payload["sender_company_name"],
        "prospect_name":          payload["prospect_name"],
        "prospect_position":      payload["prospect_position"],
        "prospect_company_name":  payload["prospect_company_name"],
        "prospect_company_info":  payload["prospect_company_info"],
        "original_outreach":      payload["original_outreach"],
        "company_knowledge":      company_knowledge,
        "manager_notes":          manager_notes,
    })

    # --- Parse, Redact, Enrich ---
    result = _parse_followup_output(raw_output, channel)
    result["followup_number"] = followup_number
    result["followup_stage"]  = stage_name
    result["stage_label"]     = stage_label
    result["rag_collection"]  = COLLECTION_COMPANY_ATLASSIAN
    return result


# ===========================================================================
# DEMO / TEST EXECUTION
# ===========================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    BASE_PAYLOAD = {
        "sender_name":            "Jordan Lee",
        "sender_role":            "Enterprise SDR",
        "sender_company_name":    "Atlassian",
        "campaign_name":          "US SaaS Engineering Leaders",
        "prospect_name":          "Marcus Vance",
        "prospect_position":      "VP of Engineering",
        "prospect_company_name":  "CloudScale Systems",
        "prospect_company_info":  "Series B B2B SaaS platform scaling distributed microservices.",
        "original_outreach": (
            "Hi Marcus,\n\n"
            "Atlassian Rovo AI can automate task routing across your sprint cycles. "
            "Over 300,000 customers rely on us for exactly this.\n\n"
            "Worth a brief look next week?\n\nJordan Lee, Enterprise SDR at Atlassian"
        ),
        "contact_info": {"email": "marcus@cloudscalesystems.io", "phone": ""},
        "manager_notes": "",
    }

    for count, label in [(0, "1st Follow-Up"), (1, "2nd Follow-Up"), (2, "3rd / Final")]:
        print(f"\n{'=' * 65}")
        print(f"  TEST: {label}  (followup_count={count})")
        print("=" * 65)
        r = generate_followup({**BASE_PAYLOAD, "followup_count": count})
        print(f"  Stage   : {r['stage_label']}")
        print(f"  Channel : {r['outreach_type'].upper()}")
        print(f"  Subject : {r.get('subject', 'N/A')}")
        print(f"\n  Body:\n{r['body']}\n")

    print("All Follow-Up Agent tests completed!")
