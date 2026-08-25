"""The fantasy import pipelines.

Reads a fantasy workbook and writes it in one transaction: one lookup per
table the sheets name, then the inserts and updates those sheets need. A
failure leaves the database as it was.
"""

import io
import logging
from collections.abc import Callable, Iterable
from typing import NamedTuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet
from app.models.fantasy_team import FantasyTeam, FantasyTeamCreate
from app.models.match import Match
from app.models.relationships import DBFantasyTeamPlayer
from app.models.season import Season
from app.models.series import Series
from app.models.settings import Settings
from app.models.team import Team
from app.models.user import User, UserCreate
from app.services.fantasy_bets import resolve_bet_points
from app.services.season_import import cell_value, whole_number

logger = logging.getLogger(__name__)


class Draft(NamedTuple):
    """One row of the team sheet, with the rows it names resolved."""

    name: str
    captain: User
    team_id: int
    race: Race
    players: list[User]


def import_fantasy_teams_workbook(
    file_bytes: bytes, season_id: int | None, season_name: str | None
) -> None:
    """Read the "Formatted Responses" sheet and write the fantasy teams."""
    frame = pd.read_excel(io.BytesIO(file_bytes), sheet_name="Formatted Responses")
    rows = _rows(frame)
    with Session.begin() as session:
        _teams(session, rows, _season_id(session, season_id, season_name))


def import_fantasy_bets_workbook(
    file_bytes: bytes, season_id: int | None, season_name: str | None
) -> None:
    """Read the "Betting Matches" and "Bets" sheets and write the bets."""
    # sheet_name=None reads both sheets, so the workbook is parsed once
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
    with Session.begin() as session:
        season = _season_id(session, season_id, season_name)
        matches, series = _fantasy_matches(session, sheets["Betting Matches"], season)
        _bets(session, sheets["Bets"], season, matches, series)


def _rows(frame: pd.DataFrame) -> list[pd.Series]:
    """The rows of a sheet that carry a first cell. A sheet ends where that
    cell is empty."""
    return [row for _, row in frame.iterrows() if cell_value(row.iloc[0])]


def _by_key[K, V](values: Iterable[V], key: Callable[[V], K]) -> dict[K, list[V]]:
    """Group the stored rows under the value the import matches them by."""
    grouped: dict[K, list[V]] = {}
    for value in values:
        grouped.setdefault(key(value), []).append(value)
    return grouped


def _folded(value: object) -> object:
    """The key a lookup matches on. Text folds to lower case, so a form
    entry finds the stored row whatever the case it was typed in."""
    return value.strip().lower() if isinstance(value, str) else value


def _column(rows: list[pd.Series], index: int) -> set[object]:
    """The keys one column of the sheet holds, without its empty cells."""
    return {_folded(value) for row in rows if (value := cell_value(row.iloc[index]))}


def _season_id(
    session: OrmSession, season_id: int | None, season_name: str | None
) -> int:
    """The season the import writes into, named by id or by name."""
    if season_id:
        return season_id
    if not season_name:
        raise BadRequestError(
            "Missing Season parameter, either season_id or season name is required"
        )
    season = session.scalars(select(Season).where(Season.name == season_name)).first()
    if not season:
        raise NotFoundError(f"Season could not be found by name: {season_name}")
    return season.id


