"""
fitment_agent.py
================
ICP Fitment & Prospect Scoring Agent
Evaluates a list of company websites against user ICP (Ideal Customer Profile) filters.

INPUT FORMAT:
{
    "websites": ["https://example1.com", "https://example2.com"],
    "user_prompt": {
        "user_prompt": "Find me 5 Saas companies",
        "Target_geography": "North America",
        "Company_size_range": "50-200",
        "Industry_filters": "Software",
        "Technology_requirements": "AI",
        "Revenue_or_funding_filters": "Above $1M"
    }
}

OUTPUT FORMAT:
[
    {
        "website": "https://example1.com",
        "meets_criteria": true,
        "description": "Example1 is a leading software company specializing in AI solutions.",
        "evaluation_results": {
            "score_out_of_100": 92,
            "Interest_of_user": true,
            "Target_geography": true,
            "Company_size_range": false,
            "Industry_filters": true,
            "Technology_requirements": true,
            "Revenue_or_funding_filters": true
        },
        "notes": "Company size does not match the specified range."
    }
]
"""

import os
import re
import sys
import json
from typing import List, Dict, Any
from urllib.parse import urlparse
from dotenv import load_dotenv
import requests

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# -----------------------------------------------------------------------
# Environment Setup
# -----------------------------------------------------------------------
from groq_utils import get_fallback_groq_llm

llm = get_fallback_groq_llm(
    model="openai/gpt-oss-120b",
    temperature=0.1,
    max_tokens=800,
    max_retries=3,
)

# ===========================================================================
# WEB CONTENT RETRIEVAL (Live Scrape / Domain Summary)
# ===========================================================================

def fetch_website_summary(url: str, max_chars: int = 1200) -> str:
    """
    Fetches clean text from the target website.
    Returns plain text context summarizing the company's product, mission, and scope.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    text = ""
    if HAS_TRAFILATURA:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
                if extracted:
                    text = extracted.strip()
        except Exception:
            pass

    if not text:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                raw_html = resp.text
                cleaned = re.sub(r"<(script|style).*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
                cleaned = re.sub(r"<[^>]+>", " ", cleaned)
                text = " ".join(cleaned.split())
        except Exception:
            text = f"Website domain: {url}"

    # Clean and truncate
    text = " ".join(text.split())
    return text[:max_chars] if text else f"Website domain: {url}"


# ===========================================================================
# PROMPTS
# ===========================================================================

SYSTEM_PROMPT = """You are an elite B2B Sales Intelligence & Lead Fitment Evaluator Agent.
Your job is to thoroughly evaluate a company against an Ideal Customer Profile (ICP) based on its website data and known web presence.

CRITERIA TO EVALUATE (Strict Boolean true/false):
1. Interest_of_user: Does this company align with the user's primary search intent / prompt? (true/false)
2. Target_geography: Is the company headquartered or operating in the requested target geography? (true/false)
3. Company_size_range: Does the estimated employee headcount match the target range? (true/false)
4. Industry_filters: Does the company operate in the specified industry / vertical? (true/false)
5. Technology_requirements: Does the company offer, use, or build the required technologies? (true/false)
6. Revenue_or_funding_filters: Does the company meet the specified revenue/funding stage? (true/false)

SCORING RULES (score_out_of_100):
- Calculate a score between 0 and 100 based on overall alignment:
  * Interest_of_user match: 25 pts
  * Industry_filters match: 20 pts
  * Technology_requirements match: 20 pts
  * Target_geography match: 15 pts
  * Company_size_range match: 10 pts
  * Revenue_or_funding_filters match: 10 pts
- meets_criteria: Set to true if score_out_of_100 >= 65, else false.

OUTPUT FORMAT REQUIREMENTS:
- You MUST return ONLY a single valid JSON object representing the evaluation of the company.
- Do NOT include markdown code fences (no ```json or ```).
- Follow this exact JSON structure:
{
  "website": "https://example.com",
  "meets_criteria": true,
  "description": "1-2 concise sentences describing what the company does and its core offering.",
  "evaluation_results": {
    "score_out_of_100": 92,
    "Interest_of_user": true,
    "Target_geography": true,
    "Company_size_range": false,
    "Industry_filters": true,
    "Technology_requirements": true,
    "Revenue_or_funding_filters": true
  },
  "notes": "Concise 1-sentence note explaining what matched or why any criteria failed."
}
"""

USER_EVALUATION_PROMPT = """EVALUATE THIS COMPANY:
Target Website: {website}

LIVE WEBSITE & INDUSTRY DATA:
{website_content}

USER ICP CRITERIA:
- User Prompt / Goal: {user_prompt_text}
- Target Geography: {target_geography}
- Company Size Range: {company_size_range}
- Industry Filters: {industry_filters}
- Technology Requirements: {technology_requirements}
- Revenue / Funding Filters: {revenue_filters}

