"""Per-day capture universe from condition-search inclusion logs."""

from __future__ import annotations

import csv


def parse_hhmmss(text: str) -> int:
    """Convert HHMM, HH:MM, HHMMSS, or HH:MM:SS to seconds since midnight."""
    raw = str(text).strip()
    parts = raw.split(":")
    if len(parts) == 1:
        digits = raw
        if not digits.isdigit() or len(digits) not in (4, 6):
            raise ValueError(f"시간 형식 오류: {text!r}")
        values = (int(digits[:2]), int(digits[2:4]), int(digits[4:6] or "0"))
    elif len(parts) in (2, 3) and all(part.isdigit() for part in parts):
        if len(parts[0]) not in (1, 2) or any(len(part) != 2 for part in parts[1:]):
            raise ValueError(f"시간 형식 오류: {text!r}")
        values = (
            int(parts[0]),
            int(parts[1]),
            int(parts[2]) if len(parts) == 3 else 0,
        )
    else:
        raise ValueError(f"시간 형식 오류: {text!r}")

    hour, minute, second = values
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"시간 범위 오류: {text!r}")
    return hour * 3600 + minute * 60 + second


def capture_minute(seconds: int) -> int:
    """Return the first minute boundary at or after a capture time."""
    return (int(seconds) + 59) // 60


def load_universe(
    path: str, capture_from: str, capture_to: str
) -> dict[str, dict[str, int]]:
    lo, hi = parse_hhmmss(capture_from), parse_hhmmss(capture_to)
    if lo > hi:
        raise ValueError("universe.capture_from must be <= universe.capture_to")

    first: dict[tuple[str, str], int] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"date", "code", "time"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("universe CSV must contain date,code,time columns")
        for line, row in enumerate(reader, start=2):
            date = "".join(ch for ch in (row.get("date") or "") if ch.isdigit())
            raw_code = (row.get("code") or "").strip().upper()
            if raw_code.startswith("A"):
                raw_code = raw_code[1:]
            if not date or not raw_code or not (row.get("time") or "").strip():
                continue
            date = date[:8]
            if len(date) != 8 or not date.isdigit():
                continue
            if not raw_code.isdigit() or len(raw_code) > 6:
                continue
            code = raw_code.zfill(6)
            try:
                sec = parse_hhmmss(row["time"].strip())
            except ValueError as exc:
                raise ValueError(f"universe CSV line {line}: {exc}") from exc
            key = (code, date)
            if key not in first or sec < first[key]:
                first[key] = sec

    out: dict[str, dict[str, int]] = {}
    for (code, date), sec in first.items():
        if lo <= sec <= hi:
            out.setdefault(code, {})[date] = sec
    return out


def universe_symbols(universe: dict[str, dict[str, int]]) -> list[str]:
    return sorted(universe)


def universe_range(universe: dict[str, dict[str, int]]) -> tuple[str, str] | None:
    dates = sorted({day for days in universe.values() for day in days})
    return (dates[0], dates[-1]) if dates else None


def watch_phase(
    capture: dict[str, int] | None, day: str, minute_of_day: int, watch_start_min: int
) -> str:
    """Return off before capture, pre before watch start, or live for entries."""
    if capture is None:
        start = watch_start_min
    else:
        seconds = capture.get(day)
        if seconds is None:
            return "off"
        start = max(capture_minute(seconds), watch_start_min)
    return "live" if minute_of_day >= start else "pre"
