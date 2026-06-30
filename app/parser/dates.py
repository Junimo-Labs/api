"""In-game date helpers.

Vendored from SDV-Summary's `sdv/getDate.py`, with Flask-Babel removed.
"""

from math import floor

SEASON_NAMES = {
    "0": "Spring",
    "1": "Summer",
    "2": "Fall",
    "3": "Winter",
}


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def get_date_data(stats_days_played: int) -> tuple[str, str, str]:
    day_of_month = int(((stats_days_played - 1) % 28) + 1)
    year = int(floor((stats_days_played - day_of_month) / (28 * 4)) + 1)
    season = int(floor((stats_days_played - day_of_month) / 28) - ((year - 1) * 4))
    return str(day_of_month), str(season), str(year)


def preprocess_data(data: dict) -> dict:
    if (
        data.get("dayOfMonthForSaveGame") is not None
        and int(data["dayOfMonthForSaveGame"]) > 28
    ):
        data["dayOfMonthForSaveGame"] = str(int(data["dayOfMonthForSaveGame"]) % 28)
        data["seasonForSaveGame"] = str(int(data["seasonForSaveGame"]) + 1)
    if (
        data.get("seasonForSaveGame") is not None
        and int(data["seasonForSaveGame"]) > 3
    ):
        data["seasonForSaveGame"] = str(int(data["seasonForSaveGame"]) % 4)
        data["yearForSaveGame"] = str(int(data["yearForSaveGame"]) + 1)
    return data


def format_date(day: str, season: str, year: str) -> str:
    season_name = SEASON_NAMES.get(str(season), str(season))
    try:
        day_str = _ordinal(int(day))
    except (TypeError, ValueError):
        day_str = str(day)
    return f"{day_str} of {season_name}, Year {year}"


def get_date(data: dict) -> str:
    data = preprocess_data(dict(data))
    if (
        data.get("dayOfMonthForSaveGame") is not None
        and data.get("seasonForSaveGame") is not None
        and data.get("yearForSaveGame") is not None
    ):
        return format_date(
            data["dayOfMonthForSaveGame"],
            data["seasonForSaveGame"],
            data["yearForSaveGame"],
        )
    if data.get("statsDaysPlayed") is not None:
        return format_date(*get_date_data(int(data["statsDaysPlayed"])))
    raise ValueError("Insufficient date fields in save")
