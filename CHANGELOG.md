# Changelog

All notable changes to the SaskPower SmartMeter integration are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.2] - 2026-02-19

### Fixed

#### Login & Authentication (`scraper.py`)
- **Azure B2C policy name extraction broke with new URL format**: Microsoft
  changed the Azure B2C authorize URL structure. The policy name was previously
  found in the `?p=` query parameter, but is now embedded in the URL path
  (e.g. `.../b2c_1a_accountlink_signuporsignin/oauth2/v2.0/authorize`). The
  integration was failing at Step 2 of login with the error *"could not extract
  B2C policy name"* for all users. Policy extraction now tries the query
  parameter first for backwards compatibility, then falls back to reading the
  path segment immediately after the tenant name that starts with `b2c_`.

#### Data Retrieval (`scraper.py`)
- **`meterTypes[]` removal caused 500 Server Error**: Version 1.1.1 removed the
  `meterTypes[]: "7"` field from the API payload to improve portability for
  non-standard meters. In practice the SaskPower `DownloadData` endpoint
  requires the field to be present and returns a 500 Internal Server Error when
  it is absent, breaking data retrieval for all users. The field has been
  restored. Non-standard meter users who receive no data are asked to open an
  issue so the correct value for their meter type can be identified and made
  configurable.
- **500 Server Error response body now logged before raising**: Previously a
  server error only surfaced the HTTP status code in the logs with no indication
  of the underlying cause. The first 500 characters of the response body are now
  logged at ERROR level before the exception is raised, making future server-
  side failures much easier to diagnose.

#### Home Assistant Statistics (`sensor.py`)
- **`get_last_statistics` signature incorrectly changed in 1.1.1**: A prior
  change removed the `convert_units` positional argument from the
  `get_last_statistics` call based on incorrect information that it had been
  removed in HA 2024.2. This caused a `TypeError: missing 1 required positional
  argument: 'types'` on startup, preventing both the `SaskPower Total
  Consumption` and `SaskPower Estimated Total Cost` sensors from loading. The
  confirmed current signature is
  `(hass, number_of_stats, statistic_id, convert_units, types)` and
  `convert_units=True` has been restored to both call sites.

---

## [1.1.1] - 2026-02-19

### Fixed

#### Login & Authentication (`scraper.py`)
- **Step 5 multiple-form vulnerability**: The B2C confirmation page may contain
  more than one `<form>` element (e.g. analytics or hidden CSRF forms). The
  previous code grabbed the action URL from whichever form appeared first in
  the HTML, meaning a new form inserted before the token-exchange form would
  cause login to silently fail. The integration now identifies the correct form
  by locating the one that contains the `id_token` field, making it immune to
  form ordering changes.
- **Double-encoded return URL in Step 1**: Parts of the return URL were
  manually percent-encoded and then passed through `quote()` a second time,
  producing `%253a` instead of `%3a`. Sitecore rejected the malformed URL,
  preventing login entirely. The URL is now built as a plain string and encoded
  exactly once per nesting level.
- **Stale cookies interfering with re-login**: Session cookies from a previous
  update cycle are now cleared before each login attempt, preventing stale
  authentication state from interfering with a fresh login.
- **B2C policy fallback removed**: The code previously fell back to a hardcoded
  policy name if the policy could not be extracted from the redirect URL. A
  wrong hardcoded value would cause silent login failures with confusing errors.
  The integration now fails loudly with a clear message if the policy name
  cannot be determined.

#### Data Retrieval (`scraper.py`)
- **Hardcoded `meterTypes[]` excluded non-standard accounts**: The API payload
  hardcoded `meterTypes[]: "7"` (standard residential smart meter). Users with
  solar/bi-directional meters, commercial meters, or legacy meter types received
  no data. The filter has been removed so the API returns data for all meters
  on the account.
- **96-reading threshold skipped days with minor packet loss**: The daily usage
  summary required exactly 96 × 15-minute readings to consider a day "complete."
  A single dropped wireless packet (95 readings) caused the integration to
  silently roll back to the previous day's data. The threshold is now 80 readings
  (~83% of a day), which tolerates normal smart meter packet loss while still
  correctly skipping genuinely incomplete days. A warning is logged when the
  best available day is between 80–95 readings.
- **`BadZipFile` exception not caught**: If the SaskPower server returned an
  HTML error page with a 200 status code, `zipfile.ZipFile()` raised
  `BadZipFile` which was not caught and caused an unhandled exception. This is
  now caught explicitly, with the first 200 bytes of the response logged to aid
  diagnosis.
- **`base64.b64decode` error not caught**: A malformed or empty `FileData` field
  in the JSON response raised `binascii.Error`. This is now caught and logged
  as a clear error.
