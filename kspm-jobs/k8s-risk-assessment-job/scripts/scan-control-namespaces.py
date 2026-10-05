#!/usr/bin/env python3
"""Scan one control + namespace, merge to disk, delete temporary JSON, repeat."""
import gc
import re
import shutil
import ssl
import subprocess
import urllib.parse
import urllib.request
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import ijson


def encode(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def value_from(events, first):
    """Materialize one record, never the complete resource/result arrays."""
    builder = ijson.ObjectBuilder()
    _, event, value = first
    builder.event(event, value)
    depth = int(event in ("start_map", "start_array"))
    while depth:
        _, event, value = next(events)
        builder.event(event, value)
        depth += (event in ("start_map", "start_array")) - (event in ("end_map", "end_array"))
    return builder.value


def array_records(events, field):
    _, event, value = next(events)
    # Go's nil slices serialize as null rather than an empty array.
    if event == "null":
        return
    if event != "start_array":
        raise ValueError(f"Expected JSON array or null for {field}; got {event}: {value!r}")
    for first in events:
        if first[1] == "end_array":
            return
        yield value_from(events, first)
    raise ValueError("Truncated array")


def store(db, kind, key, value):
    db.execute("INSERT OR IGNORE INTO records(kind, key, data) VALUES (?, ?, ?)",
               (kind, key, encode(value)))


def ingest_summary(db, events):
    if next(events)[1] != "start_map":
        raise ValueError("Expected v2 summaryDetails object")
    for _, event, key in events:
        if event == "end_map":
            return
        if event != "map_key":
            raise ValueError("Invalid summaryDetails")
        if key == "frameworks":
            for framework in array_records(events, "summaryDetails.frameworks"):
                store(db, "framework", framework["name"], framework)
        elif key == "controls":
            _, event, _ = next(events)
            if event == "null":
                continue
            if event != "start_map":
                raise ValueError("Expected summary control map")
            for _, event, control_id in events:
                if event == "end_map":
                    break
                if event != "map_key":
                    raise ValueError("Invalid summary control map")
                store(db, "summary_control", control_id, value_from(events, next(events)))
        else:
            # Preserve allcontrols global scores/counters, without summing
            # overlapping framework counts or inventing a combined score.
            store(db, "summary", key, value_from(events, next(events)))


def ingest_result(db, result):
    resource_id = result["resourceID"]
    controls = result.pop("controls", None) or []
    store(db, "result", resource_id, result)
    for control in controls:
        control_id = control["controlID"]
        old = db.execute("SELECT data FROM controls WHERE resource_id=? AND control_id=?",
                         (resource_id, control_id)).fetchone()
        if old:
            previous = json.loads(old[0])
            # Preserve distinct rule evidence from every scan for this control.
            rules = {encode(rule): rule for rule in (previous.get("rules") or [])}
            rules.update((encode(rule), rule) for rule in (control.get("rules") or []))
            if rules:
                previous["rules"] = list(rules.values())
            # A later failed observation must not disappear behind a pass.
            if (control.get("status") or {}).get("status") == "failed":
                previous["status"] = control["status"]
            control = previous
        db.execute("INSERT OR REPLACE INTO controls VALUES (?, ?, ?)",
                   (resource_id, control_id, encode(control)))


def ingest(db, path):
    with open(path, "rb") as source:
        events = iter(ijson.parse(source, use_float=True))
        if next(events)[1] != "start_map":
            raise ValueError("Expected a Kubescape v2 JSON object")
        has_summary = False
        for _, event, key in events:
            if event == "end_map":
                break
            if event != "map_key":
                raise ValueError("Invalid report object")
            if key == "summaryDetails":
                has_summary = True
                ingest_summary(db, events)
            elif key in ("results", "resources", "attributes"):
                for record in array_records(events, key):
                    if key == "results":
                        ingest_result(db, record)
                    elif key == "resources":
                        store(db, "resource", record["resourceID"], record)
                    else:
                        store(db, "attribute", encode(record), record)
            else:
                store(db, "metadata", key, value_from(events, next(events)))
        if next(events, None) is not None:
            raise ValueError("Trailing data after report")
        if not has_summary:
            raise ValueError("Missing Kubescape v2 summaryDetails")
    db.commit()


def records(db, kind):
    return db.execute("SELECT key, data FROM records WHERE kind=? ORDER BY rowid", (kind,))


def write_array(out, values):
    out.write("[")
    separator = ""
    for value in values:
        out.write(separator + value)
        separator = ","
    out.write("]")


def write_report(db, out):
    out.write("{")
    for key, data in records(db, "metadata"):
        out.write(encode(key) + ":" + data + ",")
    out.write('"summaryDetails":{')
    for key, data in records(db, "summary"):
        out.write(encode(key) + ":" + data + ",")
    out.write('"controls":{')
    separator = ""
    for key, data in records(db, "summary_control"):
        out.write(separator + encode(key) + ":" + data)
        separator = ","
    out.write('},"frameworks":')
    write_array(out, (data for _, data in records(db, "framework")))
    out.write('},"resources":')
    write_array(out, (data for _, data in records(db, "resource")))
    out.write(',"attributes":')
    write_array(out, (data for _, data in records(db, "attribute")))
    out.write(',"results":[')
    separator = ""
    for resource_id, data in records(db, "result"):
        out.write(separator + data[:-1] + ',"controls":')
        write_array(out, (row[0] for row in db.execute(
            "SELECT data FROM controls WHERE resource_id=? ORDER BY control_id", (resource_id,))))
        out.write("}")
        separator = ","
    out.write("]}\n")


def open_database(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA cache_size=-1024")
    db.execute("PRAGMA mmap_size=0")
    db.execute("PRAGMA temp_store=FILE")
    db.execute("CREATE TABLE IF NOT EXISTS records(kind TEXT, key TEXT, data TEXT, UNIQUE(kind,key))")
    db.execute("CREATE TABLE IF NOT EXISTS controls(resource_id TEXT, control_id TEXT, data TEXT, PRIMARY KEY(resource_id,control_id))")
    db.execute("CREATE TABLE IF NOT EXISTS namespaces(name TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE IF NOT EXISTS scan_controls(id TEXT PRIMARY KEY)")
    return db


def publish_report(db, output):
    output = Path(output)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="report-",
                                         suffix=".tmp", dir=output.parent, delete=False) as out:
            temporary = Path(out.name)
            write_report(db, out)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def merge(paths, output):
    # Retained as a callable helper for merger regression tests.
    output = Path(output)
    with tempfile.TemporaryDirectory(prefix="merge-", dir=output.parent) as temp:
        db = open_database(Path(temp) / "reports.sqlite")
        try:
            for path in paths:
                ingest(db, path)
            publish_report(db, output)
        finally:
            db.close()


FRAMEWORKS = ("allcontrols", "mitre", "nsa")
EXCLUDED_NAMESPACES = {"openshift-ovn-kubernetes"}


def discover_namespaces():
    credentials = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    context = ssl.create_default_context(cafile=str(credentials / "ca.crt"))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=context))
    continuation = ""
    while True:
        query = urllib.parse.urlencode({"limit": 100, "continue": continuation})
        request = urllib.request.Request(f"https://{host}:{port}/api/v1/namespaces?{query}",
            headers={"Authorization": "Bearer " + (credentials / "token").read_text().strip()})
        continuation = ""
        with opener.open(request, timeout=60) as response:
            for prefix, event, value in ijson.parse(response):
                if prefix == "items.item.metadata.name" and event == "string":
                    yield value
                elif prefix == "metadata.continue" and event == "string":
                    continuation = value
        if not continuation:
            return


