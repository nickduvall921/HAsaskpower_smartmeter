"""
Web scraper for SaskPower to retrieve smart meter and billing data.

This module handles the complex, multi-step Azure B2C authentication process,
downloads power usage (PD) and billing breakdown (BB) reports, and processes
the data into a structured format for Home Assistant.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests

_LOGGER = logging.getLogger(__name__)

# --- URL Constants ---
# Centralised here so that if SaskPower ever changes their URL structure,
# there is a single place to update rather than hunting through login logic.
_BASE_URL = "https://www.saskpower.com"
_B2C_TENANT_HOST = "saskpowerb2c.b2clogin.com"
_B2C_ONMICROSOFT = "saskpowerb2c.onmicrosoft.com"
_LOGIN_PATH = "/identity/externallogin"
_CALLBACK_PATH = "/identity/externallogincallback"
_DASHBOARD_PATH = "/profile/my-dashboard"
_DOWNLOAD_PAGE_PATH = "/Profile/My-Dashboard/My-Reports/Download-Data"
_DOWNLOAD_API_PATH = "/api/sitecore/Analytics/DownloadData"

# Regina does not observe Daylight Saving Time, so this offset is fixed year-round.
_SASK_TZ = ZoneInfo("America/Regina")


def _parse_form_inputs(html: str) -> dict[str, str]:
    """
    Robustly parse all <input> tag name/value pairs from an HTML string.

    Standard regex approaches break when HTML attribute order varies (which is
    valid). This function parses each input tag independently so attribute
    order doesn't matter.
    """
    inputs: dict[str, str] = {}
    for input_tag in re.finditer(r"<input([^>]*)>", html, re.IGNORECASE):
        attrs = input_tag.group(1)
        name_match = re.search(r'name=["\']([^"\']+)["\']', attrs)
        value_match = re.search(r'value=["\']([^"\']*)["\']', attrs)
        if name_match:
            inputs[name_match.group(1)] = value_match.group(1) if value_match else ""
    return inputs


def _get_verification_token(html: str) -> str | None:
    """
    Extract __RequestVerificationToken from an HTML page.

    Uses a per-tag approach so the attribute order (name vs value vs type)
    doesn't matter.
    """
    for input_tag in re.finditer(r"<input([^>]*)>", html, re.IGNORECASE):
        attrs = input_tag.group(1)
        name_match = re.search(r'name=["\']([^"\']+)["\']', attrs)
        if name_match and name_match.group(1) == "__RequestVerificationToken":
            value_match = re.search(r'value=["\']([^"\']+)["\']', attrs)
            if value_match:
                return value_match.group(1)
    return None


class SaskPowerScraper:
    """Orchestrates the scraping of data from the SaskPower website."""

    def __init__(
        self,
        username: str,
        password: str,
        account_number: str,
        session: requests.Session | None = None,
    ) -> None:
        """
        Initialize the scraper.

        Args:
            username: The username for SaskPower online access.
            password: The password for SaskPower online access.
            account_number: The SaskPower account number.
            session: An optional requests.Session object (useful for testing).
        """
        if not all([username, password, account_number]):
            raise ValueError("Username, password, and account number cannot be empty.")

        self._username = username
        self._password = password
        self._account_number = account_number
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Connection": "keep-alive",
            }
        )

    def login(self) -> bool:
        """
        Perform the complete, multi-step Azure B2C authentication flow.

        Returns:
            True if login is successful, False otherwise.
        """
        # Clear any stale cookies from a previous session so they don't
        # interfere with a fresh login attempt.
        self._session.cookies.clear()

        try:
            _LOGGER.info("Attempting to log in to SaskPower...")

            # --- Step 1: POST to SaskPower to trigger the B2C redirect ---
            _LOGGER.debug("Step 1: Initiating login to get Azure B2C redirect.")
            return_url = (
                f"{_BASE_URL}{_CALLBACK_PATH}"
                f"?ReturnUrl=http%3a%2f%2f{_BASE_URL.replace('https://', '')}{_DASHBOARD_PATH}"
                f"&sc_site=SaskPower&authenticationSource=Default"
            )
            initial_url = (
                f"{_BASE_URL}{_LOGIN_PATH}"
                f"?authenticationType=SaskPower.Azure.B2C"
                f"&ReturnUrl={requests.utils.quote(return_url, safe='')}"
                f"&sc_site=SaskPower"
            )
            response = self._session.post(initial_url, allow_redirects=True, timeout=30)
            response.raise_for_status()

            if _B2C_TENANT_HOST not in response.url:
                _LOGGER.error(
                    "Step 1 failed: did not redirect to B2C login page. "
                    "The SaskPower login URL structure may have changed. "
                    "Current URL: %s",
                    response.url,
                )
                return False

            # --- Step 2: Extract dynamic tokens from the B2C page's JavaScript ---
            _LOGGER.debug("Step 2: Extracting CSRF token and Transaction ID from B2C page.")
            settings_match = re.search(r"var SETTINGS = ({.*?});", response.text, re.DOTALL)
            if not settings_match:
                _LOGGER.error(
                    "Step 2 failed: could not find 'SETTINGS' JavaScript block. "
                    "The B2C login page structure may have changed."
                )
                return False

            settings_str = settings_match.group(1)
            csrf_match = re.search(r'"csrf":\s*"([^"]+)"', settings_str)
            transid_match = re.search(r'"transId":\s*"([^"]+)"', settings_str)

            if not csrf_match or not transid_match:
                _LOGGER.error(
                    "Step 2 failed: could not parse CSRF token or Transaction ID from SETTINGS block."
                )
                return False

            csrf_token = csrf_match.group(1)
            trans_id = transid_match.group(1)

            # Extract the B2C policy name from the URL query string.
            # This is critical — if it can't be found we must fail loudly rather
            # than silently falling back to a hardcoded value that may be wrong.
            policy = parse_qs(urlparse(response.url).query).get("p", [None])[0]
            if not policy:
                _LOGGER.error(
                    "Step 2 failed: could not extract B2C policy name from URL '%s'. "
                    "The login URL structure may have changed.",
                    response.url,
                )
                return False

            _LOGGER.debug("Extracted B2C policy: %s", policy)

            # --- Step 3: Submit credentials via XHR POST ---
            _LOGGER.debug("Step 3: Submitting credentials to B2C SelfAsserted endpoint.")
            self_asserted_url = (
                f"https://{_B2C_TENANT_HOST}/{_B2C_ONMICROSOFT}/{policy}"
                f"/SelfAsserted?tx={trans_id}&p={policy}"
            )
            login_payload = {
                "request_type": "RESPONSE",
                "signInName": self._username,
                "password": self._password,
            }
            xhr_headers = {
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": response.url,
                "Origin": f"https://{_B2C_TENANT_HOST}",
            }
            auth_response = self._session.post(
                self_asserted_url, headers=xhr_headers, data=login_payload, timeout=30
            )
            auth_response.raise_for_status()

            auth_json = auth_response.json()
            if auth_json.get("status") != "200":
                _LOGGER.error(
                    "Step 3 failed: B2C credential submission rejected: %s",
                    auth_json.get("message", "Unknown error"),
                )
                return False

            # --- Step 4: GET the B2C 'confirmed' endpoint ---
            _LOGGER.debug("Step 4: Following B2C confirmation redirect.")
            confirmed_url = (
                f"https://{_B2C_TENANT_HOST}/{_B2C_ONMICROSOFT}/{policy}"
                f"/api/CombinedSigninAndSignup/confirmed"
                f"?rememberMe=false&csrf_token={csrf_token}&tx={trans_id}&p={policy}"
            )
            confirmed_response = self._session.get(confirmed_url, timeout=30)
            confirmed_response.raise_for_status()

            # --- Step 5: Parse and submit the final token-exchange form ---
            _LOGGER.debug("Step 5: Submitting final token exchange form back to SaskPower.")
            form_action_match = re.search(
                r"<form[^>]+action=['\"]([^'\"]+)['\"]", confirmed_response.text
            )
            if not form_action_match:
                _LOGGER.error(
                    "Step 5 failed: could not find form action in B2C confirmation page. "
                    "The B2C flow may have changed."
                )
                return False

            form_action = form_action_match.group(1).replace("&amp;", "&")

            # Use the robust per-tag parser so attribute order doesn't matter.
            form_data = _parse_form_inputs(confirmed_response.text)

            if not form_data.get("id_token"):
                _LOGGER.error(
                    "Step 5 failed: 'id_token' not found in the final form. "
                    "Available fields: %s",
                    list(form_data.keys()),
                )
                return False

            final_response = self._session.post(
                form_action, data=form_data, allow_redirects=True, timeout=30
            )
            final_response.raise_for_status()

            # Verify we landed somewhere sensible on the SaskPower domain.
            if _DASHBOARD_PATH in final_response.url:
                _LOGGER.info("Login successful!")
                return True

            # Fallback: if cookies are present we're probably logged in even if
            # the redirect landed on an unexpected page (e.g. a maintenance banner).
            if any(_BASE_URL.replace("https://", "") in d for d in self._session.cookies.list_domains()):
                _LOGGER.warning(
                    "Login appears successful but did not land on dashboard. "
                    "Final URL: %s",
                    final_response.url,
                )
                return True

            _LOGGER.error(
                "Login failed: unexpected final URL '%s' and no SaskPower session cookies found.",
                final_response.url,
            )
            return False

        except requests.exceptions.RequestException as e:
            _LOGGER.error("Network error during login: %s", e)
            return False
        except Exception:
            _LOGGER.exception("Unexpected error during login")
            return False

    def _fetch_data_from_api(
        self,
        verification_token: str,
        data_category: str,
        start_date: date,
        end_date: date,
    ) -> list[dict] | None:
        """
        Fetch a data report for a given category and date range.

        Args:
            verification_token: The __RequestVerificationToken from the download page.
            data_category: 'PD' for power usage or 'BB' for billing breakdown.
            start_date: The start date for the report.
            end_date: The end date for the report.

        Returns:
            A list of row dicts from the CSV, or None on failure.
        """
        _LOGGER.debug(
            "Requesting '%s' data from %s to %s", data_category, start_date, end_date
        )
        api_url = f"{_BASE_URL}{_DOWNLOAD_API_PATH}"
        payload = {
            "accountNumbers[]": self._account_number,
            "collectiveAccountNumbers[]": "",
            "bpNumbers[]": "undefined",
            "meterTypes[]": "7",
            "isChildSelected[]": "false",
            "fromDate": start_date.strftime("%Y%m%d"),
            "toDate": end_date.strftime("%Y%m%d"),
            "dataDownloadPath": "src/temp/",
            "dataCategory": data_category,
            "isEmptyList": "false",
            "__RequestVerificationToken": verification_token,
        }
        api_headers = {
            "Accept": "*/*",
            "Origin": _BASE_URL,
            "Referer": f"{_BASE_URL}{_DOWNLOAD_PAGE_PATH}",
            "X-Requested-With": "XMLHttpRequest",
        }

        api_response = self._session.post(
            api_url, headers=api_headers, data=payload, timeout=60
        )
        api_response.raise_for_status()

        content_type = api_response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            json_data = api_response.json()
            if json_data.get("NoDataAvailable"):
                _LOGGER.warning("No data available for category '%s'.", data_category)
                return None
            zip_bytes = base64.b64decode(json_data.get("FileData", ""))
        elif "application/zip" in content_type:
            zip_bytes = api_response.content
        else:
            _LOGGER.error(
                "Unexpected content type for '%s': %s", data_category, content_type
            )
            return None

        if not zip_bytes:
            _LOGGER.warning("API returned empty file data for '%s'.", data_category)
            return None

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_filename = next((f for f in zf.namelist() if f.endswith(".csv")), None)
            if not csv_filename:
                _LOGGER.error("No CSV file found in ZIP for '%s'.", data_category)
                return None
            with zf.open(csv_filename) as csv_file:
                csv_text = io.TextIOWrapper(csv_file, "utf-8-sig")
                return list(csv.DictReader(csv_text))

    @staticmethod
    def _parse_saskpower_datetime(raw: str) -> datetime:
        """
        Parse a SaskPower datetime string in a locale-independent way.

        SaskPower uses the format '2024-Jan-15 02:00 PM'. The %b directive is
        locale-dependent on some systems, so we normalise the month abbreviation
        to uppercase English before parsing.

        Args:
            raw: The raw datetime string from the CSV.

        Returns:
            A naive datetime object (caller should attach timezone).

        Raises:
            ValueError: If the string cannot be parsed.
        """
        # Normalise to uppercase so strptime's English %b works regardless of locale.
        return datetime.strptime(raw.strip().upper(), "%Y-%b-%d %I:%M %p")

    def get_data(self, fetch_days: int = 60) -> dict | None:
        """
        Fetch and process both power usage and billing data.

        Args:
            fetch_days: Number of days of historical data to fetch.

        Returns:
            A dictionary of processed data, or None on complete failure.
            Partial data (e.g. usage without billing) is returned with a warning.
        """
        _LOGGER.info(
            "Starting data retrieval for account %s (%d days).",
            self._account_number,
            fetch_days,
        )
        if not self.login():
            _LOGGER.error("Data retrieval aborted: login failed.")
            return None

        try:
            # --- Obtain the request verification token ---
            _LOGGER.debug("Fetching verification token from download page.")
            download_page_url = f"{_BASE_URL}{_DOWNLOAD_PAGE_PATH}"
            response = self._session.get(download_page_url, timeout=30)
            response.raise_for_status()

            verification_token = _get_verification_token(response.text)
            if not verification_token:
                _LOGGER.error(
                    "Could not find __RequestVerificationToken on the download page. "
                    "The page structure may have changed."
                )
                return None

            end_date = date.today()
            start_date = end_date - timedelta(days=fetch_days)

            # --- 1. Power Usage Data (PD) ---
            usage_data = self._fetch_data_from_api(
                verification_token, "PD", start_date, end_date
            )
            usage_stats: dict = {}
            interval_readings: list[dict] = []

            if usage_data:
                data_by_day: dict = defaultdict(list)
                latest_reading_dt: datetime | None = None

                for row in usage_data:
                    try:
                        usage = float(row["Consumption"])
                        # Use locale-safe parser (fix #6)
                        naive_dt = self._parse_saskpower_datetime(row["DateTime"])
                        aware_dt = naive_dt.replace(tzinfo=_SASK_TZ)
                        interval_readings.append({"datetime": aware_dt, "usage": usage})
                        data_by_day[aware_dt.date()].append(usage)
                        if latest_reading_dt is None or aware_dt > latest_reading_dt:
                            latest_reading_dt = aware_dt
                    except (ValueError, TypeError, KeyError) as exc:
                        _LOGGER.debug("Skipping invalid usage row: %s — %s", row, exc)
                        continue

                interval_readings.sort(key=lambda x: x["datetime"])

                # A "full day" has 96 x 15-minute readings.
                most_recent_full_day = next(
                    (
                        d
                        for d in sorted(data_by_day.keys(), reverse=True)
                        if len(data_by_day[d]) >= 96
                    ),
                    None,
                )

                daily_usage = (
                    sum(data_by_day[most_recent_full_day]) if most_recent_full_day else 0
                )
                weekly_usage = (
                    sum(
                        sum(data_by_day.get(most_recent_full_day - timedelta(days=i), []))
                        for i in range(7)
                    )
                    if most_recent_full_day
                    else 0
                )

                today = datetime.now(_SASK_TZ).date()
                last_day_prev_month = today.replace(day=1) - timedelta(days=1)
                first_day_prev_month = last_day_prev_month.replace(day=1)
                monthly_usage = sum(
                    sum(usages)
                    for day, usages in data_by_day.items()
                    if first_day_prev_month <= day <= last_day_prev_month
                )

                usage_stats = {
                    "daily_usage": round(daily_usage, 3),
                    "weekly_usage": round(weekly_usage, 3),
                    "monthly_usage": round(monthly_usage, 3),
                    "latest_data_timestamp": latest_reading_dt,
                    "interval_readings": interval_readings,
                }
                _LOGGER.info(
                    "Processed %d interval readings.", len(interval_readings)
                )
            else:
                _LOGGER.warning(
                    "No power usage data retrieved for account %s. "
                    "Billing data may still be available.",
                    self._account_number,
                )

            # --- 2. Billing Data (BB) ---
            # Billing files are small so always fetch the full history.
            billing_data = self._fetch_data_from_api(
                verification_token, "BB", date(2000, 1, 1), date.today()
            )
            billing_stats: dict = {}

            if billing_data:
                try:
                    bill_date_key = "BillIssueDate"
                    charges_key = "TotalCharges"
                    usage_key = "ConsumptionKwh"

                    if bill_date_key not in billing_data[0]:
                        _LOGGER.warning(
                            "Billing data missing '%s' column. Found: %s",
                            bill_date_key,
                            list(billing_data[0].keys()),
                        )
                    else:
                        latest_bill = max(
                            billing_data,
                            key=lambda row: datetime.strptime(
                                row[bill_date_key].strip(), "%d-%b-%Y"
                            ),
                        )
                        last_bill_charges = float(
                            latest_bill.get(charges_key, "0")
                            .replace("$", "")
                            .replace(",", "")
                        )
                        last_bill_usage = float(latest_bill.get(usage_key, 0))
                        avg_cost = (
                            last_bill_charges / last_bill_usage
                            if last_bill_usage > 0
                            else 0
                        )
                        billing_stats = {
                            "last_bill_total_charges": last_bill_charges,
                            "last_bill_total_usage": last_bill_usage,
                            "avg_cost_per_kwh": avg_cost,
                        }
                        _LOGGER.info(
                            "Processed latest bill from %s.", latest_bill[bill_date_key]
                        )
                except (ValueError, TypeError, KeyError) as exc:
                    _LOGGER.error(
                        "Could not process billing data: %s. Headers: %s",
                        exc,
                        list(billing_data[0].keys()) if billing_data else "N/A",
                    )
            else:
                _LOGGER.warning(
                    "No billing data retrieved for account %s. "
                    "Usage data may still be available.",
                    self._account_number,
                )

            # --- 3. Combine results ---
            combined_data = {**usage_stats, **billing_stats}
            if not combined_data:
                _LOGGER.error(
                    "Both usage and billing data failed for account %s.",
                    self._account_number,
                )
                return None

            # Warn clearly if only one half succeeded so logs make it obvious.
            if not usage_stats:
                _LOGGER.warning("Returning partial data: billing only (no usage data).")
            if not billing_stats:
                _LOGGER.warning("Returning partial data: usage only (no billing data).")

            return combined_data

        except requests.exceptions.RequestException as exc:
            _LOGGER.error("Network error during data retrieval: %s", exc)
            return None
        except Exception:
            _LOGGER.exception("Unexpected error during data retrieval")
            return None