- **Each data fetch now independently guarded**: A failure fetching power usage
  (PD) data no longer suppresses billing (BB) data and vice versa. Each fetch
  is wrapped in its own `try/except` block.
- **`date.today()` called twice inconsistently**: Billing data fetch now uses
  the already-computed `end_date` variable instead of calling `date.today()` a
  second time, ensuring both fetches always reference the same date even if
  midnight falls between them.
- **CSV column names logged at DEBUG level**: After parsing any CSV response,
  the actual column headers are now logged at DEBUG level. If SaskPower renames
  a column (e.g. `Consumption` → `Consumption (kWh)`), enabling debug logging
  immediately reveals the new column names without needing to inspect raw
  responses.
- **Billing date parsing was locale-dependent**: The `%b` format code in
  `strptime` is locale-dependent on some Linux systems and would raise
  `ValueError` on non-English locales. Both usage and billing date strings are
  now uppercased before parsing, making the parse locale-independent.

#### Home Assistant Statistics (`sensor.py`)
- **Wrong `get_last_statistics` signature caused full re-import on every cycle**:
  The `convert_units` parameter was removed in Home Assistant 2024.2. Passing
  `True` as the third positional argument caused the function to silently return
  no results, making every update look like a first run and re-importing all
  backfill data each cycle. The call signature is now correct.
- **Cost sensor backfill ignored `backfill_days` setting**: When no existing
  statistics were found for the cost sensor, the filter time was set to Unix
  epoch (1970) instead of `now - backfill_days`, causing all available readings
  to be imported regardless of the user's configured backfill window.
- **Statistics filter boundary created a one-hour gap**: The filter used `>`
  against the last recorded statistic's start timestamp, which could skip the
  boundary hour. The filter now advances by one full hour (`last_start + 1h`)
  so only readings from the next unrecorded hour onwards are imported.
- **Inconsistent empty-statistics check on cost sensor**: The cost sensor only
  checked `if last_stat_row:`, which evaluated `True` for a list containing an
  empty dict `{}`. This caused the sensor to believe statistics existed when
  they did not, resulting in incorrect filter times. Both sensors now check
  `if last_stat_row and last_stat_row[0]:`.
- **`_attr_native_value = 0` masked unavailable state**: Statistics sensors
  initialised with `0` on startup, making them appear available with a
  misleading zero reading before any data had been imported. Sensors now start
  as `None` (unavailable) and update to a real value only after the first
  statistics import completes.

#### Configuration Flow (`config_flow.py`, `__init__.py`)
- **Options form pre-filled from wrong source**: The options form read from
  `entry.data` (original setup values) instead of `entry.options` (previously
  saved option changes). Opening Configure after a previous options change
  showed the original setup values, not the current ones.
- **No reload listener for options changes**: Changing `update_interval_hours`
  or `backfill_days` via the options form had no effect until the next Home
  Assistant restart. A reload listener is now registered so the integration
  reloads automatically when options are saved.

### Added

- **Options flow**: `backfill_days` and `update_interval_hours` can now be
  changed after initial setup via Settings → Integrations → SaskPower →
  Configure, without needing to delete and re-add the integration.
- **Automatic retry with exponential backoff**: The HTTP session now uses a
  `Retry` adapter (3 attempts, 1s backoff factor) that automatically retries on
  429, 500, 502, 503, and 504 responses. This prevents a single transient
  SaskPower server error at the one daily poll window from causing a missed data
  update.
- **URL constants**: All SaskPower and Azure B2C URLs are now defined as named
  module-level constants (`_BASE_URL`, `_B2C_TENANT_HOST`, etc.) so a URL
  structure change requires editing a single location rather than hunting
  through login logic.
- **Robust HTML input parser**: `<input>` tag name/value pairs are now parsed
  per-tag so attribute order (`name` before `value` vs `value` before `name`)
  and self-closing tags (`<input ... />`) do not affect extraction.
- **Partial data warnings**: If only one of usage or billing data is
  successfully retrieved, the integration returns the available data and logs a
  clear warning identifying which half is missing, rather than returning
  nothing.

### Changed

- **User-Agent updated** from Chrome/124 to Chrome/131 to reflect a more
  current browser version.
- Version bumped from `1.0.0` → `1.1.0` → `1.1.1` → `1.1.2`.

---

## [1.0.0] - Initial Release

- Initial release with Azure B2C authentication flow.
- 15-minute interval smart meter data retrieval.
- Daily, weekly, and previous-month usage summary sensors.
- Last bill total charges and total usage sensors.
- Last data point timestamp sensor.
- Energy Dashboard integration via `TOTAL_INCREASING` statistics sensors
  with historical backfill on first run.