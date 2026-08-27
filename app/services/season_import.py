"""The season import pipeline.

Reads an exported season workbook and writes it in one transaction: one
lookup statement per sheet, then the inserts and updates that sheet needs.
A failure leaves the database as it was.
"""

import io
import logging
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import SQLModel

from app.core.db import Session
from app.core.exceptions import BadRequestError
from app.core.scoring import DEFAULT_SYSTEM, MAX_POINTS
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet, FantasyBetCreate
from app.models.fantasy_team import FantasyTeam, FantasyTeamCreate
from app.models.map import Map, MapCreate
from app.models.match import Match, MatchCreate
from app.models.relationships import DBFantasyTeamPlayer, DBMapSeason
from app.models.season import Season, SeasonCreate
from app.models.series import Series, SeriesCreate
from app.models.team import Team, TeamCreate
from app.models.team_season import DBTeamSeason
from app.models.user import User, UserCreate
from app.models.user_team_season import DBUserTeamSeason

logger = logging.getLogger(__name__)

type Sheets = dict[str, pd.DataFrame]


class ImportedSeason(NamedTuple):
    """The season the workbook wrote."""

    id: int
    name: str
    duplicate_bets: int


@dataclass
class Users:
    """The users the workbook names, by the id it carries and by battle tag."""

    by_old_id: dict[int, User] = field(default_factory=dict)
    by_tag: dict[str, User] = field(default_factory=dict)


def strip_text(frame: pd.DataFrame) -> pd.DataFrame:
    """A sheet with the spaces around every text cell dropped, so a lookup
    by name matches the value the workbook carries."""
    return frame.map(lambda value: value.strip() if isinstance(value, str) else value)


def cell_value[T](value: T) -> T | None:
    """Read a spreadsheet cell. An empty cell reads as None, not as NaN."""
    if pd.isna(value):
        return None
    return value


def whole_number(value: object) -> int | None:
    """Read a cell that holds a whole number."""
    value = cell_value(value)
    if value is None or value == "":
        return None
    return int(float(value)) if isinstance(value, str) else int(value)


def import_season_workbook(
    file_bytes: bytes, create_new: bool, score_system: str | None = None
) -> ImportedSeason:
    """Read the workbook and write the season it holds."""
    # sheet_name=None reads every sheet, so the workbook is parsed once
    frames = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
    sheets = {name: strip_text(frame) for name, frame in frames.items()}
    with Session.begin() as session:
        return _write(session, sheets, create_new, score_system)


def _rows(frame: pd.DataFrame | None, required: list[str]) -> list[pd.Series]:
    """The rows of a sheet that carry every column the import reads. A
    workbook without an optional sheet answers no rows."""
    if frame is None:
        return []
    return [row for _, row in frame.dropna(subset=required).iterrows()]


def _apply(obj: SQLModel, values: SQLModel) -> None:
    """Write the fields the workbook carried onto a stored row."""
    for name, value in values.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)


def _write(
    session: OrmSession, sheets: Sheets, create_new: bool, score_system: str | None
) -> ImportedSeason:
    """Write every sheet of the workbook through one session."""
    season = _season(session, sheets, create_new, _score_system(sheets, score_system))
    maps = _maps(session, sheets, season)
    teams = _teams(session, sheets, season)
    users = _players(session, sheets, season, teams)
    matches = _matches(session, sheets, season, teams, maps)
    series = _series(session, sheets, matches, users)
    _fantasy_users(session, sheets, users)
    fantasy_teams = _fantasy_teams(session, sheets, season, teams, users)
    _fantasy_players(session, sheets, fantasy_teams, users)
    duplicate_bets = _fantasy_bets(session, sheets, season, series, users)
    logger.info(f"Import completed for season: {season.name}")
    return ImportedSeason(id=season.id, name=season.name, duplicate_bets=duplicate_bets)


def _known_system(system: str) -> str:
    """A score system the scoring rule knows."""
    if system not in MAX_POINTS:
        raise BadRequestError(f"Unknown score system: {system}")
    return system


