import unittest
from decimal import Decimal
from tools.research_cli import money, ratio_pass

class ResearchTests(unittest.TestCase):
    def test_budget_invalid(self):
        for x in ['NaN', '-1', 'Infinity', 'unknown']:
            with self.assertRaises(ValueError): money(x)
    def test_budget_exact(self):
        self.assertEqual(money('99.99') + money('0.01'), Decimal('100'))
    def test_threshold_exact(self):
        self.assertTrue(ratio_pass(98, 100, Decimal('.98')))
        self.assertFalse(ratio_pass(9799, 10000, Decimal('.98')))
        self.assertFalse(ratio_pass(0, 0, Decimal('.98')))
