"""Fixtures for the Elli Charger tests: an API client serving canned account data."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from elli_client.models import (
    AuthorizationSession,
    ChargingSession,
    FirmwareInfo,
    RFIDCard,
    Station,
    TokenResponse,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry

from custom_components.elli_charger_ha.const import CONF_REFRESH_TOKEN, DOMAIN

SUBJECT = "account-subject"
STATION_ID = "station-1"
CARD_ID = "card-1"
REFRESH_TOKEN = "refresh-1"
ROTATED_TOKEN = "refresh-2"
CALLBACK_URL = "https://example.invalid/callback?code=abc&state=xyz"


def id_token(subject: str = SUBJECT) -> str:
    """Build an unsigned JWT carrying only a sub claim."""

    def part(data: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
        return raw.rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'sub': subject})}.sig"


def tokens(refresh_token: str | None = REFRESH_TOKEN) -> TokenResponse:
    return TokenResponse(
        access_token="access",
        refresh_token=refresh_token,
        id_token=id_token(),
    )


def station() -> Station:
    return Station(
        id=STATION_ID,
        name="Garage",
        serial_number="SN123",
        model="Elli Wallbox Pro",
        firmware_version="1.0.0",
    )


def session(**overrides: object) -> ChargingSession:
    values: dict = {
        "id": "session-1",
        "station_id": STATION_ID,
        "start_date_time": "2026-11-07T10:00:00+00:00",
        "energy_consumption_wh": 12345,
        "momentary_charging_speed_watts": 11000.5,
        "lifecycle_state": "active",
        "charging_state": "charging",
        "rfid_card_id": CARD_ID,
        "rfid_card_serial_number": "ELLI-0001",
    }
    values.update(overrides)
    return ChargingSession(**values)


def rfid_card() -> RFIDCard:
    return RFIDCard(id=CARD_ID, number="ELLI-0001", status="active")


def firmware_station() -> Station:
    return Station(
        id=STATION_ID,
        name="Garage",
        installed_firmware=FirmwareInfo(id="fw", version="2.0.0"),
    )


@pytest.fixture
def client() -> Generator[MagicMock]:
    """Replace ElliAPIClient in the integration and the config flow."""
    mock = MagicMock()
    mock.create_authorization.return_value = AuthorizationSession(
        authorization_url="https://example.invalid/authorize",
        state="xyz",
        code_verifier="verifier",
        created_at=dt_util.utcnow(),
    )
    mock.exchange_callback.return_value = tokens()
    mock.refresh.return_value = tokens()
    mock.get_charging_sessions.return_value = [session()]
    mock.get_stations.return_value = [station()]
    mock.get_firmware_info.return_value = [firmware_station()]
    mock.get_rfid_cards.return_value = [rfid_card()]
    with (
        patch("custom_components.elli_charger_ha.ElliAPIClient", return_value=mock),
        patch(
            "custom_components.elli_charger_ha.config_flow.ElliAPIClient",
            return_value=mock,
        ),
    ):
        yield mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Elli",
        unique_id=SUBJECT,
        version=2,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN},
    )
