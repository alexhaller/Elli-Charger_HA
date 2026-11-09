"""Diagnostics for the Elli Charger integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ElliConfigEntry
from .const import CONF_REFRESH_TOKEN

# Account and hardware identifiers: enough to tell records apart is kept by
# Home Assistant's redaction marker, the values themselves are not shared.
TO_REDACT = {
    CONF_REFRESH_TOKEN,
    "id",
    "station_id",
    "serial_number",
    "number",
    "rfid_card_id",
    "rfid_card_serial_number",
    "subscriber_id",
    "tenant_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ElliConfigEntry
) -> dict[str, Any]:
    """Return the entry settings and the last data fetched, without identifiers."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "last_update_success": coordinator.last_update_success,
            "update_interval_s": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "data": {
                key: [item.model_dump() for item in items]
                for key, items in data.items()
            },
        },
        TO_REDACT,
    )