def _drafts(
    session: OrmSession,
    rows: list[pd.Series],
    season_id: int,
    stored: dict[int, list[FantasyTeam]],
) -> tuple[list[Draft], list[User]]:
    """Read every row of the team sheet: its captain, its GNL team, its race
    and its eight drafted players. A captain on no roster is created."""
    by_tag = _by_key(
        session.scalars(
            select(User).where(func.lower(User.discordTag).in_(_column(rows, 1)))
        ),
        lambda user: _folded(user.discordTag),
    )
    names = {
        _folded(name) for row in rows for name in row.iloc[2:10] if cell_value(name)
    }
    by_name = _by_key(
        session.scalars(select(User).where(func.lower(User.name).in_(names))),
        lambda user: _folded(user.name),
    )
    teams = _by_key(
        session.scalars(
            select(Team).where(func.lower(Team.name).in_(_column(rows, 10)))
        ),
        lambda team: _folded(team.name),
    )
    drafts: list[Draft] = []
    captains: list[User] = []
    for row in rows:
        name = cell_value(row.iloc[0])
        tag = cell_value(row.iloc[1])
        if not tag:
            raise BadRequestError(f"Team without captain: {name}")
        found_users = by_tag.get(_folded(tag), [])
        if len(found_users) > 1:
            raise BadRequestError(
                f"No or multiple users found for captain[{tag}]: {found_users}"
            )
        if found_users:
            captain = found_users[0]
        else:
            logger.debug(f"No user found for discordTag {tag}: create a fantasy user")
            captain = User(
                **UserCreate(
                    name=tag,
                    battleTag="Fantasy_User",
                    discordTag=tag,
                    discordId="",
                    race=Race.RANDOM,
                ).model_dump()
            )
            captains.append(captain)
            by_tag[_folded(tag)] = [captain]

        team_name = cell_value(row.iloc[10])
        if not team_name:
            raise BadRequestError(f"No GNL team defined for team: {name}")
        found_teams = teams.get(_folded(team_name), [])
        if len(found_teams) != 1:
            raise BadRequestError(
                f"No or multiple teams found for gnl team name[{team_name} ]: {found_teams}"
            )

        if not cell_value(row.iloc[11]):
            raise BadRequestError(f"No Race defined for team: {row.iloc[11]}")
        try:
            race = Race.from_text(str(row.iloc[11]))
        except ValueError as error:
            raise BadRequestError(str(error)) from error

        if len(stored.get(captain.id, [])) > 1:
            raise BadRequestError(
                f"More than one bet found by search: season_id=={season_id} "
                f"and captain_id=={captain.id}"
            )

        players = []
        for cell in row.iloc[2:10]:
            if not cell:
                raise BadRequestError(f"Player missing for team: {name}")
            found_players = by_name.get(_folded(cell), [])
            if len(found_players) != 1:
                raise BadRequestError(f"Could not find player by name: {cell}")
            players.append(found_players[0])
        drafts.append(Draft(name, captain, found_teams[0].id, race, players))
    return drafts, captains


def _teams(session: OrmSession, rows: list[pd.Series], season_id: int) -> None:
    """Write one fantasy team per row of the sheet, matched by captain."""
    stored = _by_key(
        session.scalars(select(FantasyTeam).where(FantasyTeam.season_id == season_id)),
        lambda fteam: fteam.captain_id,
    )
    drafts, captains = _drafts(session, rows, season_id, stored)
    session.add_all(captains)
    session.flush()

    written: list[FantasyTeam] = []
    drafted: list[tuple[FantasyTeam, list[User]]] = []
    for draft in drafts:
        values = FantasyTeamCreate(
            name=draft.name,
            season_id=season_id,
            captain_id=draft.captain.id,
            drafted_team_id=draft.team_id,
            drafted_race=draft.race,
        )
        found = stored.get(draft.captain.id, [])
        if found:
            fteam = found[0]
            for field, value in values.model_dump().items():
                setattr(fteam, field, value)
        else:
            fteam = FantasyTeam(**values.model_dump())
            written.append(fteam)
            stored[draft.captain.id] = [fteam]
        drafted.append((fteam, draft.players))
    session.add_all(written)
    session.flush()

    _drafted_players(session, drafted)


def _drafted_players(
    session: OrmSession, drafted: list[tuple[FantasyTeam, list[User]]]
) -> None:
    """The drafted players a row names replace the ones its team holds."""
    wanted = {fteam.id: {player.id for player in players} for fteam, players in drafted}
    if not wanted:
        return
    linked: set[tuple[int, int]] = set()
    for link in session.scalars(
        select(DBFantasyTeamPlayer).where(
            DBFantasyTeamPlayer.fantasy_team_id.in_(wanted)
        )
    ):
        if link.user_id in wanted[link.fantasy_team_id]:
            linked.add((link.fantasy_team_id, link.user_id))
        else:
            session.delete(link)
    session.add_all(
        [
            DBFantasyTeamPlayer(fantasy_team_id=fteam_id, user_id=user_id)
            for fteam_id, user_ids in wanted.items()
            for user_id in user_ids
            if (fteam_id, user_id) not in linked
        ]
    )


