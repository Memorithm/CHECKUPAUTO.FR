"""Tests of the proposed shared helper, independent of customer data or network."""
import datetime as dt
import json
import re
import subprocess
import unittest

import customer_vehicle_inputs as inputs


class VehicleInputGrammarTests(unittest.TestCase):
    def test_only_typography_is_normalised(self):
        self.assertEqual(inputs.compact_identifier(' ab\u2013123\u2011cd '), 'AB123CD')
        self.assertEqual(inputs.compact_identifier('2020 ab 12345'), '2020AB12345')
        self.assertEqual(inputs.compact_identifier('AB12?CD'), 'AB12?CD')
        self.assertEqual(inputs.compact_identifier('ß123AA'), 'ß123AA')

    def test_fni_variable_groups_and_corsican_department(self):
        for value, expected in (
            ('1A01', ('1', 'A', '01')),
            ('1234AB78', ('1234', 'AB', '78')),
            ('123ABC971', ('123', 'ABC', '971')),
            ('123AB2A', ('123', 'AB', '2A')),
            ('123AB2B', ('123', 'AB', '2B')),
        ):
            with self.subTest(value=value):
                self.assertEqual(re.fullmatch(inputs.FNI_PATTERN, value).groups(), expected)
        for value in ('12345AB78', '123ABCD78', '123AB7', '123AB2C', '123ABZZ', '123AB9714'):
            with self.subTest(value=value):
                self.assertIsNone(re.fullmatch(inputs.FNI_PATTERN, value))

    def test_formula_requires_exact_year_letters_digits_order(self):
        self.assertIsNotNone(re.fullmatch(inputs.FORMULA_PATTERN, '2020AB12345'))
        for value in ('AB12CD34EF5', '2020A123456', '2020ABC1234', '2020AB1234', '2020AB123456'):
            with self.subTest(value=value):
                self.assertIsNone(re.fullmatch(inputs.FORMULA_PATTERN, value))

    def test_generated_script_uses_server_date(self):
        script = inputs.vehicle_inputs_script(dt.date(2026, 10, 8))
        self.assertIn('"year": 2026', script)
        self.assertIn('"today": "2026-10-08"', script)
        self.assertNotIn('__VEHICLE_RULES__', script)

    def test_javascript_formatters_and_validation(self):
        checks = r'''
const assert = require('node:assert/strict');
const v = CheckupAutoVehicleInputs;
for (const [raw,system,expected] of [
  ['a','siv','A'],['ab','siv','AB-'],['ab1','siv','AB-1'],
  ['ab123','siv','AB-123-'],['ab123cd','siv','AB-123-CD'],
  ['ab–123–cd','siv','AB-123-CD'],
  ['1','fni','1'],['1234','fni','1234 '],['1234a','fni','1234 A'],
  ['1234ab78','fni','1234 AB 78'],['1a01','fni','1 A 01'],
  ['123abc971','fni','123 ABC 971'],['123ab2a','fni','123 AB 2A'],
  ['123ab2b','fni','123 AB 2B']
]) assert.equal(v.formatRegistration(raw,system),expected,raw);
assert.equal(v.formatRegistration('AB','siv',false),'AB');
assert.equal(v.formatRegistration('1234','fni',false),'1234');
for (const [raw,system] of [
  ['AB123CD','siv'],['aa 123 aa','siv'],
  ['1234AB78','fni'],['1A01','fni'],['123ABC971','fni'],['123AB2A','fni'],['123AB2B','fni']
]) assert.equal(v.registrationError(raw,system),'',raw);
for (const [raw,system] of [
  ['AB123CD4','siv'],['AB12CD','siv'],['AI123AA','siv'],['SS123AA','siv'],
  ['AB000CD','siv'],['AB12?CD','siv'],['ß123AA','siv'],
  ['12345AB78','fni'],['123ABCD78','fni'],['123AB7','fni'],['123AB2C','fni'],
  ['123ABZZ','fni'],['0000AB78','fni'],['123AB00','fni']
]) {
  assert.notEqual(v.registrationError(raw,system),'',raw);
  assert.equal(v.compact(v.formatRegistration(raw,system)),v.compact(raw),raw+' must not be truncated');
}
for (const raw of ['2009AB12345','2026AB12345','2020 ab 12345'])
  assert.equal(v.formulaError(raw),'',raw);
for (const raw of ['', 'AB12CD34EF5','2020A123456','2020ABC1234','2020AB1234','2020AB123456',
                   '2008AB12345','2027AB12345','0000AB12345','2020AB1234?'])
  assert.notEqual(v.formulaError(raw),'',raw);
console.log('Vehicle input helper assertions passed');
'''
        result = subprocess.run(
            ['node', '-'], input=inputs.vehicle_inputs_script(dt.date(2026, 10, 8)) + checks,
            text=True, capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
