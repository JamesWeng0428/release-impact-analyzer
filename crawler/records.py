"""Validate persisted inputs with file/line diagnostics before analysis."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile


def version_key(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise ValueError("version must contain dot-separated nonnegative integers")
    return tuple(int(part) for part in value.split("."))


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("date must be an ISO 8601 string with timezone")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must be an ISO 8601 string with timezone") from error
    if parsed.tzinfo is None:
        raise ValueError("date must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_review(record: dict) -> None:
    for field in ("id", "app_version", "date", "title", "text"):
        if not isinstance(record.get(field), str):
            raise ValueError(f"review needs string {field}")
    if not record["id"].strip():
        raise ValueError("review ID must be nonempty")
    if type(record.get("rating")) is not int or not 1 <= record["rating"] <= 5:
        raise ValueError("review rating must be an integer from 1 to 5")
    if "country" in record and not isinstance(record["country"], str):
        raise ValueError("country must be a string")
    version_key(record["app_version"])
    timestamp(record["date"])


def validate_release(record: dict) -> None:
    version_key(record.get("version"))
    timestamp(record.get("release_date"))
    if "notes" in record and not isinstance(record["notes"], str):
        raise ValueError("release notes must be a string")


def read_records(path: Path, validator, key: str, *, missing_ok: bool = False) -> list[dict]:
    if missing_ok and not path.exists():
        return []
    rows, seen = [], set()
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record must be a JSON object")
                validator(record)
                if record[key] in seen:
                    raise ValueError(f"duplicate {key}: {record[key]}")
                seen.add(record[key])
                rows.append(record)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
    return rows


def write_records(path: Path, rows: list[dict], validator) -> None:
    """Validate first, then replace atomically; failures leave the old data intact."""
    for record in rows:
        validator(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".ria-", delete=False) as stream:
            temporary = Path(stream.name)
            for record in rows:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
