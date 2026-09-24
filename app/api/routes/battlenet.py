"""The Battle.net link: a proof that a member owns a tag, never a login.

The member asks for the Blizzard authorize URL, Blizzard sends the browser
back to the callback, and the callback records the account on the tag and
sends the browser to the profile page with `bnet=linked` or `bnet=error`.
"""

import os
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import RequireLogin, UserServiceDep
from app.api.routes.users import _discord_id
from app.core.config import frontend_url
from app.core.exceptions import ApiError, NotFoundError
from app.core.security import create_access_token, decode_token
from app.services.battle_tags import TagTakenError

router = APIRouter(tags=["battlenet"])

OAUTH_URL = "https://oauth.battle.net"
STATE_KIND = "bnet_state"


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


@router.get("/users/me/bnet/start")
def start_bnet_link(request: Request, claims: RequireLogin) -> dict[str, str]:
    """The Blizzard authorize URL; its state is a signed token naming the member."""
    client_id = os.getenv("BNET_CLIENT_ID")
    if not client_id or not os.getenv("BNET_CLIENT_SECRET"):
        raise ApiError(503, {"error": "Battle.net login is not configured"})
    query = urlencode(
        {
            "response_type": "code",
            "scope": "openid",
            "client_id": client_id,
            "redirect_uri": _callback_url(request),
            "state": create_access_token(_discord_id(claims), 10, STATE_KIND),
        }
    )
    return {"url": f"{OAUTH_URL}/authorize?{query}"}


@router.get("/auth/battlenet/callback", name="battlenet_callback")
def battlenet_callback(
    request: Request,
    service: UserServiceDep,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Record the Blizzard account on its tag and send the browser to the profile."""
    if error or not code:
        return _profile("bnet=error&reason=denied")
    try:
        claims = decode_token(state)
    except jwt.InvalidTokenError:
        return _profile("bnet=error&reason=state")
    if claims.get("type") != STATE_KIND:
        return _profile("bnet=error&reason=state")
    try:
        account = _userinfo(_exchange_code(code, _callback_url(request)))
        account_id, tag = str(account["sub"]), str(account["battletag"])
    except (requests.RequestException, KeyError, ValueError):
        return _profile("bnet=error&reason=token")
    try:
        service.link_own_bnet(str(claims["sub"]), account_id, tag)
    except TagTakenError:
        return _profile("bnet=error&reason=taken")
    except NotFoundError:
        return _profile("bnet=error&reason=state")
    return _profile("bnet=linked")
