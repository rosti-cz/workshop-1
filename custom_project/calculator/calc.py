import datetime
from typing import List

from calculator.miner import PriceNotFound, get_energy_prices, get_eur_czk_ratio
from calculator.schema import BatteryChargingInfo, Price, SpotPrices


def get_spot_prices(date: datetime.date, hour:str, kwh_fees_low:float, kwh_fees_high:float, sell_fees:float, VAT:float, low_tariff_hours:List[int], no_cache: bool = False) -> SpotPrices:
    is_today = datetime.date.today() == date
    
    spot_hours = {}
    spot_hours_for_sell = {}
    spot_hours_total = {}

    spot_data = get_energy_prices(date, no_cache=no_cache)
    currency_ratio = get_eur_czk_ratio(date, no_cache=no_cache)
    
    for key, value in spot_data.items():
        kwh_fees = kwh_fees_low if key in low_tariff_hours else kwh_fees_high

        spot_hours[key] = value * currency_ratio / 1000
        spot_hours_total[key] = (value * currency_ratio / 1000 + kwh_fees) * VAT
        spot_hours_for_sell[key] = value * currency_ratio / 1000 - sell_fees
    
    spot = Price(hours=spot_hours, now=spot_hours[hour] if is_today else None)
    
    spot_hours_total_sorted = {k: v for k, v in sorted(spot_hours_total.items(), key=lambda item: item[1])}
    spot_total = Price(hours=spot_hours_total_sorted, now=spot_hours_total[hour] if is_today else None)
    spot_for_sell = Price(hours=spot_hours_for_sell, now=spot_hours_for_sell[hour] if is_today else None)
    
    return SpotPrices(
        spot=spot,
        spot_hours_total_sorted=Price(hours=spot_hours_total_sorted, now=spot_hours_total[hour] if is_today else None),
        spot_total=spot_total,
        spot_for_sell=spot_for_sell,
    )


def battery_charging_info(kwh_fees_low:float, kwh_fees_high:float, sell_fees:float, VAT:float, low_tariff_hours:List[int], no_cache: bool = False, battery_kwh_price:float=2.5) -> BatteryChargingInfo:
    today = datetime.date.today()
    now = datetime.datetime.now()
    hour = f"{now.hour}:{minutes_to_15mins(now.minute)}"
    tomorrow = today + datetime.timedelta(days=1)
    
    spot_prices_today:SpotPrices = get_spot_prices(today, hour, kwh_fees_low, kwh_fees_high, sell_fees, VAT, low_tariff_hours, no_cache)
    
    # average4hours = sum(list(spot_prices_today.spot_hours_total_sorted.hours.values())[0:4]) / 4
    max_cheapest_hour = max(list(spot_prices_today.spot_hours_total_sorted.hours.values())[0:4])
    max_most_expensive_hour = max(
        [x[1] for x in list(spot_prices_today.spot_hours_total_sorted.hours.items())[0:20]]
    ) if spot_prices_today.spot_hours_total_sorted.hours else 0
    diff = max_most_expensive_hour - max_cheapest_hour
    
    charging_hours = [k for k, v in spot_prices_today.spot_hours_total_sorted.hours.items()][0:4]
    discharging_hours = [k for k, v in spot_prices_today.spot_hours_total_sorted.hours.items() if v > (max_cheapest_hour + battery_kwh_price)]
    
    # Add charging hours if the price is just 10% above the most expensive charging hour
    if charging_hours:
        for h in spot_prices_today.spot_hours_total_sorted.hours.keys():
            value = spot_prices_today.spot_hours_total_sorted.hours[h]
            if value <= max_cheapest_hour*1.1:
                charging_hours.append(h)
    
    # We remove end of the day hours from charging hours if the average of the last 4 hours is higher than the average of the first 4 hours of the next day
    try:
        spot_prices_tomorrow:SpotPrices = get_spot_prices(tomorrow, hour, kwh_fees_low, kwh_fees_high, sell_fees, VAT, low_tariff_hours, no_cache)    
        average_last_4hours_today = sum(list(spot_prices_today.spot_hours_total_sorted.hours.values())[20:24]) / 4
        average_first_4hours_tomorrow = sum(list(spot_prices_tomorrow.spot_hours_total_sorted.hours.values())[0:4]) / 4
        if average_last_4hours_today > average_first_4hours_tomorrow:
            for h in range(20,24):
                if h in charging_hours:
                    charging_hours.remove(h)
    except PriceNotFound:
        pass

    is_viable = len(discharging_hours) > 0

    return BatteryChargingInfo(
        diff=diff,
        is_viable=is_viable,
        charging_hours=sorted(charging_hours) if len(charging_hours) > 0 else [],
        is_charging_hour=hour in charging_hours if len(charging_hours) > 0 and is_viable else False,
        discharging_hours=sorted(discharging_hours) if len(discharging_hours) > 0 else [],
        is_discharging_hour=hour in discharging_hours if len(discharging_hours) > 0 and is_viable else False,
        total_price=spot_prices_today.spot_hours_total_sorted
    )


def minutes_to_15mins(mins:int|str) -> str:
    mins = int(mins)
    
    if mins < 15:
        return "00"
    elif mins < 30:
        return "15"
    elif mins < 45:
        return "30"
    else:
        return "45"
