import datetime
import calendar
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from calculator.calc import battery_charging_info, get_spot_prices, minutes_to_15mins
from calculator.miner import PriceNotFound
from calculator.schema import BatteryChargingInfo, CheapestHours, DayPrice, MostExpensiveHours, Price

from .consts import VAT

def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]

app = FastAPI(title="Spot market home calculator", version="0.1", description="Calculate your energy costs based on spot market prices")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", description="Redirect to /docs")
def docs():
    return RedirectResponse(url="/docs")

docs = """
Return spot prices for the whole day with all fees included.<br>
<br>
**Options:**<br>
**date** - date in format YYYY-MM-DD, default is today<br>
**hour** - hour of the day, default is current hour, works only when date is today<br>, in format HH:MM where MM can be 00, 15, 30 or 45 if the data is in 15-min intervals, or 00 if the data is in hourly intervals
**monthly_fees** - monthly fees, default is 509.24 (D57d, BezDodavatele)<br>
**daily_fees** - daily fees, default is 4.18 (BezDodavatele)<br>
**kwh_fees_low** - additional fees per kWh in low tariff, usually distribution + other fees, default is 1.62421 (D57d, BezDodavatele)<br>
**kwh_fees_high** - additional fees per kWh in high tariff, usually distribution + other fees, default is 1.83474 (D57d, BezDodavatele)<br>
**sell_fees** - selling energy fees, default is 0.45 (BezDodavatele)<br>
**num_cheapest_hours** - number of cheapest hours to return, default is 8, use this to plan your consumption<br>
**num_most_expensive_hours** - number of the most expensive hours to return, default is 8, use this to plan your consumption<br>
**low_tariff_hours** - list of low tariff hours, default is 0,1,2,3,4,5,6,7,9,10,11,13,14,16,17,18,20,21,22,23 (D57d, ČEZ)<br>
**average_hours** - used for calculation of cheapest hours based on average price of first few hours, this sets number of cheapest hours used to calculate number that is a base number for the calculation<br>
**average_hours_threshold** - used for calculation of average price, cheapest hours will be all hours with price lower than `average_price * threshold`<br>
<br>
Output:<br>
**spot** - current spot prices on our market<br>
**total** - total price for the day including all fees and VAT<br>
**sell** - current spot prices minus sell_fees<br>
**cheapest_hours** - 8 (or configured) cheapest hours in the day<br>
**most_expensive_hours** - 8 (or configured) the most expensive hours in the day<br>
**cheapest_hours_by_average** - cheapest hours based on average_hours and average_hours_threshold<br>
**most_expensive_hours_by_average** - the most expensive hours based on average_hours and average_hours_threshold<br>
<br>
The final price on the invoice is calculated as:<br>
    monthly_fees + kWh consumption in low tariff * kwh_fees_low + kWh consumption in high tariff * kwh_fees_high<br>
<br>
Except spot and sell prices all prices include VAT.<br>
<br>
<br>
Integration into Home Assistant can be done in configuration.yaml file:<br>
<br>
```
rest:
- resource: https://pricepower2.rostiapp.cz/price/day
  scan_interval: 60
  sensor:
  - name: "energy_price"
    value_template: "{{ value_json.total.now|round(2) }}"
    unit_of_measurement: "CZK/kWh"
  - name: "energy_market_price"
    value_template: "{{ value_json.spot.now|round(2) }}"
    unit_of_measurement: "CZK/kWh"
  - name: "energy_market_price_sell"
    value_template: "{{ value_json.sell.now|round(2) }}"
    unit_of_measurement: "CZK/kWh"
  binary_sensor:
  - name: "energy_cheap_hour"
    value_template: "{{ value_json.cheapest_hours.is_cheapest }}"
  - name: "energy_expensive_hour"
    value_template: "{{ value_json.most_expensive_hours.is_the_most_expensive }}"
  - name: "energy_expensive_hour_by_average"
    value_template: "{{ value_json.most_expensive_hours_by_average.is_the_most_expensive }}"
  - name: "energy_cheap_hour_by_average"
    value_template: "{{ value_json.cheapest_hours_by_average.is_cheapest }}""
```

"""


docs_battery = """
Returns data for battery charging and discharging. It takes four cheapest hours from today
and calculates if it's viable and when it's viable to charge or discharge the battery.
It partly checks data from the next day and doesn't charge the battery in the evening if
it's going to be cheaper next day in the morning.<br>
<br>
**Options:**<br>
**kwh_fees_low** - additional fees per kWh in low tariff, usually distribution + other fees, default is 1.62421 (D57d, BezDodavatele)<br>
**kwh_fees_high** - additional fees per kWh in high tariff, usually distribution + other fees, default is 1.83474 (D57d, BezDodavatele)<br>
**sell_fees** - selling energy fees, default is 0.45 (BezDodavatele), not important for this endpoint<br>
**low_tariff_hours** - list of low tariff hours, default is 0,1,2,3,4,5,6,7,9,10,11,13,14,16,17,18,20,21,22,23 (D57d, ČEZ)<br>
**battery_kwh_price** - price from which it is viable to charge and discharge the battery, default is 2.5<br>
<br>
Output:<br>
**diff** - Difference between the most expensive cheapest hour and the most expensive hour<br>
**is_viable** - True if it is viable to charge or discharge the battery today<br>
**charging_hours** - Hours when it is viable to charge the battery<br>
**is_charging_hour** - True if it is viable to charge the battery in the current hour<br>
**discharging_hours** - Hours when it is viable to discharge the battery<br>
**is_discharging_hour** - True if it is viable to discharge the battery in the current hour<br>
**total_price** - total price for the day including all fees and VAT<br>
<br>
<br>

<br>
<br>
Integration into Home Assistant can be done in configuration.yaml file:<br>
<br>
```
rest:
- resource: https://pricepower2.rostiapp.cz/battery/charging
  scan_interval: 60
  binary_sensor:
  - name: "battery_charging_plan_is_viable"
    value_template: "{{ value_json.is_viable }}"
  - name: "battery_charging_plan_is_charging_hour"
    value_template: "{{ value_json.is_charging_hour }}"
  - name: "battery_charging_plan_is_discharging_hour"
    value_template: "{{ value_json.is_discharging_hour }}"
```

"""