def _fantasy_matches(
    session: OrmSession, frame: pd.DataFrame, season_id: int
) -> tuple[dict[int, list[Match]], dict[int, list[Series]]]:
    """Flag the series the "Betting Matches" sheet names, and answer the
    matches and series of the season for the sheet that follows."""
    rows = _rows(frame)
    matches = _by_key(
        session.scalars(select(Match).where(Match.season_id == season_id)),
        lambda match: match.playday,
    )
    match_ids = {match.id for day in matches.values() for match in day}
    series: dict[int, list[Series]] = {}
    if match_ids:
        series = _by_key(
            session.scalars(select(Series).where(Series.match_id.in_(match_ids))),
            lambda one: one.match_id,
        )

    names = _column(rows, 1) | _column(rows, 2)
    by_name = _by_key(
        session.scalars(select(User).where(func.lower(User.name).in_(names))),
        lambda user: _folded(user.name),
    )
    for row in rows:
        players = []
        for index in (1, 2):
            found = by_name.get(_folded(cell_value(row.iloc[index])), [])
            if len(found) != 1:
                raise BadRequestError(
                    f"No or multiple users found for bet player[{row.iloc[1]}]: {found}"
                )
            players.append(found[0])
        pair = {players[0].id, players[1].id}
        played = None
        for match in matches.get(whole_number(row.iloc[0]), []):
            # A match holding more than one such series names none of them
            found_series = [
                one
                for one in series.get(match.id, [])
                if {one.player1_id, one.player2_id} == pair
            ]
            if len(found_series) == 1:
                played = found_series[0]
                break
        if not played:
            raise BadRequestError(
                f"Could not identfy series for player: {row.iloc[1]}!"
            )
        played.is_fantasy_match = True
    return matches, series


def _bets(
    session: OrmSession,
    frame: pd.DataFrame,
    season_id: int,
    matches: dict[int, list[Match]],
    series: dict[int, list[Series]],
) -> None:
    """Write one bet per row of the "Bets" sheet, matched by series, bettor
    and pick."""
    rows = _rows(frame)
    by_tag = _by_key(
        session.scalars(
            select(User).where(func.lower(User.discordTag).in_(_column(rows, 1)))
        ),
        lambda user: _folded(user.discordTag),
    )
    by_name = _by_key(
        session.scalars(
            select(User).where(func.lower(User.name).in_(_column(rows, 2)))
        ),
        lambda user: _folded(user.name),
    )
    stored = _by_key(
        session.scalars(select(FantasyBet).where(FantasyBet.season_id == season_id)),
        lambda bet: (bet.series_id, bet.user_id, bet.winner_id),
    )
    settings = Settings.get_all_as_dict(session)

    written: list[FantasyBet] = []
    for row in rows:
        if not cell_value(row.iloc[1]):
            raise BadRequestError(f"Captain not defined: {row.iloc[1]}")
        found = by_tag.get(_folded(cell_value(row.iloc[1])), [])
        if len(found) != 1:
            raise BadRequestError(
                f"No or multiple users found for captain[{row.iloc[1]}]: {found}"
            )
        captain = found[0]

        if not cell_value(row.iloc[2]):
            raise BadRequestError(f"Bet Player not defined: {row.iloc[2]}")
        found = by_name.get(_folded(cell_value(row.iloc[2])), [])
        if len(found) != 1:
            raise BadRequestError(
                f"No or multiple users found for bet player[{row.iloc[2]}]: {found}"
            )
        bet_player = found[0]

        played = None
        for match in matches.get(whole_number(row.iloc[0]), []):
            # A match holding more than one such series names none of them
            found_series = [
                one
                for one in series.get(match.id, [])
                if one.is_fantasy_match
                and bet_player.id in (one.player1_id, one.player2_id)
            ]
            if len(found_series) == 1:
                played = found_series[0]
                break
        if not played:
            raise BadRequestError(
                f"Could not identfy series for player: {bet_player.name}!"
            )

        if not cell_value(row.iloc[3]):
            raise BadRequestError(f"Bet Points not defined: {row.iloc[3]}")
        points = resolve_bet_points(settings, whole_number(row.iloc[3]))

        key = (played.id, captain.id, bet_player.id)
        found_bets = stored.get(key, [])
        if len(found_bets) > 1:
            raise BadRequestError(f"More than one bet found by search: {key}")
        if found_bets:
            found_bets[0].bet_points = points
        else:
            bet = FantasyBet(
                season_id=season_id,
                series_id=played.id,
                user_id=captain.id,
                winner_id=bet_player.id,
                bet_points=points,
            )
            written.append(bet)
            # A later row of the same sheet must find the bet this one made
            stored[key] = [bet]
    session.add_all(written)
