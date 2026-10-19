import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET

from wrapper.coverage_audit import audit_coverage


NETWORK = """<network><nodes>
  <node id="a" x="0" y="0"/><node id="b" x="1000" y="0"/>
  <node id="c" x="0" y="1000"/>
</nodes><links>
  <link id="road" from="a" to="b" modes="car,bike,walk"/>
  <link id="footpath" from="a" to="c" modes="walk"/>
</links></network>"""


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def audit(self, persons, network=NETWORK, compressed=False):
        suffix = ".xml.gz" if compressed else ".xml"
        network_path = self.root / ("network" + suffix)
        plans_path = self.root / ("plans" + suffix)
        for path, content in ((network_path, network), (plans_path, persons)):
            if compressed:
                with gzip.open(path, "wt") as stream:
                    stream.write(content)
            else:
                path.write_text(content)
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (network_path, plans_path)]
        result = audit_coverage(network_path, plans_path)
        self.assertEqual(hashes, [hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (network_path, plans_path)])
        json.dumps(result, allow_nan=False)
        return result

    def person(self, content, selected='selected="yes"'):
        return f'<population><person id="PRIVATE-PERSON"><plan {selected}>{content}</plan></person></population>'

    def test_segment_distance_selected_plan_inclusive_bbox_and_mode_groups(self):
        report = self.audit('''<population><person id="PRIVATE-PERSON">
          <plan selected="no"><activity type="unused" x="999999" y="999999"/></plan>
          <plan selected="yes">
            <activity type="Home" x="500" y="0"/><leg mode="car"/>
            <activity type="Work" x="500" y="1000"/><leg mode="walk"/>
            <activity type="Shop" x="500" y="1001"/>
          </plan></person></population>''')
        acts = report["activities"]
        self.assertEqual(acts["total"], 3)
        self.assertEqual(acts["inside_node_bbox"], 2)
        self.assertEqual(acts["outside_node_bbox"], 1)
        self.assertEqual(acts["inside_node_bbox_fraction_of_finite"], 2 / 3)
        # 0 at the middle of a car link proves this is not distance to nodes.
        self.assertEqual(acts["nearest_car_distance"]["min"], 0)
        self.assertEqual(acts["nearest_car_distance"]["p50"], 1000)
        self.assertAlmostEqual(acts["nearest_car_distance"]["max"], 1001)
        self.assertEqual(acts["nearest_car_distance"]["count_greater_than"]["1000"], 1)
        self.assertEqual(report["car_endpoint_activities"]["total"], 2)
        self.assertEqual(report["by_arriving_leg_mode"]["car"]["total"], 1)
        self.assertEqual(report["by_arriving_leg_mode"]["__no_adjacent_leg__"]["total"], 1)
        self.assertEqual(report["by_departing_leg_mode"]["car"]["total"], 1)
        self.assertEqual(report["legs_by_mode"]["walk"]["inside_to_outside"], 1)
        self.assertEqual(report["plans"]["plans_not_audited"], 1)
        self.assertNotIn("unused", report["by_activity_type"])
        self.assertNotIn("PRIVATE-PERSON", json.dumps(report))
        self.assertLess(acts["nearest_car_distance"]["max"], 2000)

    def test_only_car_segments_and_explicit_mode_tokens_are_used(self):
        network = NETWORK.replace('modes="walk"', 'modes="cargo"')
        report = self.audit(self.person('<act type="Home" x="0" y="500"/>'), network)
        self.assertEqual(report["activities"]["nearest_car_distance"]["min"], 500)
        self.assertEqual(report["network"]["links"]["explicit_car_links"], 1)

    def test_coordinate_quality_denominator_and_no_imputation(self):
        report = self.audit(self.person('''
          <act type="Home" x="0" y="0"/>
          <activity type="Work" x="NaN" y="1"/>
          <act x="1" y="inf"/><act x="oops" y="2"/>
          <act x="2"/><act x="" y="oops"/><act link="road"/>
        '''))
        acts = report["activities"]
        self.assertEqual(acts["total"], 7)
        self.assertEqual(acts["finite_coordinates"], 1)
        self.assertEqual(acts["nonfinite_coordinates"], 2)
        self.assertEqual(acts["invalid_coordinates"], 1)
        self.assertEqual(acts["missing_coordinates"], 3)
        self.assertEqual(acts["inside_node_bbox_fraction_of_finite"], 1.0)
        self.assertEqual(acts["nearest_car_distance"]["count"], 1)
        self.assertEqual(report["plans"]["persons_with_unusable_coordinates"], 1)
        self.assertIn("unusable_activity_coordinates", {x["code"] for x in report["limitations"]})

    def test_plan_selection_diagnostics_exclude_ambiguity(self):
        activity = '<activity x="1" y="1" type="Home"/>'
        persons = '<population>' + ''.join([
            f'<person><plan>{activity}</plan></person>',
            f'<person><plan selected="true">{activity}</plan><plan selected="0"/></person>',
            f'<person><plan selected="1">{activity}</plan></person>',
            f'<person><plan selected="yes">{activity}</plan><plan selected="yes"/></person>',
            f'<person><plan>{activity}</plan><plan/></person>',
            f'<person><plan selected="no">{activity}</plan></person>',
            f'<person><plan selected="maybe">{activity}</plan></person>',
            '<person/>',
        ]) + '</population>'
        report = self.audit(persons)
        counts = report["plans"]
        self.assertEqual(counts["persons_total"], 8)
        self.assertEqual(counts["persons_audited"], 3)
        self.assertEqual(counts["persons_explicit_selected"], 2)
        self.assertEqual(counts["persons_unmarked_single_plan"], 1)
        self.assertEqual(counts["persons_multiple_selected"], 1)
        self.assertEqual(counts["persons_no_unique_selected_plan"], 2)
        self.assertEqual(counts["persons_invalid_selection_flags"], 1)
        self.assertEqual(counts["persons_without_plans"], 1)
        self.assertEqual(counts["persons_unaudited"], 5)
        self.assertEqual(report["activities"]["total"], 3)

    def test_namespaces_gzip_and_activity_alias(self):
        persons = self.person('<act type="Home" x="50" y="10"/>')
        plain = self.audit(persons)
        namespaced = self.audit(persons.replace('<population>', '<population xmlns="urn:matsim:test">'),
                                NETWORK.replace('<network>', '<network xmlns="urn:matsim:test">'),
                                compressed=True)
        self.assertEqual(plain, namespaced)

    def test_empty_population_and_empty_plan_return_null_fraction(self):
        for persons in ('<population/>', self.person('')):
            with self.subTest(persons=persons):
                report = self.audit(persons)
                self.assertIsNone(report["activities"]["inside_node_bbox_fraction_of_finite"])
                self.assertIsNone(report["activities"]["nearest_car_distance"]["mean"])
                self.assertEqual(report["activities"]["total"], 0)
        self.assertEqual(report["plans"]["persons_with_no_activities"], 1)

    def test_network_without_finite_nodes_is_unavailable_not_outside(self):
        network = '''<network><nodes><node id="a" x="nan" y="1"/>
          <node id="b" x="broken" y="2"/><node id="c" y="3"/></nodes>
          <links><link from="a" to="b" modes="car"/></links></network>'''
        report = self.audit(self.person('<activity x="0" y="0"/>'), network)
        self.assertIsNone(report["network"]["node_bbox"])
        self.assertIsNone(report["activities"]["inside_node_bbox_fraction_of_finite"])
        self.assertEqual(report["activities"]["outside_node_bbox"], 0)
        self.assertEqual(report["activities"]["bbox_unavailable_for_finite_coordinates"], 1)
        self.assertEqual(report["network"]["nodes"]["nonfinite_coordinates"], 1)
        self.assertEqual(report["network"]["nodes"]["invalid_coordinates"], 1)
        self.assertEqual(report["network"]["nodes"]["missing_coordinates"], 1)
        self.assertEqual(report["method"]["car_distance_status"], "no_usable_explicit_car_links")
        self.assertEqual(report["activities"]["nearest_car_distance"]["unavailable_for_finite_coordinates"], 1)

    def test_car_link_endpoint_failures_missing_modes_and_degenerate_segments(self):
        network = '''<network><nodes><node id="a" x="0" y="0"/>
          <node id="bad" x="nan" y="0"/><node x="4" y="4"/></nodes><links>
          <link from="a" to="absent" modes="car"/>
          <link from="a" to="bad" modes="car"/>
          <link from="a" to="a" modes=" car, walk "/>
          <link from="a" to="a"/></links></network>'''
        report = self.audit(self.person('<act x="3" y="4"/>'), network)
        counts = report["network"]["links"]
        self.assertEqual(counts["explicit_car_links"], 3)
        self.assertEqual(counts["car_links_with_unusable_endpoints"], 2)
        self.assertEqual(counts["usable_car_segments"], 1)
        self.assertEqual(counts["zero_length_car_segments"], 1)
        self.assertEqual(counts["missing_modes"], 1)
        self.assertEqual(report["network"]["nodes"]["missing_identifiers"], 1)
        self.assertEqual(report["activities"]["nearest_car_distance"]["min"], 5)

    def test_person_aggregates_home_repetition_and_car_endpoint_deduplication(self):
        persons = '''<population><person><plan selected="yes">
          <act type="home" x="-1" y="0"/><leg mode="car"/>
          <act type="Work" x="-1" y="0"/><leg mode="car"/>
          <act type="HOME" x="-1" y="0"/>
        </plan></person><person><plan selected="yes">
          <act type="Home" x="1" y="0"/><leg mode="walk"/>
          <act type="Work" x="-1" y="0"/>
        </plan></person></population>'''
        report = self.audit(persons)
        self.assertEqual(report["plans"]["persons_with_any_outside_bbox"], 2)
        self.assertEqual(report["plans"]["persons_with_home_outside_bbox"], 1)
        self.assertEqual(report["plans"]["persons_with_nonhome_outside_bbox"], 2)
        self.assertEqual(report["plans"]["persons_with_only_nonhome_outside_bbox"], 1)
        self.assertEqual(report["activities"]["outside_node_bbox"], 4)
        self.assertEqual(report["car_endpoint_activities"]["total"], 3)
        self.assertEqual(report["legs_by_mode"]["car"]["both_outside"], 2)

    def test_leg_endpoint_diagnostics_and_bbox_transitions(self):
        report = self.audit(self.person('''<leg mode="car"/>
          <act x="-1" y="0"/><leg mode="car"/><act x="1" y="0"/>
          <leg mode="car"/><act x="2" y="0"/>
          <leg mode="car"/><act x="inf" y="0"/>
          <leg/><act x="1" y="0"/>'''))
        self.assertEqual(report["legs_by_mode"]["car"]["missing_adjacent_activity"], 1)
        self.assertEqual(report["legs_by_mode"]["car"]["outside_to_inside"], 1)
        self.assertEqual(report["legs_by_mode"]["car"]["both_inside"], 1)
        self.assertEqual(report["legs_by_mode"]["car"]["unusable_endpoint_coordinates"], 1)
        self.assertEqual(report["legs_by_mode"]["__missing__"]["total"], 1)

    def test_missing_shapely_keeps_bbox_and_marks_distance_unavailable(self):
        with patch.dict("sys.modules", {"shapely": None}):
            report = self.audit(self.person('<activity x="1" y="1"/>'))
        self.assertEqual(report["method"]["car_distance_status"], "shapely_unavailable")
        self.assertEqual(report["activities"]["inside_node_bbox"], 1)
        self.assertIsNone(report["activities"]["nearest_car_distance"]["min"])

    def test_no_explicit_car_modes_and_empty_network_are_not_zero_distance(self):
        for network in (NETWORK.replace('car,bike,walk', 'bike,walk'), '<network/>'):
            with self.subTest(network=network):
                report = self.audit(self.person('<act x="1" y="1"/>'), network)
                self.assertEqual(report["method"]["car_distance_status"], "no_usable_explicit_car_links")
                self.assertEqual(report["activities"]["nearest_car_distance"]["count"], 0)
                self.assertIsNone(report["activities"]["nearest_car_distance"]["mean"])

    def test_nonfinite_geometry_result_is_unavailable_and_json_safe(self):
        # The Euclidean distance exceeds float range although x/y are finite.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            report = self.audit(self.person('<act x="1.7e308" y="1.7e308"/>'))
        self.assertEqual(report["activities"]["finite_coordinates"], 1)
        self.assertEqual(report["activities"]["nearest_car_distance"]["unavailable_for_finite_coordinates"], 1)
        self.assertIn("nonfinite_distance", {item["code"] for item in report["limitations"]})

    def test_unknown_crs_is_never_labelled_as_metres_or_valid_simulation(self):
        report = self.audit(self.person('<act x="144.96" y="-37.81"/>'))
        self.assertFalse(report["method"]["crs_verified"])
        self.assertEqual(report["method"]["coordinate_units"], "input_coordinate_units")
        self.assertIn("crs_unverified", {item["code"] for item in report["limitations"]})
        self.assertNotIn("passed", report)
        self.assertNotIn("valid", report)

    def test_wrong_roots_malformed_files_duplicate_nodes_and_missing_files(self):
        with self.assertRaisesRegex(ValueError, "population XML root"):
            self.audit('<network/>')
        with self.assertRaisesRegex(ValueError, "network XML root"):
            self.audit('<population/>', '<population/>')
        with self.assertRaises(ET.ParseError):
            self.audit('<population><person>')
        with self.assertRaisesRegex(ValueError, "duplicate node identifiers"):
            self.audit('<population/>', NETWORK.replace('id="c"', 'id="a"'))
        with self.assertRaises(FileNotFoundError):
            audit_coverage(self.root / 'absent.xml', self.root / 'plans.xml')


if __name__ == "__main__":
    unittest.main()
