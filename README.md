# Elli Charger Integration for Home Assistant

## Description

This is a Home Assistant custom integration for Elli EV charging stations (wallboxes).
It communicates with the Elli cloud API using the [elli-client](https://pypi.org/project/elli-client/) Python package.
API documentation: https://github.com/mawiak/elli-client/blob/main/docs/api.md

## Features

- Real-time charging session monitoring
- Current charging power (Watts) and session energy (kWh)
- Lifetime accumulated energy per wallbox
- Session start timestamp
- Firmware version (diagnostic)
- Binary sensors for charging state and cable connection
- RFID card status and details
- Configurable polling interval (1–60 minutes)
- Automatic token refresh and re-authentication flow
- Easy setup through the Home Assistant UI

## Entities

Each configured wallbox exposes the following entities under a **Elli Wallbox** device:

| Entity | Type | Description |
|---|---|---|
| Elli Wallbox `<name>` | Sensor | Charger status: `Idle`, `Connected`, or `Charging` |
| Last Session | Sensor | Current/last session charging state |
| Session Energy | Sensor | Energy delivered in the current/last session (kWh) |
| Session Power | Sensor | Current charging power (W) |
| Accumulated Energy | Sensor | Lifetime energy delivered by this wallbox (kWh) |
| Session Start | Sensor | Start timestamp of the current/last session |
| Firmware | Sensor (diagnostic) | Installed firmware version |
| Charging | Binary sensor | `On` when the wallbox is actively charging |
| Connected | Binary sensor | `On` when a car is connected (charging or idle) |

Each RFID card linked to the account is exposed under an **Elli Account** device:

| Entity | Type | Description |
|---|---|---|
| RFID `<number>` | Sensor | Card status (`active`, `inactive`, etc.) |

## HACS Installation

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three dots in the top right corner
4. Select **Custom repositories**
5. Add the repository URL: `https://github.com/alexhaller/elli-charger-ha`
6. Select category: **Integration**
7. Click **Add**
8. Find **Elli Charger** in the integration list and click **Download**
9. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Elli Charger**
4. Open the sign-in link shown in the dialog in a **new browser tab**
5. In that new tab press **F12** to open the developer tools and switch to the **Console** tab
6. Now sign in. The page will appear to do nothing, and the console shows an error containing a
   link that starts with `com.elli.ios.emsp://`
7. Copy that link **completely** — including `com.elli.ios.emsp://` and everything after the `?` —
   and paste it back into the dialog

If the console stays empty, use the **Network** tab instead: tick **Preserve log**, sign in again,
select the last entry and copy the `Location` value from its response headers.

Use a desktop browser (Chrome, Edge or Firefox); this cannot be done on a phone. Leave the Home
Assistant dialog open while you do it, because the link belongs to that dialog and is short-lived.

### Why the manual copy step

Elli requires an interactive browser login (Cloudflare Turnstile), so the integration cannot accept
an email and password directly. The OAuth client's redirect target is the Elli iOS app's custom URL
scheme, which is registered at Elli's identity provider and cannot be changed — an `https://`
callback or Home Assistant's own OAuth callback are both rejected. Your browser therefore cannot
load the final address, which is why it never appears in the address bar and has to be read from
the developer tools.

Home Assistant stores the resulting refresh token in the config entry and renews it automatically;
you only repeat this when the token is revoked or expires.

### Options

After setup, click **Configure** on the integration card to adjust:

- **Polling interval** — how often data is fetched from the Elli API (default: 5 minutes, range: 1–60 minutes)

## Services

### `elli_charger_ha.download_charging_records`

Downloads a PDF of charging records for a specific wallbox and saves it to the Home Assistant host filesystem.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `station_id` | Yes | — | ID of the charging station |
| `rfid_card_id` | Yes | — | ID of the RFID card to filter by |
| `created_at_after` | Yes | — | Start date (ISO 8601, e.g. `2024-01-01`) |
| `created_at_before` | Yes | — | End date (ISO 8601, e.g. `2024-12-31`) |
| `pdf_timezone` | No | `Europe/Berlin` | Timezone for timestamps in the PDF |
| `output_path` | No | `/config/charging_records.pdf` | Path on the HA host to write the PDF |

## Support

- [Report Issues](https://github.com/alexhaller/elli-charger-ha/issues)
- [Feature Requests](https://github.com/alexhaller/elli-charger-ha/issues)

## License

MIT License — see [LICENSE](LICENSE) for details.

## Disclaimer

This integration is not officially supported by Elli or Volkswagen Group Charging GmbH. Use at your own risk.
