# HAsaskpower_smartmeter

SaskPower SmartMeter Integration for Home Assistant

This is a custom component for Home Assistant that integrates with SaskPower's online portal to retrieve smart meter and billing data. 

It provides sensors for your daily, weekly, and monthly electricity usage, as well as sensors for your last bill's charges and total usage.Most importantly, this integration provides two sensors specifically designed for the Home Assistant Energy Dashboard, allowing you to track detailed 15-minute consumption and estimated costs over time by backfilling historical data.

Features:

Fetches 15-minute interval smart meter data.
Provides summary sensors for the most recent full day, the last 7 days, and the previous calendar month's usage.
Provides sensors for the total charges and kWh usage from your last bill.
Includes two TOTAL_INCREASING sensors for seamless integration with the Home Assistant Energy Dashboard.
Backfills up to 60 days of historical data into Home Assistant's statistics database.
All sensors are grouped under a single device for your SaskPower account.

# Installation

# HACS (Recommended)

1. Ensure you have HACS (Home Assistant Community Store) installed.
2. In HACS, go to the "Integrations" section.
3. Click the three dots in the top right corner and select "Custom repositories".
4. In the "Repository" field, paste the URL of this GitHub repository
5. For the "Category", select "Integration".
6. Click "Add".
7. The "SaskPower SmartMeter" integration will now appear in your HACS integrations list. 
8. Click on it and select "Download".
9. Restart Home Assistant.


# Energy Dashboard Setup

To get detailed graphs of your usage and cost:
1. Go to Settings -> Dashboards -> Energy.
2. Under Electricity Grid, click Add Consumption.
3. Select the "SaskPower Total Consumption" sensor.
4. Under the "Track grid consumption cost" section, click Add Cost.
5. Select "Use an entity with the total cost" and choose the "SaskPower Estimated Total Cost" sensor.
6. Click Save.
7. After a few hours, the Energy Dashboard will begin to populate with your detailed SaskPower data.
