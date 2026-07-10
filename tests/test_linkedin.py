import httpx
import pytest
import respx

from apis.linkedin import (
    _encode_urn,
    _element_to_post,
    _extract_content_media,
    _is_comment_urn,
    _is_post_urn,
    _photos_only,
    _post_payload,
    _strip_commentary,
    fetch_posts,
    publish_outbound,
)
from apis.types import MediaItem, OutboundPost
from config import NETWORK_LINKEDIN
from db.accounts import create_account, set_credentials


def test_encode_urn():
    urn = "urn:li:share:12345"
    assert _encode_urn(urn) == "urn%3Ali%3Ashare%3A12345"


def test_urn_kind_detection():
    assert _is_post_urn("urn:li:share:1")
    assert _is_post_urn("urn:li:ugcPost:1")
    assert _is_comment_urn("urn:li:comment:(urn:li:activity:1,2)")
    assert not _is_post_urn("urn:li:comment:(urn:li:activity:1,2)")


def test_post_payload_text_only():
    payload = _post_payload("urn:li:person:abc", "Hello", [])
    assert payload["commentary"] == "Hello"
    assert payload["author"] == "urn:li:person:abc"
    assert "content" not in payload


def test_post_payload_single_image():
    payload = _post_payload(
        "urn:li:person:abc", "pic", [("urn:li:image:1", "alt")]
    )
    assert payload["content"]["media"]["id"] == "urn:li:image:1"
    assert payload["content"]["media"]["altText"] == "alt"


def test_post_payload_multi_image():
    payload = _post_payload(
        "urn:li:person:abc",
        "album",
        [("urn:li:image:1", None), ("urn:li:image:2", "two")],
    )
    images = payload["content"]["multiImage"]["images"]
    assert len(images) == 2
    assert images[1]["altText"] == "two"


def test_photos_only_skips_video():
    media = [
        MediaItem(url="https://x/a.jpg", media_type="photo"),
        MediaItem(url="https://x/b.mp4", media_type="video"),
    ]
    raw = [b"jpg", b"mp4"]
    photos = _photos_only(media, raw, "1")
    assert len(photos) == 1
    assert photos[0][0].media_type == "photo"


def test_strip_commentary():
    text = "Hello @[Acme](urn:li:organization:1) {hashtag|\\#|coding}"
    assert _strip_commentary(text) == "Hello @Acme #coding"


def test_element_to_post_parses_share():
    element = {
        "id": "urn:li:share:123",
        "lifecycleState": "PUBLISHED",
        "createdAt": 1634817394721,
        "commentary": "Hello world",
        "content": {},
    }
    post = _element_to_post(element, "person-1")
    assert post is not None
    assert post.id == "urn:li:share:123"
    assert post.text == "Hello world"


def test_element_to_post_skips_reshare():
    element = {
        "id": "urn:li:share:123",
        "lifecycleState": "PUBLISHED",
        "createdAt": 1634817394721,
        "commentary": "reshared",
        "reshareContext": {"parent": "urn:li:share:999"},
    }
    assert _element_to_post(element, "person-1") is None


def test_extract_content_media_multi_image():
    content = {
        "multiImage": {
            "images": [
                {"id": "urn:li:image:1", "altText": "one"},
                {"id": "urn:li:image:2"},
            ]
        }
    }
    media = _extract_content_media(content)
    assert len(media) == 2
    assert media[0].url.endswith("urn:li:image:1")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_posts(engine):
    account = create_account(engine, NETWORK_LINKEDIN, "default", "person-1")
    set_credentials(
        engine,
        account.id,
        {
            "access_token": "token",
            "person_urn": "urn:li:person:person-1",
            "display_name": "Test User",
        },
    )

    respx.get("https://api.linkedin.com/rest/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "urn:li:share:100",
                        "lifecycleState": "PUBLISHED",
                        "createdAt": 1634817394721,
                        "commentary": "From LinkedIn",
                        "content": {},
                    }
                ],
                "paging": {"start": 0, "count": 50, "total": 1, "links": []},
            },
        )
    )

    posts = await fetch_posts(engine, account.id)
    assert len(posts) == 1
    assert posts[0].text == "From LinkedIn"
    assert posts[0].id == "urn:li:share:100"


@pytest.mark.asyncio
@respx.mock
async def test_publish_outbound_text_post(engine):
    account = create_account(engine, NETWORK_LINKEDIN, "default", "person-1")
    set_credentials(
        engine,
        account.id,
        {
            "access_token": "token",
            "person_urn": "urn:li:person:person-1",
            "display_name": "Test User",
        },
    )

    route = respx.post("https://api.linkedin.com/rest/posts").mock(
        return_value=httpx.Response(
            201,
            headers={"x-restli-id": "urn:li:share:999"},
        )
    )

    result = await publish_outbound(
        engine,
        account.id,
        OutboundPost(text="Hello LinkedIn", source_post_ids=["1"]),
        [],
    )

    assert result.post_id == "urn:li:share:999"
    assert result.reply_ref == "urn:li:share:999"
    assert route.called
    body = route.calls[0].request.content.decode()
    assert "Hello LinkedIn" in body


@pytest.mark.asyncio
@respx.mock
async def test_publish_outbound_thread_comment(engine):
    account = create_account(engine, NETWORK_LINKEDIN, "default", "person-1")
    set_credentials(
        engine,
        account.id,
        {
            "access_token": "token",
            "person_urn": "urn:li:person:person-1",
            "display_name": "Test User",
        },
    )

    share_urn = "urn:li:share:999"
    encoded = _encode_urn(share_urn)
    route = respx.post(
        f"https://api.linkedin.com/rest/socialActions/{encoded}/comments"
    ).mock(
        return_value=httpx.Response(
            201,
            headers={
                "x-restli-id": "urn:li:comment:(urn:li:activity:1,comment-2)"
            },
        )
    )

    result = await publish_outbound(
        engine,
        account.id,
        OutboundPost(text="Part two", source_post_ids=["2"]),
        [],
        reply_to=share_urn,
    )

    assert "comment" in result.post_id
    assert route.called
    body = route.calls[0].request.content.decode()
    assert "Part two" in body
    assert share_urn in body
