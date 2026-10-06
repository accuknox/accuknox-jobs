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
            self.assertFalse((Path(temp) / ".control-ns-scans").exists())

    def test_failed_scan_continues_and_records_failure(self):
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

            module.run_batches(["ns-a", "ns-b"], paths, output, "cluster", Path(temp), run=scan)
            self.assertEqual(calls, ["C-0001", "C-0002", "C-0001", "C-0002"])
            failures = [json.loads(line) for line in (Path(temp) / "scan-failures.jsonl").read_text().splitlines()]
            self.assertEqual(failures[0]["namespace"], "ns-a")
            self.assertEqual(failures[0]["controlID"], "C-0002")
            self.assertEqual(json.loads(output.read_text())["scanBatchStatus"], {"attempted": 4, "succeeded": 3, "failed": 1})
            self.assertEqual(json.loads(output.read_text())["results"][0]["controls"][0]["controlID"], "C-0001")
            self.assertFalse((Path(temp) / ".control-ns-scans").exists())

    def test_restart_resumes_successful_batches(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.definitions(temp)
            output = Path(temp) / "report.json"
            attempted = []
            def interrupted(command, check):
                attempted.append(command[3])
                if len(attempted) == 2:
                    raise KeyboardInterrupt()
                Path(command[command.index("--output") + 1]).write_text(json.dumps(
                    {"summaryDetails": {"frameworks": []}, "results": [
                        {"resourceID": "r", "controls": [{"controlID": command[3]}]}]}))
            with self.assertRaises(KeyboardInterrupt):
                module.run_batches(["ns-a"], paths, output, "cluster", Path(temp), run=interrupted)
            self.assertTrue((Path(temp) / ".control-ns-scans" / "merge.sqlite").exists())
            self.assertFalse((Path(temp) / ".control-ns-scans" / "scan.json").exists())
            resumed = []
            def scan(command, check):
                resumed.append(command[3])
                Path(command[command.index("--output") + 1]).write_text(json.dumps(
                    {"summaryDetails": {"frameworks": []}, "results": [
                        {"resourceID": "r", "controls": [{"controlID": command[3]}]}]}))
            module.run_batches(["ns-a"], paths, output, "cluster", Path(temp), run=scan)
            self.assertEqual(resumed, ["C-0002"])
            self.assertEqual(len(json.loads(output.read_text())["results"][0]["controls"]), 2)
            self.assertFalse((Path(temp) / ".control-ns-scans").exists())

    def test_all_failed_batches_do_not_upload_empty_report(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.definitions(temp)
            output = Path(temp) / "report.json"
            calls = []
            def scan(command, check):
                calls.append(command[3])
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaisesRegex(RuntimeError, "All 2 batches failed"):
                module.run_batches(["ns-a"], paths, output, "cluster", Path(temp), run=scan)
            self.assertEqual(len(calls), 2)
            self.assertFalse(output.exists())
            self.assertEqual(len((Path(temp) / "scan-failures.jsonl").read_text().splitlines()), 2)

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
