import pytest

from apis.types import MediaItem
from utils.media import (
    ensure_not_mixed,
    is_photo,
    is_video,
    partition_photos_and_videos,
)


def _items(*types: str) -> tuple[list[MediaItem], list[bytes]]:
    media = [
        MediaItem(url=f"https://example.com/{i}", media_type=kind)
        for i, kind in enumerate(types)
    ]
    raw = [f"{kind}-{i}".encode() for i, kind in enumerate(types)]
    return media, raw


def test_is_photo_and_video_helpers():
    assert is_photo(MediaItem(url="x", media_type="photo"))
    assert is_video(MediaItem(url="x", media_type="video"))
    assert is_video(MediaItem(url="x", media_type="animated_gif"))


def test_partition_photos_only():
    media, raw = _items("photo", "photo", "photo")
    photos, videos = partition_photos_and_videos(media, raw, log_id="post-1")
    assert len(photos) == 3
    assert videos == []


def test_partition_caps_photos_at_four():
    media, raw = _items("photo", "photo", "photo", "photo", "photo")
    photos, videos = partition_photos_and_videos(media, raw, log_id="post-1")
    assert len(photos) == 4
    assert videos == []


def test_partition_video_only():
    media, raw = _items("video", "video")
    photos, videos = partition_photos_and_videos(media, raw, log_id="post-1")
    assert photos == []
    assert len(videos) == 1


def test_partition_mixed_keeps_both_lists_separate():
    media, raw = _items("photo", "photo", "video")
    photos, videos = partition_photos_and_videos(media, raw, log_id="post-1")
    assert len(photos) == 2
    assert len(videos) == 1


def test_ensure_not_mixed_raises():
    media, raw = _items("photo", "video")
    photos, videos = partition_photos_and_videos(media, raw, log_id="post-1")
    with pytest.raises(RuntimeError, match="mixed photos and videos"):
        ensure_not_mixed(photos, videos, network="TestNet")


def test_partition_mismatch_raises():
    media, _ = _items("photo")
    with pytest.raises(RuntimeError, match="Media upload mismatch"):
        partition_photos_and_videos(media, [], log_id="post-1")
