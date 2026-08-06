# CLAUDE.md — Elli Charger HA Integration

## Project overview

Cloud-polling integration for Elli EV wallboxes via the Elli REST API (OAuth2 PKCE auth).

- GitHub: https://github.com/alexhaller/Elli-Charger_HA
- Project forked from: https://github.com/mawiak/hacs-elli-charger
- API documentation: https://github.com/mawiak/elli-client/blob/main/docs/api.md

Key files:
- `__init__.py` — coordinator poll interval: configurable (default 5 min); `ElliBaseEntity` base class; `ElliCoordinator` type alias; `async_migrate_entry` (v1 → v2)
- `config_flow.py` — required user input: the OAuth callback URL pasted by the user; options flow for scan_interval
- `const.py` — DOMAIN, CONF_REFRESH_TOKEN, CONF_CALLBACK_URL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
- Platforms: `sensor.py`, `binary_sensor.py`

## Project-specific notes

- **Domain**: `elli_charger_ha`; pip-audit packages: `elli-client==1.5.0`
- **Brand**: `custom_components/elli_charger_ha/brand/icon.png` + `brands/icon.png` (512×512 PNG)
- **`.releaserc.json`** `prepareCmd` path: `custom_components/elli_charger_ha/manifest.json`
- **Auth**: OAuth2 PKCE against `login.elli.eco`, not host/IP. `login(email, password)` is
  deprecated upstream and unreliable (Cloudflare Turnstile) — do not reintroduce it. The
  OAuth client's `redirect_uri` is the Elli iOS custom scheme
  (`com.elli.ios.emsp://…`), registered at Auth0 and **not** changeable, so HA cannot
  receive the callback itself and cannot use `application_credentials`. The config flow
  therefore shows `create_authorization().authorization_url` and has the user paste the
  resulting callback URL back in; `exchange_callback()` then yields the tokens.
- **Tokens**: only the refresh token is persisted (`entry.data[CONF_REFRESH_TOKEN]`).
  The coordinator calls `client.refresh()` for an access token and writes the rotated
  refresh token back via `async_update_entry`. Because that fires the entry update
  listener, `_async_options_updated` reloads **only** when the scan interval actually
  changed — otherwise every token rotation would reload the integration in a loop.
- **Config entry unique ID**: the `sub` claim of the OAuth `id_token` (decoded, not
  verified — it arrives over TLS from our own PKCE exchange). Entity unique IDs are
  unaffected and stay rooted on `station.id`.
- **Entry migration**: `VERSION = 2`. v1 entries held email/password, which cannot be
  converted into a refresh token; `async_migrate_entry` clears the data and setup raises
  `ConfigEntryAuthFailed`, which sends the user through the browser flow once.
- **Unique IDs**: entity unique IDs are rooted on `station.id` (cloud stable identifier), e.g. `f"{station_id}_session_energy"`. RFID cards use `f"{card_id}_rfid_card"`. Do not include entry_id.
- **Translations**: `strings.json` and `translations/en.json` must be identical; `translations/de.json` is also maintained
- **Scan interval**: user-configurable via options flow (1–60 min); no fixed module-level `SCAN_INTERVAL`
