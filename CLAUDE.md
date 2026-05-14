# CLAUDE.md — Elli Charger HA Integration

## Project overview

Cloud-polling integration for Elli EV wallboxes via the Elli REST API (email + password auth).

- GitHub: https://github.com/alexhaller/Elli-Charger_HA

Key files:
- `__init__.py` — coordinator poll interval: configurable (default 5 min); `ElliBaseEntity` base class; `ElliCoordinator` type alias
- `config_flow.py` — required user inputs: email, password; options flow for scan_interval
- `const.py` — DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
- Platforms: `sensor.py`, `binary_sensor.py`

## Project-specific notes

- **Domain**: `elli_charger_ha`; pip-audit packages: `elli-client==1.2.0`
- **Brand**: `custom_components/elli_charger_ha/brand/icon.png` + `brands/icon.png` (512×512 PNG)
- **`.releaserc.json`** `prepareCmd` path: `custom_components/elli_charger_ha/manifest.json`
- **Auth**: uses email/password (cloud API), not host/IP — config flow does not validate IP
- **Unique IDs**: entity unique IDs are rooted on `station.id` (cloud stable identifier), e.g. `f"{station_id}_session_energy"`. RFID cards use `f"{card_id}_rfid_card"`. Do not include entry_id.
- **Translations**: `strings.json` and `translations/en.json` must be identical; `translations/de.json` is also maintained
- **Scan interval**: user-configurable via options flow (1–60 min); no fixed module-level `SCAN_INTERVAL`
