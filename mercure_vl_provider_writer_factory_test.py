import unittest
from unittest.mock import patch
import mercure_vl_provider_writer_factory as factory

class Tests(unittest.TestCase):
    def setUp(self):
        self.metadata=dict(service_id="1763",duration="40",centre_type="1",
                           line_id="454",operator_id="464")
        self.observed=dict(prestation=["1763"],duree=["40"],centre_type=["1"],
                           ligne_id=["454"],utilisateur=["464"])
        self.kw=dict(appointment={},metadata=self.metadata,observed_metadata=self.observed,
                     expected_service_label="CONTROLE TECHNIQUE",authorized=True)

    def test_default_refuses(self):
        with self.assertRaises(factory.MercureVlWriterFactoryError):
            factory.create(**{**self.kw,"authorized":False})

    def test_unverified_metadata_refuses_before_session(self):
        with patch.object(factory.mercure,"_session") as session:
            with self.assertRaises(factory.MercureVlWriterFactoryError):
                factory.create(**{**self.kw,"observed_metadata":{}})
            session.assert_not_called()

    def test_verified_factory_binds_reader(self):
        with patch.object(factory.mercure,"_session",return_value=object()),patch.object(
            factory,"MercureVlWriteAdapter",return_value=object()) as writer:
            factory.create(**self.kw)
        self.assertIs(writer.call_args.kwargs["identity_reader"],factory.read_and_verify)
