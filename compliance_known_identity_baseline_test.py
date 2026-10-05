import importlib.util
from pathlib import Path
import tempfile
import unittest

import compliance_store

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "identity_seed",ROOT/"scripts/checkupauto-compliance-seed-known-identity.py"
)
identity_seed=importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity_seed)


class ComplianceKnownIdentityBaselineTest(unittest.TestCase):
    def test_baseline_uses_only_grounded_fields_and_keeps_external_identity_open(self):
        data=identity_seed.load_baseline()
        settings=data["settings"]
        self.assertEqual(settings["controllerName"],"CHECK UP AUTO")
        self.assertEqual(settings["publicationDirector"],"Tarek Zekriti")
        self.assertEqual(settings["approvalAuthority"],"Préfet des Yvelines")
        self.assertEqual(settings["approvalReference"],"S078Z206")
        self.assertEqual(settings["mediatorName"],"Médiateur FNA – Jean-Pierre CHEVROT")
        self.assertEqual(settings["mediatorUrl"],"https://www.mediateur.fna.fr/")
        self.assertIn("Tour Kupka B",settings["mediatorAddress"])
        self.assertNotIn("mediatorName",data["deliberatelyUnasserted"])
        self.assertNotIn("mediatorUrl",data["deliberatelyUnasserted"])
        self.assertNotIn("mediatorAddress",data["deliberatelyUnasserted"])
        self.assertNotIn("privacyContact",settings)
        self.assertIn("privacyContact",data["deliberatelyUnasserted"])

    def test_apply_is_idempotent_and_does_not_claim_identity_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            first=identity_seed.apply(db)
            second=identity_seed.apply(db)
            self.assertTrue(first["knownFieldsVerified"])
            self.assertFalse(first["identityComplete"])
            self.assertEqual(first["missingIdentityFields"],["privacyContact"])
            self.assertTrue(first["changedFields"])
            self.assertEqual(second["changedFields"],[])

    def test_existing_conflicting_fact_fails_closed_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            compliance_store.save_settings({"controllerName":"Other Company"},db)
            with self.assertRaisesRegex(RuntimeError,"conflicts"):
                identity_seed.apply(db)
            self.assertEqual(compliance_store.settings(db)["controllerName"],"Other Company")


if __name__=="__main__":
    unittest.main()
