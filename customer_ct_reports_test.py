import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import customer_ct_reports as reports


SAMPLE="""PROCÈS-VERBAL DE CONTRÔLE TECHNIQUE
IMMATRICULATION : AB-123-CD
VIN : VF3ABCDEFGH123456
DATE DU CONTRÔLE : 25/09/2026
KILOMÉTRAGE RELEVÉ : 124 550
RÉSULTAT DU CONTRÔLE : DÉFAVORABLE
DÉFAILLANCES MAJEURES
1.1.13.a.2 Plaquettes de frein : usure excessive avant
DÉFAILLANCES MINEURES
5.2.3.a.1 Pneumatique : usure irrégulière du pneumatique avant gauche
5.2.3.b.1 Pneumatique : pression anormale
"""


class CTReportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.data=root/"data";self.private=root/"private"
        self.data.mkdir();self.private.mkdir()
        self.env=patch.dict(os.environ,{
            "CYBERCHECK_DATA_DIR":str(self.data),
            "CYBERCHECK_PRIVATE_DIR":str(self.private),
        },clear=False)
        self.env.start();self.addCleanup(self.env.stop)
        self.account="00000000-0000-4000-8000-000000000001"

    def test_parser_extracts_identity_result_mileage_and_report_severities(self):
        parsed=reports.parse_report(SAMPLE)
        self.assertEqual(parsed["registration"],"AB-123-CD")
        self.assertEqual(parsed["vin"],"VF3ABCDEFGH123456")
        self.assertEqual(parsed["controlDate"],"25/09/2026")
        self.assertEqual(parsed["mileageKm"],124550)
        self.assertEqual(parsed["result"],"défavorable")
        self.assertEqual([x["severity"] for x in parsed["defects"]],["majeure","mineure","mineure"])
        self.assertEqual(parsed["defects"][0]["code"],"1.1.13.a.2")

    def test_markdown_contains_structured_findings_and_advice_version(self):
        structured=reports.parse_report(SAMPLE)
        import ct_advisor
        advice=ct_advisor.advise(structured["defects"])
        md=reports.render_markdown(structured,advice,extraction_method="synthetic-test")
        self.assertIn("# Rapport de contrôle technique",md)
        self.assertIn("| 5.2.3.a.1 | mineure |",md)
        self.assertIn("Usure irrégulière des pneumatiques",md)
        self.assertIn(ct_advisor.ADVISOR_VERSION,md)
        self.assertIn("ne remplace",md)

    def test_ingest_discards_raw_document_and_encrypts_retained_payload(self):
        raw=b"synthetic-binary-report-do-not-store"
        with patch.object(reports,"extract_text",return_value=(SAMPLE,"synthetic-text")):
            created=reports.ingest(self.account,"controle.pdf","application/pdf",raw)
        self.assertFalse(created["rawDocumentRetained"])
        self.assertIn("Plaquettes de frein",created["markdown"])
        database=reports.db_path().read_bytes()
        self.assertNotIn(raw,database)
        self.assertNotIn("Plaquettes de frein".encode(),database)
        key=self.private/"customer"/"reports.key"
        self.assertEqual(key.stat().st_mode & 0o777,0o600)
        self.assertEqual(reports.db_path().stat().st_mode & 0o777,0o600)

    def test_duplicate_document_is_idempotent_per_account(self):
        raw=b"same-document"
        with patch.object(reports,"extract_text",return_value=(SAMPLE,"synthetic-text")) as extract:
            first=reports.ingest(self.account,"controle.pdf","application/pdf",raw)
            second=reports.ingest(self.account,"controle.pdf","application/pdf",raw)
        self.assertEqual(first["reportId"],second["reportId"])
        extract.assert_called_once()

    def test_list_get_delete_are_account_scoped(self):
        with patch.object(reports,"extract_text",return_value=(SAMPLE,"synthetic-text")):
            created=reports.ingest(self.account,"controle.jpg","image/jpeg",b"jpeg-data")
        listed=reports.list_reports(self.account)
        self.assertEqual(len(listed),1)
        self.assertIsNone(listed[0]["structured"])
        self.assertEqual(reports.get_report(self.account,created["reportId"])["reportId"],created["reportId"])
        other="00000000-0000-4000-8000-000000000002"
        with self.assertRaisesRegex(reports.CTReportError,"^ct_report_not_found$"):
            reports.get_report(other,created["reportId"])
        self.assertFalse(reports.delete_report(other,created["reportId"]))
        self.assertTrue(reports.delete_report(self.account,created["reportId"]))
        self.assertEqual(reports.list_reports(self.account),[])

    def test_invalid_content_type_and_size_fail_before_extraction(self):
        with self.assertRaisesRegex(reports.CTReportError,"^ct_report_type_invalid$"):
            reports.ingest(self.account,"report.txt","text/plain",b"hello")
        with self.assertRaisesRegex(reports.CTReportError,"^ct_report_size_invalid$"):
            reports.ingest(self.account,"report.pdf","application/pdf",b"")


if __name__=="__main__":
    unittest.main()
