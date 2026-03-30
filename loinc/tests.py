"""
loinc/tests.py
~~~~~~~~~~~~~~
Tests for the LOINC code lookup.

Run with:  python manage.py test loinc
"""

from django.test import TestCase, Client
from django.urls import reverse
from .codes import LOINC_CODES, CATEGORIES


class TestLOINCData(TestCase):

    def test_codes_dict_not_empty(self):
        self.assertGreater(len(LOINC_CODES), 50)

    def test_every_code_has_required_fields(self):
        required = {"name", "long_name", "category", "specimen", "unit", "scale"}
        for code, info in LOINC_CODES.items():
            missing = required - info.keys()
            self.assertEqual(missing, set(), f"Code {code} missing fields: {missing}")

    def test_known_codes_present(self):
        for code in ["718-7", "4548-4", "8480-6", "34133-9", "2160-0"]:
            self.assertIn(code, LOINC_CODES, f"Expected LOINC code {code}")

    def test_hemoglobin_details(self):
        hgb = LOINC_CODES["718-7"]
        self.assertEqual(hgb["category"], "CBC")
        self.assertEqual(hgb["unit"], "g/dL")
        self.assertEqual(hgb["scale"], "Qn")

    def test_categories_list(self):
        self.assertIn("CBC", CATEGORIES)
        self.assertIn("Vitals", CATEGORIES)
        self.assertIn("CMP", CATEGORIES)
        self.assertIn("Cardiac", CATEGORIES)

    def test_all_categories_have_at_least_one_code(self):
        for cat in CATEGORIES:
            codes_in_cat = [c for c, v in LOINC_CODES.items() if v["category"] == cat]
            self.assertGreater(len(codes_in_cat), 0, f"Category {cat} has no codes")


class TestLOINCSearchAPI(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("loinc-search")

    def test_no_params_returns_all(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertGreater(data["count"], 0)

    def test_search_by_name(self):
        resp = self.client.get(self.url, {"q": "hemoglobin"})
        data = resp.json()
        self.assertGreater(data["count"], 0)
        names = [r["name"].lower() for r in data["results"]]
        self.assertTrue(any("hemoglobin" in n for n in names))

    def test_search_by_code(self):
        resp = self.client.get(self.url, {"q": "718-7"})
        data = resp.json()
        codes = [r["code"] for r in data["results"]]
        self.assertIn("718-7", codes)

    def test_filter_by_category(self):
        resp = self.client.get(self.url, {"category": "CBC"})
        data = resp.json()
        categories = {r["category"] for r in data["results"]}
        self.assertEqual(categories, {"CBC"})

    def test_no_match_returns_empty(self):
        resp = self.client.get(self.url, {"q": "zzznomatch99999"})
        data = resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_result_has_all_fields(self):
        resp = self.client.get(self.url, {"q": "718-7"})
        result = resp.json()["results"][0]
        for field in ["code", "name", "long_name", "category", "specimen", "unit", "scale"]:
            self.assertIn(field, result)

    def test_category_and_q_combined(self):
        resp = self.client.get(self.url, {"category": "Vitals", "q": "blood pressure"})
        data = resp.json()
        for r in data["results"]:
            self.assertEqual(r["category"], "Vitals")
