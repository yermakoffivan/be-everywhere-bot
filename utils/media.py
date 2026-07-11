"""Shared media attachment rules for destination networks."""

import logging

from apis.types import MediaItem

logger = logging.getLogger(__name__)

VIDEO_TYPES = frozenset({"video", "animated_gif"})


def is_photo(item: MediaItem) -> bool:
    return item.media_type == "photo"


def is_video(item: MediaItem) -> bool:
    return item.media_type in VIDEO_TYPES


def partition_photos_and_videos(
    media: list[MediaItem],
    raw: list[bytes],
    *,
    max_photos: int = 4,
    max_videos: int = 1,
    log_id: str = "?",
) -> tuple[list[tuple[MediaItem, bytes]], list[tuple[MediaItem, bytes]]]:
    """Split attachments into photo and video lists with per-network caps."""
    if len(raw) != len(media):
        raise RuntimeError(
            f"Media upload mismatch for post {log_id}: "
            f"{len(media)} attachment(s) but {len(raw)} downloaded"
        )

    photos: list[tuple[MediaItem, bytes]] = []
    videos: list[tuple[MediaItem, bytes]] = []
    for item, data in zip(media, raw):
        if is_photo(item):
            photos.append((item, data))
        elif is_video(item):
            videos.append((item, data))
        else:
            logger.warning(
                "[%s] Skipping unsupported media type %r",
                log_id,
                item.media_type,
            )

    if len(photos) > max_photos:
        logger.warning(
            "[%s] Keeping first %d of %d image(s)",
            log_id,
            max_photos,
            len(photos),
        )
        photos = photos[:max_photos]

    if len(videos) > max_videos:
        logger.warning(
            "[%s] Keeping first %d of %d video(s)",
            log_id,
            max_videos,
            len(videos),
        )
        videos = videos[:max_videos]

    return photos, videos


def ensure_not_mixed(
    photos: list[tuple[MediaItem, bytes]],
    videos: list[tuple[MediaItem, bytes]],
    *,
    network: str,
) -> None:
    if photos and videos:
        raise RuntimeError(
            f"{network} publish: mixed photos and videos must be split into "
            "separate outbound messages (allows_mixed_media=False upstream)"
        )
