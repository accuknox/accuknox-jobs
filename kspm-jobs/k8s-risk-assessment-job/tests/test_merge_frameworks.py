import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("merge", Path(__file__).parents[1] / "scripts/merge-frameworks.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MergeTests(unittest.TestCase):
    def test_nullable_collections(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report-input.json"
            output = Path(temp) / "report.json"
            report = {"summaryDetails": {"frameworks": None, "controls": None},
                      "resources": None, "attributes": None, "results": None}
            path.write_text(json.dumps(report))
            module.merge([path], output)
            merged = json.loads(output.read_text())
            for field in ("resources", "attributes", "results"):
                self.assertEqual(merged[field], [])
            self.assertEqual(merged["summaryDetails"]["frameworks"], [])
            report["results"] = [{"resourceID": "shared", "controls": None}]
            path.write_text(json.dumps(report))
            module.merge([path], output)
            self.assertEqual(json.loads(output.read_text())["results"][0]["controls"], [])

    def test_invalid_collection_names_field(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report-input.json"
            path.write_text(json.dumps({"summaryDetails": {"frameworks": []},
                                        "attributes": {"unexpected": "object"}}))
            with self.assertRaisesRegex(ValueError, "attributes.*start_map"):
                module.merge([path], Path(temp) / "report.json")

    def test_merge_preserves_controls_resources_and_frameworks(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for i, name in enumerate(("allcontrols", "clusterscan", "mitre", "nsa")):
                report = {"clusterName": "test", "summaryDetails": {
                    "score": i, "frameworks": [{"name": name, "score": i}],
                    "controls": {f"C-{i}": {"name": name}}},
                    "resources": [{"resourceID": "shared", "object": {"first": i}},
                                  {"resourceID": name, "object": {}}],
                    "results": [{"resourceID": "shared", "controls": [
                        {"controlID": "overlap", "status": {"status": "failed" if i == 1 else "passed"},
                         "rules": [{"name": name}]}, {"controlID": f"C-{i}"}]}],
                    "attributes": [{"name": "shared"}]}
                path = Path(temp) / f"{name}.json"
                path.write_text(json.dumps(report)); paths.append(path)
            output = Path(temp) / "report.json"
            module.merge(paths, output)
            merged = json.loads(output.read_text())
            self.assertEqual(len(merged["results"]), 1)
            controls = merged["results"][0]["controls"]
            self.assertEqual(len(controls), 5)
            overlap = next(c for c in controls if c["controlID"] == "overlap")
            self.assertEqual(len(overlap["rules"]), 4)
            self.assertEqual(overlap["status"]["status"], "failed")
            self.assertEqual(len(merged["resources"]), 5)
            self.assertEqual(merged["resources"][0]["object"]["first"], 0)
            self.assertEqual(len(merged["summaryDetails"]["frameworks"]), 4)
            self.assertEqual(len(merged["summaryDetails"]["controls"]), 4)
            self.assertEqual(merged["summaryDetails"]["score"], 0)
            self.assertEqual(len(merged["attributes"]), 1)
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()),
                             sorted([p.name for p in paths] + ["report.json"]))

    def test_invalid_input_does_not_replace_report(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            output.write_text("existing report")
            invalid = Path(temp) / "invalid.json"
            for data in ('{}', '{"summaryDetails":', '{"summaryDetails":{}} {}'):
                invalid.write_text(data)
                with self.assertRaises(Exception):
                    module.merge([invalid], output)
                self.assertEqual(output.read_text(), "existing report")
                self.assertFalse(list(Path(temp).glob("merge-*")))

    def test_601_controls_survive_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "allcontrols.json"
            path.write_text(json.dumps({"summaryDetails": {"frameworks": []}, "results": [
                {"resourceID": "shared", "controls": [{"controlID": f"C-{i}"} for i in range(601)]}]}))
            output = Path(temp) / "report.json"
            module.merge([path], output)
            self.assertEqual(len(json.loads(output.read_text())["results"][0]["controls"]), 601)


if __name__ == "__main__":
    unittest.main()
