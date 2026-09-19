from contextlib import asynccontextmanager
from typing import Literal
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from strawberry.fastapi import GraphQLRouter
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine, get_db
from .graphql import get_context, schema
from .models import User
from .schemas import SignInRequest, SignUpRequest, UserResponse
from .security import clear_auth_cookie, get_user_id_from_request, hash_password, set_auth_cookie, verify_password

settings = get_settings()
oauth = OAuth()
if settings.google_client_id and settings.google_client_secret:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    # `create_all` does not add columns to a table created by an earlier version.
    # This keeps the existing `users` table compatible with the new role field.
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid()"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(10) NOT NULL DEFAULT 'EXE'"))
    yield


app = FastAPI(title="Buildathon API", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key, https_only=settings.cookie_secure)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = db.get(User, get_user_id_from_request(request))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignUpRequest, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")
    user = User(email=email, name=payload.name, role=payload.role, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    set_auth_cookie(response, user.id)
    return user


@app.post("/api/auth/signin", response_model=UserResponse)
def signin(payload: SignInRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    set_auth_cookie(response, user.id)
    return user


@app.post("/api/auth/signout", status_code=status.HTTP_204_NO_CONTENT)
def signout(response: Response):
    clear_auth_cookie(response)


@app.get("/api/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/auth/google")
async def google_login(request: Request, role: Literal["ADMIN", "EXE"] = "EXE"):
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_redirect_uri:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    request.session["google_signup_role"] = role
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    token = await oauth.google.authorize_access_token(request)
    profile = token.get("userinfo") or await oauth.google.userinfo(token=token)
    email, google_id = profile.get("email"), profile.get("sub")
    if not email or not google_id or not profile.get("email_verified", False):
        raise HTTPException(status_code=400, detail="Google did not provide a verified email")
    signup_role = request.session.pop("google_signup_role", "EXE")
    user = db.scalar(select(User).where(User.google_id == google_id)) or db.scalar(select(User).where(User.email == email.lower()))
    if user:
        user.google_id = google_id
        if not user.name:
            user.name = profile.get("name")
    else:
        user = User(email=email.lower(), name=profile.get("name"), google_id=google_id, role=signup_role)
        db.add(user)
    db.commit()
    db.refresh(user)
    response = RedirectResponse(settings.frontend_url, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, user.id)
    return response
