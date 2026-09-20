# Buildathon FastAPI backend

FastAPI authentication service backed by PostgreSQL. It supports email/password signup and signin, JWTs stored in HttpOnly cookies, Google OAuth, and GraphQL.

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

