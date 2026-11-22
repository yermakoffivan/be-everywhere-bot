from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from apis.types import MediaItem
from config import NETWORK_LIMITS
from utils.thread_processor import build_outbound_posts, collect_ready_batch


@pytest.mark.parametrize("network", list(NETWORK_LIMITS))
@pytest.mark.parametrize("content", ["words", "unbroken", "unicode"])
def test_reformatting_preserves_all_text_media_and_provenance_within_destination_limits(
    post_factory, utc_now, network, content
):
    limits = NETWORK_LIMITS[network]
    texts = {
        "words": "A paragraph with words.\n\nAnother sentence follows. " * 150,
        "unbroken": "abcdef" * 1200,
        "unicode": "Привет 🌍 café 你好! " * 400,
    }
    text = texts[content].strip()
    media = [
        MediaItem(f"https://media.test/{i}.jpg", "photo", alt_text=f"Photo {i}")
        for i in range(limits.max_media_group + 1)
    ]
    root = post_factory("1", text=text, media=media[:2])
    reply = post_factory(
        "2", text="Last paragraph", media=media[2:], conversation_id="1",
        created_at=utc_now + timedelta(minutes=1), in_reply_to_id="1",
    )
    posts = [reply, root]
    original = deepcopy(posts)

    outbounds = build_outbound_posts(posts, limits)

    assert outbounds
    assert "".join("".join(out.text.split()) for out in outbounds) == "".join((text + "Last paragraph").split())
    if content != "unbroken":
        assert " ".join(out.text for out in outbounds).split() == (text + " Last paragraph").split()
    assert [item for out in outbounds for item in out.media] == media
    for source in (root, reply):
        parts = [out for out in outbounds if out.source_post_ids == [source.id]]
        assert "".join("".join(out.text.split()) for out in parts) == "".join(source.text.split())
        assert [item for out in parts for item in out.media] == source.media
    assert all(len(out.source_post_ids) == 1 for out in outbounds)
    assert all(len(out.media) <= limits.max_media_group for out in outbounds)
    assert all(len(out.text) <= (limits.max_caption if out.media else limits.max_text) for out in outbounds)
    assert all(out.text or out.media for out in outbounds)
    assert posts == original


@pytest.mark.parametrize("network", list(NETWORK_LIMITS))
def test_mixed_media_preserves_each_attachment_and_caption_once(post_factory, network):
    limits = NETWORK_LIMITS[network]
    media = [
        MediaItem("https://media.test/first.mp4", "video"),
        MediaItem("https://media.test/second.jpg", "photo", alt_text="Second"),
        MediaItem("https://media.test/third.gif", "animated_gif"),
        MediaItem("https://media.test/fourth.jpg", "photo", alt_text="Fourth"),
    ]
    post = post_factory("1", text="Caption", media=media)

    outbounds = build_outbound_posts([post], limits)

    assert "".join(out.text for out in outbounds) == "Caption"
    attachments = [item for out in outbounds for item in out.media]
    assert sorted(item.url for item in attachments) == sorted(item.url for item in media)
    assert [item for item in attachments if item.media_type == "photo"] == [media[1], media[3]]
    assert [item for item in attachments if item.media_type != "photo"] == [media[0], media[2]]
    assert all(out.source_post_ids == ["1"] for out in outbounds)
    assert attachments == media
    if not limits.allows_mixed_media:
        for out in outbounds:
            assert not (any(item.media_type == "photo" for item in out.media) and any(item.media_type != "photo" for item in out.media))


@pytest.mark.parametrize("already_synced", [False, True])
def test_thread_age_gate_depends_on_root_and_destination_sync_state(post_factory, already_synced):
    now = datetime.now(timezone.utc)
    root = post_factory("1", created_at=now - timedelta(minutes=5))
    reply = post_factory(
        "2", created_at=now - timedelta(minutes=1), conversation_id="1", in_reply_to_id="1"
    )

    ready = collect_ready_batch(
        [reply, root], is_synced=lambda post_id: already_synced and post_id == "1",
        enforce_min_age=True, min_age_minutes=20,
    )

    assert [post.id for post in ready] == (["2"] if already_synced else [])


