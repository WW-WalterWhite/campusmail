"""Light / dark switch for the Settings page.

.streamlit/config.toml defines a light and a dark palette, and Streamlit picks one from the
computer's setting. To force one, both palettes are pointed at the chosen colours at runtime.
This uses Streamlit's config module, which is global to the server: fine for CampusMail, which
runs on the user's own computer for one person.
"""

from __future__ import annotations

from streamlit import config

MATCH = "Match my computer"
SECTIONS = ("", ".sidebar")
_original: dict[str, dict[str, str]] | None = None


def _palettes() -> dict[str, dict[str, str]]:
    global _original
    if _original is None:  # read once, before anything is changed
        _original = {
            mode + sub: {k: v for k, v in config.get_options_for_section(f"theme.{mode}{sub}").items() if v is not None}
            for mode in ("light", "dark") for sub in SECTIONS
        }
    return _original


def apply(choice: str) -> bool:
    """Use the light or dark palette everywhere, or restore both. Returns True if anything changed,
    in which case the page should rerun so the browser receives the new theme."""
    palettes = _palettes()
    changed = False
    for mode in ("light", "dark"):
        source = mode if choice == MATCH else choice.lower()
        for sub in SECTIONS:
            for key, value in palettes.get(source + sub, {}).items():
                name = f"theme.{mode}{sub}.{key}"
                if config.get_option(name) != value:
                    config.set_option(name, value)
                    changed = True
    return changed
