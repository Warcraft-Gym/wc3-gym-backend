"""Join an earlier player to a login, or suggest it, and verify a tag.

An earlier player is a person with no login, usually from a season sheet.
Only a tag Battle.net verified on a login joins such a player without asking.
A weaker hint (the sheet's tag on an unverified login tag, a name-search guess,
the sheet's Discord name) is a suggestion the login accepts or dismisses once.
A claim (the login types the tag) joins at once, unverified.

The functions take the caller's session, so they join its transaction.
"""

from collections import defaultdict

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.battle_tags import fold, has_login
from app.core.exceptions import ApiError, NotFoundError
from app.models.base import ident
from app.models.link_prompt import LinkPrompt, LinkPromptPublic
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.services import merge
from app.services.battle_tags import (
    FOLDED_TAG,
    active_row,
    attach_tag,
    move_tag,
    people_by_tags,
    set_active_tag,
    tag_row,
)

TAKEN = "That Battle.net account or tag belongs to another player. Ask an admin."
STOPPED = (
    "Your profile and that player both hold rows that cannot be joined. Ask an admin."
)


def suggest(
    session: OrmSession,
    person: User,
    reason: str,
    tag: str | None = None,
    user_id: int | None = None,
) -> None:
    """Suggest the earlier player to the login holding `tag`, or to `user_id`.
    The same open suggestion is written once."""
    same = select(LinkPrompt).where(
        col(LinkPrompt.kind) == "suggest",
        col(LinkPrompt.person_id) == ident(person),
        col(LinkPrompt.closed_at).is_(None),
        col(LinkPrompt.tag) == tag if tag else col(LinkPrompt.user_id) == user_id,
    )
    if session.scalars(same).first() is None:
        session.add(
            LinkPrompt(
                kind="suggest",
                person_id=ident(person),
                user_id=user_id,
                tag=tag,
                reason=reason,
            )
        )
        session.flush()


def suggested_people(session: OrmSession, tags: list[str]) -> dict[str, User]:
    """The earlier player an open `sheet` suggestion names, by folded tag."""
    wanted = {fold(tag) for tag in tags}
    if not wanted:
        return {}
    rows = session.execute(
        select(col(LinkPrompt.tag), User)
        .join(User, col(User.id) == col(LinkPrompt.person_id))
        .where(
            col(LinkPrompt.kind) == "suggest",
            col(LinkPrompt.reason) == "sheet",
            col(LinkPrompt.closed_at).is_(None),
        )
    ).all()
    return {fold(tag): user for tag, user in rows if tag and fold(tag) in wanted}


def _close(session: OrmSession, where: ColumnElement[bool], outcome: str) -> None:
    session.execute(
        update(LinkPrompt)
        .where(where, col(LinkPrompt.closed_at).is_(None))
        .values(closed_at=utcnow(), outcome=outcome)
    )


def join(session: OrmSession, person: User, user: User, strict: bool = True) -> bool:
    """Merge the earlier player into the login and close its suggestions.
    A stop refuses with 409 when strict, else leaves both as they are."""
    result, _ = merge.plan(session, person, user)
    if result.stops:
        if strict:
            raise ApiError(409, {"error": STOPPED, **result.model_dump()})
        return False
    _close(session, col(LinkPrompt.person_id) == ident(person), "joined")
    merge.merge(session, person, user)
    return True


def claim(session: OrmSession, user: User, tag: str) -> None:
    """The login typed a tag it played as. Nobody holds it: a new unverified
    row. An earlier player holds it: that player joins at once. Another login
    holds it: 409."""
    row = tag_row(session, tag)
    if row is None:
        attach_tag(
            session, user, tag, "claim", active=active_row(session, ident(user)) is None
        )
        return
    if row.user_id == ident(user):
        return
    holder = session.get(User, row.user_id)
    assert holder is not None
    if has_login(holder.discordId):
        raise ApiError(
            409,
            {"error": f"{row.tag} belongs to another player. Ask an admin to move it."},
        )
    join(session, holder, user)