def _detected_system(sheets: Sheets) -> str:
    """The score system the played series imply. A series pays 3 points
    across both sides under standard and 4 under helpstone."""
    frame = sheets.get("Series")
    columns = ["Player1 Points", "Player2 Points"]
    if frame is None or not all(column in frame.columns for column in columns):
        logger.info(f"Score system {DEFAULT_SYSTEM}: the workbook carries no points")
        return DEFAULT_SYSTEM

    # A losing side writes an empty cell, so a played row carries one value
    played = frame[columns].apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if played.empty:
        logger.info(f"Score system {DEFAULT_SYSTEM}: the workbook has no played series")
        return DEFAULT_SYSTEM

    mean = float(played.fillna(0).sum(axis=1).mean())
    system = "helpstone" if mean >= 3.5 else DEFAULT_SYSTEM
    logger.info(
        f"Score system {system}: {len(played)} played series mean {mean:.2f} points"
    )
    return system


def _score_system(sheets: Sheets, override: str | None) -> str:
    """The score system of the import: the request, then the Season sheet,
    then what the played series imply."""
    if override is not None:
        logger.info(f"Score system {override}: named by the request")
        return _known_system(override)

    row = sheets["Season"].iloc[0]
    if "Score System" in row.index and cell_value(row["Score System"]) is not None:
        system = str(row["Score System"])
        logger.info(f"Score system {system}: named by the Season sheet")
        return _known_system(system)

    return _detected_system(sheets)


def _season(
    session: OrmSession, sheets: Sheets, create_new: bool, score_system: str
) -> Season:
    """The season row. Its name matches it, because the id the file carries
    belongs to the database the file was exported from."""
    row = sheets["Season"].iloc[0]
    data = {
        "name": row["Name"],
        "number_weeks": whole_number(row["Number of Weeks"]) or 0,
        "series_per_week": whole_number(row["Series Per Week"]) or 0,
        "pick_ban": cell_value(row["Pick Ban"]),
        "discordRole": cell_value(row["Discord Role"]),
        "score_system": score_system,
    }
    for name, column in (("start_date", "Start Date"), ("end_date", "End Date")):
        if cell_value(row[column]) is not None:
            data[name] = row[column]
    values = SeasonCreate(**data)

    stored = None
    if not create_new:
        stored = session.scalars(
            select(Season).where(Season.name == values.name)
        ).first()
    if stored:
        _apply(stored, values)
        logger.info(f"Updating season {values.name} with ID: {stored.id}")
        return stored

    season = Season(**values.model_dump())
    session.add(season)
    session.flush()
    logger.info(f"Created new season with ID: {season.id}")
    return season


def _maps(session: OrmSession, sheets: Sheets, season: Season) -> dict[int, int]:
    """The map pool of the season, matched by shortname."""
    rows = _rows(sheets.get("Maps"), ["Name"])
    values = [
        MapCreate(
            name=row["Name"],
            shortname=row["Shortname"],
            image=cell_value(row["Image URL"]),
        )
        for row in rows
    ]
    wanted = {value.shortname for value in values if value.shortname is not None}
    stored: dict[str, Map] = {}
    if wanted:
        stored = {
            map_obj.shortname: map_obj
            for map_obj in session.scalars(select(Map).where(Map.shortname.in_(wanted)))
        }

    written: list[Map] = []
    pool: list[Map] = []
    old_ids: dict[int, Map] = {}
    for row, value in zip(rows, values, strict=True):
        map_obj = stored.get(value.shortname)
        if map_obj:
            _apply(map_obj, value)
        else:
            map_obj = Map(**value.model_dump())
            written.append(map_obj)
            if value.shortname is not None:
                stored[value.shortname] = map_obj
        pool.append(map_obj)
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = map_obj
    session.add_all(written)
    session.flush()

    if pool:
        linked = set(
            session.scalars(
                select(DBMapSeason.map_id).where(DBMapSeason.season_id == season.id)
            )
        )
        session.add_all(
            [
                DBMapSeason(season_id=season.id, map_id=map_id)
                for map_id in {map_obj.id for map_obj in pool} - linked
            ]
        )
    return {old_id: map_obj.id for old_id, map_obj in old_ids.items()}


