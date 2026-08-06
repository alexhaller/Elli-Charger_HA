"""Config flow for Elli Charger integration."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import voluptuous as vol
from elli_client import (  # type: ignore[import-not-found]
    AuthenticationError,
    ElliAPIClient,
    InvalidOAuthCallback,
)
from elli_client.models import TokenResponse  # type: ignore[import-not-found]
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CALLBACK_URL,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_CALLBACK_DATA_SCHEMA = vol.Schema({vol.Required(CONF_CALLBACK_URL): str})


def _account_subject(id_token: str | None) -> str | None:
    """Return the OpenID subject claim of an ID token, without verifying it."""
    if not id_token:
        return None
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) else None


class ElliConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Elli Charger."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        # elli_client ships no types to mypy here, so these are plain Any.
        self._client: Any = None
        self._authorization: Any = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ElliOptionsFlowHandler:
        """Return the options flow handler."""
        return ElliOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                tokens = await self._exchange(user_input[CONF_CALLBACK_URL])
            except InvalidCallback:
                errors["base"] = "invalid_callback"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(_account_subject(tokens.id_token))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Elli",
                    data={CONF_REFRESH_TOKEN: tokens.refresh_token},
                )

        return await self._async_show_authorization_form("user", errors)

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                tokens = await self._exchange(user_input[CONF_CALLBACK_URL])
            except InvalidCallback:
                errors["base"] = "invalid_callback"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during re-auth")
                errors["base"] = "unknown"
            else:
                reauth_entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_REFRESH_TOKEN: tokens.refresh_token,
                    },
                )

        return await self._async_show_authorization_form("reauth_confirm", errors)

    async def _async_show_authorization_form(
        self, step_id: str, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Show the form that carries the authorization URL."""
        if self._client is None:
            self._client = await self.hass.async_add_executor_job(ElliAPIClient)
        if self._authorization is None:
            # create_authorization() only derives PKCE values; it does no I/O.
            self._authorization = self._client.create_authorization()

        return self.async_show_form(
            step_id=step_id,
            data_schema=STEP_CALLBACK_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "authorization_url": self._authorization.authorization_url
            },
        )

    async def _exchange(self, callback_url: str) -> TokenResponse:
        """Exchange an OAuth callback URL for tokens."""
        if self._client is None or self._authorization is None:
            raise CannotConnect("No authorization session in progress")

        try:
            tokens: TokenResponse = await self.hass.async_add_executor_job(
                self._client.exchange_callback,
                callback_url.strip(),
                self._authorization,
            )
        except InvalidOAuthCallback as err:
            raise InvalidCallback from err
        except AuthenticationError as err:
            raise InvalidAuth from err
        except Exception as err:
            raise CannotConnect from err

        if not tokens.refresh_token:
            raise InvalidAuth("Elli did not return a refresh token")

        return tokens


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate the authorization was rejected."""


class InvalidCallback(HomeAssistantError):
    """Error to indicate the pasted callback URL is not usable."""


class ElliOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Elli Charger options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=60)
                    ),
                }
            ),
        )
