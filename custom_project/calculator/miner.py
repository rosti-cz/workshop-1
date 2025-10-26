from dataclasses import dataclass
import datetime
import json
import os
from typing import Dict, List

import requests


class PriceException(Exception): pass
class PriceNotFound(Exception): pass


url_energy = "https://www.ote-cr.cz/cs/kratkodobe-trhy/elektrina/denni-trh/@@chart-data?report_date={}"
url_currency = "https://data.kurzy.cz/json/meny/b[1].json"
url_currency2 = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt?date={day}.{month}.{year}"
CACHE_PATH = "./cache"


def get_energy_prices(d: datetime.date=datetime.date.today(), no_cache:bool=False) -> Dict[str, float]:
    """
    Get energy prices for a given date.
    """
    date_str = d.strftime("%Y-%m-%d")

    hours = {}

    cache_file = os.path.join(CACHE_PATH, "hours-{}.json".format(date_str))

    if os.path.isfile(cache_file) and not no_cache:
        with open(cache_file, "r") as f:
            hours = json.load(f)

    if not hours or no_cache:
        r = requests.get(url_energy.format(date_str))
        resp = r.json()["data"]["dataLine"]
        
        if len(resp) == 0:
            raise PriceNotFound()
        
        data = resp[1]["point"]

        if len(data) == 24:
            try:
                for raw in data:
                    hour = str(int(raw["x"])-1)
                    hours[hour] = raw["y"]
            except IndexError:
                raise PriceNotFound()
        else:
            try:
                mins_index = 0
                hour = 0
                
                # Adjust for daylight saving time changes
                if len(data) == 100:
                    data = data[0:8] + data[12:100]

                for raw in data:
                    hour_str = f"{hour}:00"
                    if mins_index == 1:
                        hour_str = f"{hour}:15"
                    elif mins_index == 2:
                        hour_str = f"{hour}:30"
                    elif mins_index == 3:
                        hour_str = f"{hour}:45"
                    
                    hours[hour_str] = raw["y"]

                    mins_index += 1                    
                    if mins_index >= 4:
                        mins_index = 0
                        hour += 1
            except IndexError:
                raise PriceNotFound()

        # Only cache if all 24 hours are present
        if len(hours) in (24, 96): # 96 for 15-min intervals
            with open(cache_file, "w") as f:
                f.write(json.dumps(hours))
        # If incomplete, do not cache, but return what is available

    # Ensure all hours are in the right format of HH:MM
    correct_format_hours = {}
    if len(hours) == 24:
        for k, v in hours.items():
            if ":" in k:
                correct_format_hours[k] = v
            else:
                hour_int = int(k)
                correct_format_hours[f"{hour_int}:00"] = v
    else:
        correct_format_hours = hours

    return hours

#def get_currency_ratio(currency):
#    r = requests.get(url_currency)
#    return r.json()["kurzy"][currency]["dev_stred"]

def get_eur_czk_ratio(d: datetime.date=datetime.date.today(), no_cache:bool=False) -> float:
    ratio = 0

    cache_file = os.path.join(CACHE_PATH, "eur-czk-{}.json".format(d.strftime("%Y-%m-%d")))

    if os.path.isfile(cache_file):
        with open(cache_file, "r") as f:
            ratio = float(f.read())
        
    if not ratio or no_cache:
        url = url_currency2.format(day=d.day,month=d.month,year=d.year)
        r = requests.get(url)
        for row in [x.split("|") for x in r.text.split("\n") if x and "|" in x]:
            if row[3] == "EUR":
                ratio = float(row[4].replace(",", "."))
                break

        if not ratio:
            raise PriceException("EUR not found")
        
        with open(cache_file, "w") as f:
            f.write(str(ratio))

    return ratio



    

    