@app.get("/price/day", description=docs)
@app.get("/price/day/{date}", description=docs)
def read_item(
    date: Optional[datetime.date]=None, 
    hour: Optional[str]=None, 
    monthly_fees: float=610.84,
    daily_fees: float=4.18, 
    kwh_fees_low: float=1.35022,
    kwh_fees_high: float=1.86567,
    sell_fees: float=0.45, 
    low_tariff_hours:str="0,1,2,3,4,5,6,7,9,10,11,13,14,16,17,18,20,21,22,23", 
    no_cache:bool = False, 
    num_cheapest_hours:int = 8,
    num_most_expensive_hours:int = 8,
    average_hours:int=4,
    average_hours_threshold:float=1.25,
    ) -> DayPrice:
    
    if not date:
        date = datetime.date.today()
    if not hour:
        now = datetime.datetime.now()
        hour = f"{now.hour}:{minutes_to_15mins(now.minute)}"
    
    if re.match(r"^\d{1,2}$", hour):
        hour = f"{hour}:00"
      
    hour_parts = hour.split(":")
    hour = f"{hour_parts[0]}:{minutes_to_15mins(hour_parts[1])}"
    
    is_today = datetime.date.today() == date

    low_tariff_hours_parsed = []
    for low_hour in [x.strip() for x in low_tariff_hours.split(",")]:
      low_tariff_hours_parsed.append(f"{low_hour}:00")
      low_tariff_hours_parsed.append(f"{low_hour}:15")
      low_tariff_hours_parsed.append(f"{low_hour}:30")
      low_tariff_hours_parsed.append(f"{low_hour}:45")

    monthly_fees = (monthly_fees + daily_fees * days_in_month(date.year, date.month))
    monthly_fees_hour = monthly_fees / days_in_month(date.year, date.month) / 24

    try:
      spot_prices = get_spot_prices(date, hour, kwh_fees_low, kwh_fees_high, sell_fees, VAT, low_tariff_hours_parsed, no_cache=no_cache)
    except PriceNotFound:
      raise HTTPException(status_code=404, detail="prices not found")

    cheapest_hours = [k for k, v in list(spot_prices.spot_hours_total_sorted.hours.items())[0:num_cheapest_hours]]
    most_expensive_hours = [k for k, v in list(reversed(spot_prices.spot_hours_total_sorted.hours.items()))[0:num_most_expensive_hours]]
    
    # Average over four cheapest hours and calculation of all hours that are in this average +20 %
    four_cheapest_hours = [v for k, v in list(spot_prices.spot_hours_total_sorted.hours.items())[0:average_hours]]
    four_cheapest_hours_average = sum(four_cheapest_hours) / average_hours
    cheapest_hours_by_average = [k for k, v in list(spot_prices.spot_hours_total_sorted.hours.items()) if v < four_cheapest_hours_average * average_hours_threshold]
    most_expensive_hours_by_average = list(set([k for k,v in spot_prices.spot_hours_total_sorted.hours.items()]) - set(cheapest_hours_by_average))

    data = DayPrice(
        monthly_fees=monthly_fees * VAT,
        monthly_fees_hour=monthly_fees_hour * VAT,
        kwh_fees_low=kwh_fees_low * VAT,
        kwh_fees_high=kwh_fees_high * VAT,
        sell_fees=sell_fees,
        low_tariff_hours=low_tariff_hours_parsed,
        hour=hour,
        vat=VAT,
        spot=spot_prices.spot,
        total=spot_prices.spot_total,
        sell=spot_prices.spot_for_sell,
        cheapest_hours=CheapestHours(hours=cheapest_hours, is_cheapest=hour in cheapest_hours if is_today else None),
        most_expensive_hours=MostExpensiveHours(hours=most_expensive_hours, is_the_most_expensive=hour in most_expensive_hours if is_today else None),
        cheapest_hours_by_average=CheapestHours(hours=cheapest_hours_by_average, is_cheapest=hour in cheapest_hours_by_average if is_today else None),
        most_expensive_hours_by_average=MostExpensiveHours(hours=most_expensive_hours_by_average, is_the_most_expensive=hour in most_expensive_hours_by_average if is_today else None),
    )
    return data

@app.get("/battery/charging", description=docs_battery)
def battery_charging(
    kwh_fees_low: float=1.35022,
    kwh_fees_high: float=1.86567,
    sell_fees: float=0.45, 
    battery_kwh_price: float=2.5, 
    low_tariff_hours:str="0,1,2,3,4,5,6,7,9,10,11,13,14,16,17,18,20,21,22,23", 
    no_cache:bool = False, 
    ) -> BatteryChargingInfo:
      low_tariff_hours_parsed = [int(x.strip()) for x in low_tariff_hours.split(",")]
  
      info = battery_charging_info(
        kwh_fees_low,
        kwh_fees_high,
        sell_fees,
        VAT,
        low_tariff_hours_parsed,
        no_cache,
        battery_kwh_price
      )
      
      return info

@app.get("/widget", response_class=HTMLResponse)
def get_widget():
    with open("calculator/index.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)
