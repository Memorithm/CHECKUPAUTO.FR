"""Q-06: the identity annotation resolves to the real class under type checking."""
import importlib.util
import typing
import unittest
from unittest import mock

import customer_booking_reconcile
from mercure_booking_identity_evidence import VerifiedBookingIdentity


class ReconcileTypingTest(unittest.TestCase):
    def test_identity_annotation_resolves_when_type_checking(self):
        spec = importlib.util.spec_from_file_location("_reconcile_typed", customer_booking_reconcile.__file__)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(typing, "TYPE_CHECKING", True):
            spec.loader.exec_module(module)
        hints = typing.get_type_hints(module.reconcile_with_identity)
        self.assertIs(hints["identity_evidence"], VerifiedBookingIdentity)

    def test_runtime_import_stays_lazy(self):
        self.assertFalse(hasattr(customer_booking_reconcile, "VerifiedBookingIdentity"))


if __name__ == "__main__":
    unittest.main()
