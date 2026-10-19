import tempfile
import unittest
from pathlib import Path

from scripts.report_demo_comparison import _config, export_report, verify_capacity_change


class DemoReportTests(unittest.TestCase):
    def network(self, path, capacity=100, speed=10, node_x=0):
        path.write_text(f'''<network><nodes><node id="a" x="{node_x}" y="0"/>
        <node id="b" x="100" y="0"/></nodes><links>
        <link id="one" from="a" to="b" capacity="{capacity}" freespeed="{speed}" modes="car"/>
        <link id="two" from="b" to="a" capacity="{capacity}" freespeed="10" modes="car"/>
        </links></network>''')

    def test_capacity_only_comparison_is_verified_without_mutating_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            base, alt = (Path(directory) / name for name in ("base.xml", "alt.xml"))
            self.network(base)
            self.network(alt, capacity=50)
            original = alt.read_bytes()
            result = verify_capacity_change(base, alt, {
                "type": "capacity_scale", "value": 50, "link_id": "one", "include_reverse": True})
            self.assertEqual(result["directed_links"], 2)
            self.assertEqual({row["link_id"] for row in result["changes"]}, {"one", "two"})
            self.assertEqual(alt.read_bytes(), original)

    def test_hidden_speed_topology_or_wrong_scale_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base, alt = (Path(directory) / name for name in ("base.xml", "alt.xml"))
            self.network(base)
            for values in ({"capacity": 50, "speed": 9}, {"capacity": 50, "node_x": 5}, {"capacity": 60}):
                with self.subTest(values=values):
                    self.network(alt, **values)
                    with self.assertRaises(ValueError):
                        verify_capacity_change(base, alt, {
                            "type": "capacity_scale", "value": 50, "link_id": "one", "include_reverse": True})

    def test_config_allows_only_network_and_output_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base, alt = (Path(directory) / name for name in ("base.xml", "alt.xml"))
            template = '''<config><module name="network"><param name="inputNetworkFile" value="{network}"/></module>
            <module name="controler"><param name="outputDirectory" value="{output}"/></module>
            <module name="global"><param name="randomSeed" value="{seed}"/></module></config>'''
            base.write_text(template.format(network="a", output="a", seed=4711))
            alt.write_text(template.format(network="b", output="b", seed=4711))
            self.assertEqual(_config(base), _config(alt))
            alt.write_text(template.format(network="b", output="b", seed=1234))
            self.assertNotEqual(_config(base), _config(alt))

    def test_export_never_overwrites_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.txt"
            marker.write_text("original")
            with self.assertRaises(FileExistsError):
                export_report({}, Path(directory))
            self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
