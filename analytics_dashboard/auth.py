from __future__ import annotations

import hashlib
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)


def create_auth_dependency(password: str):
    async def verify_auth(
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> None:
        if not password:
            return
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )
        is_match = hashlib.compare_digest(credentials.password.encode(), password.encode())
        if not is_match:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    return verify_auth
