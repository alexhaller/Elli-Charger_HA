"""Setup, token handling, entities and the service of the Elli Charger integration."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from elli_client import ReauthenticationRequired
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_ON
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.elli_charger_ha.const import (
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import CARD_ID, REFRESH_TOKEN, ROTATED_TOKEN, STATION_ID, tokens

SERVICE = "download_charging_records"


def _state(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _reauth_sources(hass: HomeAssistant) -> list[str]:
    return [
        flow["context"]["source"] for flow in hass.config_entries.flow.async_progress()
    ]


async def test_setup_creates_entities(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor", f"{STATION_ID}_last_session") == "charging"
    assert float(_state(hass, "sensor", f"{STATION_ID}_session_energy")) == 12.35
    assert float(_state(hass, "sensor", f"{STATION_ID}_session_power")) == 11.001
    assert _state(hass, "sensor", f"{STATION_ID}_serial_number") == "SN123"
    assert _state(hass, "sensor", f"{STATION_ID}_session_rfid") == "ELLI-0001"
    assert _state(hass, "sensor", f"{CARD_ID}_rfid_card") == "active"
    assert _state(hass, "binary_sensor", f"{STATION_ID}_charging") == STATE_ON
    assert _state(hass, "binary_sensor", f"{STATION_ID}_connected") == STATE_ON


async def test_firmware_endpoint_enriches_the_station(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert _state(hass, "sensor", f"{STATION_ID}_firmware") == "2.0.0"
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, STATION_ID), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Elli Wallbox Garage"
    assert device.sw_version == "2.0.0"


async def test_optional_endpoints_may_fail(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Firmware details and RFID cards are extras; their outage keeps the station."""
    client.get_firmware_info.side_effect = ValueError("500 FETCH_FIRMWARE_FAILURE")
    client.get_rfid_cards.side_effect = ValueError("503")

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor", f"{STATION_ID}_firmware") == "1.0.0"
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_rfid_card") is None
    )


async def test_v1_entry_is_migrated_and_starts_reauth(
    hass: HomeAssistant, client: MagicMock
) -> None:
    """A v1 entry held email and password; it needs the browser authorization."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data={"email": "x", "password": "y"}
    )

    await _setup(hass, entry)

    assert entry.version == 2
    assert entry.data == {}
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert _reauth_sources(hass) == [SOURCE_REAUTH]


async def test_revoked_refresh_token_starts_reauth(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    client.refresh.side_effect = ReauthenticationRequired("revoked")

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert _reauth_sources(hass) == [SOURCE_REAUTH]


async def test_refresh_failure_retries_setup(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    client.refresh.side_effect = OSError("offline")

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    client.close.assert_called_once()


async def test_rotated_refresh_token_is_persisted(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    client.refresh.return_value = tokens(ROTATED_TOKEN)

    await _setup(hass, config_entry)

    client.refresh.assert_called_once_with(REFRESH_TOKEN)
    assert config_entry.data[CONF_REFRESH_TOKEN] == ROTATED_TOKEN
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("error", "refreshes"),
    [
        (ValueError("API request failed: 401 Unauthorized"), 2),
        (TimeoutError("timed out"), 1),
    ],
)
async def test_only_auth_errors_renew_the_token(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    error: Exception,
    refreshes: int,
) -> None:
    """A 401 renews the access token once; a timeout must not burn a rotation."""
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    sessions = client.get_charging_sessions.return_value
    client.get_charging_sessions.side_effect = [error, sessions]

    await coordinator.async_refresh()

    assert client.refresh.call_count == refreshes
    assert coordinator.last_update_success is (refreshes == 2)


async def test_interval_change_reloads(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == timedelta(minutes=15)


async def test_service_writes_the_pdf(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    tmp_path: Path,
) -> None:
    client.get_charging_records_pdf.return_value = b"%PDF-1.7"
    await _setup(hass, config_entry)
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    output = tmp_path / "records.pdf"

    await hass.services.async_call(
        DOMAIN,
        SERVICE,
        {
            "station_id": STATION_ID,
            "rfid_card_id": CARD_ID,
            "created_at_after": "2026-10-01",
            "created_at_before": "2026-11-01",
            "output_path": str(output),
        },
        blocking=True,
    )

    assert output.read_bytes() == b"%PDF-1.7"
    client.get_charging_records_pdf.assert_called_once_with(
        STATION_ID, CARD_ID, "2026-10-01", "2026-11-01", "Europe/Berlin"
    )


async def test_unload_closes_the_client(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    client.close.assert_called_once()


def _download(output: str) -> dict[str, str]:
    return {
        "station_id": STATION_ID,
        "rfid_card_id": CARD_ID,
        "created_at_after": "2026-10-01",
        "created_at_before": "2026-11-01",
        "output_path": output,
    }


@pytest.mark.parametrize(
    ("relative", "message"),
    [("records.txt", "must end in .pdf"), ("../outside.pdf", "must be inside")],
)
async def test_service_refuses_other_files_and_places(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    tmp_path: Path,
    relative: str,
    message: str,
) -> None:
    """The caller names the file, so only a .pdf in an allowed place is written."""
    await _setup(hass, config_entry)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    hass.config.allowlist_external_dirs = {str(allowed)}

    with pytest.raises(ServiceValidationError, match=message):
        await hass.services.async_call(
            DOMAIN, SERVICE, _download(str(allowed / relative)), blocking=True
        )

    client.get_charging_records_pdf.assert_not_called()


async def test_service_needs_an_admin(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    hass_read_only_user,
    tmp_path: Path,
) -> None:
    await _setup(hass, config_entry)
    hass.config.allowlist_external_dirs = {str(tmp_path)}

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            _download(str(tmp_path / "records.pdf")),
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert not (tmp_path / "records.pdf").exists()


async def test_service_without_a_loaded_account(
    hass: HomeAssistant,
    client: MagicMock,
    config_entry: MockConfigEntry,
    tmp_path: Path,
) -> None:
    await _setup(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    hass.config.allowlist_external_dirs = {str(tmp_path)}

    with pytest.raises(ServiceValidationError, match="No Elli account"):
        await hass.services.async_call(
            DOMAIN, SERVICE, _download(str(tmp_path / "records.pdf")), blocking=True
        )


async def test_diagnostics_hide_token_and_identifiers(
    hass: HomeAssistant, client: MagicMock, config_entry: MockConfigEntry
) -> None:
    from custom_components.elli_charger_ha.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    await _setup(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert REFRESH_TOKEN not in str(diagnostics)
    assert STATION_ID not in str(diagnostics)
    assert "SN123" not in str(diagnostics)
    station = diagnostics["data"]["stations"][0]
    assert station["model"] == "Elli Wallbox Pro"
    assert station["firmware_version"] == "2.0.0"
