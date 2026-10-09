#!/usr/bin/env python3
"""Snapshot, scan, upload and clean up one namespace at a time."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import ijson

FRAMEWORKS = ("allcontrols", "clusterscan", "nsa", "mitre")
BLOCK_SIZE = 64 * 1024
MAX_RESPONSE = 1024 * 1024


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def copy_value(events, first, out):
    """Copy JSON tokens without materializing resource/result objects or arrays."""
    _, event, value = first
    if event in ("start_map", "start_array"):
        mapping = event == "start_map"
        out.write("{" if mapping else "[")
        end = "end_map" if mapping else "end_array"
        separator = ""
        while True:
            token = next(events)
            if token[1] == end:
                break
            out.write(separator)
            separator = ","
            if mapping:
                if token[1] != "map_key":
                    raise ValueError("Invalid JSON object")
                out.write(encode(token[2]) + ":")
                token = next(events)
            copy_value(events, token, out)
        out.write("}" if mapping else "]")
    elif event == "number":
        out.write(str(value))
    elif event in ("string", "boolean", "null"):
        out.write(encode(value))
    else:
        raise ValueError(f"Unexpected JSON event: {event}")


class Discard:
    def write(self, value):
        pass


def load_controls(db, paths):
    db.execute("PRAGMA cache_size=-1024")
    db.execute("PRAGMA mmap_size=0")
    db.execute("PRAGMA temp_store=FILE")
    db.execute("CREATE TABLE controls(id TEXT PRIMARY KEY, data TEXT)")
    for path in paths:
        with Path(path).open("rb") as source:
            count = 0
            for control in ijson.items(source, "controls.item", use_float=True):
                control_id = control.get("controlID")
                if not isinstance(control_id, str) or not control_id:
                    raise ValueError(f"Invalid control definition in {path}")
                # Match knoxjobs: later framework definitions override duplicates.
                db.execute("INSERT OR REPLACE INTO controls VALUES (?, ?)",
                           (control_id, encode(control)))
                count += 1
            if not count:
                raise ValueError(f"No controls found in {path}")
    db.commit()


def augment_report(report, framework_paths, metadata, directory):
    replacement = Path(directory) / "augmented.json"
    with closing(sqlite3.connect(Path(directory) / "controls.sqlite")) as db:
        load_controls(db, framework_paths)
        with Path(report).open("rb") as source, replacement.open("w", encoding="utf-8") as out:
            events = iter(ijson.parse(source))
            if next(events)[1] != "start_map":
                raise ValueError("Report must be a JSON object")
            out.write("{")
            separator = ""
            for token in events:
                if token[1] == "end_map":
                    break
                if token[1] != "map_key":
                    raise ValueError("Invalid report object")
                key = token[2]
                first = next(events)
                if key in ("summary", "generationTime", "accuknox_metadata"):
                    copy_value(events, first, Discard())
                    continue
                out.write(separator + encode(key) + ":")
                copy_value(events, first, out)
                separator = ","
            if next(events, None) is not None:
                raise ValueError("Trailing data after report")
            out.write(separator + '"generationTime":' + encode(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")))
            out.write(',"accuknox_metadata":' + encode(metadata))
            out.write(',"summary":{"controls":[')
            separator = ""
            for (data,) in db.execute("SELECT data FROM controls ORDER BY id"):
                out.write(separator + data)
                separator = ","
            out.write("]}}\n")
    os.replace(replacement, report)


def prepare_body(report, directory):
    archive = Path(directory) / "report.json.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("report.json")
        info.mode = 0o600
        info.size = Path(report).stat().st_size
        with Path(report).open("rb") as source:
            tar.addfile(info, source)
    boundary = "knoxjobs-" + uuid.uuid4().hex
    body = Path(directory) / "multipart.body"
    with body.open("wb") as out, archive.open("rb") as source:
        out.write((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                   'filename="report.json.tar.gz"\r\nContent-Type: application/octet-stream\r\n\r\n').encode())
        shutil.copyfileobj(source, out, length=BLOCK_SIZE)
        out.write(f"\r\n--{boundary}--\r\n".encode())
    archive.unlink()
    return body, f"multipart/form-data; boundary={boundary}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def upload(body, content_type, url, token, tenant_id, context, attempts=3, sleep=time.sleep):
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    for attempt in range(1, attempts + 1):
        try:
            # New request and file handle on every retry, always starting at byte 0.
            with Path(body).open("rb") as source:
                request = urllib.request.Request(url, data=source, method="POST", headers={
                    "Authorization": "Bearer " + token,
                    "Tenant-Id": str(tenant_id),
                    "Content-Type": content_type,
                    "Content-Length": str(Path(body).stat().st_size),
                })
                with opener.open(request, timeout=120) as response:
                    message = response.read(MAX_RESPONSE + 1)
                    if len(message) > MAX_RESPONSE:
                        raise RuntimeError("Artifact response exceeds 1 MiB")
                    if response.status != 200:
                        raise RuntimeError(f"Artifact API returned HTTP {response.status}")
                    print("Report published: " + message.decode("utf-8", errors="replace"), flush=True)
                    return
        except urllib.error.HTTPError as error:
            # Bound error bodies as well and never log credentials.
            with error:
                error.read(MAX_RESPONSE)
            failure = RuntimeError(f"Artifact API returned HTTP {error.code}")
        except (urllib.error.URLError, OSError, RuntimeError) as error:
            failure = error
        if attempt == attempts:
            raise RuntimeError(f"Artifact upload failed after {attempts} attempts: {failure}") from failure
        print(f"Artifact upload attempt {attempt} failed; retrying", flush=True)
        sleep(2 ** (attempt - 1))


def tenant_settings(url, token, configured):
    tenant = configured
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claim = claims.get("tenant-id")
        if isinstance(claim, int) and not isinstance(claim, bool) and claim > 0:
            tenant = str(claim)
    except (IndexError, ValueError, UnicodeError):
        pass
    if not str(tenant).isdigit() or int(tenant) <= 0:
        raise ValueError("Set a positive tenant ID, or use an AUTH_TOKEN containing tenant-id")
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(key, str(tenant) if key == "tenant_id" and not value else value) for key, value in query]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))), str(tenant)


def tls_context(directory):
    if os.environ.get("SKIP_TLS_VERIFICATION", "false").lower() == "true":
        return ssl._create_unverified_context()
    context = ssl.create_default_context()
    ca_path = os.environ.get("CA_PATH", "")
    ca_url = os.environ.get("CA_URL", "")
    if ca_path:
        context.load_verify_locations(cafile=ca_path)
    elif ca_url:
        ca_path = Path(directory) / "ca.crt"
        with urllib.request.urlopen(ca_url, timeout=60) as response, ca_path.open("wb") as out:
            shutil.copyfileobj(response, out, length=BLOCK_SIZE)
        context.load_verify_locations(cafile=str(ca_path))
    return context


class KubernetesAPI:
    """Read the in-cluster API; rotate service-account tokens between requests."""
    def __init__(self):
        self.credentials = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        if ":" in host:
            host = "[" + host + "]"
        self.url = "https://" + host + ":" + os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=str(self.credentials / "ca.crt"))))

    def open(self, path):
        request = urllib.request.Request(self.url + path, headers={
            "Authorization": "Bearer " + (self.credentials / "token").read_text().strip(),
            "Accept": "application/json"})
        return self.opener.open(request, timeout=120)

    def discovery(self, path):
        with self.open(path) as response:
            return json.load(response)

    def resources(self):
        # One served version per group avoids duplicate copies of the same object.
        versions = ["/api/v1"]
        versions.extend("/apis/" + group["preferredVersion"]["groupVersion"]
                        for group in self.discovery("/apis")["groups"])
        for version in versions:
            for resource in self.discovery(version)["resources"]:
                if resource.get("namespaced") and "list" in resource.get("verbs", []) and "/" not in resource["name"]:
                    yield version, resource["name"], resource["kind"]

    def list_into(self, path, out, api_version, kind):
        """Stream paginated items as JSON documents (valid multi-document YAML)."""
        continuation = ""
        count = 0
        while True:
            query = urllib.parse.urlencode({"limit": 100, "continue": continuation})
            with self.open(path + "?" + query) as response:
                events = iter(ijson.parse(response))
                continuation = ""
                for token in events:
                    if token[:2] == ("items.item", "start_map"):
                        out.write("---\n")
                        # API List items can omit TypeMeta. Local file scans require it.
                        out.write('{"apiVersion":' + encode(api_version) + ',"kind":' + encode(kind))
                        for field in events:
                            if field[1] == "end_map":
                                break
                            if field[1] != "map_key":
                                raise ValueError("Invalid Kubernetes resource object")
                            value = next(events)
                            if field[2] in ("apiVersion", "kind"):
                                copy_value(events, value, Discard())
                            else:
                                out.write("," + encode(field[2]) + ":")
                                copy_value(events, value, out)
                        out.write("}\n")
                        count += 1
                    elif token[:2] == ("metadata.continue", "string"):
                        continuation = token[2]
            if not continuation:
                return count

    def namespaces(self, directory):
        # Namespace enumeration is also disk backed, including on very large clusters.
        path = Path(directory) / "namespaces.yaml"
        with path.open("w", encoding="utf-8") as out:
            self.list_into("/api/v1/namespaces", out, "v1", "Namespace")
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.startswith("{"):
                    yield json.loads(line)["metadata"]["name"]

    def snapshot(self, namespace, resources, manifest):
        count = 0
        with Path(manifest).open("w", encoding="utf-8") as out:
            for version, resource, kind in resources:
                path = version + "/namespaces/" + urllib.parse.quote(namespace, safe="") + "/" + resource
                try:
                    count += self.list_into(path, out, version.removeprefix("/apis/").removeprefix("/api/"), kind)
                except urllib.error.HTTPError as error:
                    # Never publish a snapshot silently missing denied/unavailable resources.
                    status = error.code
                    error.close()
                    raise RuntimeError(f"Cannot collect {resource} in {namespace}: HTTP {status}") from None
        return count


def main(data_dir="/data", artifact_dir="/opt/kubescape/artifacts"):
    url = os.environ.get("ARTIFACT_URL", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("Set global.artifactURL or configure the artifact API host")
    token = Path(os.environ.get("AUTH_TOKEN_PATH", "/secrets/tokens/AUTH_TOKEN")).read_text().strip()
    if not token:
        raise ValueError("AUTH_TOKEN is empty; direct HTTP upload requires a bearer token")
    url, tenant = tenant_settings(url, token, os.environ.get("TENANT_ID", ""))
    label = os.environ.get("LABEL_NAME", "")
    if not label:
        raise ValueError("LABEL_NAME is required")
    metadata = {"cluster_name": os.environ.get("CLUSTER_NAME", ""),
                "cluster_id": int(os.environ.get("CLUSTER_ID", "0")), "label_name": label}
    cache = Path(data_dir) / "kubescape-cache"
    cache.mkdir(parents=True, exist_ok=True)
    failed = completed = 0
    with tempfile.TemporaryDirectory(prefix="scan-upload-", dir=data_dir) as directory:
        context = tls_context(directory)
        if os.environ.get("AIRGAPPED", "false").lower() == "true":
            shutil.copytree(artifact_dir, cache, dirs_exist_ok=True)
        else:
            subprocess.run(["kubescape", "download", "artifacts", "--output", str(cache)], check=True)
            subprocess.run(["kubescape", "download", "framework", "clusterscan", "--output",
                            str(cache / "clusterscan.json")], check=True)
        extra = []
        config_url = os.environ.get("CONTROLS_CONFIG_URL", "")
        if config_url:
            controls_config = Path(directory) / "controls.json"
            with urllib.request.urlopen(config_url, timeout=60, context=context) as response, controls_config.open("wb") as out:
                shutil.copyfileobj(response, out, length=BLOCK_SIZE)
            extra = ["--controls-config", str(controls_config)]
        api = KubernetesAPI()
        resources = tuple(api.resources())
        for namespace in api.namespaces(directory):
            try:
                with tempfile.TemporaryDirectory(prefix="namespace-", dir=directory) as scratch:
                    manifest = Path(scratch) / (namespace + ".manifest.yaml")
                    report = Path(scratch) / "report.json"
                    print(f"Downloading resources for namespace {namespace}", flush=True)
                    count = api.snapshot(namespace, resources, manifest)
                    print(f"Scanning namespace {namespace}: {count} resources", flush=True)
                    command = ["kubescape", "scan", "framework", ",".join(FRAMEWORKS), str(manifest),
                               "--format", "json", "--format-version", "v2", "--cache-dir", str(cache),
                               "--use-artifacts-from", str(cache), "--output", str(report),
                               "--cluster-name", metadata["cluster_name"]] + extra
                    subprocess.run(command, check=True)
                    augment_report(report, (cache / (name + ".json") for name in FRAMEWORKS),
                                   dict(metadata, namespace=namespace), scratch)
                    body, content_type = prepare_body(report, scratch)
                    print(f"Uploading report for namespace {namespace}", flush=True)
                    upload(body, content_type, url, token, tenant, context)
                    completed += 1
                print(f"Deleted manifest, report and temporary files for {namespace}", flush=True)
            except Exception as error:
                failed += 1
                print(f"Namespace {namespace} failed ({type(error).__name__}: {error}); temporary files deleted; continuing", flush=True)
        print(f"Namespace processing finished: {completed} uploaded, {failed} failed", flush=True)
    if failed:
        raise RuntimeError(f"{failed} namespace(s) failed; all remaining namespaces were attempted")


if __name__ == "__main__":
    main()
