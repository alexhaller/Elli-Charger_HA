"""The Elli Charger integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from elli_client import ElliAPIClient  # type: ignore[import-untyped,import-not-found]
from elli_client.models import ChargingSession  # type: ignore[import-untyped,import-not-found]

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# The Elli API returns fractional watts; patch the model to accept float.
ChargingSession.__annotations__["momentary_charging_speed_watts"] = float | None
ChargingSession.model_rebuild(force=True)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type ElliCoordinator = DataUpdateCoordinator[dict]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elli Charger from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = await hass.async_add_executor_job(ElliAPIClient)

    try:
        await hass.async_add_executor_job(
            client.login,
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )
    except ValueError as err:
        if "401" in str(err) or "authorization code" in str(err).lower():
            raise ConfigEntryAuthFailed("Invalid credentials") from err
        raise ConfigEntryNotReady("Could not connect to Elli API") from err
    except Exception as err:
        raise ConfigEntryNotReady("Could not connect to Elli API") from err

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = ElliDataUpdateCoordinator(
        hass, client, entry.data, timedelta(minutes=scan_interval)
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not hass.services.has_service(DOMAIN, "download_charging_records"):

        async def handle_download_charging_records(call: ServiceCall) -> None:
            """Download a PDF of charging records and write it to a file."""
            first_coordinator: ElliDataUpdateCoordinator = next(
                iter(hass.data[DOMAIN].values())
            )
            pdf_bytes: bytes = await hass.async_add_executor_job(
                first_coordinator.client.get_charging_records_pdf,
                call.data["station_id"],
                call.data["rfid_card_id"],
                call.data["created_at_after"],
                call.data["created_at_before"],
                call.data.get("pdf_timezone", "Europe/Berlin"),
            )
            output_path: str = call.data.get(
                "output_path", "/config/charging_records.pdf"
            )

            def write_pdf() -> None:
                with open(output_path, "wb") as f:
                    f.write(pdf_bytes)

            await hass.async_add_executor_job(write_pdf)
            _LOGGER.info("Charging records PDF written to %s", output_path)

        hass.services.async_register(
            DOMAIN,
            "download_charging_records",
            handle_download_charging_records,
            schema=vol.Schema(
                {
                    vol.Required("station_id"): str,
                    vol.Required("rfid_card_id"): str,
                    vol.Required("created_at_after"): str,
                    vol.Required("created_at_before"): str,
                    vol.Optional("pdf_timezone", default="Europe/Berlin"): str,
                    vol.Optional(
                        "output_path", default="/config/charging_records.pdf"
                    ): str,
                }
            ),
        )

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        try:
            coordinator.client.close()
        except Exception:
            _LOGGER.warning(
                "Error closing Elli API client during unload", exc_info=True
            )

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "download_charging_records")

    return unload_ok


class ElliDataUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Class to manage fetching Elli data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ElliAPIClient,
        config_data: Mapping[str, Any],
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self._email = config_data[CONF_EMAIL]
        self._password = config_data[CONF_PASSWORD]

    @override
    async def _async_update_data(self) -> dict:
        """Fetch data from API endpoint."""
        try:
            if not self.client.access_token:
                await self.hass.async_add_executor_job(
                    self.client.login, self._email, self._password
                )
            return await self._fetch_data()
        except Exception as err:
            _LOGGER.debug("API call failed, re-authenticating: %s", err)
            try:
                await self.hass.async_add_executor_job(
                    self.client.login, self._email, self._password
                )
                return await self._fetch_data()
            except Exception as retry_err:
                raise UpdateFailed(
                    f"Error communicating with API: {retry_err}"
                ) from retry_err

    async def _fetch_data(self) -> dict:
        """Fetch sessions, stations, RFID cards and accumulated data from the API."""
        sessions = await self.hass.async_add_executor_job(
            self.client.get_charging_sessions
        )
        stations = await self.hass.async_add_executor_job(self.client.get_stations)
        await self._merge_firmware_info(stations)

        try:
            rfid_cards = await self.hass.async_add_executor_job(
                self.client.get_rfid_cards
            )
        except Exception as err:
            _LOGGER.warning("Could not fetch RFID cards: %s", err)
            rfid_cards = []

        return {
            "sessions": sessions,
            "stations": stations,
            "rfid_cards": rfid_cards,
        }

    async def _merge_firmware_info(self, stations: list) -> None:
        """Fetch firmware info and merge it into the station list."""
        try:
            firmware_stations = await self.hass.async_add_executor_job(
                self.client.get_firmware_info
            )
            firmware_map = {
                s.id: s.installed_firmware
                for s in firmware_stations
                if s.installed_firmware
            }
            for station in stations:
                if station.id in firmware_map:
                    station.installed_firmware = firmware_map[station.id]
                    station.firmware_version = firmware_map[station.id].version
        except Exception as fw_err:
            _LOGGER.warning("Could not fetch firmware info: %s", fw_err)


class ElliBaseEntity(CoordinatorEntity[ElliCoordinator]):
    """Shared base for all Elli Charger station entities."""

    has_entity_name = True

    def __init__(self, coordinator: ElliCoordinator, station_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._station_id = station_id

    def _get_station(self):
        """Return the station object for this entity."""
        stations = self.coordinator.data.get("stations", [])
        return next((s for s in stations if s.id == self._station_id), None)

    def _get_latest_session(self):
        """Return the latest session for this station."""
        sessions = self.coordinator.data.get("sessions", [])
        return next((s for s in sessions if s.station_id == self._station_id), None)

    def _has_active_session(self) -> bool:
        """Return True if the station has an active session."""
        session = self._get_latest_session()
        return bool(session and session.lifecycle_state == "active")

    def _is_charging(self) -> bool:
        """Return True if the station is actively charging."""
        session = self._get_latest_session()
        if not session:
            return False
        if session.charging_state and "charging" in session.charging_state.lower():
            return True
        if (
            session.momentary_charging_speed_watts
            and session.momentary_charging_speed_watts > 0
        ):
            return True
        return False

    @override
    @property
    def available(self) -> bool:
        """Return False if coordinator failed or station is no longer present."""
        return super().available and self._get_station() is not None

    @override
    @property
    def device_info(self) -> DeviceInfo:
        """Group entities under the wallbox device."""
        station = self._get_station()
        name = station.name if station else self._station_id
        model = station.model if station else None
        sw_version = station.firmware_version if station else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=f"Elli Wallbox {name}",
            manufacturer="Elli",
            model=model,
            sw_version=sw_version,
        )
