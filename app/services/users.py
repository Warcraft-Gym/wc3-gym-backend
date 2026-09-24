import logging
from collections.abc import Iterable
from datetime import timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlmodel import col

from app.core.battle_tags import STAND_IN_ID_PREFIX, has_login, is_real_tag
from app.core.db import Session, rel
from app.core.exceptions import (
    ApiError,
    BadRequestError,
    NotFoundError,
    W3CThrottledError,
)
from app.core.query import QueryElement, QueryUtil
from app.models.link_prompt import LinkPromptPublic
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import (
    User,
    UserCreate,
    UserListPublic,
    UserPublic,
    UserReduced,
    UserUpdate,
)
from app.models.user_battle_tag import MergePlan, UserBattleTag
from app.models.w3c_stats import (
    W3CStats,
    W3CStatsCreate,
)
from app.services import derived, link_prompts, merge
from app.services.battle_tags import (
    attach_tag,
    drop_tag,
    move_tag,
    person_by_tag,
    set_active_tag,
)
from app.services.w3c import REQUEST_TIMEOUT, W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Threads that call w3champions at once. The work is network wait, so four
# of them cost no CPU and keep a team of 18 players under five seconds.
W3C_SYNC_WORKERS = 4

# A button absorbs a double click and a second admin, and still refreshes
# a roster before its match.
SYNC_MAX_AGE = timedelta(minutes=10)


# The list row has no gnl_stats, so the link rows stay out
_LIST_OPTIONS = (
    noload(rel(User.team_seasons)),
    joinedload(rel(User.w3c_stats)),
    selectinload(rel(User.signup_seasons)).joinedload(rel(DBUserSeasonSignup.season)),
    selectinload(rel(User.battle_tags)),
)


def _public(session: OrmSession, user: User) -> UserPublic:
    """One user, with the season record of every team he played for and his trophies."""
    public = UserPublic.from_user(user)
    derived.fill_gnl_stats(session, [public])
    derived.fill_trophies(session, [public])
    return public