def _teams(session: OrmSession, sheets: Sheets, season: Season) -> dict[int, int]:
    """The teams of the season, matched by name."""
    rows = _rows(sheets["Teams"], ["Name"])
    values = [
        TeamCreate(
            name=row["Name"],
            long_name=cell_value(row["Long Name"]),
            discord_role=cell_value(row["Discord Role"]),
        )
        for row in rows
    ]
    stored = {
        team.name: team
        for team in session.scalars(
            select(Team).where(Team.name.in_({value.name for value in values}))
        )
    }

    written: list[Team] = []
    old_ids: dict[int, Team] = {}
    for row, value in zip(rows, values, strict=True):
        team = stored.get(value.name)
        if team:
            _apply(team, value)
        else:
            team = Team(**value.model_dump())
            written.append(team)
            stored[value.name] = team
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = team
    session.add_all(written)
    session.flush()

    team_ids = {team.id for team in old_ids.values()}
    if team_ids:
        linked = set(
            session.scalars(
                select(DBTeamSeason.team_id).where(DBTeamSeason.season_id == season.id)
            )
        )
        session.add_all(
            [
                DBTeamSeason(season_id=season.id, team_id=team_id)
                for team_id in team_ids - linked
            ]
        )
    return {old_id: team.id for old_id, team in old_ids.items()}


def _player_values(row: pd.Series) -> UserCreate:
    """A player of the Players sheet. An empty cell leaves the field unset,
    so a column the workbook does not carry writes nothing."""
    data: dict[str, Any] = {"battleTag": row["Battle Tag"]}
    columns = {
        "name": "Name",
        "discordTag": "Discord Tag",
        "discordId": "Discord ID",
        "race": "Race",
        "mmr": "MMR",
        "country": "Country",
        "fantasy_tier": "Fantasy Tier",
    }
    for name, column in columns.items():
        if cell_value(row[column]) is not None:
            data[name] = row[column]
    try:
        return UserCreate(**data)
    except ValidationError as error:
        missing = ", ".join(str(detail["loc"][0]) for detail in error.errors())
        raise BadRequestError(
            f"Player {row['ID']} of the Players sheet has no {missing}"
        ) from error


def _players(
    session: OrmSession, sheets: Sheets, season: Season, teams: dict[int, int]
) -> Users:
    """The rostered players, matched by battle tag. A stored player is
    reused as it stands, so the workbook overwrites no profile."""
    rows = _rows(sheets["Players"], ["Battle Tag"])
    values = [_player_values(row) for row in rows]
    users = Users(
        by_tag={
            user.battleTag: user
            for user in session.scalars(
                select(User).where(
                    User.battleTag.in_({value.battleTag for value in values})
                )
            )
        }
    )

    written: list[User] = []
    for value in values:
        if value.battleTag not in users.by_tag:
            user = User(**value.model_dump())
            written.append(user)
            users.by_tag[value.battleTag] = user
    session.add_all(written)
    session.flush()

    roster: set[tuple[int, int]] = set()
    for row, value in zip(rows, values, strict=True):
        old_id = whole_number(row["ID"])
        if not old_id:
            continue
        user = users.by_tag[value.battleTag]
        users.by_old_id[old_id] = user
        team_id = teams.get(whole_number(row["Team ID"]))
        if team_id:
            roster.add((user.id, team_id))

    if roster:
        linked = set(
            session.execute(
                select(DBUserTeamSeason.user_id, DBUserTeamSeason.team_id).where(
                    DBUserTeamSeason.season_id == season.id
                )
            ).all()
        )
        session.add_all(
            [
                DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=season.id)
                for user_id, team_id in roster - linked
            ]
        )
    return users


def _matches(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    teams: dict[int, int],
    maps: dict[int, int],
) -> dict[int, int]:
    """The matches of the season, matched by the two teams and the playday."""
    rows = _rows(sheets["Matches"], ["Team1 ID", "Team2 ID", "Playday"])
    stored = {
        (match.team1_id, match.team2_id, match.playday): match
        for match in session.scalars(select(Match).where(Match.season_id == season.id))
    }

    written: list[Match] = []
    old_ids: dict[int, Match] = {}
    for row in rows:
        team1_id = teams.get(whole_number(row["Team1 ID"]))
        team2_id = teams.get(whole_number(row["Team2 ID"]))
        if not team1_id or not team2_id:
            raise BadRequestError(f"Match {row['ID']} names a team the workbook lacks")
        values = MatchCreate(
            team1_id=team1_id,
            team2_id=team2_id,
            season_id=season.id,
            playday=whole_number(row["Playday"]),
            fixed_map_id=maps.get(whole_number(row["Fixed Map ID"])),
            date_frame=cell_value(row["Date Frame"]),
        )
        key = (team1_id, team2_id, values.playday)
        match = stored.get(key)
        if match:
            _apply(match, values)
        else:
            match = Match(**values.model_dump())
            written.append(match)
            stored[key] = match
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = match
    session.add_all(written)
    session.flush()
    return {old_id: match.id for old_id, match in old_ids.items()}


