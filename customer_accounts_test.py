import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics
import customer_accounts as accounts


class CustomerAccountsTest(unittest.TestCase):
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
        self.previous_db=analytics.DB
        analytics.DB=root/"analytics.sqlite3"
        self.addCleanup(setattr,analytics,"DB",self.previous_db)

    def create(self,provider="google",subject="sub-1",email="client@example.test"):
        return accounts.create_from_verified_identity(
            provider,subject,email,"Client Test",email_verified=True,
        )

    def test_verified_identity_creates_encrypted_account_and_loyalty_wallet(self):
        result=self.create()
        self.assertEqual(result["kind"],"individual")
        self.assertEqual(result["displayName"],"Client Test")
        self.assertEqual(result["email"],"client@example.test")
        self.assertEqual(result["providers"],["google"])
        self.assertEqual(result["phone"],"")
        self.assertEqual(result["addressLine1"],"")
        self.assertFalse(result["contactDetailsComplete"])
        self.assertRegex(result["loyalty"]["referralCode"],r"^[A-Z0-9-]{4,24}$")
        self.assertEqual(result["loyalty"]["balanceCents"],0)

        raw=accounts.data_path().read_bytes()
        self.assertNotIn(b"client@example.test",raw)
        self.assertNotIn(b"Client Test",raw)
        key=Path(os.environ["CYBERCHECK_PRIVATE_DIR"])/"customer"/"accounts.key"
        self.assertEqual(key.stat().st_mode & 0o777,0o600)
        self.assertEqual(accounts.data_path().stat().st_mode & 0o777,0o600)

    def test_identity_login_is_idempotent_but_foreign_identity_cannot_auto_link_email(self):
        first=self.create()
        again=self.create()
        self.assertEqual(first["accountId"],again["accountId"])
        with self.assertRaisesRegex(accounts.CustomerAccountError,"^customer_account_link_required$"):
            self.create(provider="apple",subject="apple-sub",email="client@example.test")

    def test_unverified_email_is_never_accepted(self):
        with self.assertRaisesRegex(accounts.CustomerAccountError,"^customer_email_not_verified$"):
            accounts.create_from_verified_identity(
                "google","sub-1","client@example.test","Client Test",email_verified=False,
            )
        self.assertFalse(accounts.data_path().exists())

    def test_professional_profile_requires_company_and_validates_siret(self):
        created=self.create()
        with self.assertRaisesRegex(accounts.CustomerAccountError,"^customer_company_name_invalid$"):
            accounts.update_profile(
                created["accountId"],kind="professional",display_name="Client Test",
                company_name="",siret="",
            )
        updated=accounts.update_profile(
            created["accountId"],kind="professional",display_name="Client Test",
            company_name="Garage Exemple",siret="12345678901234",
        )
        self.assertEqual(updated["kind"],"professional")
        self.assertEqual(updated["companyName"],"Garage Exemple")
        self.assertEqual(updated["siret"],"12345678901234")

    def test_contact_details_are_encrypted_and_complete_only_when_phone_and_address_present(self):
        created=self.create()
        updated=accounts.update_contact_details(
            created["accountId"],
            phone="+33 6 12 34 56 78",
            address_line1="12 rue de Paris",
            address_line2="Bâtiment B",
            postal_code="78130",
            city="Les Mureaux",
        )
        self.assertTrue(updated["contactDetailsComplete"])
        self.assertEqual(updated["phone"],"+33 6 12 34 56 78")
        self.assertEqual(updated["addressLine1"],"12 rue de Paris")
        self.assertEqual(updated["postalCode"],"78130")
        self.assertEqual(updated["city"],"Les Mureaux")
        raw=accounts.data_path().read_bytes()
        self.assertNotIn(b"+33 6 12 34 56 78",raw)
        self.assertNotIn(b"12 rue de Paris",raw)
        self.assertNotIn(b"Les Mureaux",raw)

    def test_each_passage_requires_fresh_one_time_contact_confirmation(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],
            phone="0612345678",
            address_line1="12 rue de Paris",
            postal_code="78130",
            city="Les Mureaux",
        )
        first=accounts.begin_passage_confirmation(created["accountId"])
        second=accounts.begin_passage_confirmation(created["accountId"])
        self.assertNotEqual(first["passageToken"],second["passageToken"])

        with self.assertRaisesRegex(PermissionError,"customer_passage_not_confirmed"):
            accounts.consume_passage_confirmation(created["accountId"],first["passageToken"])

        confirmed=accounts.confirm_passage_contact(
            created["accountId"],first["passageToken"],action="validated"
        )
        self.assertTrue(confirmed["confirmed"])
        consumed=accounts.consume_passage_confirmation(
            created["accountId"],first["passageToken"]
        )
        self.assertTrue(consumed["consumed"])
        self.assertFalse(consumed["confirmationRetained"])
        with self.assertRaisesRegex(PermissionError,"customer_passage_invalid"):
            accounts.consume_passage_confirmation(created["accountId"],first["passageToken"])

        with self.assertRaisesRegex(PermissionError,"customer_passage_not_confirmed"):
            accounts.consume_passage_confirmation(created["accountId"],second["passageToken"])

    def test_confirmation_and_handoff_use_locked_profile_snapshot(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],
            phone="0612345678",
            address_line1="12 rue de Paris",
            postal_code="78130",
            city="Les Mureaux",
        )
        passage=accounts.begin_passage_confirmation(created["accountId"])

        with patch.object(
            accounts,"profile",
            side_effect=AssertionError("critical confirmation path must not use unlocked profile()"),
        ):
            confirmed=accounts.confirm_passage_contact(
                created["accountId"],passage["passageToken"],action="validated"
            )
            self.assertTrue(confirmed["confirmed"])
            consumed=accounts.consume_latest_passage_confirmation(created["accountId"])
            self.assertTrue(consumed["consumed"])

    def test_latest_confirmed_passage_is_consumed_once_at_booking_handoff(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],
            phone="0612345678",
            address_line1="12 rue de Paris",
            postal_code="78130",
            city="Les Mureaux",
        )
        passage=accounts.begin_passage_confirmation(created["accountId"])
        accounts.confirm_passage_contact(
            created["accountId"],passage["passageToken"],action="validated"
        )

        consumed=accounts.consume_latest_passage_confirmation(created["accountId"])
        self.assertTrue(consumed["consumed"])
        self.assertEqual(consumed["action"],"validated")
        self.assertFalse(consumed["confirmationRetained"])

        with self.assertRaisesRegex(PermissionError,"customer_passage_confirmation_required"):
            accounts.consume_latest_passage_confirmation(created["accountId"])

    def test_passage_confirmation_is_invalidated_if_contact_details_change(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],
            phone="0612345678",
            address_line1="12 rue de Paris",
            postal_code="78130",
            city="Les Mureaux",
        )
        passage=accounts.begin_passage_confirmation(created["accountId"])
        accounts.confirm_passage_contact(
            created["accountId"],passage["passageToken"],action="validated"
        )
        accounts.update_contact_details(
            created["accountId"],
            phone="0699999999",
            address_line1="12 rue de Paris",
            postal_code="78130",
            city="Les Mureaux",
        )
        with self.assertRaisesRegex(PermissionError,"customer_passage_contact_changed"):
            accounts.consume_passage_confirmation(
                created["accountId"],passage["passageToken"]
            )

    def test_incomplete_contact_details_cannot_be_confirmed_for_passage(self):
        created=self.create()
        passage=accounts.begin_passage_confirmation(created["accountId"])
        with self.assertRaisesRegex(accounts.CustomerAccountError,"customer_contact_details_incomplete"):
            accounts.confirm_passage_contact(
                created["accountId"],passage["passageToken"],action="validated"
            )

    def test_siv_and_fni_vehicle_details_are_validated_and_encrypted(self):
        created=self.create()
        siv=accounts.save_vehicle(
            created["accountId"],
            registration_system="siv",
            registration="aa 123 aa",
            formula_number="2020AB12345",
        )
        self.assertEqual(siv["registration"],"AA-123-AA")
        self.assertEqual(siv["registrationSystem"],"siv")
        self.assertTrue(siv["formulaNumberPresent"])
        self.assertEqual(siv["cardIssueDate"],"")

        fni=accounts.save_vehicle(
            created["accountId"],
            registration_system="fni",
            registration="1234 ab 78",
            card_issue_date="2008-05-17",
        )
        self.assertEqual(fni["registration"],"1234 AB 78")
        self.assertEqual(fni["registrationSystem"],"fni")
        self.assertFalse(fni["formulaNumberPresent"])
        self.assertEqual(fni["cardIssueDate"],"2008-05-17")

        summaries=accounts.list_vehicles(created["accountId"])
        self.assertEqual({row["vehicleId"] for row in summaries},{siv["vehicleId"],fni["vehicleId"]})
        self.assertNotIn("2020AB12345",repr(summaries))
        raw=accounts.data_path().read_bytes()
        for private in (b"AA-123-AA",b"2020AB12345",b"1234 AB 78",b"2008-05-17"):
            self.assertNotIn(private,raw)

    def test_vehicle_registration_branch_requires_formula_or_card_issue_date(self):
        created=self.create()
        with self.assertRaisesRegex(accounts.CustomerAccountError,"formula_number_invalid"):
            accounts.save_vehicle(
                created["accountId"],registration_system="siv",
                registration="AA-123-AA",formula_number="",
            )
        with self.assertRaisesRegex(accounts.CustomerAccountError,"card_issue_date_invalid"):
            accounts.save_vehicle(
                created["accountId"],registration_system="fni",
                registration="1234 AB 78",card_issue_date="",
            )
        with self.assertRaisesRegex(accounts.CustomerAccountError,"registration_invalid"):
            accounts.save_vehicle(
                created["accountId"],registration_system="siv",
                registration="1234 AB 78",formula_number="2020AB12345",
            )
        for invalid in ("AI-123-AA","AA-123-OU","SS-123-AA","AA-123-SS"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(accounts.CustomerAccountError,"registration_invalid"):
                accounts.save_vehicle(
                    created["accountId"],registration_system="siv",
                    registration=invalid,formula_number="2020AB12345",
                )

    def test_vehicle_can_be_updated_by_id_and_deleted_from_customer_space(self):
        created=self.create()
        first=accounts.save_vehicle(
            created["accountId"],registration_system="siv",
            registration="AA-123-AA",formula_number="2020AB12345",
        )
        updated=accounts.save_vehicle(
            created["accountId"],vehicle_id=first["vehicleId"],
            registration_system="siv",registration="AB-456-CD",
            formula_number="2021ZX98765",
        )
        self.assertEqual(updated["vehicleId"],first["vehicleId"])
        self.assertEqual(updated["registration"],"AB-456-CD")
        self.assertEqual(len(accounts.list_vehicles(created["accountId"])),1)
        removed=accounts.delete_vehicle(created["accountId"],first["vehicleId"])
        self.assertEqual(removed["registration"],"AB-456-CD")
        self.assertEqual(accounts.list_vehicles(created["accountId"]),[])
        raw=accounts.data_path().read_bytes()
        self.assertNotIn(b"2021ZX98765",raw)

    def test_vehicle_linked_to_active_booking_confirmation_cannot_be_deleted(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],phone="0612345678",address_line1="12 rue de Paris",
            postal_code="78130",city="Les Mureaux",
        )
        vehicle=accounts.save_vehicle(
            created["accountId"],registration_system="fni",
            registration="1234 AB 78",card_issue_date="2008-05-17",
        )
        target="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-15&preferredTime=10%3A30"
        passage=accounts.begin_passage_confirmation(created["accountId"],target)
        accounts.confirm_passage_contact(
            created["accountId"],passage["passageToken"],action="validated",
            vehicle_id=vehicle["vehicleId"],booking_target=target,
        )
        with self.assertRaisesRegex(accounts.CustomerAccountError,"customer_vehicle_in_use"):
            accounts.delete_vehicle(created["accountId"],vehicle["vehicleId"])
        accounts.consume_latest_passage_confirmation(created["accountId"],target)
        accounts.delete_vehicle(created["accountId"],vehicle["vehicleId"])
        self.assertEqual(accounts.list_vehicles(created["accountId"]),[])

    def test_booking_confirmation_is_bound_to_selected_vehicle_and_slot(self):
        created=self.create()
        accounts.update_contact_details(
            created["accountId"],phone="0612345678",address_line1="12 rue de Paris",
            postal_code="78130",city="Les Mureaux",
        )
        vehicle=accounts.save_vehicle(
            created["accountId"],registration_system="siv",
            registration="AB-123-CD",formula_number="2020AB12345",
        )
        target="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-15&preferredTime=10%3A30"
        other="/go/booking?service=Contr%C3%B4le+technique&preferredDate=2026-10-16&preferredTime=10%3A30"
        passage=accounts.begin_passage_confirmation(created["accountId"],target)
        accounts.confirm_passage_contact(
            created["accountId"],passage["passageToken"],action="validated",
            vehicle_id=vehicle["vehicleId"],booking_target=target,
        )
        with self.assertRaisesRegex(PermissionError,"confirmation_required"):
            accounts.consume_latest_passage_confirmation(created["accountId"],other)
        consumed=accounts.consume_latest_passage_confirmation(created["accountId"],target)
        self.assertEqual(consumed["vehicleId"],vehicle["vehicleId"])
        self.assertEqual(consumed["vehicle"]["registration"],"AB-123-CD")

    def test_session_is_opaque_hashed_and_can_be_closed(self):
        created=self.create()
        session=accounts.issue_session(created["accountId"])
        self.assertEqual(accounts.authenticate_session(session["token"]),created["accountId"])
        raw=accounts.data_path().read_bytes()
        self.assertNotIn(session["token"].encode(),raw)
        accounts.close_session(session["token"])
        with self.assertRaisesRegex(PermissionError,"^customer_session_invalid$"):
            accounts.authenticate_session(session["token"])


if __name__=="__main__":
    unittest.main()
