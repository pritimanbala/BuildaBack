# Buildathon FastAPI backend

FastAPI authentication service backed by PostgreSQL. It supports email/password signup and signin, JWTs stored in HttpOnly cookies, Google OAuth, and GraphQL.

## Setup

1. Create a PostgreSQL database, then copy `.env.example` to `.env` and replace every placeholder.
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

Tables are created automatically on first startup. Open `http://localhost:8000/docs` for REST documentation and `http://localhost:8000/graphql` for GraphQL IDE.

## REST API

- `POST /api/auth/signup` — `{ "email", "password", "name?" }`
- `POST /api/auth/signin` — `{ "email", "password" }`
- `POST /api/auth/signout`
- `GET /api/auth/me`
- `GET /api/auth/google` — redirect the browser here to start Google sign-in.

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