def _series_values(
    row: pd.Series, match_id: int, player1: User, player2: User, host: User
) -> SeriesCreate:
    """A series of the Series sheet. An empty date leaves the field unset,
    so a stored series keeps the time it already holds."""
    data: dict[str, Any] = {
        "match_id": match_id,
        "player1_id": player1.id,
        "player2_id": player2.id,
        "player1_score": whole_number(row["Player1 Score"]),
        "player2_score": whole_number(row["Player2 Score"]),
        "host_player_id": host.id,
        "caster": cell_value(row["Caster"]),
        "is_fantasy_match": bool(cell_value(row["Is Fantasy Match"])),
    }
    if cell_value(row["Date Time"]) is not None:
        data["date_time"] = row["Date Time"]
    return SeriesCreate(**data)


def _series(
    session: OrmSession, sheets: Sheets, matches: dict[int, int], users: Users
) -> dict[int, int]:
    """The series of those matches, matched by match and the two players."""
    rows = _rows(sheets["Series"], ["Match ID", "Player1 ID", "Player2 ID"])
    match_ids = set(matches.values())
    stored: dict[tuple[int, int, int], Series] = {}
    if match_ids:
        stored = {
            (series.match_id, series.player1_id, series.player2_id): series
            for series in session.scalars(
                select(Series).where(Series.match_id.in_(match_ids))
            )
        }

    written: list[Series] = []
    old_ids: dict[int, Series] = {}
    for row in rows:
        match_id = matches.get(whole_number(row["Match ID"]))
        player1 = users.by_old_id.get(whole_number(row["Player1 ID"]))
        player2 = users.by_old_id.get(whole_number(row["Player2 ID"]))
        if not match_id or not player1 or not player2:
            raise BadRequestError(
                f"Series {row['ID']} names a match or a player the workbook lacks"
            )
        host = users.by_old_id.get(whole_number(row["Host Player ID"])) or player1
        values = _series_values(row, match_id, player1, player2, host)
        key = (match_id, player1.id, player2.id)
        series = stored.get(key)
        if series:
            _apply(series, values)
        else:
            series = Series(**values.model_dump())
            written.append(series)
            stored[key] = series
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = series
    session.add_all(written)
    session.flush()
    return {old_id: series.id for old_id, series in old_ids.items()}


def _fantasy_users(session: OrmSession, sheets: Sheets, users: Users) -> None:
    """The captains and bettors on no roster, mapped before the sheets that
    name them. A stored player is reused as it stands."""
    rows = _rows(sheets.get("Fantasy Users"), ["ID", "Battle Tag"])
    values = [
        UserCreate(
            battleTag=row["Battle Tag"],
            # A fantasy user plays no series, and the sheet carries no race
            race=Race.RANDOM,
            name=cell_value(row["Name"]) or row["Battle Tag"],
            discordTag=cell_value(row["Discord Tag"]) or "",
            discordId=cell_value(row["Discord ID"]) or "",
        )
        for row in rows
    ]
    unknown = {
        value.battleTag for value in values if value.battleTag not in users.by_tag
    }
    if unknown:
        for user in session.scalars(select(User).where(User.battleTag.in_(unknown))):
            users.by_tag[user.battleTag] = user

    written: list[User] = []
    for value in values:
        if value.battleTag not in users.by_tag:
            user = User(**value.model_dump())
            written.append(user)
            users.by_tag[value.battleTag] = user
    session.add_all(written)
    session.flush()

    for row, value in zip(rows, values, strict=True):
        old_id = whole_number(row["ID"])
        users.by_old_id.setdefault(old_id, users.by_tag[value.battleTag])


