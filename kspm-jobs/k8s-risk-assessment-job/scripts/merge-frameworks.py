#!/usr/bin/env python3
"""Merge Kubescape v2 reports using an on-disk SQLite index."""
import argparse
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


def merge(paths, output):
    output = Path(output)
    # Use the writable data volume, not tmpfs, for all intermediate storage.
    with tempfile.TemporaryDirectory(prefix="merge-", dir=output.parent) as temp:
        with sqlite3.connect(Path(temp) / "reports.sqlite") as db:
            db.execute("PRAGMA cache_size=-8192")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("CREATE TABLE records(kind TEXT, key TEXT, data TEXT, UNIQUE(kind,key))")
            db.execute("CREATE TABLE controls(resource_id TEXT, control_id TEXT, data TEXT, PRIMARY KEY(resource_id,control_id))")
            for path in paths:
                print(f"Merging framework report: {path}", flush=True)
                ingest(db, path)
            merged = Path(temp) / "report.json"
            with merged.open("w", encoding="utf-8") as out:
                write_report(db, out)
            # Publish only once every input has parsed and output is complete.
            os.replace(merged, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    merge(args.reports, args.output)
