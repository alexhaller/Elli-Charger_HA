"""Config, re-auth and options flow of the Elli Charger integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from elli_client import AuthenticationError, InvalidOAuthCallback
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant.common import MockConfigEntry

from custom_components.elli_charger_ha.const import (
    CONF_CALLBACK_URL,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import CALLBACK_URL, REFRESH_TOKEN, ROTATED_TOKEN, SUBJECT, tokens


async def _submit(hass: HomeAssistant, callback_url: str = CALLBACK_URL) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "authorization_url": "https://example.invalid/authorize"
    }
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CALLBACK_URL: callback_url}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant, client: MagicMock) -> None:
    result = await _submit(hass, f"  {CALLBACK_URL} ")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Elli"
    assert result["data"] == {CONF_REFRESH_TOKEN: REFRESH_TOKEN}
    assert result["result"].unique_id == SUBJECT
    exchanged_url, authorization = client.exchange_callback.call_args.args
    assert exchanged_url == CALLBACK_URL
    assert authorization is client.create_authorization.return_value


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidOAuthCallback("bad"), "invalid_callback"),
        (AuthenticationError("rejected"), "invalid_auth"),
        (OSError("offline"), "cannot_connect"),
    ],
)
async def test_exchange_errors(
    hass: HomeAssistant, client: MagicMock, error: Exception, expected: str
) -> None:
    client.exchange_callback.side_effect = error

    result = await _submit(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_missing_refresh_token_is_rejected(
    hass: HomeAssistant, client: MagicMock
) -> None:
    client.exchange_callback.return_value = tokens(refresh_token=None)

    result = await _submit(hass)

    assert result["errors"] == {"base": "invalid_auth"}


async def test_same_account_is_configured_once(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)

    result = await _submit(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_stores_the_new_refresh_token(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    client.exchange_callback.return_value = tokens(ROTATED_TOKEN)
    client.refresh.return_value = tokens(ROTATED_TOKEN)

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CALLBACK_URL: CALLBACK_URL}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_REFRESH_TOKEN] == ROTATED_TOKEN


async def test_options_flow_bounds_the_interval(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    with pytest.raises(InvalidData, match=CONF_SCAN_INTERVAL):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 61}
        )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 10}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 10}
