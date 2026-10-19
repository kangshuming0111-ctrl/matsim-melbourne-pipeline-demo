"""Shared trip measurement rules for summaries and evidence-checked impact analysis."""

import math

TRIP_MODES = frozenset({"car", "bike", "walk", "pt"})


def nonnegative_number(value: object) -> float | None:
    """Missing, malformed, negative and non-finite measurements are unavailable."""
    try:
        if isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_time(value: str | None) -> float | None:
    """Seconds or H+:MM:SS; hours may exceed 24 and seconds may be fractional."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    if len(parts) == 1:
        return nonnegative_number(parts[0])
    if len(parts) != 3:
        return None
    hours, minutes, seconds = (nonnegative_number(part) for part in parts)
    if None in (hours, minutes, seconds):
        return None
    if not hours.is_integer() or not minutes.is_integer() or minutes >= 60 or seconds >= 60:
        return None
    return nonnegative_number(hours * 3600 + minutes * 60 + seconds)


def trip_mode(row: dict) -> tuple[str | None, bool]:
    """Prefer main_mode; only a single recognized fallback mode is unambiguous."""
    primary = (row.get("main_mode") or "").strip()
    candidate = primary or (row.get("modes") or "").strip()
    mode = candidate if candidate in TRIP_MODES else None
    fallback = "main_mode" in row and not primary and mode is not None
    return mode, fallback


def measurement_stats(values, parser) -> tuple[float | None, dict]:
    import statistics
    valid = []
    quality = {"valid": 0, "missing": 0, "invalid": 0}
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            quality["missing"] += 1
            continue
        parsed = parser(value)
        if parsed is None:
            quality["invalid"] += 1
        else:
            valid.append(parsed)
    quality["valid"] = len(valid)
    return (statistics.mean(valid) if valid else None), quality
