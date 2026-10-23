"""The user's profile and settings, saved as JSON on this computer only (in the git-ignored
`private/` folder). Nothing here is sent anywhere; **Settings → Delete my saved data** removes it."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .importer import parse_course_list

DATA_DIR = Path(os.environ.get("CAMPUSMAIL_DATA_DIR", Path(__file__).resolve().parent.parent / "private"))
THEMES = ("Match my computer", "Light", "Dark")
ENGINES = ("Local AI (Ollama)", "Cloud AI (API key)", "Rules only (no AI)")

DEFAULT_PROFILE = {"name": "", "email": "", "programme": "", "year": "", "courses": []}
DEFAULT_SETTINGS = {"theme": THEMES[0], "engine": ENGINES[0], "ollama_model": "", "days_back": 14}


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def _load(name: str, default: dict) -> dict:
    try:
        data = json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    # Keep only known keys with the right type, so a hand-edited file cannot break the app.
    return {k: data[k] if isinstance(data.get(k), type(v)) else v for k, v in default.items()}


def _save(name: str, data: dict, default: dict) -> dict:
    clean = {k: data.get(k, v) for k, v in default.items()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path(name).write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return clean


def load_profile() -> dict:
    return _load("profile", DEFAULT_PROFILE)


def save_profile(profile: dict) -> dict:
    profile = dict(profile)
    courses = profile.get("courses", [])
    profile["courses"] = parse_course_list(courses if isinstance(courses, str) else ", ".join(courses))
    for key in ("name", "email", "programme", "year"):
        profile[key] = str(profile.get(key, "")).strip()[:120]
    return _save("profile", profile, DEFAULT_PROFILE)


def load_settings() -> dict:
    settings = _load("settings", DEFAULT_SETTINGS)
    if settings["theme"] not in THEMES:
        settings["theme"] = THEMES[0]
    if settings["engine"] not in ENGINES:
        settings["engine"] = ENGINES[0]
    return settings


def save_settings(settings: dict) -> dict:
    return _save("settings", settings, DEFAULT_SETTINGS)


def delete_all() -> None:
    for name in ("profile", "settings"):
        _path(name).unlink(missing_ok=True)


def first_name(profile: dict) -> str:
    return profile.get("name", "").split(" ")[0] if profile.get("name") else ""
