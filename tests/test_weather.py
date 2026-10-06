# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest
from unittest import mock
import importlib

PKG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "custom_components", "lume")
_pkg = types.ModuleType("lume_under_test")
_pkg.__path__ = [PKG_DIR]
sys.modules.setdefault("lume_under_test", _pkg)
weather = importlib.import_module("lume_under_test.weather")


class WeatherPlaceTests(unittest.TestCase):
    def test_default_and_normalize(self):
        self.assertEqual("Coimbra", weather.default_place()["name"])
        self.assertEqual(weather.default_place(), weather.normalize_place(None))
        place = weather.normalize_place({"name": "Lisboa", "region": "Portugal", "lat": "38.7", "lon": "-9.1"})
        self.assertEqual("Lisboa (Portugal)", weather.place_label(place))

    def test_geocode_hint_filters(self):
        payload = {
            "results": [
                {"name": "Coimbra", "latitude": 1.0, "longitude": 2.0, "country": "Portugal", "admin1": "Coimbra", "country_code": "PT"},
                {"name": "Coimbra", "latitude": -20.0, "longitude": -43.0, "country": "Brasil", "admin1": "Minas Gerais", "country_code": "BR"},
            ]
        }
        with mock.patch.object(weather, "_get_json", return_value=payload):
            place = weather.geocode("Coimbra, Brasil", "pt")
        self.assertAlmostEqual(-20.0, place["lat"])

    def test_fetch_falls_back(self):
        with mock.patch.object(weather, "_get_json", side_effect=RuntimeError("limite")):
            with mock.patch.object(weather, "_met_no", return_value={"temp": 12.0, "key": "rain"}) as met:
                out = weather.fetch(38.7, -9.1)
        self.assertEqual({"temp": 12.0, "key": "rain"}, out)
        met.assert_called_once_with(38.7, -9.1)


if __name__ == "__main__":
    unittest.main()
