"""
groq_utils.py
=============
Groq API Key Manager & Multi-Key Fallback Engine.

Automatically discovers:
- GROQ_API_KEY1
- GROQ_API_KEY2
- GROQ_API_KEY3
- GROQ_API_KEY (legacy / fallback)

If the primary key runs out of quota, hits a 429 rate limit, or fails,
LangChain's runnable fallback pipeline automatically switches to the next available key
without interrupting or crashing the agent.
"""

import os
from typing import List
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()


def get_all_groq_keys() -> List[str]:
    """
    Returns a list of non-empty, unique Groq API keys in priority order:
    GROQ_API_KEY1 -> GROQ_API_KEY2 -> GROQ_API_KEY3 -> GROQ_API_KEY
    """
    candidate_names = ["GROQ_API_KEY1", "GROQ_API_KEY2", "GROQ_API_KEY3", "GROQ_API_KEY"]
    keys = []
    seen = set()

    for name in candidate_names:
        val = os.environ.get(name, "").strip()
        if val and val not in seen:
            keys.append(val)
            seen.add(val)

    return keys


def get_fallback_groq_llm(
    model: str = "groq/compound",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    max_retries: int = 0,
    timeout: float = 3.0,
):
    """
    Creates a ChatGroq LLM instance with automatic multi-key failover.
    If the primary key hits quota limits or errors, it falls back seamlessly to the next key.
    """
    keys = get_all_groq_keys()
    if not keys:
        raise EnvironmentError(
            "No Groq API keys found in .env! "
            "Please ensure GROQ_API_KEY1, GROQ_API_KEY2, or GROQ_API_KEY is configured."
        )

    llms = [
        ChatGroq(
            model=model,
            api_key=k,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            request_timeout=timeout,
        )
        for k in keys
    ]

    primary_llm = llms[0]
    fallback_llms = llms[1:]

    if fallback_llms:
        return primary_llm.with_fallbacks(fallback_llms)
    return primary_llm
