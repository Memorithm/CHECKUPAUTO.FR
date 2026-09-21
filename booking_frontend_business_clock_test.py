import unittest
from pathlib import Path


class BookingFrontendBusinessClockContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).with_name("app.js").read_text(encoding="utf-8")

    def test_planner_waits_for_server_business_bounds(self):
        self.assertIn("loadPlannerBounds().finally(()=>initPlanner())", self.source)
        self.assertIn("fetch('/api/booking/services'", self.source)
        self.assertIn("d.businessDate", self.source)
        self.assertIn("d.horizonEnd", self.source)

    def test_planner_input_uses_resolved_bounds_only(self):
        start = self.source.index("function initPlanner()")
        end = self.source.index("\n\nfunction trackingDevice", start)
        planner = self.source[start:end]
        self.assertIn("plannerState.bounds||plannerFallbackBounds()", planner)
        self.assertIn("date.min=bounds.businessDate", planner)
        self.assertIn("date.max=bounds.horizonEnd", planner)
        self.assertNotIn("new Date()", planner)
        self.assertNotIn("getFullYear", planner)
        self.assertNotIn("getMonth", planner)
        self.assertNotIn("getDate", planner)

    def test_fallback_is_explicitly_paris_based(self):
        self.assertIn("timeZone:'Europe/Paris'", self.source)
        self.assertIn("Date.UTC(", self.source)
        self.assertNotIn("function localISODate", self.source)


if __name__ == "__main__":
    unittest.main()
