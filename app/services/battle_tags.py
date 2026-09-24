"""Find a person by any battle tag they hold, and attach a tag to a person.

Every way in finds a person through user_battle_tag, so a second tag lands
on the person who holds it. A stand-in tag has no row and matches on
users.battleTag. users.battleTag holds a copy of the active tag; only
set_active_tag writes it for a real tag.

The functions take the caller's session, so they join its transaction.
"""

from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.battle_tags import fold, is_real_tag
from app.core.exceptions import ApiError
from app.models.base import ident
from app.models.ladder_sync import LadderSync
from app.models.types import utcnow
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag

FOLDED_TAG = func.lower(func.trim(col(UserBattleTag.tag)))
FOLDED_USER_TAG = func.lower(func.trim(col(User.battleTag)))


def tag_row(session: OrmSession, tag: str) -> UserBattleTag | None:
    """The row of this tag, whatever its case."""
    return session.scalars(select(UserBattleTag).where(FOLDED_TAG == fold(tag))).first()


def people_by_tags(session: OrmSession, tags: Iterable[str]) -> dict[str, User]:
    """The person behind each tag, keyed by the folded tag; two statements
    at most. A real tag matches its user_battle_tag row, a stand-in the
    users.battleTag it was written with."""
    wanted = {fold(tag) for tag in tags if tag and tag.strip()}
    real = {tag for tag in wanted if is_real_tag(tag)}
    found: dict[str, User] = {}
    if real:
        for folded, user in session.execute(
            select(FOLDED_TAG, User)
            .join(User, col(User.id) == col(UserBattleTag.user_id))
            .where(FOLDED_TAG.in_(real))
        ).all():
            found[folded] = user
    if stand_ins := wanted - real:
        for user in session.scalars(select(User).where(FOLDED_USER_TAG.in_(stand_ins))):
            found[fold(user.battleTag or "")] = user
    return found


def person_by_tag(session: OrmSession, tag: str) -> User | None:
    """The person who holds this tag, or None."""
    return people_by_tags(session, [tag]).get(fold(tag))


def set_active_tag(session: OrmSession, user: User, row: UserBattleTag) -> None:
    """Make the row the person's active tag; users.battleTag follows."""
    session.execute(
        update(UserBattleTag)
        .where(
            col(UserBattleTag.user_id) == ident(user),
            col(UserBattleTag.is_active),
            col(UserBattleTag.id) != row.id,
        )
        .values(is_active=False)
    )
    row.is_active = True
    row.last_seen = utcnow()
    user.battleTag = row.tag


def attach_tag(
    session: OrmSession,
    user: User,
    tag: str,
    source: str,
    active: bool = True,
) -> UserBattleTag | None:
    """Give the person this tag and, by default, make it active.

    A stand-in tag gets no row; it is written to users.battleTag as it is.
    A tag another person holds answers 409. A tag new to a person clears
    their ladder ledger, so the next sync reads the new tag's seasons too.
    """
    text = tag.strip()
    if not is_real_tag(text):
        user.battleTag = text
        return None
    session.flush()
    row = tag_row(session, text)
    if row is not None and row.user_id != ident(user):
        raise ApiError(
            409,
            {"error": f"{text} belongs to another player. Ask an admin to move it."},
        )
    if row is None:
        row = UserBattleTag(user_id=ident(user), tag=text, source=source)
        session.add(row)
        session.flush()
        session.execute(
            delete(LadderSync).where(col(LadderSync.user_id) == ident(user))
        )
    if active:
        set_active_tag(session, user, row)
    session.flush()
    return row
