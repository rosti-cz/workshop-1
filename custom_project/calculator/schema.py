from dataclasses import dataclass
from operator import is_
from typing import Dict, List, Optional


@dataclass
class Price:
    hours: Dict[str, List[float]]
    now: Optional[float] = None # Price in current hour


@dataclass
class CheapestHours:
    hours: List[int]
    is_cheapest: Optional[bool] = None


@dataclass
class MostExpensiveHours:
    hours: List[int]
    is_the_most_expensive: Optional[bool] = None


@dataclass
class DayPrice:
    monthly_fees: float
    monthly_fees_hour: float
    kwh_fees_low: float
    kwh_fees_high: float
    sell_fees: float
    low_tariff_hours: List[int]
    hour: int
    vat: float
    spot: Price
    total: Price
    sell: Price
    cheapest_hours: CheapestHours
    most_expensive_hours: MostExpensiveHours
    cheapest_hours_by_average: CheapestHours
    most_expensive_hours_by_average: MostExpensiveHours


@dataclass
class SpotPrices:
    spot: Price
    spot_hours_total_sorted: Price
    spot_total: Price
    spot_for_sell: Price
    
@dataclass
class BatteryChargingInfo:
    diff: float # Difference between the cheapest and the most expensive hour
    is_viable: bool # Is it viable to charge or discharge the battery today
    charging_hours: List[int] # Hours when it is viable to charge the battery
    is_charging_hour:bool # Is it viable to charge the battery in the current hour
    discharging_hours: List[int] # Hours when it is viable to discharge the battery
    is_discharging_hour:bool # Is it viable to discharge the battery in the current hour
    total_price:Price

    

