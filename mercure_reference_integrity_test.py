import unittest
from mercure_reference_integrity import validate,MercureReferenceIntegrityError

class Tests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate([{"id":"12","label":" Peugeot "}]),[{"id":"12","label":"Peugeot"}])
    def test_duplicates(self):
        for rows in ([{"id":"1","label":"A"},{"id":"1","label":"B"}],[{"id":"1","label":"A"},{"id":"2","label":" a "}]):
            with self.assertRaises(MercureReferenceIntegrityError):
                validate(rows)
    def test_malformed(self):
        for rows in (None,{},[{"id":"abc","label":"A"}]):
            with self.assertRaises(MercureReferenceIntegrityError):
                validate(rows)
if __name__=="__main__": unittest.main()
