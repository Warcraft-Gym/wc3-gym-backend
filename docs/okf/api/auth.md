---
type: API Area
title: Authentication
description: A bearer token is the admin token's JWT or a member's Discord session, both signed by the backend; the claims resolve the Discord id and the role once per request, and five guards build on them.
resource: ../../../app/api/deps.py
tags: [auth]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-27T12:00:00Z }
sources:
  - id: deps
    resource: ../../../app/api/deps.py
    title: The claims and the guards
  - id: login
    resource: ../../../app/api/routes/login.py
    title: /login and /me
  - id: battlenet
    resource: ../../../app/api/routes/battlenet.py
    title: The Battle.net link routes
  - id: security
    resource: ../../../app/core/security.py
    title: The admin token's JWT
---

# Two kinds of bearer

1. **The admin token.** `POST /login` with `{"token": <ADMIN_TOKEN>}` mints a JWT signed with `JWT_SECRET_KEY` that lasts `TOKEN_TIME` minutes. Its subject is `admin`, it carries no Discord account, and `/me` names it "Super Admin". The admin UI's `/admin-login` page and scripts use it.
2. **A member's Discord session.** A JWT of type `discord`, signed with `JWT_SECRET_KEY`, that lasts 30 days (`SESSION_MINUTES` in `app/core/security.py`). Its subject is the Discord id, and it carries the Discord name and avatar as they were at sign-in. It carries no role. The Discord login below mints it.

`require_login` decodes the bearer and answers 401 `{"error": "Not signed in"}` for a token that is not one of these or has expired. It admits a guest too.

# Discord login

1. `GET /auth/discord/start` answers 302 to Discord's authorize page with scope `identify`. Its `state` is a JWT signed with `JWT_SECRET_KEY`, type `discord_state`, 10 minutes; it names no one. The client id is `DISCORD_APPLICATION_ID`. The `redirect_uri` is this backend's `/auth/discord/callback`, with the scheme from `x-forwarded-proto`. `DISCORD_APPLICATION_ID` or `DISCORD_CLIENT_SECRET` unset answers 503 `{"error": "Discord login is not configured"}`.
2. `GET /auth/discord/callback?code=&state=` checks the state, trades the code for the account's token with `DISCORD_CLIENT_SECRET`, reads `/users/@me` once, and keeps no Discord token. It answers 302 to `FRONTEND_URL` + `/sso-callback#token=<session>`: the token rides in the URL fragment, which a browser sends to no server and in no Referer. A failure answers `/login?login=error&reason=<reason>`: `denied` (the member cancelled), `state` (a bad or expired state) or `token` (Discord refused the code). Both answers carry `Cache-Control: no-store`.

The Discord application lists the callback of every deployment that signs members in as an OAuth2 redirect.

# Local dev login

A local instance has no Discord server, so no Discord session passes the guild check there. To test the app as a player, set `DEV_LOGIN=1` in the local backend's `.env`; never set it on a deployment. Both routes then admit only the admin token's session: no bearer answers 401, and any other session answers 403, a dev session and a Discord admin included, so a player never switches to another player. `GET /dev/players?search=` lists up to 30 players that have a Discord id, each marked `captain` when it holds a seat in a running season, and `POST /dev/login {"user_id", "role"}` answers a token for one of them as `member`, `guest` or `admin`. The session is that player: `require_login` resolves its role the way it resolves a member's session, so a member with a seat is a captain and an admin can view as a lower role. With `DEV_LOGIN` unset both routes answer 404 to every caller, the admin token included, and such a token is refused.

# From a session to claims

Once per request, `_session_claims` resolves and caches on `request.state`:

- the Discord id, the session's subject;
- the role: `admin` from `admin_grant` or `ADMIN_DISCORD_IDS` with no guild read, carrying a `seats` list when the admin also captains; else `member` or `guest` from the guild read; a member with captain seats in a running season becomes `captain` with a `seats` list.

An admin grant and a captain seat are read live, so they show on the next request. The guild answer, member or guest, is kept per process for one minute (`ROLE_TTL` in `app/services/discord.py`), so a guild join, leave or kick shows within a minute. A failed guild read is never kept. See [Discord integration](../concepts/discord-integration.md).

# The guards

