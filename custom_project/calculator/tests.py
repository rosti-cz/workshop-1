import unittest
import datetime
from .miner import get_energy_prices, get_eur_czk_ratio

class TestMiner(unittest.TestCase):

    def test_get_energy_prices(self):
        data = get_energy_prices(datetime.datetime.now(), no_cache=True)

        data_cache = get_energy_prices(datetime.datetime.now())

        self.assertGreater(data["0"], 0)
        self.assertEqual(data["0"], data_cache["0"])
        self.assertEqual(data, data_cache)

    def test_currency_ratio(self):
        data = get_eur_czk_ratio(datetime.datetime.now(), no_cache=True)
        data_cache = get_eur_czk_ratio(datetime.datetime.now())

        self.assertGreater(data, 0)
        self.assertEqual(data, data_cache)
