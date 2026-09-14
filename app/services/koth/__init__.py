"""King of the Hill as a kind of event: the night, the carry and the chat signup.

A night is one event of the KOTH league with one koth stage and three
divisions, the brackets. Everything KOTH does that no other kind does lives
here, so the shared services and the stage engine never name the kind.
`legacy` answers the old /koth/* paths from the same rows until 4f drops them.
"""

from app.services.koth.carry import follow_signup, kings_of
from app.services.koth.night import close_night, open_night, tonight
from app.services.koth.nightbot import enter, signup

__all__ = [
    "close_night",
    "enter",
    "follow_signup",
    "kings_of",
    "open_night",
    "signup",
    "tonight",
]
