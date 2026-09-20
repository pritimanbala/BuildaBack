# Buildathon FastAPI backend

FastAPI authentication service backed by PostgreSQL. It supports email/password signup and signin, JWTs stored in HttpOnly cookies, Google OAuth, and GraphQL.

> **📖 This README is organized in two parts:**
> **Part 1 — Software** (backend, database, API) and **Part 2 — AI Agents** (the autonomous SDR agent layer). Scroll to the **⚙️ ➜ 🧠 From Software to Intelligence** divider below to jump straight to the AI section.

## Setup

1. Create a PostgreSQL database (e.g. on **Neon** serverless Postgres or local PostgreSQL), then copy `.env.example` to `.env` and replace every placeholder.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Run the server from this folder:

   ```powershell
   uvicorn app.main:app --reload
   ```

Tables are created automatically on first startup via SQLAlchemy `Base.metadata.create_all()`. Open `http://localhost:8000/docs` for REST documentation and `http://localhost:8000/graphql` for GraphQL IDE.

---

## SQLAlchemy & Neon PostgreSQL (The 2nd hardest part)

This was one of the hardest part because we needed to include so many things at once, thats why we should use ORM like sqlalchemy and also it should be hosted somewhere so Neon Postgres is one of the best free option we have.

The backend uses **SQLAlchemy 2.0 (Mapped / Declarative)** alongside PostgreSQL native features (`pgcrypto` for UUID generation, `ARRAY`, and `JSONB` data types).

### Neon PostgreSQL Configuration
Set your Neon connection string in `.env`:
```env
DATABASE_URL=postgresql://<user>:<password>@<neon-hostname>/<dbname>?sslmode=require
```

- **Connection Pooling**: Uses `pool_pre_ping=True` in `create_engine` to handle serverless connection drops seamlessly.
- **UUID & Timestamps**: Primary keys use native PostgreSQL UUID (`gen_random_uuid()`) with timezone-aware `TIMESTAMPTZ` columns.
- **Automatic Migrations & Extensions**: On startup, the `lifespan` handler runs `CREATE EXTENSION IF NOT EXISTS pgcrypto` and ensures schema compatibility.

---

## Database Tables & Schema Structure

The database schema is organized into 6 core domains:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATABASE SCHEMA                                │
├─────────────────┬──────────────────┬─────────────────┬──────────────────────┤
│ 1. Identity &   │ 2. Campaigns &   │ 3. Accounts &   │ 4. Messaging &       │
│    Access       │    Orchestration │    Leads        │    Voice             │
├─────────────────┼──────────────────┼─────────────────┼──────────────────────┤
│ • users         │ • campaigns      │ • companies     │ • conversations      │
│ • system_setting│ • campaign_member│ • contacts      │ • messages           │
│ • audit_logs    │ • campaign_channe│ • campaign_conta│ • drafts             │
│                 │ • agents         │ • suppressions  │ • approvals          │
│                 │ • campaign_agents│                 │ • call_logs          │
│                 │ • prompt_versions│                 │                      │
│                 │ • agent_runs     │                 │                      │
└─────────────────┴──────────────────┴─────────────────┴──────────────────────┘
```

### 1. Identity & Access Control
- **`users`**: Platform users including Admins, Managers, and Sales Executives.
  - *Key columns*: `id` (UUID PK), `email` (unique), `hashed_password`, `google_id`, `name`, `role` (`ADMIN` | `EXECUTIVE`), `daily_limit`, `working_hours` (JSON), `channel_access` (ARRAY).
  - *Relationships*: Owns campaigns, has memberships, assigned contacts, and sent messages.
- **`system_settings`**: Key-value JSON store for global flags like `global_kill_switch`, app configurations, and shared queues.
- **`audit_logs`**: Tamper-evident actor and entity change audit logs (`actor_id`, `entity_type`, `entity_id`, `before`, `after`, `created_at`).

### 2. Campaigns & Multi-Agent Orchestration
- **`campaigns`**: Core autonomous outreach campaign definition.
  - *Key columns*: `id`, `name`, `description`, `objective`, `status` (`DRAFT`, `LIVE`, `PAUSED`, `COMPLETED`, `ARCHIVED`), `target_roles` (ARRAY), `geography` (ARRAY), `icp` (JSONB), `daily_limit`, `requires_approval`.
- **`campaign_members`**: Assigns sales executives/reps to specific campaigns with custom daily limits and sender identities (`role_in_campaign`: `OWNER`, `MANAGER`, `REP`).
- **`campaign_channels`**: Channel-level switchboard (`EMAIL`, `LINKEDIN`, `SMS`, `VOICE`) with individual pause states and rate limits.
- **`agents`**: Catalog of AI agent types (`ICP_FITMENT`, `LEAD_RESEARCH`, `OUTREACH_STRATEGY`, `PERSONALISATION`, `CONVERSATION`, `VOICE_SDR`, `FOLLOW_UP`).
- **`campaign_agents`**: Per-campaign configuration, enabling/disabling individual sub-agents, model overrides, and hyperparameter tuning.
- **`prompt_versions`**: Versioned system instructions and prompt templates per agent and campaign with lineage tracking.
- **`agent_runs`**: Execution log of every agent invocation tracking input/output context, status (`QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, `ESCALATED`), token usage, cost (USD), and latency (ms).

