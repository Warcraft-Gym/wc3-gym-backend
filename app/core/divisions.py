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
    its rating reaches. An entrant the answer leaves out is unplaced.
    """
    if any(size is not None for _, size in bands):
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
    """The first band whose lower bound the rating reaches, counting from the top.

    An unrated entrant falls in the weakest band while that band names no
    bound; a band list that bounds every band leaves it unplaced, because no
    band of it takes a player the cut cannot read.
    """
    weakest = len(bounds) - 1
    bands: dict[int, int] = {}
    for entrant_id, mmr in rated:
        index = next(
            (
                index
                for index, bound in enumerate(bounds)
                if bound is not None and mmr is not None and mmr >= bound
            ),
            None,
        )
        if index is None and mmr is None and bounds[weakest] is not None:
            continue
        bands[entrant_id] = weakest if index is None else index
    return bands
