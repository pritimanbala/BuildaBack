import strawberry
from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from .database import SessionLocal
from strawberry.types import Info
from .models import User
from .security import clear_auth_cookie, get_user_id_from_request, hash_password, set_auth_cookie, verify_password


@strawberry.type
class UserType:
    id: strawberry.ID
    email: str
    name: str | None
    role: str


def as_type(user: User) -> UserType:
    return UserType(id=str(user.id), email=user.email, name=user.name, role=user.role)


async def get_context(request: Request, response: Response):
    return {"request": request, "response": response}

@strawberry.type
class Query:

    @strawberry.field
    def me(self, info: Info) -> UserType:
        user_id = get_user_id_from_request(info.context["request"])

        with SessionLocal() as db:
            user = db.get(User, user_id)

            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated"
                )

            return as_type(user)

@strawberry.type
class Mutation:
    @strawberry.mutation
    def sign_up(self, info: Info, email: str, password: str, name: str | None = None, role: str = "EXE") -> UserType:
        if len(password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
        if role not in {"ADMIN", "EXE"}:
            raise HTTPException(status_code=422, detail="Role must be ADMIN or EXE")
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.email == email.lower())):
                raise HTTPException(status_code=409, detail="Email is already registered")
            user = User(email=email.lower(), name=name, role=role, hashed_password=hash_password(password))
            db.add(user)
            db.commit()
            db.refresh(user)
            set_auth_cookie(info.context["response"], user.id)
            return as_type(user)

    @strawberry.mutation
    def sign_in(self, info: Info, email: str, password: str) -> UserType:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email.lower()))
            if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
                raise HTTPException(status_code=401, detail="Incorrect email or password")
            set_auth_cookie(info.context["response"], user.id)
            return as_type(user)

    @strawberry.mutation
    def sign_out(self, info: Info) -> bool:
        clear_auth_cookie(info.context["response"])
        return True


schema = strawberry.Schema(query=Query, mutation=Mutation)