### 3. Accounts, Contacts & Lifecycle Stages
- **`companies`**: Target organizations enriched with industry, size range, LinkedIn URL, location, and AI enrichment payloads.
- **`contacts`**: Individual prospect profiles with first/last name, job title, email, phone, timezone, and company link.
- **`campaign_contacts`**: Links prospects to campaigns and tracks SDR lifecycle stage progression:
  - *Stages*: `DISCOVERED` → `RESEARCHED` → `QUALIFIED` → `CONTACTED` → `ENGAGED` → `MEETING` → `OPPORTUNITY` (or `REJECTED` / `UNSUBSCRIBED`).
  - *Scores*: `icp_score` (Numeric), `icp_reasoning`, `research_summary` (JSONB), `assigned_user_id`, `next_action_at`.
- **`suppression_entries`**: Do-Not-Contact lists across emails, domains, phone numbers, and LinkedIn handles.

### 4. Communication & Voice Logs
- **`conversations`**: Multi-channel thread headers linked to a `campaign_contact` (`channel`, `subject`, `external_thread_id`, `is_open`).
- **`messages`**: Individual inbound/outbound communication units with direction (`INBOUND` / `OUTBOUND`), delivery timestamps, and sender attribution.
- **`drafts`**: AI-generated message copy awaiting human review (`status`: `PENDING_REVIEW`, `EXEC_EDITED`, `APPROVED`, `REJECTED`, `SENT`).
- **`approvals`**: Manager approval decisions on message drafts with timestamped review notes.
- **`call_logs`**: Autonomous Voice SDR phone call records (`duration_seconds`, `transcript`, `summary`, `outcome`: `CONNECTED`, `INTERESTED`, `NOT_INTERESTED`, `CALLBACK`, `ESCALATED`, and `recording_url`).
- **`evaluations`**: Quality control benchmarks and LLM-as-a-judge score cards for agent outputs.

---

## REST API

- **Authentication**
  - `POST /api/auth/signup` — `{ "email", "password", "name?", "role?" }`
  - `POST /api/auth/signin` — `{ "email", "password" }`
  - `POST /api/auth/signout`
  - `GET /api/auth/me`
  - `GET /api/auth/google` — redirect browser for Google OAuth sign-in.
- **Campaigns**
  - `GET /api/campaigns` — list all campaigns with contact counts & filters
  - `POST /api/campaigns` — create new campaign
  - `GET /api/campaigns/{id}` — get campaign details
  - `PUT /api/campaigns/{id}` — update campaign configuration
  - `PATCH /api/campaigns/{id}/status` — change campaign status (`LIVE`, `PAUSED`, `DRAFT`)
  - `DELETE /api/campaigns/{id}` — delete campaign