Return ONLY the raw JSON object.
"""

# ===========================================================================
# AGENT RUNNER
# ===========================================================================

def evaluate_single_company(
    url: str,
    user_prompt_text: str,
    target_geography: str,
    company_size_range: str,
    industry_filters: str,
    technology_requirements: str,
    revenue_filters: str
) -> Dict[str, Any]:
    """Evaluates a single company website against ICP filters."""
    print(f"[Fitment Agent] Gathering web intelligence for: {url}...")
    web_content = fetch_website_summary(url)

    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessagePromptTemplate.from_template(USER_EVALUATION_PROMPT),
    ])

    chain = prompt | llm | StrOutputParser()

    raw_output = chain.invoke({
        "website": url,
        "website_content": web_content,
        "user_prompt_text": user_prompt_text,
        "target_geography": target_geography,
        "company_size_range": company_size_range,
        "industry_filters": industry_filters,
        "technology_requirements": technology_requirements,
        "revenue_filters": revenue_filters,
    })

    cleaned = raw_output.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        data["website"] = url
        return data
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                data["website"] = url
                return data
            except Exception:
                pass
        print(f"[Warning] Failed to parse JSON. Raw LLM output was:\n{raw_output}\n")
        return {
            "website": url,
            "meets_criteria": False,
            "description": "Failed to parse evaluation response.",
            "evaluation_results": {
                "score_out_of_100": 0,
                "Interest_of_user": False,
                "Target_geography": False,
                "Company_size_range": False,
                "Industry_filters": False,
                "Technology_requirements": False,
                "Revenue_or_funding_filters": False,
            },
            "notes": "Error parsing LLM response."
        }


def evaluate_fitment(payload: dict) -> List[Dict[str, Any]]:
    """
    Main entry point for Fitment Agent.
    Evaluates a list of websites against user ICP criteria.

    Parameters:
    -----------
    payload : dict
        {
            "websites": ["https://...", ...],
            "user_prompt": {
                "user_prompt": "...",
                "Target_geography": "...",
                "Company_size_range": "...",
                "Industry_filters": "...",
                "Technology_requirements": "...",
                "Revenue_or_funding_filters": "..."
            }
        }

    Returns:
    --------
    List[Dict[str, Any]]
        Exact format requested.
    """
    websites = payload.get("websites", [])
    if not websites:
        return []

    # Normalize website URLs if passed as dicts or strings
    normalized_urls = []
    for w in websites:
        if isinstance(w, dict):
            normalized_urls.append(w.get("url") or w.get("website_url") or "")
        elif isinstance(w, str):
            normalized_urls.append(w)

    user_prompt_data = payload.get("user_prompt", {})

    user_prompt_text = (
        user_prompt_data.get("user_prompt")
        or user_prompt_data.get("raw_query")
        or "Evaluate fitment"
    )
    target_geography = (
        user_prompt_data.get("Target_geography")
        or user_prompt_data.get("location")
        or "Not specified"
    )
    company_size_range = (
        user_prompt_data.get("Company_size_range")
        or user_prompt_data.get("company_size")
        or "Not specified"
    )
    industry_filters = (
        user_prompt_data.get("Industry_filters")
        or user_prompt_data.get("industry")
        or "Not specified"
    )
    technology_requirements = (
        user_prompt_data.get("Technology_requirements")
        or user_prompt_data.get("technology")
        or "Not specified"
    )
    revenue_filters = (
        user_prompt_data.get("Revenue_or_funding_filters")
        or str(user_prompt_data.get("minimum_revenue", "Not specified"))
    )

    results = []
    for url in normalized_urls:
        if not url:
            continue
        eval_result = evaluate_single_company(
            url=url,
            user_prompt_text=user_prompt_text,
            target_geography=target_geography,
            company_size_range=company_size_range,
            industry_filters=industry_filters,
            technology_requirements=technology_requirements,
            revenue_filters=revenue_filters,
        )
        results.append(eval_result)

    return results


# ===========================================================================
# DEMO EXECUTION
# ===========================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sample_input = {
        "websites": [
            "https://n8n.io"
        ],
        "user_prompt": {
            "user_prompt": "Find me 5 Saas companies",
            "Target_geography": "North America",
            "Company_size_range": "50-200",
            "Industry_filters": "Software",
            "Technology_requirements": "AI",
            "Revenue_or_funding_filters": "Above $1M"
        }
    }

    print("=" * 70)
    print("RUNNING FITMENT AGENT EVALUATION DEMO")
    print("=" * 70)
    results = evaluate_fitment(sample_input)
    print("\nFINAL OUTPUT JSON:")
    print(json.dumps(results, indent=2))
