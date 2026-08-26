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
