"""The skyline severity legend has fixed ratio anchors across simulation runs."""

import unittest

from wrapper.skyline import _absolute_severity, _congestion_color


class TrafficScaleTests(unittest.TestCase):
    def test_fixed_ratio_anchors_match_the_display_legend(self):
        for ratio, expected in ((1, 0), (1.2, .35), (1.5, .55), (2, .72), (3, .88), (5, 1)):
            with self.subTest(ratio=ratio):
                self.assertAlmostEqual(_absolute_severity(ratio), expected)

    def test_freeflow_floor_and_gridlock_ceiling_do_not_stretch_to_sample_ranks(self):
        for ratio in (0, .5, .99, 1):
            with self.subTest(ratio=ratio):
                self.assertEqual(_absolute_severity(ratio), 0)
        for ratio in (5, 6, 100):
            with self.subTest(ratio=ratio):
                self.assertEqual(_absolute_severity(ratio), 1)

    def test_intermediate_ratios_interpolate_between_fixed_anchors(self):
        for ratio, expected in ((1.1, .175), (1.35, .45), (1.75, .635), (2.5, .8), (4, .94)):
            with self.subTest(ratio=ratio):
                self.assertAlmostEqual(_absolute_severity(ratio), expected)

    def test_ratio_anchors_produce_distinct_normalized_colors(self):
        colors = [_congestion_color(_absolute_severity(ratio)) for ratio in (1, 1.2, 1.5, 2, 3, 5)]
        self.assertEqual(len(set(colors)), 6)
        self.assertTrue(all(len(color) == 3 and all(0 <= channel <= 1 for channel in color) for color in colors))
        self.assertEqual(_congestion_color(_absolute_severity(.5)), colors[0])
        self.assertEqual(_congestion_color(_absolute_severity(20)), colors[-1])


if __name__ == "__main__":
    unittest.main()
