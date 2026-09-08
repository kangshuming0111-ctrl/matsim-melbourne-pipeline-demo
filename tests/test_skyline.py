import unittest

from wrapper.skyline import _congestion_color, _visual_building_style


class SkylineStyleTests(unittest.TestCase):
    def test_congestion_ramp_has_distinct_endpoints(self):
        free = _congestion_color(0.0)
        jammed = _congestion_color(1.0)

        self.assertGreater(free[1], free[0])
        self.assertLess(sum(jammed), sum(free))
        self.assertNotEqual(free, jammed)

    def test_explicit_building_category_is_preserved(self):
        kind, color = _visual_building_style({
            "kind": "civic",
            "height": 18,
            "coords": [[144.96, -37.81]],
            "name": "State Library Victoria",
        })

        self.assertEqual(kind, "civic")
        self.assertTrue(color.startswith("#"))

    def test_uncategorised_tower_gets_office_visual_style(self):
        building = {
            "kind": "generic",
            "height": 120,
            "coords": [[144.961, -37.812]],
            "name": "",
        }

        first = _visual_building_style(building)
        second = _visual_building_style(building)
        self.assertEqual(first, second)
        self.assertEqual(first[0], "office")


if __name__ == "__main__":
    unittest.main()
