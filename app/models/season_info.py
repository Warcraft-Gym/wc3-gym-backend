"""What one team scored in one season.

The row is the team_season link table; this is the shape the API sends
for it, under the name seasons_info on a team. app.services.derived fills
final_score, points_against, points_available and the series record from
the series, and names the event and its league.
"""

from sqlmodel import SQLModel


class SeasonInfoPublic(SQLModel):
    season_id: int | None = None
    # The name of that event and the short name of its league, so a team page
    # labels its season tabs without reading the events again
    name: str | None = None
    league_short_name: str | None = None
    final_score: int | None = None
    points_available: int | None = None
    points_against: int | None = None
    # Scored series of the team's fixtures in that event; the side with more
    # map wins takes one, an unscored series counts for neither
    series_won: int | None = None
    series_lost: int | None = None
