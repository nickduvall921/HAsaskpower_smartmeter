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
import json
import logging
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests

_LOGGER = logging.getLogger(__name__)


class SaskPowerScraper:
    """Orchestrates the scraping of data from the SaskPower website."""

    def __init__(
        self, username: str, password: str, account_number: str, session: requests.Session | None = None
    ) -> None:
        """
        Initialize the scraper.

        Args:
            username: The username for SaskPower online access.
            password: The password for SaskPower online access.
            account_number: The SaskPower account number.
            session: An optional requests.Session object.
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
        Perform the complete, multi-step authentication flow.

        Returns:
            True if login is successful, False otherwise.
        """
        try:
            _LOGGER.info("Attempting to log in to SaskPower...")

            # 1. Initial POST to get the B2C redirect URL.
            _LOGGER.debug("Step 1: Initiating login to get Azure B2C redirect.")
            initial_url = "https://www.saskpower.com/identity/externallogin?authenticationType=SaskPower.Azure.B2C&ReturnUrl=%2fidentity%2fexternallogincallback%3fReturnUrl%3dhttp%253a%252f%252fwww.saskpower.com%252fprofile%252fmy-dashboard%26sc_site%3dSaskPower%26authenticationSource%3dDefault&sc_site=SaskPower"
            response = self._session.post(initial_url, allow_redirects=True, timeout=30)
            response.raise_for_status()

            if "saskpowerb2c.b2clogin.com" not in response.url:
                _LOGGER.error("Failed to redirect to B2C login page. Current URL: %s", response.url)
                return False

            # 2. Extract dynamic tokens from the B2C login page's JavaScript.
            _LOGGER.debug("Step 2: On B2C login page, extracting CSRF and Transaction ID.")
            settings_match = re.search(r"var SETTINGS = ({.*?});", response.text, re.DOTALL)
            if not settings_match:
                _LOGGER.error("Could not find 'SETTINGS' JavaScript block in login page HTML.")
                return False

            settings_str = settings_match.group(1)
            csrf_match = re.search(r'"csrf":\s*"([^"]+)"', settings_str)
            transid_match = re.search(r'"transId":\s*"([^"]+)"', settings_str)

            if not csrf_match or not transid_match:
                _LOGGER.error("Could not parse CSRF token or Transaction ID from SETTINGS.")
                return False

            csrf_token = csrf_match.group(1)
            trans_id = transid_match.group(1)
            policy = parse_qs(urlparse(response.url).query).get("p", [""])[0]

            # 3. Submit credentials via an XHR POST request.
            _LOGGER.debug("Step 3: Submitting credentials to B2C SelfAsserted endpoint.")
            self_asserted_url = f"https://saskpowerb2c.b2clogin.com/saskpowerb2c.onmicrosoft.com/{policy}/SelfAsserted?tx={trans_id}&p={policy}"
            login_payload = {"request_type": "RESPONSE", "signInName": self._username, "password": self._password}
            xhr_headers = {
                "X-CSRF-TOKEN": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": response.url,
                "Origin": "https://saskpowerb2c.b2clogin.com",
            }
            auth_response = self._session.post(self_asserted_url, headers=xhr_headers, data=login_payload, timeout=30)
            auth_response.raise_for_status()

            auth_json = auth_response.json()
            if auth_json.get("status") != "200":
                _LOGGER.error("B2C authentication failed: %s", auth_json.get("message", "Unknown error"))
                return False

            # 4. Follow the confirmation step.
            _LOGGER.debug("Step 4: Making GET request to B2C 'confirmed' endpoint.")
            confirmed_url = f"https://saskpowerb2c.b2clogin.com/saskpowerb2c.onmicrosoft.com/{policy}/api/CombinedSigninAndSignup/confirmed?rememberMe=false&csrf_token={csrf_token}&tx={trans_id}&p={policy}"
            confirmed_response = self._session.get(confirmed_url, timeout=30)
            confirmed_response.raise_for_status()

            # 5. The 'confirmed' response contains an HTML form. Submit it to finalize login.
            _LOGGER.debug("Step 5: Submitting final token exchange form back to SaskPower.")
            form_action_match = re.search(r"<form[^>]+action=['\"]([^'\"]+)['\"]", confirmed_response.text)
            if not form_action_match:
                _LOGGER.error("Could not find form action in the final confirmation page.")
                return False

            form_action = form_action_match.group(1).replace("&amp;", "&")
            inputs = re.findall(r"<input[^>]+name=['\"]([^'\"]+)['\"][^>]+value=['\"]([^'\"]*)['\"]", confirmed_response.text)
            form_data = {name: value for name, value in inputs}

            if "id_token" not in form_data:
                _LOGGER.error("Could not find 'id_token' in the final form post. Login failed.")
                return False

            final_response = self._session.post(form_action, data=form_data, allow_redirects=True, timeout=30)
            final_response.raise_for_status()

            if "my-dashboard" in final_response.url:
                _LOGGER.info("Login successful!")
                return True
            
            _LOGGER.warning("Login process may have succeeded, but did not land on dashboard. Final URL: %s", final_response.url)
            return ".saskpower.com" in self._session.cookies.list_domains()

        except requests.exceptions.RequestException as e:
            _LOGGER.error("A network error occurred during the login process: %s", e)
            return False
        except Exception:
            _LOGGER.exception("An unexpected error occurred during login")
            return False

    def _fetch_data_from_api(
        self, verification_token: str, data_category: str, start_date: date, end_date: date
    ) -> list[dict] | None:
        """
        Generic function to fetch a data report for a given category and date range.

        Args:
            verification_token: The __RequestVerificationToken from the download page.
            data_category: The category of data to download ('PD' or 'BB').
            start_date: The start date for the report.
            end_date: The end date for the report.

        Returns:
            A list of dictionaries representing the rows of the CSV, or None on failure.
        """
        _LOGGER.debug("Requesting data for category '%s' from %s to %s", data_category, start_date, end_date)
        api_url = "https://www.saskpower.com/api/sitecore/Analytics/DownloadData"
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
            "Origin": "https://www.saskpower.com",
            "Referer": "https://www.saskpower.com/Profile/My-Dashboard/My-Reports/Download-Data",
            "X-Requested-With": "XMLHttpRequest",
        }

        api_response = self._session.post(api_url, headers=api_headers, data=payload, timeout=60)
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
            _LOGGER.error("Expected ZIP or JSON for '%s', but got %s", data_category, content_type)
            return None

        if not zip_bytes:
             _LOGGER.warning("API returned empty file data for category '%s'.", data_category)
             return None

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_filename = next((f for f in zf.namelist() if f.endswith(".csv")), None)
            if not csv_filename:
                _LOGGER.error("No CSV file found in ZIP for '%s'.", data_category)
                return None
            with zf.open(csv_filename) as csv_file:
                csv_text = io.TextIOWrapper(csv_file, "utf-8-sig")
                return list(csv.DictReader(csv_text))

    def get_data(self, fetch_days: int = 60) -> dict | None:
        """
        Fetch and process both power usage and billing data after logging in.

        Args:
            fetch_days: Number of days of historical data to fetch (default: 60)

        Returns:
            A dictionary containing all processed data, or None on failure.
        """
        _LOGGER.info("Starting data retrieval for SaskPower account %s (fetching %d days).", 
                     self._account_number, fetch_days)
        if not self.login():
            _LOGGER.error("Cannot retrieve data because login failed.")
            return None

        try:
            # Get the verification token needed for API calls
            _LOGGER.debug("Navigating to download page to get verification token.")
            download_page_url = "https://www.saskpower.com/Profile/My-Dashboard/My-Reports/Download-Data"
            response = self._session.get(download_page_url, timeout=30)
            response.raise_for_status()
            token_match = re.search(r"name=['\"]__RequestVerificationToken['\"]\s+type=['\"]hidden['\"]\s+value=['\"]([^'\"]+)['\"]", response.text)
            if not token_match:
                _LOGGER.error("Could not find __RequestVerificationToken on the download page.")
                return None
            verification_token = token_match.group(1)

            # Calculate date range based on fetch_days parameter
            end_date = date.today()
            start_date = end_date - timedelta(days=fetch_days)

            # --- 1. Fetch and Process Power Usage Data (PD) ---
            usage_data = self._fetch_data_from_api(verification_token, "PD", start_date, end_date)
            usage_stats = {}
            interval_readings = []
            if usage_data:
                sask_tz = ZoneInfo("America/Regina")
                data_by_day = defaultdict(list)
                latest_reading_dt = None

                for row in usage_data:
                    try:
                        usage = float(row["Consumption"])
                        aware_dt = datetime.strptime(row["DateTime"].strip(), "%Y-%b-%d %I:%M %p").replace(tzinfo=sask_tz)
                        interval_readings.append({"datetime": aware_dt, "usage": usage})
                        data_by_day[aware_dt.date()].append(usage)
                        if latest_reading_dt is None or aware_dt > latest_reading_dt:
                            latest_reading_dt = aware_dt
                    except (ValueError, TypeError, KeyError):
                        _LOGGER.debug("Skipping invalid usage data row: %s", row)
                        continue
                
                interval_readings.sort(key=lambda x: x["datetime"])
                most_recent_full_day = next((d for d in sorted(data_by_day.keys(), reverse=True) if len(data_by_day[d]) >= 96), None)
                daily_usage = sum(data_by_day.get(most_recent_full_day, []))
                weekly_usage = sum(sum(data_by_day.get(most_recent_full_day - timedelta(days=i), [])) for i in range(7)) if most_recent_full_day else 0

                today = datetime.now(sask_tz).date()
                last_day_prev_month = today.replace(day=1) - timedelta(days=1)
                monthly_usage = sum(sum(usages) for day, usages in data_by_day.items() if last_day_prev_month.replace(day=1) <= day <= last_day_prev_month)
                
                usage_stats = {
                    "daily_usage": round(daily_usage, 3),
                    "weekly_usage": round(weekly_usage, 3),
                    "monthly_usage": round(monthly_usage, 3),
                    "latest_data_timestamp": latest_reading_dt,
                    "interval_readings": interval_readings,
                }
                _LOGGER.info("Successfully processed %d interval readings (requested %d days).", 
                           len(interval_readings), fetch_days)

            # --- 2. Fetch and Process Billing Data (BB) ---
            # Always fetch full billing history (billing data is much smaller)
            billing_data = self._fetch_data_from_api(verification_token, "BB", date(2000, 1, 1), date.today())
            billing_stats = {}
            if billing_data:
                try:
                    bill_date_key, charges_key, usage_key = "BillIssueDate", "TotalCharges", "ConsumptionKwh"
                    if bill_date_key not in billing_data[0]:
                        _LOGGER.warning("Billing data is missing the '%s' column.", bill_date_key)
                    else:
                        latest_bill = max(billing_data, key=lambda row: datetime.strptime(row[bill_date_key].strip(), "%d-%b-%Y"))
                        last_bill_charges = float(latest_bill.get(charges_key, "0").replace("$", "").replace(",", ""))
                        last_bill_usage = float(latest_bill.get(usage_key, 0))
                        avg_cost = last_bill_charges / last_bill_usage if last_bill_usage > 0 else 0
                        billing_stats = {
                            "last_bill_total_charges": last_bill_charges,
                            "last_bill_total_usage": last_bill_usage,
                            "avg_cost_per_kwh": avg_cost,
                        }
                        _LOGGER.info("Successfully processed latest bill from %s.", latest_bill[bill_date_key])
                except (ValueError, TypeError, KeyError) as e:
                     _LOGGER.error("Could not process billing data: %s. Headers found: %s", e, billing_data[0].keys() if billing_data else "N/A")

            # --- 3. Combine and Return Results ---
            combined_data = {**usage_stats, **billing_stats}
            if not combined_data:
                _LOGGER.warning("No data could be retrieved for account %s.", self._account_number)
                return None
            
            return combined_data

        except requests.exceptions.RequestException as e:
            _LOGGER.error("A network error occurred during data retrieval: %s", e)
            return None
        except Exception:
            _LOGGER.exception("An unexpected error occurred during data retrieval")
            return None