| Guard | Admits |
|---|---|
| `optional_login` | anyone; answers `None` with no bearer |
| `require_login` | any valid session, guest included |
| `require_member` | a guild member or higher |
| `require_captain` | a captain of a running season, or an admin |
| `require_admin` | an admin, or the admin token |

Routes use them as `Annotated` types (`RequireAdmin`, `RequireMember`) or as `dependencies=[Depends(require_admin)]`. A helper that builds on a guard, such as the player identity in `app/api/routes/public.py`, is an `Annotated` dependency too, so FastAPI runs it in the thread pool before the handler. `is_admin(claims)` in `app/core/security.py` is the one admin test: the `admin` role or the admin token. See [roles](../concepts/roles-and-permissions.md) for the ownership checks that sit beside them.

# Battle.net link

A member proves they own a battle tag with their Battle.net account. The link is no login. Only a request under the member's own login writes the link.

1. `GET /users/me/bnet/start` (`require_login`) answers `{"url": ...}`, the Blizzard authorize URL with scope `openid`. Its `state` is a JWT signed with `JWT_SECRET_KEY`, type `bnet_state`, 10 minutes; it names no one. The `redirect_uri` is this backend's `/auth/battlenet/callback`, with the scheme from `x-forwarded-proto`. `BNET_CLIENT_ID` or `BNET_CLIENT_SECRET` unset answers 503 `{"error": "Battle.net login is not configured"}`.
2. `GET /auth/battlenet/callback?code=&state=` takes no bearer and writes nothing. It checks the state, trades the code for a token with the client id and secret, and reads `sub` and `battletag` from Blizzard's userinfo. It answers 302 to `FRONTEND_URL` + `/profile?bnet=<token>`, a JWT of type `bnet_link` holding `sub|battletag` for 10 minutes. A failure answers `/profile?bnet=error&reason=<reason>`: `denied` (the member cancelled), `state` (a bad or expired state) or `token` (Blizzard refused the code).
3. `POST /users/me/bnet/finish` `{token}` (`require_login`) records the account on the caller's tag and answers the caller's user read; see [user_battle_tag](../data/tables/user_battle_tag.md). A bad or expired token, or a token of another type, answers 400 `{"error": "The Battle.net link expired. Try again."}`. A tag or account another person holds answers 409.

A token of type `bnet_state` or `bnet_link` is no bearer: `require_login` admits only type `access`. Register each backend's callback URL on the Blizzard client.

# /me

`GET /me` answers the account: `discord_id`, `name`, `avatar`, `role`, `actual_role`, `user` (the linked players row or null), `superadmin`, `organizer` (whether the account may create events, see [organizers](../concepts/roles-and-permissions.md#organizers)), `organizer_request` (`pending` while its request waits, else null), `signed_up`, `season_id`, `team`, `seats`, and `seasons` (every season that is not complete, newest first, each with its phase, switches, dates, and this account's roster and captain facts). The frontend keeps this answer for the session and reads its role from it. It also keeps the profile avatar at the one the session carries, the avatar Discord showed at sign-in. A local dev login carries no avatar, so its `name` is the player's, it rewrites no avatar, and `superadmin` is false.

# View as

An admin's `X-View-As` and `X-View-Seats` headers lower the role for one request. See [roles](../concepts/roles-and-permissions.md).

# Examples

`GET /me` with a session bearer, answered for a captain during a running season. The `user` object is the player row, cut short here.

```json
{
  "discord_id": "42",
  "name": "Player",
  "avatar": null,
  "role": "captain",
  "actual_role": "captain",
  "user": { "id": 7, "name": "Player", "race": "HU" },
  "superadmin": false,
  "organizer": false,
  "organizer_request": null,
  "signed_up": true,
  "season_id": 18,
  "team": { "id": 3, "name": "Team A" },
  "seats": [{ "team_id": 3, "season_id": 18 }],
  "seasons": [
    {
      "id": 18, "name": "Season 18", "league_short_name": "GNL", "phase": "commenced",
      "signups_open": false, "scheduling_enabled": true, "checkin_days": 3,
      "start_date": "2026-09-01", "end_date": "2026-10-15",
      "signed_up": true, "team": { "id": 3, "name": "Team A" }, "captain": true
    }
  ]
}
```

A bearer that is no session, or an expired one, answers `401 {"error": "Not signed in"}`.
