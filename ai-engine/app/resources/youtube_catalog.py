import re
from collections.abc import Iterable

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
SUPPORTED_TYPES = {"youtube", "diagram", "animation", "simulation"}


def _nonnegative_int(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def select_resource(
    resources: Iterable[dict],
    *,
    subject: str,
    topic: str,
    language: str | None = None,
    class_level: int | None = None,
    concept_id: str | None = None,
) -> dict | None:
    subject_key = subject.strip().casefold()
    topic_key = topic.strip().casefold()
    language_key = language.strip().casefold() if language else None
    candidates = []

    for resource in resources:
        if resource.get("embedding_allowed") not in (True, 1, "1"):
            continue
        resource_type = str(resource.get("resource_type", "")).casefold()
        if resource_type not in SUPPORTED_TYPES:
            continue
        resource_subject = str(resource.get("subject", "")).strip().casefold()
        resource_topic = str(resource.get("topic", "")).strip().casefold()
        resource_concept = str(resource.get("concept", resource.get("concept_id", ""))).strip()
        if resource_subject != subject_key:
            continue
        if resource_topic != topic_key and (not concept_id or resource_concept != concept_id):
            continue
        if class_level is not None and resource.get("class_level") not in (None, "", class_level, str(class_level)):
            continue
        resource_language = str(resource.get("language", "")).strip().casefold()
        if language_key and resource_language and resource_language != language_key:
            continue
        if not str(resource.get("title", "")).strip():
            continue
        if not str(resource.get("resource_id") or resource.get("name") or "").strip():
            continue
        if resource_type == "youtube" and not YOUTUBE_ID.fullmatch(str(resource.get("youtube_video_id", ""))):
            continue
        candidates.append(resource)

    if not candidates:
        return None

    candidates.sort(
        key=lambda resource: (
            str(resource.get("topic", "")).strip().casefold() != topic_key,
            bool(language_key and str(resource.get("language", "")).strip().casefold() != language_key),
            _nonnegative_int(resource.get("start_time")),
        )
    )
    resource = candidates[0]
    duration = resource.get("duration")
    return {
        "type": str(resource["resource_type"]).casefold(),
        "resource_id": str(resource.get("resource_id") or resource.get("name")),
        "title": str(resource["title"]).strip()[:300],
        "video_id": str(resource["youtube_video_id"]) if resource.get("resource_type") == "youtube" else None,
        "start_time": _nonnegative_int(resource.get("start_time")),
        "duration": _nonnegative_int(duration) if duration not in (None, "") else None,
        "language": resource.get("language"),
    }
