"""Cutting an entrant pool into divisions.

The rule the frontend draws in src/helpers/divisions.mjs, written once here.
Divisions come strongest first, the way event_division.position reads them,
so the bands descend where the frontend's bands ascend.
"""

from collections.abc import Sequence

# One division as the cut reads it: its lower bound, or how many it takes
type Band = tuple[int | None, int | None]
# One entrant as the cut reads it: its id and the rating of its signup race
type Rated = tuple[int, int | None]


def cut(rated: Sequence[Rated], bands: Sequence[Band]) -> dict[int, int]:
    """Each entrant id against the index of the band it falls in.

    A band list that names any size cuts by size from the top and the last
    band takes what is left; otherwise every entrant falls in the first band
    its rating reaches. An unrated entrant sits in the weakest band.
    """
    if any(size for _, size in bands):
        return _by_size(rated, [size for _, size in bands])
    return _by_bound(rated, [bound for bound, _ in bands])


def _by_size(rated: Sequence[Rated], sizes: Sequence[int | None]) -> dict[int, int]:
    """The strongest `size` entrants fill each band in turn, the id breaking ties."""
    order = sorted(rated, key=lambda pair: (-(pair[1] or 0), pair[0]))
    bands: dict[int, int] = {}
    at = 0
    for index, size in enumerate(sizes):
        left = len(order) - at
        take = left if index == len(sizes) - 1 else min(size or 0, left)
        for entrant_id, _ in order[at : at + take]:
            bands[entrant_id] = index
        at += take
    return bands


def _by_bound(rated: Sequence[Rated], bounds: Sequence[int | None]) -> dict[int, int]:
    """The first band whose lower bound the rating reaches, counting from the top."""
    weakest = len(bounds) - 1
    return {
        entrant_id: next(
            (
                index
                for index, bound in enumerate(bounds)
                if bound is not None and (mmr or 0) >= bound
            ),
            weakest,
        )
        for entrant_id, mmr in rated
    }
