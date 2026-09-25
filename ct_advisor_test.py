import unittest

import ct_advisor


class CTAdvisorTest(unittest.TestCase):
    def test_minor_irregular_tyre_wear_gets_prevention_without_reclassification(self):
        advice=ct_advisor.advise([{
            "code":"5.2.3.a.1",
            "severity":"mineure",
            "description":"Pneumatique : usure irrégulière du pneumatique avant gauche",
        }])
        self.assertTrue(any(item["ruleId"]=="tyre-irregular-wear" for item in advice))
        item=next(item for item in advice if item["ruleId"]=="tyre-irregular-wear")
        self.assertEqual(item["severity"],"mineure")
        self.assertIn("restera mineur",item["severityContext"])
        self.assertIn("pression",item["prevention"].lower())
        self.assertIn("géométrie",item["prevention"].lower())

    def test_brake_wear_advice_preserves_major_severity(self):
        advice=ct_advisor.advise([{
            "code":"1.1.13.a.2",
            "severity":"majeure",
            "description":"Plaquettes de frein : usure excessive",
        }])
        item=next(item for item in advice if item["ruleId"]=="brake-wear")
        self.assertEqual(item["severity"],"majeure")
        self.assertIn("contre-visite",item["severityContext"].lower())
        self.assertIn("épaisseur",item["prevention"].lower())

    def test_unknown_defect_uses_generic_advice_without_inventing_category(self):
        advice=ct_advisor.advise([{
            "code":"9.9.9.a.1","severity":"non classée","description":"Observation non reconnue",
        }])
        self.assertEqual(advice[0]["ruleId"],"generic")
        self.assertEqual(advice[0]["severity"],"non classée")
        self.assertIn("ne la déduit pas",advice[0]["severityContext"])

    def test_summary_counts_only_report_severity(self):
        text=ct_advisor.summary([
            {"severity":"mineure"},{"severity":"mineure"},{"severity":"majeure"},{"severity":"critique"},
        ])
        self.assertIn("2 mineure",text)
        self.assertIn("1 majeure",text)
        self.assertIn("1 critique",text)


if __name__=="__main__":
    unittest.main()
