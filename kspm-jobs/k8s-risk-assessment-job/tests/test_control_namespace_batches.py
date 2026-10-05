import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("batches", Path(__file__).parents[1] / "scripts/scan-control-namespaces.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BatchTests(unittest.TestCase):
    def definitions(self, folder):
        paths = []
        for name, ids in (("allcontrols", ["C-0001", "C-0002"]), ("nsa", ["C-0001"])):
            path = Path(folder) / f"{name}.json"
            path.write_text(json.dumps({"controls": [{"controlID": cid} for cid in ids]}))
            paths.append(path)
        return paths

    def test_one_control_one_namespace_then_merge_then_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.definitions(temp)
            output = Path(temp) / "report.json"
            calls = []
            temporary = []

            def scan(command, check):
                self.assertTrue(check)
                self.assertEqual(command[:3], ["kubescape", "scan", "control"])
                control = command[3]
                namespace = command[command.index("--include-namespaces") + 1]
                report = Path(command[command.index("--output") + 1])
                self.assertFalse(report.exists(), "previous temporary JSON was not deleted")
                if calls:
                    merged = json.loads(output.read_text())
                    self.assertEqual(sum(len(r["controls"]) for r in merged["results"]), len(calls))
                calls.append((namespace, control)); temporary.append(report)
                self.assertIn("--controls-config", command)
                report.write_text(json.dumps({"summaryDetails": {"frameworks": [],
                    "controls": {control: {"name": control}}}, "attributes": None,
                    "resources": [{"resourceID": namespace, "object": {}}],
                    "results": [{"resourceID": namespace, "controls": [{"controlID": control}]}]}))

            module.run_batches(["ns-b", "ns-a", "ns-a", "openshift-ovn-kubernetes"],
                               paths, output, "cluster", Path(temp), "/controls.json", scan)
            self.assertEqual(calls, [("ns-a", "C-0001"), ("ns-a", "C-0002"),
                                     ("ns-b", "C-0001"), ("ns-b", "C-0002")])
            self.assertTrue(all(not p.exists() for p in temporary))
            merged = json.loads(output.read_text())
            self.assertEqual(len(merged["results"]), 2)
            self.assertEqual(len(merged["summaryDetails"]["controls"]), 2)
            self.assertFalse(list(Path(temp).glob("control-ns-scans-*")))

    def test_failed_scan_removes_temporary_json_and_database(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.definitions(temp)
            output = Path(temp) / "report.json"
            calls = []

            def scan(command, check):
                calls.append(command[3])
                path = Path(command[command.index("--output") + 1])
                if len(calls) == 2:
                    path.write_text('{"truncated":')
                    raise subprocess.CalledProcessError(1, command)
                path.write_text(json.dumps({"summaryDetails": {"frameworks": []},
                                           "results": [{"resourceID": "r", "controls": [{"controlID": command[3]}]}]}))

            with self.assertRaises(subprocess.CalledProcessError):
                module.run_batches(["ns-a"], paths, output, "cluster", Path(temp), run=scan)
            self.assertEqual(calls, ["C-0001", "C-0002"])
            self.assertEqual(json.loads(output.read_text())["results"][0]["controls"][0]["controlID"], "C-0001")
            self.assertFalse(list(Path(temp).glob("control-ns-scans-*")))

    def test_cache_is_bounded_and_mmap_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            db = module.open_database(Path(temp) / "test.sqlite")
            try:
                self.assertEqual(db.execute("PRAGMA cache_size").fetchone()[0], -1024)
                self.assertEqual(db.execute("PRAGMA mmap_size").fetchone()[0], 0)
                self.assertEqual(db.execute("PRAGMA temp_store").fetchone()[0], 1)
            finally:
                db.close()

    def test_empty_namespace_and_invalid_framework_fail_before_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.definitions(temp)
            output = Path(temp) / "report.json"
            def unexpected(*args, **kwargs):
                self.fail("unexpected scan")
            with self.assertRaisesRegex(ValueError, "No namespaces"):
                module.run_batches([], paths, output, "cluster", Path(temp), run=unexpected)
            paths[0].write_text('{"controls":[]}')
            with self.assertRaisesRegex(ValueError, "No control IDs"):
                module.run_batches(["ns-a"], paths, output, "cluster", Path(temp), run=unexpected)


if __name__ == "__main__":
    unittest.main()
