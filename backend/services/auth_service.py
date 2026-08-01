"""Authentication service — login and JWT token generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from core.deps import create_access_token

# Demo users (hardcoded for development)
DEMO_USERS: dict[str, str] = {
    "trader": "trader123",
}


def authenticate(username: str, password: str) -> dict:
    """Validate credentials and return a JWT token.

    Args:
        username: Demo username.
        password: Demo password.

    Returns:
        Dict with ``token`` and ``expires_at`` (ISO format, 24h from now).

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    if DEMO_USERS.get(username) != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token({"sub": username})
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    return {"token": token, "expires_at": expires_at}
