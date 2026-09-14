"""Move every past KOTH night onto the model

Each koth_events row becomes one event of the KOTH league: a koth stage of
best of one, a round for the night, and three divisions from the two
thresholds, the strongest at position 1. Each signup becomes an entrant and
each 1v1 match a series of the division's chain, with the feeder of the
series before it and one series_game for the result. Nothing is dropped; the
four koth_* tables stay, and koth_events.round_id names the round written
here.

On prod, taken 2026-09-14 before this ran: 2 nights, 9 signups, 1 match, 1
match participant. Three signups fold away, because two players signed a
night up on more than one race and only the higher MMR row is kept. No match
is a 2v1 or an FFA. One match names one participant instead of two, so it
holds no pair to play and is skipped as well; both skips are counted and
reported in the log.

Revision ID: a3f7c05b2e91
Revises: b3e7d1a5c904
Create Date: 2026-09-14 10:00:00.000000

"""

import logging
from collections.abc import Sequence
from datetime import date, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c05b2e91"
down_revision: str | Sequence[str] | None = "b3e7d1a5c904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

LEAGUE_NAME = "King of the Hill"
LEAGUE_SHORT_NAME = "KOTH"
# The old bracket numbers, weakest first; the strongest takes position 1
BRACKETS = (1, 2, 3)


def upgrade() -> None:
    bind = op.get_bind()
    nights = bind.execute(
        sa.text(
            "SELECT id, name, description, event_date, is_active, "
            "bracket_1_threshold, bracket_2_threshold "
            "FROM koth_events ORDER BY id"
        )
    ).all()
    if not nights:
        return

    league_id = _league(bind)
    users = _users(bind)
    taken = {
        str(name).strip().lower()
        for (name,) in bind.execute(sa.text("SELECT name FROM event"))
    }
    counts = {"events": 0, "entrants": 0, "series": 0, "folded": 0, "skipped": 0}

    for night in nights:
        name = _free_name(str(night.name), taken)
        taken.add(name.strip().lower())
        event_id = _event(bind, night, name, league_id)
        stage_id = _stage(bind, event_id)
        round_id = _round(bind, event_id, stage_id, _as_date(night.event_date))
        divisions = _divisions(
            bind, event_id, (0, night.bracket_1_threshold, night.bracket_2_threshold)
        )
        players, entered, folded = _entrants(bind, night.id, event_id, divisions, users)
        counts["events"] += 1
        counts["entrants"] += entered
        counts["folded"] += folded
        written, skipped = _chains(bind, night.id, round_id, divisions, players)
        counts["series"] += written
        counts["skipped"] += skipped
        bind.execute(
            sa.text("UPDATE koth_events SET round_id = :round WHERE id = :night"),
            {"round": round_id, "night": night.id},
        )

    log.info(
        "KOTH backfill: %(events)s events, %(entrants)s entrants "
        "(%(folded)s signups folded), %(series)s series, %(skipped)s matches skipped",
        counts,
    )


def downgrade() -> None:
    bind = op.get_bind()
    events = [
        row.season_id
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT r.season_id AS season_id FROM event_round r "
                "JOIN koth_events k ON k.round_id = r.id"
            )
        )
    ]
    bind.execute(sa.text("UPDATE koth_events SET round_id = NULL"))
    if not events:
        return
    ids = {"ids": tuple(events)}
    rounds = "SELECT id FROM event_round WHERE season_id IN :ids"
    series = f"SELECT id FROM series WHERE round_id IN ({rounds})"
    for statement in (
        f"DELETE FROM series_game WHERE series_id IN ({series})",
        f"DELETE FROM series WHERE round_id IN ({rounds})",
        "DELETE FROM event_round WHERE season_id IN :ids",
        "DELETE FROM event_entrant WHERE event_id IN :ids",
        "DELETE FROM event_division WHERE event_id IN :ids",
        "DELETE FROM event_stage WHERE event_id IN :ids",
        "DELETE FROM event WHERE id IN :ids",
    ):
        bind.execute(
            sa.text(statement).bindparams(sa.bindparam("ids", expanding=True)), ids
        )


