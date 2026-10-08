import unittest
from customer_vehicle_booking_readiness import assess

class Tests(unittest.TestCase):
    def test_complete(self):
        self.assertTrue(assess({"registration":"AB-123-CD","registrationSystem":"siv","formulaNumberPresent":True,"characteristics":{"brand":"Peugeot","model":"208","energy":"Essence"}})["ready"])
    def test_legacy_incomplete(self):
        r=assess({"registration":"AB-123-CD","registrationSystem":"siv","formulaNumberPresent":True})
        self.assertFalse(r["ready"])
        self.assertIn("characteristics",r["missing"])
    def test_fni(self):
        r=assess({"registration":"1234 AB 78","registrationSystem":"fni","cardIssueDate":"","characteristics":{"brand":"Peugeot","model":"208","energy":"Essence"}})
        self.assertIn("cardIssueDate",r["missing"])
if __name__=="__main__": unittest.main()
