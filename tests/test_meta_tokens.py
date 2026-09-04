from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from config import META_TOKEN_MIN_REMAINING_DAYS, META_TOKEN_RETRY_HOURS
from db.accounts import create_account, get_all_credentials, set_credentials
from utils.meta_tokens import (
    FACEBOOK_TOKEN,
    INSTAGRAM_TOKEN,
    THREADS_TOKEN,
    KEY_ATTEMPTED_AT,
    KEY_EXPIRES_AT,
    MetaToken,
    TokenRenewalError,
    _due_for_renewal,
    auth_error_hint,
    ensure_fresh_token,
    initialize_token,
    token_credentials,
)

SIXTY_DAYS_SECONDS = 5183944


@pytest.fixture
def threads_account(engine):
    account = create_account(engine, "threads", "default", "user-1")
    return account


def _creds(engine, account_id: int, **overrides) -> dict[str, str]:
    set_credentials(engine, account_id, {"access_token": "old-token", **overrides})
    return get_all_credentials(engine, account_id)


def _in(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_due_for_renewal_waits_while_token_has_time_left():
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=META_TOKEN_MIN_REMAINING_DAYS + 5)
    assert _due_for_renewal({}, expires_at, now) is False


def test_due_for_renewal_when_close_to_expiry():
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=META_TOKEN_MIN_REMAINING_DAYS - 1)
    assert _due_for_renewal({}, expires_at, now) is True


def test_due_for_renewal_backs_off_after_recent_attempt():
    now = datetime.now(timezone.utc)
    creds = {
        KEY_ATTEMPTED_AT: (
            now - timedelta(hours=META_TOKEN_RETRY_HOURS - 1)
        ).isoformat()
    }
    assert _due_for_renewal(creds, now + timedelta(days=1), now) is False


def test_due_for_renewal_probes_unknown_expiry():
    now = datetime.now(timezone.utc)
    assert _due_for_renewal({}, None, now) is True


@pytest.mark.asyncio
@respx.mock
async def test_ensure_fresh_token_refreshes_and_persists(engine, threads_account):
    creds = _creds(engine, threads_account.id, token_expires_at=_in(3))
    route = respx.get(THREADS_TOKEN.refresh.url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-token",
                "token_type": "bearer",
                "expires_in": SIXTY_DAYS_SECONDS,
            },
        )
    )

    token = await ensure_fresh_token(
        engine, threads_account.id, creds, THREADS_TOKEN
    )

    assert token == "new-token"
    assert route.calls[0].request.url.params["grant_type"] == "th_refresh_token"
    stored = get_all_credentials(engine, threads_account.id)
    assert stored["access_token"] == "new-token"
    expires_at = datetime.fromisoformat(stored[KEY_EXPIRES_AT])
    assert expires_at - datetime.now(timezone.utc) > timedelta(days=50)


@pytest.mark.asyncio
@respx.mock
async def test_ensure_fresh_token_skips_healthy_token(engine, threads_account):
    creds = _creds(engine, threads_account.id, token_expires_at=_in(45))
    route = respx.get(THREADS_TOKEN.refresh.url)

    token = await ensure_fresh_token(
        engine, threads_account.id, creds, THREADS_TOKEN
    )

    assert token == "old-token"
    assert not route.called


@pytest.mark.asyncio
async def test_ensure_fresh_token_rejects_expired_token(engine, threads_account):
    creds = _creds(engine, threads_account.id, token_expires_at=_in(-1))

    with pytest.raises(TokenRenewalError, match="Re-authenticate"):
        await ensure_fresh_token(engine, threads_account.id, creds, THREADS_TOKEN)