class UserService:
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    def add(self, user: UserCreate, source: str = "admin") -> UserPublic:
        """A new person, and their tag as the active one."""
        with Session.begin() as session:
            row = User.add(session, user.model_dump())
            attach_tag(session, row, user.battleTag, source)
            return _public(session, row)

    def update(
        self, user_id: int, user: UserUpdate, source: str = "admin"
    ) -> UserPublic:
        """Change the fields sent. A tag sent becomes the active one; a tag
        the person held before stays theirs."""
        fields = user.model_dump(exclude_unset=True)
        tag = fields.pop("battleTag", None)
        with Session.begin() as session:
            row = User.update(session, user_id, **fields)
            if not row:
                raise NotFoundError("User not found")
            if tag:
                attach_tag(session, row, tag, source)
            return _public(session, row)

    def set_avatar(self, user_id: int, avatar_url: str | None) -> None:
        """The Discord avatar the login just read: one UPDATE, nothing derived."""
        with Session.begin() as session:
            User.update(session, user_id, avatar_url=avatar_url)

    def set_fantasy_tiers(
        self, season_id: int, cuts: list[int], tiers: dict[int, int]
    ) -> None:
        """Replace one season's whole allocation: the cuts, and listed players get
        their tier, the rest none."""
        by_tier: dict[int, list[int]] = {}
        for user_id, tier in tiers.items():
            by_tier.setdefault(tier, []).append(user_id)
        signups = update(DBUserSeasonSignup).where(
            col(DBUserSeasonSignup.season_id) == season_id
        )
        with Session.begin() as session:
            season = session.get(Season, season_id)
            if season is None:
                raise NotFoundError("Season not found")
            if not 1 <= len(cuts) <= 5 or any(a >= b for a, b in pairwise(cuts)):
                raise BadRequestError("Cuts must be 1 to 5 strictly ascending MMRs")
            if tiers and max(tiers.values()) > len(cuts) + 1:
                raise BadRequestError(f"The cuts make only {len(cuts) + 1} tiers")
            signed_up = set(
                session.scalars(
                    select(col(DBUserSeasonSignup.user_id)).where(
                        col(DBUserSeasonSignup.season_id) == season_id
                    )
                )
            )
            if missing := set(tiers) - signed_up:
                raise BadRequestError(
                    f"{len(missing)} players are not signed up for this season"
                )
            season.fantasy_tier_cuts = cuts
            season.fantasy_tiers_applied_at = utcnow()
            session.execute(signups.values(fantasy_tier=None))
            for tier, ids in by_tier.items():
                session.execute(
                    signups.where(col(DBUserSeasonSignup.user_id).in_(ids)).values(
                        fantasy_tier=tier
                    )
                )

    def delete(self, user_id: int) -> None:
        with Session.begin() as session:
            User.delete(session, user_id)

    def set_banned(self, user_id: int, banned: bool) -> None:
        """Stamp or clear the ban. A banned player still signs up; the entrant
        row of the event warns and an admin decides."""
        with Session.begin() as session:
            row = session.get(User, user_id)
            if row is None:
                raise NotFoundError(f"User not found by id: {user_id}")
            row.banned_at = utcnow() if banned else None

    def get(self, key: int | str) -> UserPublic:
        """One user by id, or by any tag they hold when the key is not all digits.

        A battle tag always carries a `#`, so the two never collide.
        """
        key = str(key).strip()
        with Session.begin() as session:
            if key.isdecimal():
                user_id: int | None = int(key)
            else:
                held = person_by_tag(session, key)
                user_id = held.id if held is not None else None
            # Eager load related entities, disable nested loading
            user = (
                session.scalars(
                    select(User)
                    .options(
                        joinedload(rel(User.team_seasons)).noload("*"),
                        joinedload(rel(User.w3c_stats)),
                        selectinload(rel(User.signup_seasons)).joinedload(
                            rel(DBUserSeasonSignup.season)
                        ),
                        selectinload(rel(User.battle_tags)),
                    )
                    .where(col(User.id) == user_id)
                )
                .unique()
                .first()
            )
            if not user:
                raise NotFoundError(f"User not found: {key}")
            return _public(session, user)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[UserListPublic]:
        return self._where(
            QueryUtil.convert_query_to_db_filter(User, query),
            limit=limit,
            offset=offset,
        )

    def find_by_ids(self, user_ids: Iterable[int | None]) -> list[UserListPublic]:
        """The users of those ids, read in one statement."""
        ids = [user_id for user_id in user_ids if user_id is not None]
        if not ids:
            return []
        return self._where(col(User.id).in_(ids))

    def find_by_discord_id(self, discord_id: str) -> list[UserListPublic]:
        return self._where(col(User.discordId) == discord_id)

    def id_by_discord_id(self, discord_id: str) -> int | None:
        """The id of the player behind a Discord account, in one statement.

        A route that only identifies its caller reads this; find_by_discord_id
        also loads his whole W3C history and every season he signed up for.
        """
        with Session.begin() as session:
            return session.scalar(
                select(col(User.id)).where(col(User.discordId) == discord_id)
            )

    def signup_match(
        self, discord_id: str, discord_name: str, battle_tag: str
    ) -> tuple[int | None, bool, int | None]:
        """The row a member signup writes (None for a new one), whether the
        Discord name may be stored on it, and the earlier player to suggest.

        The login's own row first. Typing a tag an earlier player (no login)
        holds claims that player at once, unverified: a login with no row
        becomes it, one with a row joins it. A tag another login holds is
        refused. An earlier player holding only the Discord name is a guess:
        it lets go of the name and becomes a suggestion. A namesake with a
        login of its own is another person, so the name is left off.
        """
        with Session.begin() as session:
            own = session.scalars(
                select(User).where(col(User.discordId) == discord_id)
            ).first()
            tagged = person_by_tag(session, battle_tag)
            if tagged is not None and (own is None or tagged.id != own.id):
                if has_login(tagged.discordId):
                    raise ApiError(
                        409,
                        {
                            "error": f"The battle tag {battle_tag} is on another player's"
                            " profile."
                            " Ask an admin on Discord to move it to you."
                        },
                    )
                if own is not None:
                    link_prompts.join(session, tagged, own)
                    tagged = None
            row = own or tagged
            named = session.scalars(
                select(User).where(
                    func.lower(func.trim(col(User.discordTag)))
                    == discord_name.strip().lower()
                )
            ).first()
            suggest_id = None
            if named is not None and (row is None or named.id != row.id):
                if has_login(named.discordId):
                    return (row.id if row is not None else None), False, None
                named.discordTag = None
                session.flush()
                suggest_id = named.id
            return (row.id if row is not None else None), True, suggest_id

    def _where(
        self,
        filter: ColumnElement[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserListPublic]:
        if filter is None:
            return []
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(User)
                .options(*_LIST_OPTIONS)
                .where(filter)
                .order_by(col(User.id))
                .offset(offset)
                .limit(limit)
            )
            users = session.scalars(statement).unique().all()
            return [UserListPublic.from_user(user) for user in users]

    def get_all(
        self,
        limit: int | None = None,
        offset: int = 0,
        no_discord: bool = False,
        tag_source: str | None = None,
    ) -> tuple[list[UserListPublic], int]:
        """The users, or one page of them, and the total row count.

        no_discord keeps the people with no login; tag_source keeps the people
        who hold a tag row of that source.
        """
        filters: list[ColumnElement[bool]] = []
        if no_discord:
            discord_id = func.trim(col(User.discordId))
            filters.append(
                or_(
                    col(User.discordId).is_(None),
                    discord_id == "",
                    discord_id.startswith(STAND_IN_ID_PREFIX),
                )
            )
        if tag_source:
            filters.append(
                col(User.id).in_(
                    select(col(UserBattleTag.user_id)).where(
                        col(UserBattleTag.source) == tag_source
                    )
                )
            )
        with Session.begin() as session:
            total = (
                session.scalar(select(func.count()).select_from(User).where(*filters))
                or 0
            )
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(User)
                .options(*_LIST_OPTIONS)
                .where(*filters)
                .order_by(col(User.id))
                .offset(offset)
                .limit(limit)
            )
            users = session.scalars(statement).unique().all()
            return [UserListPublic.from_user(user) for user in users], total

    def _own(self, session: OrmSession, discord_id: str) -> User:
        user = session.scalars(
            select(User).where(col(User.discordId) == discord_id)
        ).first()
        if user is None:
            raise NotFoundError("No profile for this account")
        return user

    def _own_tag(self, session: OrmSession, user: User, tag_id: int) -> UserBattleTag:
        row = session.get(UserBattleTag, tag_id)
        if row is None or row.user_id != user.id:
            raise NotFoundError(f"No tag {tag_id} on your profile")
        return row

    def add_own_tag(self, discord_id: str, tag: str) -> UserPublic:
        """A tag the member also played as: a new unverified row with source
        `claim`, active only when they hold no active tag. An earlier player
        holding it joins the member at once; another login holding it is 409."""
        tag = tag.strip()
        if not is_real_tag(tag) or not self.validate_battle_tag(tag):
            raise NotFoundError(f"W3Champions does not know {tag}")
        with Session.begin() as session:
            user = self._own(session, discord_id)
            link_prompts.claim(session, user, tag)
            user_id = user.id
        return self.get(str(user_id))

    def link_own_bnet(self, discord_id: str, account_id: str, tag: str) -> UserPublic:
        """Record the member's Battle.net account on its tag; taken answers 409."""
        with Session.begin() as session:
            user = self._own(session, discord_id)
            link_prompts.verify(session, user, account_id, tag)
            user_id = user.id
        return self.get(str(user_id))

    def suggest_person(self, person_id: int, user_id: int) -> None:
        """Suggest an earlier player to a login by the Discord name they share."""
        with Session.begin() as session:
            person = session.get(User, person_id)
            if person is not None and not has_login(person.discordId):
                link_prompts.suggest(session, person, "discord", user_id=user_id)

    def own_prompts(self, discord_id: str) -> list[LinkPromptPublic]:
        """The member's open suggestions and notices."""
        with Session() as session:
            return link_prompts.open_for(session, self._own(session, discord_id))

    def answer_own_prompt(
        self, discord_id: str, prompt_id: int, accept: bool
    ) -> UserPublic:
        """Accept or dismiss one of the member's prompts."""
        with Session.begin() as session:
            user = self._own(session, discord_id)
            link_prompts.answer(session, user, prompt_id, accept)
            user_id = user.id
        return self.get(str(user_id))

    def activate_own_tag(self, discord_id: str, tag_id: int) -> UserPublic:
        """Make one of the member's tags the active one."""
        with Session.begin() as session:
            user = self._own(session, discord_id)
            set_active_tag(session, user, self._own_tag(session, user, tag_id))
            user_id = user.id
        return self.get(str(user_id))

    def remove_own_tag(self, discord_id: str, tag_id: int) -> UserPublic:
        """Remove an unverified, inactive tag of the member and its games."""
        with Session.begin() as session:
            user = self._own(session, discord_id)
            drop_tag(session, self._own_tag(session, user, tag_id))
            user_id = user.id
        return self.get(str(user_id))

    def give_tag(self, user_id: int, tag_id: int, to_user_id: int) -> UserPublic:
        """An admin gives one tag row of a person to another person."""
        with Session.begin() as session:
            row = session.get(UserBattleTag, tag_id)
            if row is None or row.user_id != user_id:
                raise NotFoundError(f"No tag {tag_id} on user {user_id}")
            if to_user_id == user_id:
                raise BadRequestError("The tag is already on this person")
            to = session.get(User, to_user_id)
            if to is None:
                raise NotFoundError(f"User not found: {to_user_id}")
            move_tag(session, row, to, "admin")
            # only the player's own Battle.net sign-in verifies a tag
            row.bnet_account_id = None
        return self.get(str(to_user_id))

    def merge_into(
        self, user_id: int, into_user_id: int, dry_run: bool
    ) -> MergePlan | UserPublic:
        """Merge one person into another; a dry run answers the plan alone."""
        if user_id == into_user_id:
            raise BadRequestError("A person cannot be merged into themselves")
        with Session.begin() as session:
            source = session.get(User, user_id)
            target = session.get(User, into_user_id)
            if source is None or target is None:
                missing = user_id if source is None else into_user_id
                raise NotFoundError(f"User not found: {missing}")
            if dry_run:
                return merge.plan(session, source, target)[0]
            merge.merge(session, source, target)
        return self.get(str(into_user_id))

    def validate_battle_tag(self, battle_tag: str) -> bool:
        """
        Validate that a BattleTag exists on W3Champions without persisting anything.
        Returns True if player exists, False otherwise.
        """
        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        try:
            return w3c_service.validate_player(battle_tag)
        except Exception as e:
            logger.debug(f"BattleTag validation failed for {battle_tag}: {e!s}")
            return False

    def update_w3c_stats(
        self, user: UserReduced, timeout: float = REQUEST_TIMEOUT
    ) -> None:
        w3c_service = W3CService(
            settings_app_service=self.settings_app_service, timeout=timeout
        )

        # Resolve the season once, so both fetches agree and w3champions is
        # asked for the season list at most once per player.
        try:
            current_season = w3c_service.current_season()
        except Exception as e:
            logger.warning(f"No W3C season to sync {user.battleTag} against: {e}")
            raise

        if not user.battleTag:
            raise BadRequestError(f"User {user.id} has no battle tag to sync")
        seasons = (current_season, current_season - 1)
        all_stats = []
        refusals: list[Exception] = []
        for season in seasons:
            try:
                stats = w3c_service.get_player_stats(
                    user.battleTag, season_override=season
                )
                if stats:
                    all_stats.extend(stats)
            except W3CThrottledError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to fetch season {season} W3C stats for {user.battleTag}: {e}"
                )
                refusals.append(e)

        # A season that answers nothing is an unranked player, so only a sync
        # w3champions refused for every season is a failure the caller reports.
        if len(refusals) == len(seasons):
            raise refusals[0]

        # One transaction reads and writes the rows of this player, so no
        # other sync can insert between the read and the write.
        with Session.begin() as session:
            for s in all_stats:
                self._write_w3c_stats(session, user.id, s)
            # The stamp says when the app last asked, not that stats were found
            session.execute(
                update(User)
                .where(col(User.id) == user.id)
                .values(w3c_synced_at=utcnow())
            )

    def _write_w3c_stats(
        self, session: OrmSession, user_id: int, w3c_stats: W3CStatsCreate
    ) -> None:
        """Update the row of this race and season, or insert it."""
        values = {**w3c_stats.model_dump(), "user_id": user_id}
        existing = session.scalars(self._w3c_stats_key(user_id, w3c_stats)).all()
        if existing:
            for row in existing:
                W3CStats.update_object(session, row, **values)
            return
        try:
            # A savepoint, so a lost race rolls back the insert alone
            with session.begin_nested():
                W3CStats.add(session, values)
        except IntegrityError:
            # Another sync inserted the row first, so update that row
            row = session.scalars(
                self._w3c_stats_key(user_id, w3c_stats).with_for_update()
            ).first()
            if row is None:
                raise
            W3CStats.update_object(session, row, **values)

    @staticmethod
    def _w3c_stats_key(
        user_id: int, w3c_stats: W3CStatsCreate
    ) -> Select[tuple[W3CStats]]:
        """The rows the unique index holds to one: user, race and season."""
        return select(W3CStats).where(
            col(W3CStats.user_id) == user_id,
            col(W3CStats.race) == w3c_stats.race,
            col(W3CStats.wc3_season) == w3c_stats.wc3_season,
        )

    def update_w3c_stats_by_id(self, user_id: int) -> UserPublic:
        self.update_w3c_stats(self.get(user_id))
        return self.get(user_id)
