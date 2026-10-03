import unittest
from unittest.mock import patch
import mac_clock as clock


class ClockTests(unittest.TestCase):
    def test_parent_uptime_is_not_sent_to_child(self):
        with patch.object(clock.time, 'monotonic', return_value=100000), patch.object(clock, 'shared_now', return_value=700000):
            self.assertEqual(clock.lease_deadline(100060), 700061)

    def test_expired_lease_has_only_one_second_grace(self):
        with patch.object(clock.time, 'monotonic', return_value=100000), patch.object(clock, 'shared_now', return_value=700000):
            self.assertEqual(clock.lease_deadline(10), 700001)

    def test_watchdog_validates_shared_clock_and_bounds(self):
        with patch.object(clock, 'shared_now', return_value=700000):
            self.assertEqual(clock.valid_deadline(700061), 700061)
            for value in (61,700000,714403,float('nan'),float('inf')):
                with self.assertRaises(ValueError):clock.valid_deadline(value)


if __name__ == '__main__':unittest.main()