- **Analytics**
  - `GET /api/analytics/overview` — aggregated KPI stats, trends, comparison, and team metrics
  - `GET /api/analytics/team` — sales team & representative performance breakdown
  - `GET /api/analytics/trend` — multi-campaign performance curves over time
  - `GET /api/analytics/comparison` — campaign-level grouped metric comparisons
- **Conversations & Escalations**
  - `GET /api/conversations/summary`
  - `GET /api/conversations/recent`
  - `GET /api/conversations/escalations`
  - `POST /api/conversations/{id}/takeover`
  - `POST /api/conversations/{id}/resolve`
- **Settings & Controls**
  - `GET /api/settings` & `PUT /api/settings`
  - `GET /api/system/kill-switch` & `POST /api/system/kill-switch`

The browser frontend must send cookies: `fetch(url, { credentials: 'include' })` or Axios `{ withCredentials: true }`.

## GraphQL

Example mutation:

```graphql
mutation {
  signUp(email: "user@example.com", password: "password123", name: "User") { id email name }
}
```

Other operations: `signIn`, `signOut`, and `me`. GraphQL mutations also send the auth cookie.

## Google Cloud Console

Create an OAuth 2.0 Web Application client and add the exact `GOOGLE_REDIRECT_URI` from `.env` (for local development: `http://localhost:8000/api/auth/google/callback`) as an authorized redirect URI. Place the client ID and secret in `.env`; never commit that file.





---

<div align="center">

## ⚙️ ➜ 🧠 From Software to Intelligence

**Everything above this line is the platform. Everything below is the brain.**

The following section covers the **Autonomous AI Agent Layer** — the multi-agent system that turns the application above into a self-operating SDR: sourcing leads, scoring them, writing outreach, reading replies, and following up, without a human touching a keyboard.

---

## Agent Handbook

For the full I/O contract of every agent — exact request/response JSON, webhook URLs, scoring rubrics, and the reasoning behind each design decision — see the complete reference document:

**➡️ [Agent Handbook (PDF)](https://drive.google.com/file/d/1rjU5eD2KrHV9xSL7e-IVOnAnRF_usBjv/view?usp=sharing)**

*If hosted in this repo instead of externally, use a relative path, e.g. `docs/Agent_Handbook.pdf`.*

</div>

---

# AI Agent Layer — Autonomous SDR Intelligence

## Why Multi-Agent, Not One Big Prompt?

A single monolithic LLM call cannot reliably do lead scoring, outreach writing, reply triage, and follow-up cadence at once — the context, the failure modes, and the guardrails needed for each task are fundamentally different. So instead of one god-prompt, this layer is built as **six specialized agents**, each with a narrow job, its own prompt contract, its own JSON schema, and its own guardrails — chained together with **LangChain LCEL** so the output of one agent becomes verified, structured input for the next.

This was a deliberate architectural choice:
- **Narrow responsibility → higher accuracy.** A fitment-scoring prompt doesn't also have to know how to write a break-up email.
- **Composable pipeline.** Any single agent can be swapped, re-prompted, or re-scored without touching the rest of the system.
- **Debuggable & auditable.** Every agent emits structured JSON, so a failure is traceable to one exact stage, not buried inside a giant chain-of-thought.
- **Grounded, not generative-for-generative's-sake.** Every agent that produces prospect-facing text is forced to pull from **Qdrant RAG** rather than the model's parametric memory — this is what makes the outreach *zero-hallucination* instead of just "sounds plausible."

---

## The Agent Pipeline, In Depth

### 1️⃣ Company Discovery Agent — *Built on DronaHQ*

**The problem it solves:** A user shouldn't have to manually go find 50 company websites that match "AI infra startups in the Bay Area." That's the single most tedious, low-leverage task in SDR work — so it's the first thing to automate.

**How it works:** Takes a high-level, natural-language ICP query and decomposes it into targeted web searches, resolving real company domains rather than generic search snippets. It hands off a clean list of raw candidate URLs — no scoring, no judgment yet, just discovery — to keep this agent fast and cheap to run at scale.

**Why it's a separate agent:** Discovery is a *breadth* problem (cast a wide net) while scoring is a *depth* problem (evaluate one company thoroughly). Merging them would force every discovery call to pay the token cost of deep evaluation.

---

### 2️⃣ ICP Fitment & Lead Scoring Agent — *Built with Langchain* (`fitment_agent.py`)

**The problem it solves:** Not every company that shows up is worth pursuing. Someone has to *actually check the website* and decide — not guess.

**How it works:**
1. Receives raw domains + the user's ICP definition (geography, size, industry, tech stack, funding).
2. **Live-scrapes the real website** (Trafilatura/HTTP) — this agent never scores off a name or a guess, it reads the actual page.
3. Runs a **weighted 6-factor rubric** against the scraped content:

| Criterion | Weight | What it's really checking |
|---|---|---|
| `Interest_of_user` | 25 pts | Does this company's stated focus actually match campaign intent? |
| `Industry_filters` | 20 pts | Vertical match against required industries |
| `Technology_requirements` | 20 pts | Detected tech stack / AI capability signals |
| `Target_geography` | 15 pts | HQ / operational footprint |
| `Company_size_range` | 10 pts | Headcount band |
| `Revenue_or_funding_filters` | 10 pts | Funding stage / financial tier |

4. Outputs a hard **0–100 score**, a boolean `meets_criteria` gate at **≥ 65**, a 1–2 sentence summary, and a written audit trail explaining *why* each sub-score landed where it did.

**Why it's designed this way:** A binary yes/no from an LLM is a black box you can't trust or debug. A **weighted, auditable rubric** turns lead qualification into something a sales manager can actually inspect and tune — this agent is built to be *accountable*, not just "smart."

---

### 3️⃣ Contact Enrichment Agent — *the finder*

**The problem it solves:** A qualified *company* isn't a lead — a qualified *person* is. This agent closes that gap.

**How it works:** Inspects the qualified company's web presence for individuals holding the target persona (e.g. "VP of Engineering"), and extracts a structured contact payload — full name, title, work email, phone — ready to hand straight into outreach with zero manual lookup.

**Why it's a separate agent:** Contact extraction requires a different scanning strategy (people/team pages, leadership bios) than fitment scoring does (product/pricing pages) — separating them keeps each agent's scraping and prompt focused on what it's actually looking for.

---

### 4️⃣ Autonomous Cold Outreach Agent — *the writer* (`outreach_agent.py`)

**The problem it solves:** Generic outreach doesn't convert, and hallucinated outreach is worse — it burns trust and violates compliance. This agent has to be persuasive *and* provably grounded.

**How it works:**
- **Dynamic channel routing**: automatically picks the highest-signal channel available — `email → phone (SMS) → LinkedIn` — so no lead goes untouched just because one contact field is empty.
- **Qdrant Campaign RAG**: before writing a single word, it queries the vector store for campaign-specific proof points, ROI metrics, and persona-matched case studies — so every claim in the message is retrievable, cited knowledge, not invention.
- **Human-in-the-loop revision**: a rep can say "make this shorter" or "lead with the ROI stat" and the agent revises *without* losing prior context or violating guardrails — this was intentionally built so the AI augments a rep's judgment instead of replacing their final say.

**Why it's designed this way:** This is the single highest-risk agent in the pipeline — it's the one actually talking to a real human prospect. It was built RAG-first specifically so the model is *structurally incapable* of fabricating a customer name or a fake statistic — it can only say what's in the knowledge base.

---

### 5️⃣ Inbound Reply & Decision Agent — *the listener* (`reply_agent.py`)

**The problem it solves:** A prospect's reply carries intent, tone, and sometimes a legal obligation (opt-out) — treating every reply the same is both bad sales and a compliance risk.

**How it works:** Classifies every inbound reply into one of five intents, then drafts an appropriate, context-aware counter-reply — never a generic template.

| Intent | What triggers it |
|---|---|
| `MEETING_REQUEST` / `POSITIVE` | Interest expressed, or a meeting time proposed |
| `OBJECTION` | Friction voiced — *"too expensive," "already using a competitor," "not right now"* |
| `INFORMATION_REQUEST` | A technical or capability question |
| `UNSUBSCRIBE_OPT_OUT` | An explicit removal request |
| `NOT_INTERESTED` | A soft rejection, no explicit opt-out |

Critically, `UNSUBSCRIBE_OPT_OUT` detection **automatically flags the contact for the CRM's Do-Not-Contact list and suppresses all further pitching** — this isn't a nice-to-have, it's a compliance guardrail baked directly into the intent classifier, not bolted on afterward.

**Why it's designed this way:** Objection handling, meeting booking, and legal opt-out are three completely different downstream actions — routing them through one classifier first means the *right* action always happens automatically, with no chance of a human forgetting to update a suppression list.

---

### 6️⃣ Autonomous Follow-Up Cadence Agent — *the closer* (`followup_agent.py`)

**The problem it solves:** Most follow-up sequences are the same email sent three times with a subject-line change — which is why prospects tune them out. A good SDR *advances the narrative* with every touch. So does this agent.

**How it works — a genuine 3-stage narrative arc, not a repeat loop:**

| Stage | Trigger | What actually happens |
|---|---|---|
| **1 · Gentle Nudge** | `followup_count: 0` | Acknowledges the prospect is busy, then pulls a **fresh** RAG proof point — one *not* present in the original message — and closes with a low-friction CTA |
| **2 · Objection Reframe** | `followup_count: 1` | Proactively anticipates the *unvoiced* friction for that specific role (e.g. a VP Eng worries about implementation bandwidth) and reframes with customer proof data |
| **3 · Break-Up** | `followup_count ≥ 2` | Respectfully closes the thread, removes all sales pressure, and leaves the door open for future contact |

**Why it's designed this way:** Each stage queries Qdrant for a *different angle* of context, so the agent is structurally prevented from just re-sending the same pitch — the progression from nudge → reframe → break-up mirrors what a genuinely thoughtful human SDR does, and it's why leads don't go cold from repetition fatigue.

---

##  Guardrails Are Part of the Architecture, Not an Afterthought

Every agent above runs through the same four non-negotiable checks before anything reaches a prospect:

| ID | Guardrail | Why it exists |
|---|---|---|
| **G1** | Anti-Hallucination & Strict Grounding | Every claim must trace back to retrieved Qdrant context — this is what makes "zero-hallucination outreach" a real property of the system, not a marketing line |
| **G2** | Tone & Anti-Cliché Filter | Programmatically bans SDR-spam phrases (*"I hope this email finds you well," "just following up," "synergy," "leverage"*) so messages read human, not templated |
| **G3** | Zero Competitor Bashing | Prompts are structurally forbidden from naming or disparaging competitors — outreach stays value-prop focused, which is both better sales practice and lower legal risk |
| **G4** | PII & Sensitive Data Redaction | Post-generation regex catches and masks SSNs and card numbers before anything is sent, as a last-line safety net |

---

## Why This Was Built on Groq + Qdrant + LangChain LCEL

- **Groq** was chosen for inference speed — a multi-agent pipeline (discover → score → enrich → write → route → follow up) makes *many* sequential LLM calls per lead, and latency compounds fast. Groq keeps the whole chain fast enough to feel real-time.
- **Multi-key failover (`groq_utils.py`)** was built because a live demo — or a live sales team — going down mid-pipeline because of a rate limit is unacceptable. `RunnableWithFallbacks` silently rotates across `GROQ_API_KEY1 → 2 → 3` with **zero lost state**.
- **Qdrant + FastEmbed (`bge-small-en-v1.5`)** was chosen specifically because it runs **fully locally with no external embedding API key** — meaning the RAG grounding layer that every guardrail depends on has no external point of failure and no added cost per embedding call.
- **LangChain LCEL** ties all six agents into one declarative, composable chain — so the system is genuinely a *pipeline*, not six disconnected scripts glued together with manual JSON parsing.

---

<div align="center">

*Six agents. One pipeline. Zero hallucinations. A full sales cycle, run autonomously.*

</div>
