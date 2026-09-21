from pathlib import Path
import unittest


class AdminBusinessClockBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path('admin_server.py').read_text()

    def _block(self, start, end):
        begin = self.source.find(start)
        self.assertGreaterEqual(begin, 0, start)
        finish = self.source.find(end, begin)
        self.assertGreaterEqual(finish, 0, end)
        return self.source[begin:finish]

    def test_server_never_uses_host_local_date_for_business_rules(self):
        self.assertNotIn('datetime.date.today()', self.source)

    def test_booking_services_publish_server_business_bounds(self):
        block = self._block("  if path=='/api/booking/services':", "  if path=='/api/geo/coverage':")
        self.assertIn('today=mercure_admin.business_today()', block)
        self.assertIn("'businessDate':today.isoformat()", block)
        self.assertIn("'horizonEnd':horizon.isoformat()", block)

    def test_booking_availability_uses_paris_business_day(self):
        block = self._block("  if path=='/api/booking/availability':", "  if path=='/go/app':")
        self.assertIn('today=mercure_admin.business_today()', block)
        self.assertIn('limit=today+datetime.timedelta', block)

    def test_mercure_promotion_boundaries_use_same_business_day(self):
        get_block = self._block("    if path=='/api/admin/mercure/promotions':", "    if path=='/api/admin/mercure/secret':")
        self.assertIn('today=mercure_admin.business_today()', get_block)
        post_block = self._block("  if path=='/api/admin/mercure/promo-slot':", "  if path=='/api/admin/mercure/rotate-secret':")
        self.assertIn('today=mercure_admin.business_today()', post_block)


if __name__ == '__main__':
    unittest.main()