def _fantasy_teams(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    teams: dict[int, int],
    users: Users,
) -> dict[int, int]:
    """The fantasy teams of the season, matched by captain."""
    rows = _rows(sheets.get("Fantasy Teams"), ["Name", "Captain ID"])
    stored = {
        fteam.captain_id: fteam
        for fteam in session.scalars(
            select(FantasyTeam).where(FantasyTeam.season_id == season.id)
        )
    }

    written: list[FantasyTeam] = []
    old_ids: dict[int, FantasyTeam] = {}
    for row in rows:
        captain = users.by_old_id.get(whole_number(row["Captain ID"]))
        if not captain:
            logger.warning(f"Skipping fantasy team - captain not named: {row['Name']}")
            continue
        values = FantasyTeamCreate(
            name=row["Name"],
            season_id=season.id,
            captain_id=captain.id,
            drafted_team_id=teams.get(whole_number(row["Drafted Team ID"])),
            drafted_race=cell_value(row["Drafted Race"]),
        )
        fteam = stored.get(captain.id)
        if fteam:
            _apply(fteam, values)
        else:
            fteam = FantasyTeam(**values.model_dump())
            written.append(fteam)
            stored[captain.id] = fteam
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = fteam
    session.add_all(written)
    session.flush()
    return {old_id: fteam.id for old_id, fteam in old_ids.items()}


def _fantasy_players(
    session: OrmSession, sheets: Sheets, fantasy_teams: dict[int, int], users: Users
) -> None:
    """The drafted players of each fantasy team."""
    drafted: set[tuple[int, int]] = set()
    for row in _rows(
        sheets.get("Fantasy Team Players"), ["Fantasy Team ID", "Player ID"]
    ):
        fteam_id = fantasy_teams.get(whole_number(row["Fantasy Team ID"]))
        user = users.by_old_id.get(whole_number(row["Player ID"]))
        if fteam_id and user:
            drafted.add((fteam_id, user.id))
    if not drafted:
        return

    linked = set(
        session.execute(
            select(
                DBFantasyTeamPlayer.fantasy_team_id, DBFantasyTeamPlayer.user_id
            ).where(
                DBFantasyTeamPlayer.fantasy_team_id.in_(set(fantasy_teams.values()))
            )
        ).all()
    )
    session.add_all(
        [
            DBFantasyTeamPlayer(fantasy_team_id=fteam_id, user_id=user_id)
            for fteam_id, user_id in drafted - linked
        ]
    )


def _fantasy_bets(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    series: dict[int, int],
    users: Users,
) -> int:
    """The bets of the season, matched by series and bettor. Answers how
    many rows repeat a key an earlier row of the sheet already held."""
    rows = _rows(sheets.get("Fantasy Bets"), ["Series ID", "User ID", "Winner ID"])
    if not rows:
        return 0
    stored = {
        (bet.series_id, bet.user_id): bet
        for bet in session.scalars(
            select(FantasyBet).where(FantasyBet.season_id == season.id)
        )
    }

    written: list[FantasyBet] = []
    seen: set[tuple[int, int]] = set()
    duplicates = 0
    for row in rows:
        series_id = series.get(whole_number(row["Series ID"]))
        user = users.by_old_id.get(whole_number(row["User ID"]))
        winner = users.by_old_id.get(whole_number(row["Winner ID"]))
        if not series_id or not user or not winner:
            logger.warning(
                f"Skipping fantasy bet - row not in the workbook: {row['ID']}"
            )
            continue
        values = FantasyBetCreate(
            season_id=season.id,
            series_id=series_id,
            user_id=user.id,
            winner_id=winner.id,
            bet_points=whole_number(row["Bet Points"]) or 0,
        )
        key = (series_id, user.id)
        if key in seen:
            duplicates += 1
        seen.add(key)
        bet = stored.get(key)
        if bet:
            _apply(bet, values)
        else:
            bet = FantasyBet(**values.model_dump())
            written.append(bet)
            stored[key] = bet
    session.add_all(written)
    if duplicates:
        logger.warning(f"Skipped {duplicates} repeated rows of the Fantasy Bets sheet")
    return duplicates
