import os
import re
import unicodedata

# secure_filename is copied from Werkzeug 3.x, BSD-3-Clause
# https://github.com/pallets/werkzeug

_filename_ascii_strip_re = re.compile(r"[^A-Za-z0-9_.-]")
_windows_device_files = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def secure_filename(filename: str) -> str:
    """Return a safe version of an untrusted filename: ASCII only, no path
    separators, no leading dots or underscores."""
    filename = unicodedata.normalize("NFKD", filename)
    filename = filename.encode("ascii", "ignore").decode("ascii")

    for sep in os.sep, os.path.altsep:
        if sep:
            filename = filename.replace(sep, " ")
    filename = str(_filename_ascii_strip_re.sub("", "_".join(filename.split()))).strip(
        "._"
    )

    # On Windows a filename must not be a reserved device name.
    if (
        os.name == "nt"
        and filename
        and filename.split(".")[0].upper() in _windows_device_files
    ):
        filename = f"_{filename}"

    return filename
