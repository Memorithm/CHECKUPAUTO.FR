import datetime as dt
import unittest
from unittest.mock import patch
import customer_booking_api as api

class CompletePreflightTests(unittest.TestCase):
    def setUp(self):
        self.day=(dt.date.today()+dt.timedelta(days=2)).isoformat()
        self.vehicle={'vehicleId':'v1','registration':'AB-123-CD','registrationSystem':'siv','formulaNumberPresent':True,'characteristics':{'brand':'Peugeot','model':'208','energy':'Essence'}}
        self.account={'vehicles':[self.vehicle]}
        self.payload={'vehicleId':'v1','service':'technical','date':self.day,'time':'10:20'}
    def availability(self,price=80):
        return {'days':[{'date':self.day,'slots':[{'time':'10:20','price':price}]}]}
    def test_incomplete_saved_vehicle_stops_before_provider(self):
        for field in ('brand','model','energy'):
            with self.subTest(field=field),patch.object(api.mercure_public_client,'availability') as provider:
                self.vehicle['characteristics'][field]=''
                with self.assertRaisesRegex(api.BookingPreflightError,'booking_vehicle_incomplete'):
                    api.preflight(self.payload,account=self.account)
                provider.assert_not_called()
                self.vehicle['characteristics'][field]='value'
    def test_available_is_not_a_hold_or_confirmation(self):
        with patch.object(api.mercure_public_client,'availability',return_value=self.availability(19.99)):
            result=api.preflight(self.payload,account=self.account)
        self.assertEqual(result['priceCents'],1999)
        self.assertIs(result['slotHeld'],False);self.assertIs(result['bookingConfirmed'],False)
    def test_bad_price_or_duplicate_slot_refused(self):
        for price in (float('nan'),float('inf'),80.005,True,'80',-1):
            with self.subTest(price=price),patch.object(api.mercure_public_client,'availability',return_value=self.availability(price)):
                with self.assertRaisesRegex(api.BookingPreflightError,'booking_price_unverified'):
                    api.preflight(self.payload,account=self.account)
        data=self.availability();data['days'][0]['slots']*=2
        with patch.object(api.mercure_public_client,'availability',return_value=data):
            with self.assertRaisesRegex(api.BookingPreflightError,'booking_slot_ambiguous'):api.preflight(self.payload,account=self.account)
    def test_fni_and_disabled_slots(self):
        self.vehicle.update(registrationSystem='fni',registration='1234 AB 78',cardIssueDate='2005-01-01',formulaNumberPresent=False)
        with patch.object(api.mercure_public_client,'availability',return_value=self.availability()):
            self.assertTrue(api.preflight(self.payload,account=self.account)['ok'])
        data=self.availability();data['days'][0]['available']=False
        with patch.object(api.mercure_public_client,'availability',return_value=data):
            with self.assertRaisesRegex(api.BookingPreflightError,'booking_slot_unavailable'):api.preflight(self.payload,account=self.account)
    def test_business_date_is_the_authority(self):
        with patch.object(api.mercure_admin_client,'business_today',return_value=dt.date.fromisoformat(self.day)+dt.timedelta(days=1)),patch.object(api.mercure_public_client,'availability') as provider:
            with self.assertRaisesRegex(api.BookingPreflightError,'booking_date_invalid'):api.preflight(self.payload,account=self.account)
            provider.assert_not_called()
