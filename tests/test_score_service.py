"""The scoring math, called directly on the service.

No Flask and no database: the score system comes from a stub settings
service, and getScoreByMapScore touches nothing else. These tests move
to any framework unchanged.

The GNL scale: losing scores keep their map score (0 or 1); a winning
2-x score converts to points from the top of the scale, and the scale
depends on the score system (standard tops at 3, helpstone at 4).
"""

import pytest

from src.service.score_service import ScoreAppService


class StubSettings:
    def __init__(self, score_system=None):
        self._value = score_system

    def get_by_key(self, key):
        if self._value is None:
            return None

        class Setting:
            value = self._value

        return Setting()


def make_service(score_system=None):
    return ScoreAppService(
        match_service=None,
        serires_service=None,
        team_service=None,
        team_season_service=None,
        season_service=None,
        settings_service=StubSettings(score_system),
    )


@pytest.mark.parametrize("player,opponent,expected", [
    (2, 0, 3),  # clean win takes the maximum
    (2, 1, 2),
    (1, 2, 1),  # a loss keeps the map score
    (0, 2, 0),
])
def test_standard_scores(player, opponent, expected):
    service = make_service("standard")
    assert service.getScoreByMapScore(player, opponent) == expected


@pytest.mark.parametrize("player,opponent,expected", [
    (2, 0, 4),
    (2, 1, 3),
    (1, 2, 1),
    (0, 2, 0),
])
def test_helpstone_scores(player, opponent, expected):
    service = make_service("helpstone")
    assert service.getScoreByMapScore(player, opponent) == expected


def test_unset_score_system_falls_back_to_standard(monkeypatch):
    monkeypatch.delenv("SCORE_SYSTEM", raising=False)
    service = make_service(None)
    assert service.getScoreByMapScore(2, 0) == 3
    assert service.getMaxPointsPerSeries() == 3


def test_unplayed_series_has_no_points():
    service = make_service("standard")
    assert service.getScoreByMapScore(None, None) is None


@pytest.mark.parametrize("player,opponent", [
    (3, 0),   # above the 0-2 map score range
    (-1, 2),
    (2, 3),
    (None, 1),  # half-reported result
])
def test_invalid_scores_raise(player, opponent):
    service = make_service("standard")
    with pytest.raises(Exception, match="Score is not valid"):
        service.getScoreByMapScore(player, opponent)


def test_max_points_per_series():
    assert make_service("standard").getMaxPointsPerSeries() == 3
    assert make_service("helpstone").getMaxPointsPerSeries() == 4