def _league(bind: sa.Connection) -> int:
    """The KOTH league, written when no league carries its short name yet."""
    found = bind.execute(
        sa.text("SELECT id FROM league WHERE short_name = :short"),
        {"short": LEAGUE_SHORT_NAME},
    ).scalar()
    if found is not None:
        return int(found)
    return int(
        bind.execute(
            sa.text(
                "INSERT INTO league (name, short_name, kind, entrant_kind) "
                "VALUES (:name, :short, 'koth', 'solo') RETURNING id"
            ),
            {"name": LEAGUE_NAME, "short": LEAGUE_SHORT_NAME},
        ).scalar_one()
    )


def _event(bind: sa.Connection, night: sa.Row, name: str, league_id: int) -> int:
    """The night as one event: it takes any battle tag and asks no check-in."""
    return int(
        bind.execute(
            sa.text(
                "INSERT INTO event (name, description, series_per_round, league_id, "
                "kind, signup_policy, published, signups_open, checkin_enabled, "
                "starts_at) VALUES (:name, :description, 1, :league, 'koth', "
                "'anyone', :published, :open, :checkin, :starts_at) RETURNING id"
            ),
            {
                "name": name,
                "description": night.description,
                "league": league_id,
                "published": True,
                "open": bool(night.is_active),
                "checkin": False,
                "starts_at": night.event_date,
            },
        ).scalar_one()
    )


def _stage(bind: sa.Connection, event_id: int) -> int:
    """The one stage of the night: a chain, played over one game."""
    return int(
        bind.execute(
            sa.text(
                "INSERT INTO event_stage (event_id, position, format, best_of) "
                "VALUES (:event, 1, 'koth', 1) RETURNING id"
            ),
            {"event": event_id},
        ).scalar_one()
    )


def _round(
    bind: sa.Connection, event_id: int, stage_id: int, night: date | None
) -> int:
    """The one round of the night, played on the night's date."""
    return int(
        bind.execute(
            sa.text(
                "INSERT INTO event_round (stage_id, season_id, number, start_date) "
                "VALUES (:stage, :event, 1, :start) RETURNING id"
            ),
            {"stage": stage_id, "event": event_id, "start": night},
        ).scalar_one()
    )


def _divisions(
    bind: sa.Connection, event_id: int, bounds: Sequence[int]
) -> dict[int, int]:
    """The three brackets as divisions, the strongest at position 1."""
    divisions: dict[int, int] = {}
    for position, bracket in enumerate(reversed(BRACKETS), start=1):
        divisions[bracket] = int(
            bind.execute(
                sa.text(
                    "INSERT INTO event_division (event_id, position, name, "
                    "lower_bound) VALUES (:event, :position, :name, :bound) "
                    "RETURNING id"
                ),
                {
                    "event": event_id,
                    "position": position,
                    "name": f"Bracket {bracket}",
                    "bound": bounds[bracket - 1],
                },
            ).scalar_one()
        )
    return divisions


def _entrants(
    bind: sa.Connection,
    night_id: int,
    event_id: int,
    divisions: dict[int, int],
    users: dict[str, int],
) -> tuple[dict[int, int], int, int]:
    """One entrant per player of the night; the signup ids that map to it.

    A player who signed the night up on more than one race enters once, on the
    race of his highest MMR signup, and every signup of his points at that one
    entrant so the matches still find him.
    """
    signups = bind.execute(
        sa.text(
            "SELECT id, battle_tag, race, mmr, bracket FROM koth_signups "
            "WHERE event_id = :night ORDER BY id"
        ),
        {"night": night_id},
    ).all()
    best: dict[str, sa.Row] = {}
    for signup in signups:
        folded = str(signup.battle_tag).strip().lower()
        standing = best.get(folded)
        if standing is None or signup.mmr > standing.mmr:
            best[folded] = signup

    for folded, signup in best.items():
        user_id = users.get(folded)
        if user_id is None:
            user_id = _user(bind, str(signup.battle_tag), str(signup.race))
            users[folded] = user_id
        bind.execute(
            sa.text(
                "INSERT INTO event_entrant (event_id, user_id, race, "
                "mmr_at_seed, division_id, channel) VALUES (:event, :user, "
                ":race, :mmr, :division, 'twitch')"
            ),
            {
                "event": event_id,
                "user": user_id,
                "race": signup.race,
                "mmr": signup.mmr,
                "division": divisions.get(signup.bracket),
            },
        )

    by_signup = {
        signup.id: users[str(signup.battle_tag).strip().lower()] for signup in signups
    }
    return by_signup, len(best), len(signups) - len(best)


