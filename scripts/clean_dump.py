"""Turn a prod /dump zip into a seed directory of CSVs: blank the Nightbot token, drop the
named seasons and their rows, drop the repeated bets and the stored score columns the app
now derives at read.

usage: uv run python scripts/clean_dump.py <in.zip> <out_dir> [season_id ...]
"""

import csv
import io
import sys
import zipfile
from operator import itemgetter
from pathlib import Path

csv.field_size_limit(sys.maxsize)
DERIVED = {
    "fantasy_bets": {"bet_result"},
    "fantasy_teams": {
        "player_points",
        "bench_points",
        "team_points",
        "race_points",
        "bet_points",
        "total_points",
    },
    "matches": {"team1_score", "team2_score"},
    "player_career_stats": {
        "rating",
        "series_won",
        "series_lost",
        "series_winrate",
        "games_won",
        "games_lost",
        "games_winrate",
        "seasons_played",
        "avg_series_per_season",
    },
    "series": {"player1_points", "player2_points"},
    "team_season": {
        "final_score",
        "points_available",
        "points_against",
        "maps_won",
        "maps_lost",
    },
    "user_team_season": {"games", "wins", "losses", "matchup_history"},
}
SEASON_TABLES = (
    "matches",
    "user_team_season",
    "user_season_signup",
    "team_season",
    "team_season_coach",
    "map_season",
    "fantasy_bets",
    "fantasy_teams",
)


def main(src: str, dst: str, seasons: set[str]) -> None:
    zin = zipfile.ZipFile(src)
    tables = {
        n[:-4]: list(csv.reader(io.TextIOWrapper(zin.open(n), encoding="utf-8")))
        for n in zin.namelist()
        if n.endswith(".csv")
    }

    def drop(table: str, col: str, ids: set[str]) -> set[str]:
        header, *rows = tables[table]
        i = header.index(col)
        gone = {r[0] for r in rows if r[i] in ids}
        tables[table] = [header] + [r for r in rows if r[i] not in ids]
        return gone

    for t in SEASON_TABLES:
        # A dump taken before a table existed simply has no file for it
        if t in tables:
            drop(t, "season_id", seasons)
    matches = {r[0] for r in tables["matches"][1:]}
    tables["series"] = [tables["series"][0]] + [
        r for r in tables["series"][1:] if r[1] in matches
    ]
    tables["draft_series"] = [tables["draft_series"][0]] + [
        r for r in tables["draft_series"][1:] if r[1] in matches
    ]
    fteams = {r[0] for r in tables["fantasy_teams"][1:]}
    tables["fantasy_team_player"] = [tables["fantasy_team_player"][0]] + [
        r for r in tables["fantasy_team_player"][1:] if r[0] in fteams
    ]
    used_teams = (
        {r[0] for r in tables["team_season"][1:]}
        | {r[1] for r in tables["matches"][1:]}
        | {r[2] for r in tables["matches"][1:]}
    )
    tables["teams"] = [tables["teams"][0]] + [
        r for r in tables["teams"][1:] if r[0] in used_teams
    ]
    drop("seasons", "id", seasons)
    # Prod holds one bet twice; the seeded database is unique per series and
    # bettor, so keep the row that holds the pick the bettor made last
    header, *bets = tables["fantasy_bets"]
    key = itemgetter(header.index("series_id"), header.index("user_id"))
    last = {key(row): row for row in bets}
    tables["fantasy_bets"] = [header] + [r for r in bets if last[key(r)] is r]
    for r in tables["settings"][1:]:
        if r[1] == "KOTH_NIGHTBOT_TOKEN":
            r[2] = ""

    out_dir = Path(dst)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        keep = [i for i, c in enumerate(rows[0]) if c not in DERIVED.get(name, set())]
        with (out_dir / f"{name}.csv").open("w", newline="") as f:
            csv.writer(f).writerows([r[i] for i in keep] for r in rows)
    for name, rows in sorted(tables.items()):
        print(f"{name}: {len(rows) - 1}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], set(sys.argv[3:]))
