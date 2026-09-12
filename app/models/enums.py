import enum


class Race(enum.Enum):
    RANDOM = "RANDOM"
    HU = "HU"
    OC = "OC"
    NE = "NE"
    UD = "UD"

    @classmethod
    def from_text(cls, text: str) -> "Race":
        """Read a race the way a person writes it, for example "Night Elf"."""
        key = " ".join(text.split()).lower()
        name = _RACE_NAMES.get(key, key.upper())
        try:
            return cls[name]
        except KeyError:
            raise ValueError(f"Unknown race: {text}") from None


_RACE_NAMES = {
    "human": "HU",
    "orc": "OC",
    "night elf": "NE",
    "nightelf": "NE",
    "undead": "UD",
    "rd": "RANDOM",
}


class RoleKind(enum.Enum):
    """What earns a bound Discord role. The name is the stored value."""

    admin = "admin"
    captain = "captain"
    team = "team"
    fantasy = "fantasy"
    gnl_participant = "gnl_participant"
    champion = "champion"


class RoleScope(enum.Enum):
    """Which seasons a bound Discord role reads. The name is the stored value."""

    current = "current"
    season = "season"
    all = "all"


class EntrantKind(enum.Enum):
    """Who enters a league's events: one player, or a team drafted for it."""

    solo = "solo"
    drafted_teams = "drafted_teams"


class EventKind(enum.Enum):
    """What one run of a league is. A GNL season is the gnl kind."""

    gnl = "gnl"
    cup = "cup"
    koth = "koth"
    signup = "signup"


class StageFormat(enum.Enum):
    """How one stage plays its entrants off. v1 builds round_robin,
    single_elimination and koth; the rest answer format_not_built."""

    round_robin = "round_robin"
    single_elimination = "single_elimination"
    double_elimination = "double_elimination"
    swiss = "swiss"
    koth = "koth"
    ffa = "ffa"


class SchedulingMode(enum.Enum):
    """Who sets the time of a series: an admin, the two sides, or nobody."""

    assigned = "assigned"
    agreed = "agreed"
    immediate = "immediate"


class SignupChannel(enum.Enum):
    """Where an entrant signed up."""

    web = "web"
    bot = "bot"
    twitch = "twitch"
