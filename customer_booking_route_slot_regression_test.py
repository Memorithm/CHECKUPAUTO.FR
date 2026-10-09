import unittest
from unittest.mock import patch
import customer_booking_server_composition as composition
import customer_booking_create_api as api

class Tests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'observed':True,'service':'technical','date':'2026-10-12','time':'09:00',
                       'lineId':'454','serviceId':'1763','duration':'40','priceCents':8000}
        self.kw=dict(payload={'service':'technical','date':'2026-10-12','time':'09:00'},
                     account={},vehicle={},line_id='454',operator_id='464',
                     payment_policy={},payment_evidence=None,authorized=True,slot_evidence=self.snapshot)
    def test_missing_slot_proof_blocks_before_provider(self):
        with patch.object(composition.mercure_vl_provider_metadata_resolver,'resolve') as resolver:
            with self.assertRaisesRegex(ValueError,'slot_evidence_required'):
                composition.execute(**(self.kw | {'slot_evidence':None}))
            resolver.assert_not_called()
    def test_changed_slot_blocks_before_writer(self):
        provider={'metadata':{},'observed_metadata':{},'service_label':'CT',
                  'slot_evidence':self.snapshot | {'time':'09:40'}}
        with patch.object(composition.mercure_vl_provider_metadata_resolver,'resolve',return_value=provider),patch.object(composition.customer_booking_server_execution,'execute') as writer:
            with self.assertRaisesRegex(ValueError,'slot_evidence_changed'):
                composition.execute(**self.kw)
            writer.assert_not_called()
    def test_identical_fresh_slot_reaches_writer(self):
        provider={'metadata':{},'observed_metadata':{},'service_label':'CT',
                  'slot_evidence':self.snapshot}
        with patch.object(composition.mercure_vl_provider_metadata_resolver,'resolve',return_value=provider),patch.object(composition.customer_booking_server_execution,'execute',return_value={'confirmed':False}) as writer:
            composition.execute(**self.kw)
            self.assertEqual(writer.call_args.kwargs['slot_evidence'],self.snapshot)
if __name__=='__main__':unittest.main()
