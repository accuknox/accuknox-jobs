#!/usr/bin/env python3
"""Collect selected resources with cluster context and write reports for knoxjobs."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import ijson

FRAMEWORKS = ("allcontrols", "clusterscan", "nsa", "mitre")
BLOCK_SIZE = 64 * 1024
NAMESPACED = {
    ("", "pods"), ("apps", "deployments"), ("apps", "statefulsets"),
    ("apps", "daemonsets"), ("batch", "jobs"), ("batch", "cronjobs"),
    ("", "services"), ("networking.k8s.io", "ingresses"),
    ("networking.k8s.io", "networkpolicies"), ("", "serviceaccounts"),
    ("rbac.authorization.k8s.io", "roles"),
    ("rbac.authorization.k8s.io", "rolebindings"), ("", "configmaps"),
}
CLUSTER = {
    ("rbac.authorization.k8s.io", "clusterroles"),
    ("rbac.authorization.k8s.io", "clusterrolebindings"),
    ("admissionregistration.k8s.io", "validatingwebhookconfigurations"),
    ("admissionregistration.k8s.io", "mutatingwebhookconfigurations"),
}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def selected_object(resource, obj):
    owners = obj.get("metadata", {}).get("ownerReferences") or []
    if resource == "pods":
        return not owners
    if resource == "jobs":
        return not any(owner.get("kind") == "CronJob" for owner in owners)
    return True


def documents(path):
    # One object per line: memory is bounded by an individual resource.
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            if line.startswith("{"):
                yield json.loads(line)


def write_object(out, obj):
    out.write("---\n" + encode(obj) + "\n")


def combine_manifests(paths, output):
    """Keep original IDs/references and avoid duplicate shared-context objects."""
    index = Path(str(output) + ".sqlite")
    count = 0
    try:
        with closing(sqlite3.connect(index)) as db, Path(output).open("w", encoding="utf-8") as out:
            db.execute("PRAGMA cache_size=-1024")
            db.execute("PRAGMA mmap_size=0")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("CREATE TABLE seen (identity TEXT PRIMARY KEY)")
            for path in paths:
                for obj in documents(path):
                    meta = obj.get("metadata", {})
                    # API version differences should not duplicate the same resource.
                    group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
                    identity = encode([group, obj["kind"], meta.get("namespace", ""), meta["name"]])
                    if db.execute("INSERT OR IGNORE INTO seen VALUES (?)", (identity,)).rowcount:
                        write_object(out, obj)
                        count += 1
            db.commit()
    finally:
        index.unlink(missing_ok=True)
    return count


class KubernetesAPI:
    def __init__(self):
        self.credentials = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        if ":" in host:
            host = "[" + host + "]"
        self.url = "https://" + host + ":" + os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.context = ssl.create_default_context(cafile=str(self.credentials / "ca.crt"))

    def open(self, path):
        request = urllib.request.Request(self.url + path, headers={
            "Authorization": "Bearer " + (self.credentials / "token").read_text().strip(),
            "Accept": "application/json"})
        return urllib.request.urlopen(request, timeout=120, context=self.context)

    def discovery(self, path):
        with self.open(path) as response:
            return json.load(response)

    def resources(self):
        include_cluster = os.environ.get("INCLUDE_CLUSTER_SCOPED", "true").lower() == "true"
        selected = NAMESPACED | CLUSTER if include_cluster else NAMESPACED
        versions = ["/api/v1"]
        versions.extend("/apis/" + group["preferredVersion"]["groupVersion"]
                        for group in self.discovery("/apis")["groups"]
                        if group["name"] in {g for g, _ in selected})
        for version in versions:
            group = version.split("/")[2] if version.startswith("/apis/") else ""
            for resource in self.discovery(version)["resources"]:
                key = (group, resource["name"])
                if "list" in resource.get("verbs", []) and (
                    key in NAMESPACED and resource.get("namespaced") or
                    include_cluster and key in CLUSTER and not resource.get("namespaced")):
                    yield version, resource["name"], resource["kind"], resource["namespaced"]

    def list_into(self, path, out, api_version, kind, resource):
        continuation = ""
        count = 0
        while True:
            query = urllib.parse.urlencode({"limit": 100, "continue": continuation})
            with tempfile.TemporaryFile(dir=os.environ.get("SCAN_DATA_DIR", "/data")) as page:
                with self.open(path + "?" + query) as response:
                    shutil.copyfileobj(response, page, length=BLOCK_SIZE)
                page.seek(0)
                for obj in ijson.items(page, "items.item", use_float=True):
                    if selected_object(resource, obj):
                        obj.update(apiVersion=api_version, kind=kind)
                        write_object(out, obj)
                        count += 1
                page.seek(0)
                continuation = next(ijson.items(page, "metadata.continue"), "")
            if not continuation:
                return count

    def snapshot(self, namespace, resources, manifest):
        count = 0
        with Path(manifest).open("w", encoding="utf-8") as out:
            for version, resource, kind, namespaced in resources:
                if namespaced != (namespace is not None):
                    continue
                path = version + ("/namespaces/" + urllib.parse.quote(namespace, safe="") if namespaced else "") + "/" + resource
                count += self.list_into(path, out, version.removeprefix("/apis/").removeprefix("/api/"), kind, resource)
        return count

    def namespaces(self, directory):
        path = Path(directory) / "namespace-discovery.yaml"
        with path.open("w", encoding="utf-8") as out:
            self.list_into("/api/v1/namespaces", out, "v1", "Namespace", "namespaces")
        for obj in documents(path):
            yield obj["metadata"]["name"]

    def referenced_context(self, cluster_manifest, output):
        """Resolve namespaced targets referenced by cluster bindings/webhooks."""
        with closing(sqlite3.connect(str(output) + ".sqlite")) as db, Path(output).open("w", encoding="utf-8") as out:
            db.execute("PRAGMA cache_size=-1024")
            db.execute("CREATE TABLE refs(path TEXT PRIMARY KEY)")
            for obj in documents(cluster_manifest):
                targets = []
                if obj["kind"] == "ClusterRoleBinding":
                    targets.extend(("serviceaccounts", subject.get("namespace"), subject.get("name"), "ServiceAccount")
                                   for subject in obj.get("subjects", []) if subject.get("kind") == "ServiceAccount")
                if obj["kind"] in ("ValidatingWebhookConfiguration", "MutatingWebhookConfiguration"):
                    for webhook in obj.get("webhooks", []):
                        service = webhook.get("clientConfig", {}).get("service")
                        if service:
                            targets.append(("services", service.get("namespace"), service.get("name"), "Service"))
                for resource, namespace, name, kind in targets:
                    if not namespace or not name:
                        raise ValueError("Cluster resource contains an incomplete namespaced reference")
                    path = "/api/v1/namespaces/" + urllib.parse.quote(namespace, safe="") + "/" + resource + "/" + urllib.parse.quote(name, safe="")
                    if not db.execute("INSERT OR IGNORE INTO refs VALUES (?)", (path,)).rowcount:
                        continue
                    try:
                        with self.open(path) as response:
                            target = json.load(response)
                    except urllib.error.HTTPError as error:
                        status = error.code
                        error.close()
                        if status == 404:
                            print(f"Referenced {kind} {namespace}/{name} does not exist; preserving dangling reference", flush=True)
                            continue
                        raise RuntimeError(f"Cannot resolve {kind} {namespace}/{name}: HTTP {status}") from None
                    target.update(apiVersion="v1", kind=kind)
                    write_object(out, target)
        Path(str(output) + ".sqlite").unlink(missing_ok=True)

def namespace_concurrency():
    value = os.environ.get("NAMESPACE_CONCURRENCY", "1")
    if not value.isdecimal() or int(value) < 1:
        raise ValueError("NAMESPACE_CONCURRENCY must be a positive integer")
    return int(value)


def run_namespaces(namespaces, worker, concurrency):
    """Bound both active workers and queued futures to the configured limit."""
    namespaces = iter(namespaces)
    completed = failed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = set()
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < concurrency:
                try:
                    namespace = next(namespaces)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(pool.submit(worker, namespace))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                if future.result():
                    completed += 1
                else:
                    failed += 1
    return completed, failed


def scanner_environment(concurrent_scans):
    """Budget Go memory across child processes, leaving headroom for Python."""
    env = dict(os.environ)
    limit = env.get("SCANNER_MEMORY_LIMIT_BYTES", "")
    percent = env.get("SCANNER_MEMORY_PERCENT", "60")
    gc = env.get("SCANNER_GOGC", "20")
    if not percent.isdecimal() or not 1 <= int(percent) <= 90:
        raise ValueError("SCANNER_MEMORY_PERCENT must be an integer from 1 to 90")
    if not gc.isdecimal() or int(gc) < 1:
        raise ValueError("SCANNER_GOGC must be a positive integer")
    env["GOGC"] = gc
    if limit:
        if not limit.isdecimal() or int(limit) < 1:
            raise ValueError("SCANNER_MEMORY_LIMIT_BYTES must be positive bytes")
        budget = int(limit) * int(percent) // 100 // concurrent_scans
        env["GOMEMLIMIT"] = str(budget) + "B"
    return env


def scan_manifest(manifest, report, cache, scratch, extra, concurrent_scans=1):
    worker_cache = Path(scratch) / "cache"
    worker_cache.mkdir()
    command = ["kubescape", "scan", "framework", ",".join(FRAMEWORKS), str(manifest),
               "--format", "json", "--format-version", "v2", "--cache-dir", str(worker_cache),
               "--use-artifacts-from", str(cache), "--output", str(report),
               "--cluster-name", os.environ.get("CLUSTER_NAME", ""), "--keep-local", "--use-default"] + extra
    env = scanner_environment(concurrent_scans)
    print(f"Scanning {Path(manifest).name}: {Path(manifest).stat().st_size} manifest bytes, "
          f"GOMEMLIMIT={env.get('GOMEMLIMIT', 'unset')}, GOGC={env['GOGC']}, "
          f"concurrent scan budget={concurrent_scans}", flush=True)
    try:
        subprocess.run(command, check=True, env=env)
    except subprocess.CalledProcessError as error:
        if error.returncode in (-9, 137):
            raise RuntimeError("Kubescape was killed (SIGKILL); check container OOM status. "
                               "Go's memory budget cannot free live policy/resource data.") from error
        raise
    # Validate before handing the file to the uploader, without retaining results.
    with Path(report).open("rb") as source:
        events = iter(ijson.parse(source))
        if next(events)[1] != "start_map":
            raise ValueError("Kubescape report must be a JSON object")
        for _ in events:
            pass


def publish_report(report, name, data, uploader_config):
    destination = data / (name + ".json")
    os.replace(report, destination)
    config = json.loads(encode(uploader_config))
    config["jobs"]["reportFile"] = str(destination)
    config_path = data / "upload-configs" / (name + ".json")
    temporary = config_path.with_suffix(".pending")
    temporary.write_text(encode(config))
    os.replace(temporary, config_path)


def main(data_dir="/data", artifact_dir="/opt/kubescape/artifacts"):
    print("Namespace/context scanner: two-container-v4", flush=True)
    concurrency = namespace_concurrency()
    scanner_environment(concurrency)  # Validate tuning before downloads/scans.
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    os.environ["SCAN_DATA_DIR"] = str(data)
    (data / "scan-failures.txt").unlink(missing_ok=True)
    (data / "upload-configs").mkdir(exist_ok=True)
    uploader_config = json.loads((data / "config" / "uploader.json").read_text())
    cache = data / "kubescape-cache"
    cache.mkdir(exist_ok=True)
    failed = 0
    with tempfile.TemporaryDirectory(prefix="resource-scans-", dir=data) as directory:
        directory = Path(directory)
        if os.environ.get("AIRGAPPED", "false").lower() == "true":
            shutil.copytree(artifact_dir, cache, dirs_exist_ok=True)
        else:
            subprocess.run(["kubescape", "download", "artifacts", "--output", str(cache)], check=True)
            subprocess.run(["kubescape", "download", "framework", "clusterscan", "--output", str(cache / "clusterscan.json")], check=True)
        extra = []
        config_url = os.environ.get("CONTROLS_CONFIG_URL", "")
        if config_url:
            controls = directory / "controls.json"
            context = ssl.create_default_context(cafile=os.environ.get("CA_PATH") or None)
            if os.environ.get("SKIP_TLS_VERIFICATION", "false").lower() == "true":
                context = ssl._create_unverified_context()
            with urllib.request.urlopen(config_url, timeout=60, context=context) as response, controls.open("wb") as out:
                shutil.copyfileobj(response, out, length=BLOCK_SIZE)
            extra = ["--controls-config", str(controls)]
        api = KubernetesAPI()
        resources = tuple(api.resources())
        include_cluster = os.environ.get("INCLUDE_CLUSTER_SCOPED", "true").lower() == "true"
        namespace_resources = tuple(resource for resource in resources if resource[3])
        cluster_resources = tuple(resource for resource in resources if not resource[3] and resource[2] != "Namespace")
        namespaces = api.namespaces(directory)

        def process_namespace(namespace):
            try:
                with tempfile.TemporaryDirectory(prefix="namespace-", dir=directory) as scratch:
                    scratch = Path(scratch)
                    local = scratch / "namespace.yaml"
                    KubernetesAPI().snapshot(namespace, namespace_resources, local)
                    manifest = scratch / (namespace + ".manifest.yaml")
                    count = combine_manifests([local], manifest)
                    print(f"Scanning namespace {namespace}: {count} resources, namespace-scoped resources only", flush=True)
                    report = scratch / "report.json"
                    scan_manifest(manifest, report, cache, scratch, extra, concurrent_scans=concurrency)
                    # Namespace names may equal a cluster report stem.
                    reserved = {"clusterrole", "clusterrolebinding",
                                "validatingwebhookconfiguration", "mutatingwebhookconfiguration"}
                    report_name = "namespace." + namespace if namespace in reserved else namespace
                    publish_report(report, report_name, data, uploader_config)
                print(f"Report ready: {data / (report_name + '.json')}", flush=True)
                return True
            except Exception as error:
                print(f"Namespace {namespace} failed: {error}; continuing", flush=True)
                return False

        completed, namespace_failed = run_namespaces(namespaces, process_namespace, concurrency)
        failed += namespace_failed
        print(f"Namespace scanning finished: {completed} reports, {namespace_failed} failed", flush=True)
        if include_cluster:
            # Complete download -> scan -> report for one type before the next.
            order = {name: index for index, name in enumerate((
                "clusterroles", "clusterrolebindings",
                "validatingwebhookconfigurations", "mutatingwebhookconfigurations"))}
            for resource in sorted(cluster_resources, key=lambda item: order[item[1]]):
                kind = resource[2]
                name = kind.lower()
                try:
                    with tempfile.TemporaryDirectory(prefix=name + "-", dir=directory) as scratch:
                        scratch = Path(scratch)
                        manifest = scratch / (name + ".manifest.yaml")
                        print(f"Collecting cluster-scoped type {kind}", flush=True)
                        count = api.snapshot(None, (resource,), manifest)
                        if count == 0:
                            print(f"No {kind} objects found; moving to next type", flush=True)
                            continue
                        report = scratch / "report.json"
                        scan_manifest(manifest, report, cache, scratch, extra)
                        publish_report(report, name, data, uploader_config)
                    print(f"Cluster-scoped report ready: {data / (name + '.json')}", flush=True)
                except Exception as error:
                    failed += 1
                    print(f"Cluster-scoped type {kind} failed: {error}; continuing to next type", flush=True)
        else:
            print("Cluster-scoped collection and scan disabled", flush=True)
    if failed:
        # Let knoxjobs upload successful reports before signalling partial failure.
        (data / "scan-failures.txt").write_text(f"{failed} scan(s) failed\n")


if __name__ == "__main__":
    main()