def test_media_only_thread_retains_attachments_without_inventing_text(post_factory, utc_now):
    first = MediaItem("https://media.test/first.jpg", "photo")
    second = MediaItem("https://media.test/second.jpg", "photo")
    root = post_factory("1", text="", media=[first])
    reply = post_factory(
        "2", text="  ", media=[second], conversation_id="1",
        created_at=utc_now + timedelta(minutes=1),
    )

    outbounds = build_outbound_posts([reply, root], NETWORK_LIMITS["telegram"])

    assert [item for out in outbounds for item in out.media] == [first, second]
    assert all(out.text == "" for out in outbounds)
    assert all(out.source_post_ids == ["1", "2"] for out in outbounds)


@pytest.mark.parametrize("network", ["mastodon", "bluesky"])
def test_multiple_videos_are_split_without_losing_attachments(post_factory, network):
    videos = [MediaItem(f"https://media.test/{index}.mp4", "video") for index in range(3)]
    post = post_factory("1", text="Three videos", media=videos)

    outbounds = build_outbound_posts([post], NETWORK_LIMITS[network])

    assert [out.media for out in outbounds] == [[video] for video in videos]
    assert "".join(out.text for out in outbounds) == "Three videos"
    assert all(out.source_post_ids == ["1"] for out in outbounds)


@pytest.mark.parametrize("network", ["mastodon", "threads", "bluesky", "twitter"])
def test_split_photo_thread_keeps_each_caption_with_its_photos(post_factory, utc_now, network):
    photos = [MediaItem(f"https://media.test/{i}.jpg", "photo") for i in range(4)]
    posts = [
        post_factory(str(i), text=letter * 250, media=media, conversation_id="0",
                     created_at=utc_now + timedelta(minutes=i))
        for i, (letter, media) in enumerate([("a", photos[:2]), ("b", []), ("c", photos[2:])])
    ]

    outbounds = build_outbound_posts(list(reversed(posts)), NETWORK_LIMITS[network])

    assert [(out.text, out.media, out.source_post_ids) for out in outbounds] == [
        (post.text, post.media, [post.id]) for post in posts
    ]


@pytest.mark.parametrize("text_length", [250, 400])
def test_telegram_photo_thread_uses_one_caption_or_one_complete_text(post_factory, utc_now, text_length):
    photos = [MediaItem(f"https://media.test/{i}.jpg", "photo") for i in range(4)]
    posts = [
        post_factory(str(i), text=letter * text_length, media=media, conversation_id="0",
                     created_at=utc_now + timedelta(minutes=i))
        for i, (letter, media) in enumerate([("a", photos[:2]), ("b", []), ("c", photos[2:])])
    ]
    joined_text = "\n\n".join(post.text for post in posts)

    outbounds = build_outbound_posts(posts, NETWORK_LIMITS["telegram"])

    assert outbounds[0].media == photos
    assert [out.text for out in outbounds if out.text] == [joined_text]
    assert all(out.source_post_ids == ["0", "1", "2"] for out in outbounds)
    if text_length == 250:
        assert len(outbounds) == 1
    else:
        assert len(outbounds) == 2
        assert outbounds[0].text == ""
        assert outbounds[1].media == []


@pytest.mark.parametrize("network", list(NETWORK_LIMITS))
def test_short_photo_thread_combines_when_everything_fits(post_factory, utc_now, network):
    photos = [MediaItem(f"https://media.test/{i}.jpg", "photo") for i in range(2)]
    posts = [post_factory(str(i), text=f"Caption {i}", media=[photo], conversation_id="0",
                          created_at=utc_now + timedelta(minutes=i)) for i, photo in enumerate(photos)]

    outbounds = build_outbound_posts(posts, NETWORK_LIMITS[network])

    assert len(outbounds) == 1
    assert outbounds[0].text == "Caption 0\n\nCaption 1"
    assert outbounds[0].media == photos
    assert outbounds[0].source_post_ids == ["0", "1"]