def verify(session: OrmSession, user: User, account_id: str, tag: str) -> None:
    """Record the Battle.net account on the tag it holds today.

    An account another person holds, or a tag another login verified, answers
    409. A tag another login holds unverified moves here and that login gets a
    `taken` notice. An earlier player holding it joins; so does every earlier
    player a `sheet` suggestion names on this tag. The tag becomes main only
    when the login had no verified tag, or it renames the main account.
    """
    elsewhere = select(UserBattleTag).where(
        col(UserBattleTag.bnet_account_id) == account_id,
        col(UserBattleTag.user_id) != ident(user),
    )
    if session.scalars(elsewhere).first() is not None:
        raise ApiError(409, {"error": TAKEN})
    main = active_row(session, ident(user))
    had_verified = (
        session.scalars(
            select(UserBattleTag).where(
                col(UserBattleTag.user_id) == ident(user),
                col(UserBattleTag.bnet_account_id).is_not(None),
            )
        ).first()
        is not None
    )
    row = tag_row(session, tag)
    if row is not None and row.user_id != ident(user):
        holder = session.get(User, row.user_id)
        assert holder is not None
        if not has_login(holder.discordId):
            join(session, holder, user, strict=False)
        elif row.bnet_account_id is not None:
            raise ApiError(409, {"error": TAKEN})
        else:
            session.add(
                LinkPrompt(
                    kind="taken", user_id=ident(holder), tag=row.tag, reason="bnet"
                )
            )
        session.refresh(row)
        if row.user_id != ident(user):
            move_tag(session, row, user, "link")
    for person in suggested_people(session, [tag]).values():
        join(session, person, user, strict=False)
    row = attach_tag(session, user, tag, "link", active=False)
    assert row is not None
    row.bnet_account_id = account_id
    row.source = "link"
    session.flush()
    renamed = main is not None and main.bnet_account_id == account_id
    if not had_verified or renamed:
        set_active_tag(session, user, row)


def _recipients(
    session: OrmSession, prompts: list[LinkPrompt]
) -> dict[int, int | None]:
    """The login each suggestion speaks to, by prompt id."""
    holders = people_by_tags(
        session, [p.tag for p in prompts if p.tag and not p.user_id]
    )
    out: dict[int, int | None] = {}
    for p in prompts:
        holder = holders.get(fold(p.tag)) if p.tag and not p.user_id else None
        to = p.user_id or (
            holder.id if holder is not None and has_login(holder.discordId) else None
        )
        out[ident(p)] = to
    return out


def open_for(session: OrmSession, user: User) -> list[LinkPromptPublic]:
    """The login's open prompts: its `taken` notices, and the suggestions
    that speak to it alone. A player two logins could be goes to no one."""
    folded_mine = select(FOLDED_TAG).where(col(UserBattleTag.user_id) == ident(user))
    candidates = session.scalars(
        select(LinkPrompt).where(
            col(LinkPrompt.closed_at).is_(None),
            or_(
                col(LinkPrompt.user_id) == ident(user),
                func.lower(func.trim(col(LinkPrompt.tag))).in_(folded_mine),
            ),
        )
    ).all()
    person_ids = {p.person_id for p in candidates if p.kind == "suggest"}
    rivals = session.scalars(
        select(LinkPrompt).where(
            col(LinkPrompt.kind) == "suggest",
            col(LinkPrompt.closed_at).is_(None),
            col(LinkPrompt.person_id).in_(person_ids),
        )
    ).all()
    to = _recipients(session, list(rivals))
    logins: dict[int, set[int]] = defaultdict(set)
    for p in rivals:
        if to[ident(p)] is not None:
            logins[p.person_id or 0].add(to[ident(p)] or 0)
    people = {
        u.id: u
        for u in session.scalars(select(User).where(col(User.id).in_(person_ids)))
    }
    seasons: dict[int, list[str]] = defaultdict(list)
    for user_id, name in session.execute(
        select(col(DBUserSeasonSignup.user_id), col(Season.name))
        .join(Season, col(Season.id) == col(DBUserSeasonSignup.season_id))
        .where(col(DBUserSeasonSignup.user_id).in_(person_ids))
        .order_by(col(Season.id))
    ).all():
        seasons[user_id].append(name)
    out: list[LinkPromptPublic] = []
    shown: set[int] = set()
    for p in candidates:
        if p.kind == "taken":
            out.append(LinkPromptPublic(id=ident(p), kind="taken", tag=p.tag))
            continue
        person = people.get(p.person_id)
        if person is None or has_login(person.discordId) or ident(person) in shown:
            continue
        if logins[ident(person)] != {ident(user)}:
            continue
        shown.add(ident(person))
        out.append(
            LinkPromptPublic(
                id=ident(p),
                kind="suggest",
                tag=p.tag,
                person_id=ident(person),
                name=person.name,
                seasons=seasons[ident(person)],
            )
        )
    return out


def answer(session: OrmSession, user: User, prompt_id: int, accept: bool) -> None:
    """The login's answer to one of its open prompts. Accepting a suggestion
    joins the player, unverified; anything else closes the prompt."""
    prompt = next((p for p in open_for(session, user) if p.id == prompt_id), None)
    if prompt is None:
        raise NotFoundError(f"No open prompt {prompt_id} on your profile")
    if accept and prompt.kind == "suggest" and prompt.person_id is not None:
        person = session.get(User, prompt.person_id)
        assert person is not None
        _close(session, col(LinkPrompt.id) == prompt_id, "accepted")
        join(session, person, user)
        return
    _close(
        session,
        col(LinkPrompt.id) == prompt_id,
        "dismissed" if prompt.kind == "suggest" else "seen",
    )
