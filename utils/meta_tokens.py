"""Automatic renewal of Meta long-lived access tokens (Threads, Instagram, Facebook).

Meta user tokens are valid for 60 days and can be renewed for another 60 only while
they are still valid — once a token lapses the account must be re-authenticated by
hand. Every call into a Meta API therefore goes through `ensure_fresh_token`, which
renews the stored token before it gets close to expiry and writes the new one back
to the credentials table.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.engine import Engine

from config import (
    INSTAGRAM_APP,
    META_TOKEN_MIN_REMAINING_DAYS,
    META_TOKEN_RETRY_HOURS,
    META_TOKEN_UNKNOWN_EXPIRY_DAYS,
    THREADS_APP,
)
from db.accounts import set_credential, set_credentials
from utils.http_utils import format_api_error, parse_error_detail

logger = logging.getLogger(__name__)

KEY_ACCESS_TOKEN = "access_token"
KEY_APP_ID = "app_id"
KEY_APP_SECRET = "app_secret"
KEY_EXPIRES_AT = "token_expires_at"
KEY_RENEWED_AT = "token_renewed_at"
KEY_ATTEMPTED_AT = "token_renew_attempted_at"

OAUTH_ERROR_CODE = 190


class TokenRenewalError(RuntimeError):
    """A token could not be exchanged or refreshed."""


@dataclass(frozen=True)
class TokenGrant:
    """One Meta OAuth token endpoint — all of them are a plain GET with query params."""

    url: str
    grant_type: str
    token_param: str = "access_token"
    needs_app_id: bool = False
    needs_app_secret: bool = False


@dataclass(frozen=True)
class MetaTokenConfig:
    api_name: str
    auth_command: str
    exchange: TokenGrant  # short-lived token -> 60-day token, needs the app secret
    refresh: TokenGrant  # 60-day token -> another 60 days


@dataclass(frozen=True)
class MetaToken:
    access_token: str
    expires_at: datetime | None
    renewed: bool = True


THREADS_TOKEN = MetaTokenConfig(
    api_name="Threads",
    auth_command="uv run python main.py --auth=threads",
    exchange=TokenGrant(
        url=f"{THREADS_APP.oauth_base_url}/access_token",
        grant_type="th_exchange_token",
        needs_app_secret=True,
    ),
    refresh=TokenGrant(
        url=f"{THREADS_APP.oauth_base_url}/refresh_access_token",
        grant_type="th_refresh_token",
    ),
)

INSTAGRAM_TOKEN = MetaTokenConfig(
    api_name="Instagram",
    auth_command="uv run python main.py --auth=instagram",
    exchange=TokenGrant(
        url=f"{INSTAGRAM_APP.oauth_base_url}/access_token",
        grant_type="ig_exchange_token",
        needs_app_secret=True,
    ),
    refresh=TokenGrant(
        url=f"{INSTAGRAM_APP.oauth_base_url}/refresh_access_token",
        grant_type="ig_refresh_token",
    ),
)

# Facebook has no refresh endpoint: re-exchanging a long-lived token extends it.
_FACEBOOK_GRANT = TokenGrant(
    url=f"{INSTAGRAM_APP.facebook_graph_url}/oauth/access_token",
    grant_type="fb_exchange_token",
    token_param="fb_exchange_token",
    needs_app_id=True,
    needs_app_secret=True,
)

FACEBOOK_TOKEN = MetaTokenConfig(
    api_name="Instagram (Facebook login)",
    auth_command="uv run python main.py --auth=instagram",
    exchange=_FACEBOOK_GRANT,
    refresh=_FACEBOOK_GRANT,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_stored_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _format_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def describe_expiry(token: MetaToken) -> str:
    if token.expires_at is None:
        return "expiry unknown"
    days = max(0, (token.expires_at - _now()).days)
    return f"valid until {_format_time(token.expires_at)} ({days} days)"


def _require_app_credential(
    config: MetaTokenConfig, creds: Mapping[str, str], key: str, label: str
) -> str:
    value = creds.get(key)
    if not value:
        raise TokenRenewalError(
            f"{config.api_name} token renewal needs the {label}. "
            f"Add it with: {config.auth_command}"
        )
    return value


def _token_from_payload(config: MetaTokenConfig, payload: dict[str, Any]) -> MetaToken:
    access_token = payload.get("access_token")
    if not access_token:
        raise TokenRenewalError(
            f"{config.api_name} token response contained no access_token"
        )
    expires_in = payload.get("expires_in")
    expires_at = (
        _now() + timedelta(seconds=int(expires_in))
        if expires_in
        else None  # Facebook omits this for tokens that never expire
    )
    return MetaToken(access_token=str(access_token), expires_at=expires_at)


async def _request_grant(
    config: MetaTokenConfig,
    grant: TokenGrant,
    access_token: str,
    creds: Mapping[str, str],
) -> MetaToken:
    params = {"grant_type": grant.grant_type, grant.token_param: access_token}
    if grant.needs_app_id:
        params["client_id"] = _require_app_credential(
            config, creds, KEY_APP_ID, "app ID"
        )
    if grant.needs_app_secret:
        params["client_secret"] = _require_app_credential(
            config, creds, KEY_APP_SECRET, "app secret"
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(grant.url, params=params)
    except httpx.HTTPError as exc:
        raise TokenRenewalError(f"{config.api_name} token request failed: {exc}") from exc

    if not response.is_success:
        raise TokenRenewalError(
            format_api_error(
                f"{config.api_name} token",
                response.status_code,
                parse_error_detail(response),
            )
        )
    return _token_from_payload(config, response.json())


async def exchange_for_long_lived(
    config: MetaTokenConfig, access_token: str, creds: Mapping[str, str]
) -> MetaToken:
    return await _request_grant(config, config.exchange, access_token, creds)


async def refresh_long_lived(
    config: MetaTokenConfig, access_token: str, creds: Mapping[str, str]
) -> MetaToken:
    return await _request_grant(config, config.refresh, access_token, creds)


async def initialize_token(
    config: MetaTokenConfig, access_token: str, creds: Mapping[str, str]
) -> MetaToken:
    """Turn a freshly pasted token into a long-lived one so it can be auto-renewed."""
    attempted: list[TokenGrant] = []

    if creds.get(KEY_APP_SECRET):
        attempted.append(config.exchange)
        try:
            return await exchange_for_long_lived(config, access_token, creds)
        except TokenRenewalError as exc:
            logger.debug("%s token exchange did not apply: %s", config.api_name, exc)

    if config.refresh not in attempted:
        try:
            return await refresh_long_lived(config, access_token, creds)
        except TokenRenewalError as exc:
            logger.debug("%s token refresh did not apply: %s", config.api_name, exc)

    return MetaToken(access_token=access_token, expires_at=None, renewed=False)


def token_credentials(token: MetaToken) -> dict[str, str]:
    now = _now().isoformat()
    values = {
        KEY_ACCESS_TOKEN: token.access_token,
        KEY_EXPIRES_AT: token.expires_at.isoformat() if token.expires_at else "",
        KEY_ATTEMPTED_AT: now,
    }
    if token.renewed:
        values[KEY_RENEWED_AT] = now
    return values


def store_token(engine: Engine, account_id: int, token: MetaToken) -> None:
    set_credentials(engine, account_id, token_credentials(token))


def _due_for_renewal(
    creds: Mapping[str, str], expires_at: datetime | None, now: datetime
) -> bool:
    last_attempt = parse_stored_time(creds.get(KEY_ATTEMPTED_AT))
    if last_attempt and now - last_attempt < timedelta(hours=META_TOKEN_RETRY_HOURS):
        return False

    if expires_at is not None:
        return expires_at - now <= timedelta(days=META_TOKEN_MIN_REMAINING_DAYS)

    # Expiry unknown: either the account predates renewal or Meta reported no
    # expiry. Probe occasionally — a successful renewal reveals the real window.
    last_renewal = parse_stored_time(creds.get(KEY_RENEWED_AT))
    if last_renewal is None:
        return True
    return now - last_renewal >= timedelta(days=META_TOKEN_UNKNOWN_EXPIRY_DAYS)


async def ensure_fresh_token(
    engine: Engine,
    account_id: int,
    creds: Mapping[str, str],
    config: MetaTokenConfig,
) -> str:
    """Return a valid access token, renewing and persisting it when it nears expiry."""
    access_token = creds[KEY_ACCESS_TOKEN]
    expires_at = parse_stored_time(creds.get(KEY_EXPIRES_AT))
    now = _now()

    if expires_at and expires_at <= now:
        raise TokenRenewalError(
            f"{config.api_name} access token expired on {_format_time(expires_at)} "
            f"and can no longer be renewed. Re-authenticate: {config.auth_command}"
        )

    if not _due_for_renewal(creds, expires_at, now):
        return access_token

    try:
        renewed = await refresh_long_lived(config, access_token, creds)
    except TokenRenewalError as exc:
        set_credential(engine, account_id, KEY_ATTEMPTED_AT, now.isoformat())
        remaining = (
            f"{(expires_at - now).days} day(s) left"
            if expires_at
            else "expiry unknown"
        )
        logger.warning(
            "%s token renewal failed (%s), retrying in %dh: %s\n"
            "If this keeps failing, reconnect the account: %s",
            config.api_name,
            remaining,
            META_TOKEN_RETRY_HOURS,
            exc,
            config.auth_command,
        )
        return access_token

    store_token(engine, account_id, renewed)
    logger.info(
        "%s access token renewed — %s", config.api_name, describe_expiry(renewed)
    )
    return renewed.access_token


def auth_error_hint(config: MetaTokenConfig) -> Callable[[int, Any], str | None]:
    """`format_api_error` hook that turns Meta OAuth failures into a re-auth hint."""

    def extra(status: int, detail: Any) -> str | None:
        error = detail.get("error") if isinstance(detail, dict) else None
        if not isinstance(error, dict):
            return None
        if error.get("code") != OAUTH_ERROR_CODE and error.get("type") != "OAuthException":
            return None
        return (
            f"{config.api_name} access token is no longer valid "
            f"({error.get('message', 'OAuth error')}).\n"
            f"Re-authenticate: {config.auth_command}"
        )

    return extra
