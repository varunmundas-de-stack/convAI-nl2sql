from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.security.auth import authenticate_user, create_access_token, get_current_user
from app.security.context import UserContext


router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(request: LoginRequest):
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return {"access_token": create_access_token(user), "user": user.profile()}


@router.post("/auth/logout")
async def logout():
    return {"success": True}


@router.get("/auth/me")
async def me(user: Annotated[UserContext, Depends(get_current_user)]):
    return {"user": user.profile()}