@pytest.mark.asyncio
@respx.mock
async def test_ensure_fresh_token_keeps_token_and_backs_off_on_failure(
    engine, threads_account
):
    creds = _creds(engine, threads_account.id, token_expires_at=_in(3))
    respx.get(THREADS_TOKEN.refresh.url).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "not old enough", "code": 190}}
        )
    )

    token = await ensure_fresh_token(
        engine, threads_account.id, creds, THREADS_TOKEN
    )

    assert token == "old-token"
    stored = get_all_credentials(engine, threads_account.id)
    assert stored["access_token"] == "old-token"
    assert KEY_ATTEMPTED_AT in stored


@pytest.mark.asyncio
@respx.mock
async def test_initialize_token_exchanges_short_lived_token():
    route = respx.get(INSTAGRAM_TOKEN.exchange.url).mock(
        return_value=httpx.Response(
            200, json={"access_token": "long-lived", "expires_in": SIXTY_DAYS_SECONDS}
        )
    )

    token = await initialize_token(
        INSTAGRAM_TOKEN, "short-lived", {"app_secret": "secret"}
    )

    assert token.access_token == "long-lived"
    assert token.renewed is True
    params = route.calls[0].request.url.params
    assert params["grant_type"] == "ig_exchange_token"
    assert params["client_secret"] == "secret"


@pytest.mark.asyncio
@respx.mock
async def test_initialize_token_falls_back_to_refresh_without_secret():
    respx.get(INSTAGRAM_TOKEN.refresh.url).mock(
        return_value=httpx.Response(
            200, json={"access_token": "renewed", "expires_in": SIXTY_DAYS_SECONDS}
        )
    )

    token = await initialize_token(INSTAGRAM_TOKEN, "pasted", {})

    assert token.access_token == "renewed"


@pytest.mark.asyncio
@respx.mock
async def test_initialize_token_keeps_token_when_meta_refuses():
    respx.get(INSTAGRAM_TOKEN.refresh.url).mock(
        return_value=httpx.Response(400, json={"error": {"message": "too young"}})
    )

    token = await initialize_token(INSTAGRAM_TOKEN, "pasted", {})

    assert token == MetaToken(access_token="pasted", expires_at=None, renewed=False)
    assert token_credentials(token)[KEY_EXPIRES_AT] == ""


@pytest.mark.asyncio
@respx.mock
async def test_facebook_token_renewal_uses_app_credentials(engine):
    account = create_account(engine, "instagram", "default", "ig-1")
    creds = _creds(
        engine,
        account.id,
        token_kind="facebook",
        app_id="123",
        app_secret="secret",
        token_expires_at=_in(2),
    )
    route = respx.get(FACEBOOK_TOKEN.refresh.url).mock(
        return_value=httpx.Response(
            200, json={"access_token": "fb-new", "expires_in": SIXTY_DAYS_SECONDS}
        )
    )

    token = await ensure_fresh_token(engine, account.id, creds, FACEBOOK_TOKEN)

    assert token == "fb-new"
    params = route.calls[0].request.url.params
    assert params["grant_type"] == "fb_exchange_token"
    assert params["fb_exchange_token"] == "old-token"
    assert params["client_id"] == "123"


@pytest.mark.asyncio
async def test_facebook_renewal_without_app_id_is_reported(engine):
    account = create_account(engine, "instagram", "default", "ig-1")
    creds = _creds(engine, account.id, token_kind="facebook", token_expires_at=_in(2))

    token = await ensure_fresh_token(engine, account.id, creds, FACEBOOK_TOKEN)

    assert token == "old-token"


def test_auth_error_hint_detects_expired_session():
    hint = auth_error_hint(THREADS_TOKEN)
    message = hint(
        400,
        {
            "error": {
                "message": "Error validating access token: Session has expired",
                "type": "OAuthException",
                "code": 190,
            }
        },
    )
    assert message is not None
    assert "--auth=threads" in message


def test_auth_error_hint_ignores_other_errors():
    hint = auth_error_hint(THREADS_TOKEN)
    assert hint(400, {"error": {"message": "bad field", "code": 100}}) is None
    assert hint(500, "boom") is None
