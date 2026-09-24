"""The Battle.net link: a proof that a member owns a tag, never a login.

The member asks for the Blizzard authorize URL, Blizzard sends the browser
back to the callback, and the callback sends the browser to the profile page
with a signed link token. The profile page posts that token under the
member's own login, and only that write records the account on the tag.
"""

import os
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.api.deps import RequireLogin, UserServiceDep, require_login
from app.api.routes.users import _discord_id
from app.core.config import frontend_url
from app.core.exceptions import ApiError
from app.core.security import create_access_token, decode_token
from app.models.user import UserPublic
from app.models.user_battle_tag import BnetFinishWrite

router = APIRouter(tags=["battlenet"])

OAUTH_URL = "https://oauth.battle.net"
STATE_KIND = "bnet_state"
LINK_KIND = "bnet_link"


def _read_token(token: str, kind: str) -> str | None:
    """The subject of a signed token of this kind, or None."""
    try:
        claims = decode_token(token)
    except jwt.InvalidTokenError:
        return None
    return str(claims["sub"]) if claims.get("type") == kind else None


def _callback_url(request: Request) -> str:
    """This backend's callback; Vercel names the public scheme in x-forwarded-proto."""
    url = request.url_for("battlenet_callback")
    return str(url.replace(scheme=request.headers.get("x-forwarded-proto", url.scheme)))


def _exchange_code(code: str, redirect_uri: str) -> str:
    """The access token Blizzard gives for the authorization code."""
    response = requests.post(
        f"{OAUTH_URL}/token",
        auth=(os.environ["BNET_CLIENT_ID"], os.environ["BNET_CLIENT_SECRET"]),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _userinfo(token: str) -> dict[str, Any]:
    """The Battle.net account behind the token: `sub` and `battletag`."""
    response = requests.get(
        f"{OAUTH_URL}/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    return dict(response.json())


def _profile(query: str) -> RedirectResponse:
    return RedirectResponse(
        f"{frontend_url()}/profile?{query}", headers={"Cache-Control": "no-store"}
    )


@router.get("/users/me/bnet/start", dependencies=[Depends(require_login)])
def start_bnet_link(request: Request) -> dict[str, str]:
    """The Blizzard authorize URL; its state is a signed token that names no one."""
    client_id = os.getenv("BNET_CLIENT_ID")
    if not client_id or not os.getenv("BNET_CLIENT_SECRET"):
        raise ApiError(503, {"error": "Battle.net login is not configured"})
    query = urlencode(
        {
            "response_type": "code",
            "scope": "openid",
            "client_id": client_id,
            "redirect_uri": _callback_url(request),
            "state": create_access_token("start", 10, STATE_KIND),
        }
    )
    return {"url": f"{OAUTH_URL}/authorize?{query}"}


@router.get("/auth/battlenet/callback", name="battlenet_callback")
def battlenet_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Send the browser to the profile with a link token; writes nothing."""
    if error or not code:
        return _profile("bnet=error&reason=denied")
    if _read_token(state, STATE_KIND) is None:
        return _profile("bnet=error&reason=state")
    try:
        account = _userinfo(_exchange_code(code, _callback_url(request)))
        subject = f"{account['sub']}|{account['battletag']}"
    except (requests.RequestException, KeyError, ValueError):
        return _profile("bnet=error&reason=token")
    return _profile(urlencode({"bnet": create_access_token(subject, 10, LINK_KIND)}))


@router.post("/users/me/bnet/finish")
def finish_bnet_link(
    data: BnetFinishWrite, claims: RequireLogin, service: UserServiceDep
) -> UserPublic:
    """Record the linked account on the caller's tag; taken answers 409."""
    subject = _read_token(data.token, LINK_KIND)
    if subject is None or "|" not in subject:
        raise ApiError(400, {"error": "The Battle.net link expired. Try again."})
    account_id, _, tag = subject.partition("|")
    return service.link_own_bnet(_discord_id(claims), account_id, tag)
