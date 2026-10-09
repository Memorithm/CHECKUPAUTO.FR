import unittest
from unittest.mock import patch
import mercure_vl_booking_coordinator as coordinator

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(request=object(),account={},vehicle={},metadata={},
                     observed_metadata={},expected_service_label="CONTROLE TECHNIQUE")

    def test_default_denies_before_assembly(self):
        with patch.object(coordinator.mercure_customer_booking_assembly,"assemble") as assemble:
            with self.assertRaises(coordinator.MercureVlBookingCoordinatorError):
                coordinator.create_and_verify(**self.kw)
            assemble.assert_not_called()

    def test_qualified_path_invokes_durable_coordinator(self):
        with patch.object(coordinator.mercure_customer_booking_assembly,"assemble",
                          return_value={"appointment":{"nom":"Test"}}),patch.object(
                          coordinator.mercure_vl_provider_writer_factory,"create",
                          return_value=object()) as factory,patch.object(
                          coordinator.customer_booking_creation,"create_and_verify",
                          return_value={"confirmed":True}) as create:
            result=coordinator.create_and_verify(**self.kw,authorized=True)
        self.assertTrue(result["confirmed"])
        factory.assert_called_once()
        create.assert_called_once()
