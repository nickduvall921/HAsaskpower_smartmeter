"""
SaskPower scraper with a corrected authentication flow based on detailed HAR analysis.
This script correctly handles the multi-step Azure B2C login process and is
designed for integration into applications like Home Assistant.
"""

import requests
import csv
import io
import logging
import re
import zipfile
import json
import base64
from datetime import date, timedelta, datetime
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

# The application using this class should configure the root logger.
_LOGGER = logging.getLogger(__name__)


class SaskPowerScraper:
    """
    Class to handle scraping data from SaskPower by correctly
    navigating the Azure B2C authentication flow.
    """

    def __init__(self, username, password, account_number, session=None):
        """
        Initialize the scraper with user credentials and account info.
        Optionally, an existing requests.Session can be passed in.
        """
        if not all([username, password, account_number]):
            raise ValueError("Username, password, and account number cannot be empty.")
            
        self._username = username
        self._password = password
        self._account_number = account_number
        self._session = session or requests.Session()
        
        # Set standard headers to mimic a real browser session
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def login(self):
        """
        Performs the complete, multi-step authentication flow.
        Returns True on success, False on failure.
        """
        try:
            # Step 1: Initial POST request to get the B2C redirect.
            _LOGGER.info("Step 1: Initiating login with a POST to get Azure B2C redirect.")
            initial_url = "https://www.saskpower.com/identity/externallogin?authenticationType=SaskPower.Azure.B2C&ReturnUrl=%2fidentity%2fexternallogincallback%3fReturnUrl%3dhttp%253a%252f%252fwww.saskpower.com%252fprofile%252fmy-dashboard%26sc_site%3dSaskPower%26authenticationSource%3dDefault&sc_site=SaskPower"
            
            response = self._session.post(initial_url, allow_redirects=True, timeout=30)
            _LOGGER.debug(f"Step 1 Response URL: {response.url}")
            _LOGGER.debug(f"Step 1 Response Status Code: {response.status_code}")
            response.raise_for_status()

            if 'saskpowerb2c.b2clogin.com' not in response.url:
                _LOGGER.error(f"Failed to redirect to B2C login page. Current URL: {response.url}")
                _LOGGER.debug(f"Response text: {response.text}")
                return False

            # Step 2: Extract dynamic tokens from the B2C login page's JavaScript.
            _LOGGER.info("Step 2: On B2C login page, extracting CSRF and Transaction ID.")
            
            settings_match = re.search(r'var SETTINGS = ({.*?});', response.text, re.DOTALL)
            if not settings_match:
                _LOGGER.error("Could not find 'SETTINGS' JavaScript block in login page HTML.")
                _LOGGER.debug(f"Response text: {response.text}")
                return False
                
            settings_str = settings_match.group(1)
            csrf_match = re.search(r'"csrf":\s*"([^"]+)"', settings_str)
            transid_match = re.search(r'"transId":\s*"([^"]+)"', settings_str)

            if not csrf_match or not transid_match:
                _LOGGER.error("Could not parse CSRF token or Transaction ID from SETTINGS.")
                _LOGGER.debug(f"Response text: {response.text}")
                return False
                
            csrf_token = csrf_match.group(1)
            trans_id = transid_match.group(1)
            
            parsed_url = urlparse(response.url)
            params = parse_qs(parsed_url.query)
            policy = params.get('p', [None])[0]
            if not policy:
                # if the policy is not in the url, we will try to extract it from the url path
                try:
                    policy = response.url.split('/')[3].split('?')[0]
                except IndexError:
                    _LOGGER.warning("Policy not found in URL, using default.")
                    policy = 'b2c_1a_accountlink_signuporsignin'
            
            _LOGGER.info("Successfully extracted B2C tokens.")

            # Step 3: Submit credentials via an XHR POST request.
            _LOGGER.info("Step 3: Submitting credentials to B2C SelfAsserted endpoint.")
            
            selfasserted_url = f"https://saskpowerb2c.b2clogin.com/saskpowerb2c.onmicrosoft.com/{policy}/SelfAsserted?tx={trans_id}&p={policy}"
            
            login_payload = {
                'request_type': 'RESPONSE',
                'signInName': self._username,
                'password': self._password,
            }
            
            xhr_headers = {
                'X-CSRF-TOKEN': csrf_token,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': response.url,
                'Origin': 'https://saskpowerb2c.b2clogin.com',
            }
            
            auth_response = self._session.post(selfasserted_url, headers=xhr_headers, data=login_payload, timeout=30)
            _LOGGER.debug(f"Step 3 Response URL: {auth_response.url}")
            _LOGGER.debug(f"Step 3 Response Status Code: {auth_response.status_code}")
            auth_response.raise_for_status()
            
            auth_json = auth_response.json()
            if auth_json.get("status") != "200":
                _LOGGER.error(f"B2C authentication failed: {auth_json.get('message', 'Unknown error')}")
                _LOGGER.debug(f"Response text: {auth_response.text}")
                return False

            _LOGGER.info("B2C credential submission successful.")

            # Step 4: Follow the confirmation step.
            _LOGGER.info("Step 4: Making GET request to B2C 'confirmed' endpoint.")
            confirmed_url = f"https://saskpowerb2c.b2clogin.com/saskpowerb2c.onmicrosoft.com/{policy}/api/CombinedSigninAndSignup/confirmed?rememberMe=false&csrf_token={csrf_token}&tx={trans_id}&p={policy}"
            
            confirmed_response = self._session.get(confirmed_url, timeout=30)
            _LOGGER.debug(f"Step 4 Response URL: {confirmed_response.url}")
            _LOGGER.debug(f"Step 4 Response Status Code: {confirmed_response.status_code}")
            confirmed_response.raise_for_status()

            # Step 5: The 'confirmed' response should contain an HTML form. Submit it.
            _LOGGER.info("Step 5: Looking for token exchange form in response.")
            
            form_action_match = re.search(r"<form[^>]+action=['\"]([^'\"]+)['\"]", confirmed_response.text)
            if not form_action_match:
                _LOGGER.error("Could not find form action in the final confirmation page.")
                _LOGGER.debug("--- UNEXPECTED CONFIRMATION RESPONSE DEBUG ---")
                _LOGGER.debug(f"URL of failed request: {confirmed_url}")
                _LOGGER.debug(f"Response Content: {confirmed_response.text}")
                _LOGGER.debug("--- END UNEXPECTED CONFIRMATION RESPONSE DEBUG ---")
                return False
            
            _LOGGER.info("Found form. Submitting final token exchange form back to SaskPower.")
            form_action = form_action_match.group(1).replace('&amp;', '&')
            
            inputs = re.findall(r"<input[^>]+name=['\"]([^'\"]+)['\"][^>]+value=['\"]([^'\"]*)['\"]", confirmed_response.text)
            form_data = {name: value for name, value in inputs}

            if not form_data.get("id_token"):
                _LOGGER.error("Could not find 'id_token' in the final form post. Login failed.")
                _LOGGER.debug(f"Full form data dictionary: {form_data}")
                _LOGGER.debug(f"Response text: {confirmed_response.text}")
                return False

            final_response = self._session.post(form_action, data=form_data, allow_redirects=True, timeout=30)
            _LOGGER.debug(f"Step 5 Response URL: {final_response.url}")
            _LOGGER.debug(f"Step 5 Response Status Code: {final_response.status_code}")
            final_response.raise_for_status()

            if "my-dashboard" in final_response.url:
                _LOGGER.info(f"Login successful! Landed on: {final_response.url}")
                return True
            else:
                _LOGGER.warning(f"Login process may have succeeded, but did not land on dashboard. Final URL: {final_response.url}")
                _LOGGER.debug(f"Response text: {final_response.text}")
                if '.saskpower.com' in self._session.cookies.list_domains():
                    return True
                return False

        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"A network error occurred during the login process: {e}")
            return False
        except Exception as e:
            _LOGGER.error(f"An unexpected error occurred during login: {e}", exc_info=True)
            return False

    def _fetch_data_from_api(self, verification_token, data_category, start_date, end_date):
        """Generic function to fetch data for a given category and date range."""
        api_url = "https://www.saskpower.com/api/sitecore/Analytics/DownloadData"
        payload = {
            "accountNumbers[]": self._account_number,
            "collectiveAccountNumbers[]": "",
            "bpNumbers[]": "undefined",
            "meterTypes[]": "7",
            "isChildSelected[]": "false",
            "fromDate": start_date.strftime('%Y%m%d'),
            "toDate": end_date.strftime('%Y%m%d'),
            "dataDownloadPath": "src/temp/",
            "dataCategory": data_category,
            "isEmptyList": "false",
            "__RequestVerificationToken": verification_token,
        }
        
        api_headers = {
            'Accept': '*/*',
            'Origin': 'https://www.saskpower.com',
            'Referer': 'https://www.saskpower.com/Profile/My-Dashboard/My-Reports/Download-Data',
            'X-Requested-With': 'XMLHttpRequest',
        }

        _LOGGER.info(f"Requesting data for category '{data_category}' from API endpoint.")
        api_response = self._session.post(api_url, headers=api_headers, data=payload, timeout=60)
        api_response.raise_for_status()

        content_type = api_response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            json_data = api_response.json()
            if json_data.get("NoDataAvailable"):
                _LOGGER.warning(f"No data available for category '{data_category}'.")
                return None
            zip_bytes = base64.b64decode(json_data.get("FileData", ""))
        elif 'application/zip' in content_type:
            zip_bytes = api_response.content
        else:
            _LOGGER.error(f"Expected ZIP or JSON for '{data_category}', but got {content_type}")
            return None

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_filename = next((f for f in zf.namelist() if f.endswith('.csv')), None)
            if not csv_filename:
                _LOGGER.error(f"No CSV file found in ZIP for '{data_category}'.")
                return None
            with zf.open(csv_filename) as csv_file:
                # Use a reader that can handle potential BOM characters at the start of the file
                csv_text = io.TextIOWrapper(csv_file, 'utf-8-sig')
                reader = csv.DictReader(csv_text)
                return list(reader)

    def get_data(self):
        """
        After a successful login, get power usage and billing data.
        Returns a dictionary on success, None on failure.
        """
        _LOGGER.info("--- Starting Data Retrieval ---")
        if not self.login():
            _LOGGER.error("Cannot retrieve data because login failed.")
            return None
        
        try:
            # Get the verification token needed for API calls
            download_page_url = "https://www.saskpower.com/Profile/My-Dashboard/My-Reports/Download-Data"
            response = self._session.get(download_page_url, timeout=30)
            response.raise_for_status()
            token_match = re.search(r"name=['\"]__RequestVerificationToken['\"]\s+type=['\"]hidden['\"]\s+value=['\"]([^'\"]+)['\"]", response.text)
            if not token_match:
                _LOGGER.error("Could not find __RequestVerificationToken on the download page.")
                return None
            verification_token = token_match.group(1)

            # --- Fetch and Process Power Usage Data (PD) ---
            usage_data = self._fetch_data_from_api(
                verification_token, 'PD', date.today() - timedelta(days=60), date.today()
            )
            
            usage_stats = {}
            total_consumption = 0 # Initialize here
            if usage_data:
                sask_tz = ZoneInfo("America/Regina")
                data_by_day = defaultdict(list)
                latest_reading_dt = None

                for row in usage_data:
                    try:
                        usage = float(row.get("Consumption"))
                        total_consumption += usage # Add to the lifetime total
                        aware_dt = datetime.strptime(row.get("DateTime").strip(), '%Y-%b-%d %I:%M %p').replace(tzinfo=sask_tz)
                        data_by_day[aware_dt.date()].append(usage)
                        if latest_reading_dt is None or aware_dt > latest_reading_dt:
                            latest_reading_dt = aware_dt
                    except (ValueError, TypeError, AttributeError):
                        continue

                most_recent_full_day = next((d for d in sorted(data_by_day.keys(), reverse=True) if len(data_by_day[d]) >= 96), None)
                
                daily_usage = sum(data_by_day[most_recent_full_day]) if most_recent_full_day else 0

                weekly_usage = 0
                if most_recent_full_day:
                    for i in range(7):
                        day_to_check = most_recent_full_day - timedelta(days=i)
                        weekly_usage += sum(data_by_day.get(day_to_check, []))

                today = datetime.now(sask_tz).date()
                last_day_prev_month = today.replace(day=1) - timedelta(days=1)
                first_day_prev_month = last_day_prev_month.replace(day=1)
                monthly_usage = sum(sum(usages) for day, usages in data_by_day.items() if first_day_prev_month <= day <= last_day_prev_month)
                
                usage_stats = {
                    "daily_usage": round(daily_usage, 3),
                    "weekly_usage": round(weekly_usage, 3),
                    "monthly_usage": round(monthly_usage, 3),
                    "latest_data_timestamp": latest_reading_dt,
                    "total_consumption": round(total_consumption, 3),
                }
                _LOGGER.info(f"Calculated usage stats: {usage_stats}")

            # --- Fetch and Process Billing Data (BB) ---
            billing_data = self._fetch_data_from_api(
                verification_token, 'BB', date(2000, 1, 1), date.today()
            )
            billing_stats = {}
            total_cost = 0 # Initialize here
            if billing_data:
                try:
                    bill_date_key = 'BillIssueDate'
                    total_charges_key = 'TotalCharges'
                    consumption_kwh_key = 'ConsumptionKwh'
                    
                    if not billing_data or bill_date_key not in billing_data[0]:
                        _LOGGER.warning(f"Billing data is missing the '{bill_date_key}' column. Headers found: {list(billing_data[0].keys()) if billing_data else 'N/A'}")
                    else:
                        latest_bill = max(billing_data, key=lambda row: datetime.strptime(row[bill_date_key].strip(), '%d-%b-%Y'))
                        
                        total_charges_str = latest_bill.get(total_charges_key, '0').replace('$', '').replace(',', '')
                        last_bill_charges = float(total_charges_str)
                        last_bill_usage = float(latest_bill.get(consumption_kwh_key, 0))
                        
                        billing_stats = {
                            'last_bill_total_charges': last_bill_charges,
                            'last_bill_total_usage': last_bill_usage
                        }

                        # --- START OF NEW CALCULATION ---
                        # Calculate the running total cost for the energy dashboard
                        if last_bill_usage > 0:
                            avg_cost_per_kwh = last_bill_charges / last_bill_usage
                            total_cost = total_consumption * avg_cost_per_kwh
                            billing_stats['total_cost'] = round(total_cost, 2)
                        # --- END OF NEW CALCULATION ---

                        _LOGGER.info(f"Calculated billing stats: {billing_stats}")

                except (ValueError, TypeError, KeyError) as e:
                     _LOGGER.error(f"Could not process billing data: {e}. Headers found: {billing_data[0].keys() if billing_data else 'N/A'}")

            # --- Combine Results ---
            combined_data = {**usage_stats, **billing_stats}
            return combined_data if combined_data else None

        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"A network error occurred during data retrieval: {e}")
            return None
        except Exception as e:
            _LOGGER.error(f"An unexpected error occurred during data retrieval: {e}", exc_info=True)
            return None
