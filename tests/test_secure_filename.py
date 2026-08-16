"""secure_filename guards the replay names the Discord upload passes on.

The copy comes from Werkzeug. These cases pin the three properties the
caller depends on: no path separators, ASCII only, no leading dot.
"""

import pytest

from app.core.security import secure_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("game1.w3g", "game1.w3g"),
        ("../../etc/passwd", "etc_passwd"),
        ("/absolute/path.w3g", "absolute_path.w3g"),
        (".hidden.w3g", "hidden.w3g"),
        ("My Replay (1).w3g", "My_Replay_1.w3g"),
        ("späte partie.w3g", "spate_partie.w3g"),
        ("", ""),
    ],
)
def test_secure_filename(raw: str, expected: str) -> None:
    assert secure_filename(raw) == expected
