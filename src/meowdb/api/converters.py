from __future__ import annotations

from datetime import UTC, datetime

from meowdb.api.models import PhotoResponse


def _cache_version(dt_str: str) -> int:
    try:
        return int(datetime.fromisoformat(dt_str).replace(tzinfo=UTC).timestamp())
    except (ValueError, TypeError):
        return 0


def photo_to_response(photo: dict) -> PhotoResponse:  # type: ignore[type-arg]
    v = _cache_version(photo.get("updated_at") or photo.get("created_at", ""))
    return PhotoResponse(
        id=photo["id"],
        filename=photo["filename"],
        created_at=photo.get("created_at", ""),
        updated_at=photo.get("updated_at") or "",
        image_url=f"/api/photos/{photo['id']}/image?v={v}",
        is_default=bool(photo.get("is_default", False)),
        animal_id=photo.get("animal_id", ""),
    )