def _user(bind: sa.Connection, battle_tag: str, race: str) -> int:
    """A player the app has never seen: the battle tag is all that is known."""
    return int(
        bind.execute(
            sa.text(
                'INSERT INTO users (name, "battleTag", "discordTag", "discordId", '
                "race) VALUES (:name, :tag, '', '', :race) RETURNING id"
            ),
            {"name": battle_tag[:50], "tag": battle_tag, "race": race},
        ).scalar_one()
    )


def _chains(
    bind: sa.Connection,
    night_id: int,
    round_id: int,
    divisions: dict[int, int],
    players: dict[int, int],
) -> tuple[int, int]:
    """One series per 1v1 match, each chained to the one played before it.

    A 2v1 or an FFA plays no pair, and neither does a match that names any
    number of players other than two the signups know, so both are skipped
    and counted.
    """
    matches = bind.execute(
        sa.text(
            "SELECT id, bracket, game_mode, winner_team_number FROM koth_matches "
            "WHERE event_id = :night ORDER BY bracket, id"
        ),
        {"night": night_id},
    ).all()
    written = skipped = 0
    # Per bracket: the series played before, its winner, and how many stand
    previous: dict[int, tuple[int, int | None, int]] = {}
    for match in matches:
        sides = [
            (players.get(row.signup_id), row.team_number)
            for row in bind.execute(
                sa.text(
                    "SELECT signup_id, team_number FROM koth_match_participants "
                    "WHERE match_id = :match ORDER BY team_number, id"
                ),
                {"match": match.id},
            )
        ]
        if (
            str(match.game_mode) != "1v1"
            or len(sides) != 2
            or any(user is None for user, _ in sides)
        ):
            skipped += 1
            continue
        feeder, king, sequence = previous.get(match.bracket, (None, None, 0))
        if king is not None and king == sides[1][0]:
            sides.reverse()
        winner = next(
            (user for user, team in sides if team == match.winner_team_number), None
        )
        scores = (1, 0) if winner == sides[0][0] else (0, 1) if winner else (None, None)
        series_id = int(
            bind.execute(
                sa.text(
                    "INSERT INTO series (round_id, division_id, sequence, "
                    "host_player_id, player1_id, player2_id, player1_score, "
                    "player2_score, result_kind, slot1_from_series_id) VALUES "
                    "(:round, :division, :sequence, :host, :player1, :player2, "
                    ":score1, :score2, 'played', :feeder) RETURNING id"
                ),
                {
                    "round": round_id,
                    "division": divisions.get(match.bracket),
                    "sequence": sequence + 1,
                    "host": sides[0][0],
                    "player1": sides[0][0],
                    "player2": sides[1][0],
                    "score1": scores[0],
                    "score2": scores[1],
                    "feeder": feeder,
                },
            ).scalar_one()
        )
        if winner is not None:
            bind.execute(
                sa.text(
                    "INSERT INTO series_game (series_id, game_no, winner_side) "
                    "VALUES (:series, 1, :side)"
                ),
                {"series": series_id, "side": "A" if scores[0] else "B"},
            )
        previous[match.bracket] = (series_id, winner, sequence + 1)
        written += 1
    return written, skipped


def _users(bind: sa.Connection) -> dict[str, int]:
    """Every player by the battle tag folded the way the users table folds it."""
    return {
        str(tag).strip().lower(): int(user_id)
        for user_id, tag in bind.execute(sa.text('SELECT id, "battleTag" FROM users'))
    }


def _free_name(name: str, taken: set[str]) -> str:
    """The night's name, cut to the event column and kept apart from the rest."""
    stem = name.strip()[:50]
    candidate = stem
    suffix = 2
    while candidate.strip().lower() in taken:
        candidate = f"{stem[: 50 - len(str(suffix)) - 1]} {suffix}"
        suffix += 1
    return candidate


def _as_date(value: object) -> date | None:
    """The date of the night, whichever way the driver reads the column back."""
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None