def add_namespaces(db, names):
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
            raise ValueError(f"Invalid namespace name: {name!r}")
        if name not in EXCLUDED_NAMESPACES:
            db.execute("INSERT OR IGNORE INTO namespaces VALUES (?)", (name,))
    if db.execute("SELECT count(*) FROM namespaces").fetchone()[0] == 0:
        raise ValueError("No namespaces available to scan")
    db.commit()


def add_controls(db, framework_paths):
    for path in framework_paths:
        count = 0
        with open(path, "rb") as source:
            # Read IDs only; never retain policy definitions in memory.
            for prefix, event, control_id in ijson.parse(source):
                if prefix == "controls.item.controlID" and event == "string":
                    if not re.fullmatch(r"C-[0-9]+", control_id):
                        raise ValueError(f"Invalid control ID in {path}: {control_id!r}")
                    db.execute("INSERT OR IGNORE INTO scan_controls VALUES (?)", (control_id,))
                    count += 1
        if count == 0:
            raise ValueError(f"No control IDs found in framework definition: {path}")
    db.commit()


def iter_plan(database_path, table, column):
    # Keyset iteration releases each read cursor before the merge writer opens.
    # table/column are internal constants, never user-supplied identifiers.
    previous = ""
    while True:
        db = open_database(database_path)
        try:
            row = db.execute(f"SELECT {column} FROM {table} WHERE {column}>? ORDER BY {column} LIMIT 1",
                             (previous,)).fetchone()
        finally:
            db.close()
        if row is None:
            return
        previous = row[0]
        yield previous


