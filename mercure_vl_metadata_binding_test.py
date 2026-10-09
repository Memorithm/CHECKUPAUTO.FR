import unittest
from unittest.mock import patch
from mercure_vl_metadata_binding import prepare,FIELDS

class Tests(unittest.TestCase):
    def setUp(self):
        self.metadata={key:"1" for key in FIELDS}
        self.observed={key:["1"] for key in FIELDS}

    def test_verified_metadata_reaches_builder(self):
        with patch("mercure_vl_metadata_binding.build",return_value={"ok":True}) as builder:
            self.assertEqual(prepare(appointment={},metadata=self.metadata,observed=self.observed),{"ok":True})
            builder.assert_called_once()

    def test_missing_observation_blocks_builder(self):
        with patch("mercure_vl_metadata_binding.build") as builder:
            with self.assertRaises(ValueError):
                prepare(appointment={},metadata=self.metadata,observed={})
            builder.assert_not_called()
