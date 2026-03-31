"""
Google OAuth 2.0 authentication for admin access.
Restricts login to allowlisted email addresses.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AdminSession

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_DURATION_HOURS = 24 * 7  # 1 week
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_admin_session(
    admin_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AdminSession:
    """
    FastAPI dependency — validates admin session cookie.
    Raises 401 if not authenticated, 403 if not authorized.
    """
    if not admin_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = _hash_token(admin_token)
    session = (
        db.query(AdminSession)
        .filter(
            AdminSession.token_hash == token_hash,
            AdminSession.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return session


def get_admin_session_optional(
    admin_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AdminSession | None:
    """Like get_admin_session but returns None instead of raising if not authenticated."""
    if not admin_token:
        return None
    token_hash = _hash_token(admin_token)
    return (
        db.query(AdminSession)
        .filter(
            AdminSession.token_hash == token_hash,
            AdminSession.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )


@router.get("/google")
def google_login(request: Request):
    """Redirects to Google OAuth consent screen."""
    settings = get_settings()
    state = secrets.token_urlsafe(32)

    # Store state in a temporary cookie for CSRF protection
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    response = RedirectResponse(url=auth_url)
    response.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="lax")
    return response


@router.get("/callback")
def google_callback(
    code: str,
    state: str,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    oauth_state: str | None = Cookie(default=None),
):
    """Handles Google OAuth callback, creates admin session."""
    settings = get_settings()

    # Validate CSRF state
    if not oauth_state or state != oauth_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for tokens
    token_data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }

    try:
        token_response = httpx.post(GOOGLE_TOKEN_URL, data=token_data, timeout=10)
        token_response.raise_for_status()
        tokens = token_response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {e}")

    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=500, detail="No access token received")

    # Get user info
    try:
        userinfo_response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Userinfo fetch failed: {e}")

    email = userinfo.get("email", "").lower()

    # Check allowlist
    if email not in settings.admin_email_list:
        raise HTTPException(status_code=403, detail="Access denied: email not authorized")

    # Create session
    session_token = secrets.token_urlsafe(64)
    token_hash = _hash_token(session_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)

    # Clean up old sessions for this email
    db.query(AdminSession).filter(AdminSession.email == email).delete()

    session = AdminSession(
        email=email,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    redirect = RedirectResponse(url="/admin.html", status_code=302)
    redirect.set_cookie(
        "admin_token",
        session_token,
        max_age=SESSION_DURATION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
    )
    # Clear the state cookie
    redirect.delete_cookie("oauth_state")
    return redirect


@router.post("/logout")
def logout(
    response: Response,
    admin_session: AdminSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
):
    """Invalidates the admin session."""
    db.delete(admin_session)
    db.commit()
    response.delete_cookie("admin_token")
    return {"message": "Logged out"}


@router.get("/me")
def get_me(admin_session: AdminSession = Depends(get_admin_session)):
    """Returns current admin user info."""
    return {"email": admin_session.email, "expires_at": admin_session.expires_at}