def run_batches(namespaces, framework_paths, output, cluster_name, artifacts,
                controls_config=None, run=subprocess.run):
    output = Path(output)
    with tempfile.TemporaryDirectory(prefix="control-ns-scans-", dir=output.parent) as temp:
        database_path = Path(temp) / "merge.sqlite"
        db = open_database(database_path)
        try:
            add_namespaces(db, namespaces)
            add_controls(db, framework_paths)
            total = db.execute("SELECT (SELECT count(*) FROM namespaces) * (SELECT count(*) FROM scan_controls)").fetchone()[0]
        finally:
            db.close()
        completed = 0
        # Plan cursors read from disk; close the merge connection between batches
        # to release its page cache before starting the next Kubescape process.
        for namespace in iter_plan(database_path, "namespaces", "name"):
            for control_id in iter_plan(database_path, "scan_controls", "id"):
                report = Path(temp) / "scan.json"
                command = ["kubescape", "scan", "control", control_id,
                           "--include-namespaces", namespace, "--enable-streaming",
                           "--exclude-namespaces", "openshift-ovn-kubernetes",
                           "--format", "json", "--format-version", "v2",
                           "--cache-dir", str(artifacts), "--use-artifacts-from", str(artifacts),
                           "--output", str(report), "--cluster-name", cluster_name]
                if controls_config:
                    command += ["--controls-config", str(controls_config)]
                print(f"[{completed + 1}/{total}] Scanning control {control_id} in namespace {namespace}", flush=True)
                try:
                    run(command, check=True)
                    db = open_database(database_path)
                    try:
                        ingest(db, report)
                        publish_report(db, output)
                    finally:
                        db.close()
                finally:
                    report.unlink(missing_ok=True)
                    gc.collect()
                completed += 1
                print(f"[{completed}/{total}] Merged into {output}; temporary JSON removed", flush=True)
    print(f"Completed {completed} control/namespace scans; merge database removed", flush=True)


def main():
    output = Path("/data/report.json")
    cache = Path("/data/kubescape-cache")
    cache.mkdir(parents=True, exist_ok=True)
    # Policy artifacts are disk files, distinct from SQLite's bounded page cache.
    shutil.copytree("/opt/kubescape/artifacts", cache, dirs_exist_ok=True)
    if os.environ.get("AIRGAPPED", "false").lower() != "true":
        subprocess.run(["kubescape", "download", "artifacts", "--output", str(cache)], check=True)
    url = os.environ.get("CONTROLS_CONFIG_URL", "")
    config_path = None
    if url:
        config_path = cache / "controls-config.json"
        with urllib.request.urlopen(url, timeout=60) as response, config_path.open("wb") as out:
            shutil.copyfileobj(response, out, length=64 * 1024)
    try:
        namespaces = json.loads(os.environ.get("SCAN_NAMESPACES", "[]"))
        if not isinstance(namespaces, list):
            raise ValueError("SCAN_NAMESPACES must be a JSON array")
        run_batches(namespaces or discover_namespaces(),
                    (cache / f"{name}.json" for name in FRAMEWORKS),
                    output, os.environ.get("CLUSTER_NAME", ""), cache, config_path)
    finally:
        if config_path is not None:
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
