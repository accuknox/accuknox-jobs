#!/usr/bin/env python3
"""Scan selected Kubernetes resources and save Kubescape reports locally.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
from collections import deque
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request

import ijson

FRAMEWORKS = ("allcontrols", "clusterscan", "nsa", "mitre")
# Load the shared disk-backed merger next to this entry point in the image.
_merge_spec = importlib.util.spec_from_file_location("merge_frameworks", Path(__file__).with_name("merge-frameworks.py"))
_merge_module = importlib.util.module_from_spec(_merge_spec)
_merge_spec.loader.exec_module(_merge_module)
merge_reports = _merge_module.merge

ACTIVE_PROCESSES = {}
SCAN_GOVERNOR = None
SCAN_MEMORY_BUDGET = None


class NamespaceFailures:
    """Keep bounded examples in memory and full failure records on disk."""
    def __init__(self, directory):
        from collections import Counter
        self.path = Path(directory) / "namespace-failures.jsonl"
        self.run_id = str(time.time_ns())
        self.counts = Counter()
        self.examples = []
        self.lock = threading.Lock()

    def record(self, namespace, error):
        error_type = type(error).__name__
        message = str(error)
        record = {"runID": self.run_id, "namespace": namespace,
                  "errorType": error_type, "message": message,
                  "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))}
        with self.lock:
            self.counts[error_type] += 1
            example = f"{namespace}: {error_type}: {message[:1500]}".replace("\n", " ")
            if len(self.examples) < 3:
                self.examples.append(example)
            try:
                with self.path.open("a", encoding="utf-8") as out:
                    out.write(encode(record) + "\n")
                    out.flush()
            except OSError as write_error:
                print(f"Could not write namespace failure details: {write_error}", flush=True)
        print(f"Namespace {namespace} failed: {error_type}: {message}; continuing", flush=True)

    def summary(self):
        with self.lock:
            counts = ", ".join(f"{name}={count}" for name, count in self.counts.most_common(10))
            return f"causes: {counts}; examples: {' | '.join(self.examples)}; details: {self.path} (runID={self.run_id})"


def memory_size(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(B|KiB|MiB|GiB|TiB|Ki|Mi|Gi|Ti|K|M|G|T)?', value)
    if not match:
        raise ValueError("INITIAL_MEMORY_BUDGET must be a positive memory size, e.g. 1Gi or 500Mi")
    units = {'B': 1, 'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3, 'Ti': 1024**4,
             'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'TiB': 1024**4,
             'K': 1000, 'M': 1000**2, 'G': 1000**3, 'T': 1000**4}
    amount = int(Decimal(match[1]) * units.get(match[2], 1))
    if amount < 1:
        raise ValueError("INITIAL_MEMORY_BUDGET must be positive")
    return amount


class ScanMemoryBudget:
    """Grow the software working budget inside the user's fixed cgroup hard cap."""
    def __init__(self, initial, enabled=True):
        self.initial = initial
        self.enabled = enabled
        self.current = None
        self.lock = threading.Lock()

    def view(self, memory):
        if memory is None or not self.enabled:
            return memory
        with self.lock:
            self.current = min(self.current or self.initial, memory[1])
            return memory[0], self.current

    def grow(self, memory, reason, required=0):
        if memory is None or not self.enabled:
            return False
        with self.lock:
            current = min(self.current or self.initial, memory[1])
            if required and current >= required:
                # Another worker may already have supplied the requested headroom.
                self.current = current
                return True
            if current >= memory[1]:
                return False
            self.current = min(memory[1], max(current * 2, required))
            print(f"Memory budget: increasing {current / 1048576:.1f} MiB -> "
                  f"{self.current / 1048576:.1f} MiB; "
                  f"container hard limit={memory[1] / 1048576:.1f} MiB; reason={reason}", flush=True)
            return True


def effective_memory():
    memory = container_memory()
    return SCAN_MEMORY_BUDGET.view(memory) if SCAN_MEMORY_BUDGET is not None else memory


def grow_memory_budget(reason, required=0):
    return SCAN_MEMORY_BUDGET is not None and SCAN_MEMORY_BUDGET.grow(container_memory(), reason, required)


class ScanMemoryExceeded(RuntimeError):
    """A scan was stopped by the memory guard or killed with SIGKILL."""


class ScanConcurrencyReduced(RuntimeError):
    """Retry the same controls after reducing competing scanner processes."""


class ScanGovernor:
    """Admit scans using measured process peaks and the shared cgroup budget."""
    def __init__(self, maximum):
        self.maximum = maximum
        self.target = 1
        self.condition = threading.Condition()
        self.active = {}
        self.waiters = deque()
        self.peaks = deque(maxlen=8)
        self.successes = 0
        self.victim = None
        self.shared_pressure = False

    def estimate(self):
        # Reserve startup space until real scans have supplied peak observations.
        return max(128 * 1048576, int(max(self.peaks) * 1.25)) if self.peaks else 256 * 1048576

    def can_start(self, memory):
        if not self.active:
            return True  # Always allow one scan to make progress, guarded at 90%.
        if self.victim is not None or not memory or len(self.active) >= self.target:
            return False
        estimate = self.estimate()
        # Account for active processes that have not reached their estimated peaks.
        reserved_growth = sum(max(0, estimate - entry['rss']) for entry in self.active.values())
        required = memory[0] + reserved_growth + estimate
        if required > memory[1] * 0.8 and grow_memory_budget("parallel scan demand", int(required / 0.8) + 1):
            memory = effective_memory()
        return memory is not None and required <= memory[1] * 0.8

    def acquire(self):
        token = object()
        with self.condition:
            self.waiters.append(token)
            try:
                while self.waiters[0] is not token or not self.can_start(effective_memory()):
                    self.condition.wait(timeout=0.25)
                self.waiters.popleft()
                self.active[token] = {'rss': 0, 'peak': 0}
                print(f"Scan scheduler: active={len(self.active)}, target={self.target}, "
                      f"maximum={self.maximum}, reservedPerScan={self.estimate() / 1048576:.1f} MiB", flush=True)
                self.condition.notify_all()
                return token
            except BaseException:
                if token in self.waiters:
                    self.waiters.remove(token)
                self.condition.notify_all()
                raise

    def sample(self, token, pid):
        try:
            status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            rss = int(status['VmRSS'].split()[0]) * 1024
            peak = int(status['VmHWM'].split()[0]) * 1024
        except (OSError, ValueError, KeyError):
            return
        with self.condition:
            self.active[token]['rss'] = rss
            self.active[token]['peak'] = max(self.active[token]['peak'], peak)

    def go_budget(self):
        with self.condition:
            memory = effective_memory()
            return int(memory[1] * 0.8 / self.target) if memory else None

    def stop_for_pressure(self, token):
        with self.condition:
            if self.victim is None:
                # Abort only the newest scan, preserving work in older scans.
                self.victim = next(reversed(self.active))
                self.shared_pressure = len(self.active) > 1
                self.target = max(1, len(self.active) // 2)
                self.successes = 0
                print(f"Scan scheduler: memory pressure; reducing target to {self.target}", flush=True)
            return self.victim is token, self.shared_pressure

    def killed(self):
        with self.condition:
            self.target = 1
            self.successes = 0
            return len(self.active) > 1

    def release(self, token, success):
        with self.condition:
            entry = self.active.pop(token)
            if entry['peak']:
                self.peaks.append(entry['peak'])
            if self.victim is token:
                self.victim = None
            memory = effective_memory()
            if success and entry['peak'] and self.victim is None and memory and memory[0] < memory[1] * 0.7:
                self.successes += 1
                if self.successes >= 2 and self.target < self.maximum:
                    self.target += 1
                    self.successes = 0
                    print(f"Scan scheduler: increasing target to {self.target} (maximum={self.maximum})", flush=True)
            elif not success:
                self.successes = 0
            self.condition.notify_all()


def container_memory():
    """Return cgroup working-set bytes and hard limit, or None if unavailable."""
    for root, usage_name, limit_name, stat_key in (
        (Path("/sys/fs/cgroup"), "memory.current", "memory.max", "inactive_file"),
        (Path("/sys/fs/cgroup/memory"), "memory.usage_in_bytes", "memory.limit_in_bytes", "total_inactive_file"),
    ):
        try:
            usage = int((root / usage_name).read_text().strip())
            limit = int((root / limit_name).read_text().strip())
            if limit <= 0 or limit >= 1 << 60:
                continue
            # Reclaimable inactive file cache should not stop otherwise healthy scans.
            try:
                stats = dict(line.split() for line in (root / "memory.stat").read_text().splitlines())
                usage = max(0, usage - int(stats.get(stat_key, "0")))
            except (OSError, ValueError):
                pass
            return usage, limit
        except (OSError, ValueError):
            continue
    return None


def stop_command(process):
    """Stop the active scan and reap it before starting a smaller retry."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def log_memory(pid=None):
    """Best-effort Linux diagnostics; missing cgroup/proc files are harmless."""
    values = []
    for label, path in (("python", "/proc/self/status"),
                        ("kubescape", f"/proc/{pid}/status" if pid else "")):
        try:
            for line in Path(path).read_text().splitlines():
                if line.startswith(("VmRSS:", "VmHWM:")):
                    field, amount, _ = line.split()
                    values.append(f"{label}.{field.rstrip(':')}={amount} kB ({int(amount) / 1024:.1f} MiB)")
        except OSError:
            pass
    for name in ("memory.current", "memory.peak", "memory.max"):
        try:
            amount = Path('/sys/fs/cgroup', name).read_text().strip()
            formatted = "unlimited" if amount == "max" else f"{amount} bytes ({int(amount) / (1024 * 1024):.1f} MiB)"
            values.append(f"cgroup.{name}={formatted}")
        except OSError:
            pass
    memory = effective_memory()
    if memory is not None:
        values.append(f"scan.budget={memory[1]} bytes ({memory[1] / 1048576:.1f} MiB)")
        values.append(f"guard.workingSet={memory[0]} bytes ({memory[0] / 1048576:.1f} MiB)")
        threshold = int(memory[1] * 0.9)
        values.append(f"guard.threshold={threshold} bytes ({threshold / 1048576:.1f} MiB)")
    for path, keys, prefix in (
        ("/sys/fs/cgroup/memory.stat", ("inactive_file",), "cgroup"),
        ("/sys/fs/cgroup/memory.events", ("max", "oom", "oom_kill"), "cgroup.events"),
    ):
        try:
            counters = dict(line.split() for line in Path(path).read_text().splitlines())
            for key in keys:
                if key in counters:
                    amount = int(counters[key])
                    formatted = f"{amount} bytes ({amount / 1048576:.1f} MiB)" if key == "inactive_file" else str(amount)
                    values.append(f"{prefix}.{key}={formatted}")
        except (OSError, ValueError):
            pass
    print("Memory: " + "; ".join(values), flush=True)


def kubescape_environment(memory_budget=None):
    environment = os.environ.copy()
    environment.setdefault("GOMEMLIMIT", "auto")
    environment.setdefault("GOGC", "50")
    if environment['GOMEMLIMIT'] == 'auto':
        if memory_budget is None:
            memory = effective_memory()
            limit = memory[1] if memory else memory_size(os.environ.get("INITIAL_MEMORY_BUDGET", "1Gi"))
            memory_budget = max(1, int(limit * 0.8))
        environment['GOMEMLIMIT'] = str(memory_budget) + 'B'
    if memory_budget is not None:
        value = environment['GOMEMLIMIT']
        match = re.fullmatch(r'(\d+)(B|KiB|MiB|GiB|TiB)?', value)
        if match or value == 'off':
            units = {'B': 1, 'KiB': 1024, 'MiB': 1048576,
                     'GiB': 1073741824, 'TiB': 1099511627776}
            configured = int(match[1]) * units.get(match[2], 1) if match else memory_budget
            environment['GOMEMLIMIT'] = str(min(configured, memory_budget)) + 'B'
    return environment


def run_command(command, check=True):
    """Track processes and share the container memory budget between scans."""
    is_scan = len(command) > 1 and command[1] == "scan"
    governor = SCAN_GOVERNOR if is_scan else None
    token = governor.acquire() if governor is not None else None
    process = None
    success = False
    try:
        environment = kubescape_environment(governor.go_budget() if governor is not None else None)
        if governor is not None:
            print(f"Scan scheduler: launching Kubescape with GOMEMLIMIT={environment['GOMEMLIMIT']}", flush=True)
        process = subprocess.Popen(command, start_new_session=True, env=environment)
        ACTIVE_PROCESSES[process.pid] = process
        if governor is not None:
            governor.sample(token, process.pid)
        next_log = time.monotonic() + 15
        while True:
            try:
                return_code = process.wait(timeout=0.25 if is_scan else 15)
                break
            except subprocess.TimeoutExpired:
                if governor is not None:
                    governor.sample(token, process.pid)
                if time.monotonic() >= next_log:
                    log_memory(process.pid)
                    next_log = time.monotonic() + 15
                memory = effective_memory() if is_scan else None
                if memory and memory[0] >= memory[1] * 0.9:
                    if grow_memory_budget("scan memory pressure", int(memory[0] / 0.8) + 1):
                        continue
                    shared_pressure = False
                    if governor is not None:
                        stop, shared_pressure = governor.stop_for_pressure(token)
                        if not stop:
                            continue
                    print(f"Memory guard: container working set={memory[0] / 1048576:.1f} MiB "
                          f"reached 90% of scan budget={memory[1] / 1048576:.1f} MiB; stopping Kubescape", flush=True)
                    stop_command(process)
                    log_memory()
                    if shared_pressure:
                        raise ScanConcurrencyReduced("Shared memory pressure; retrying with fewer concurrent scans")
                    raise ScanMemoryExceeded("Kubescape stopped at the container memory guard threshold")
        log_memory()
        if check and return_code:
            if governor is not None and return_code in (-signal.SIGKILL, 128 + signal.SIGKILL):
                if governor.killed():
                    raise ScanConcurrencyReduced("Possible OOM with competing scans; retrying with concurrency reduced")
            raise subprocess.CalledProcessError(return_code, command)
        success = return_code == 0
        return subprocess.CompletedProcess(command, return_code)
    finally:
        if process is not None:
            ACTIVE_PROCESSES.pop(process.pid, None)
        if governor is not None:
            governor.release(token, success)


def shutdown(signum, frame):
    # Never wait for executor workers: they may be blocked on Kubernetes I/O.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print(f"Received {signal.Signals(signum).name}; stopping active scans and exiting", flush=True)
    processes = list(ACTIVE_PROCESSES.values())
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2
    while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
        time.sleep(0.05)
    # Kill the groups even if their leaders exited; descendants may still be running.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # Bypass Python's ThreadPoolExecutor shutdown hooks to guarantee prompt exit.
    os._exit(128 + signum)


def install_signal_handlers():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)


BLOCK_SIZE = 64 * 1024
# kubectl aliases: pods,deploy,sts,ds,job,cronjob,svc,ingress,networkpolicy,sa,role,rolebinding,cm
NS_RESOURCES = (
    ("/api/v1", "pods", "Pod"),
    ("/apis/apps/v1", "deployments", "Deployment"),
    ("/apis/apps/v1", "statefulsets", "StatefulSet"),
    ("/apis/apps/v1", "daemonsets", "DaemonSet"),
    ("/apis/batch/v1", "jobs", "Job"),
    ("/apis/batch/v1", "cronjobs", "CronJob"),
    ("/api/v1", "services", "Service"),
    ("/apis/networking.k8s.io/v1", "ingresses", "Ingress"),
    ("/apis/networking.k8s.io/v1", "networkpolicies", "NetworkPolicy"),
    ("/api/v1", "serviceaccounts", "ServiceAccount"),
    ("/apis/rbac.authorization.k8s.io/v1", "roles", "Role"),
    ("/apis/rbac.authorization.k8s.io/v1", "rolebindings", "RoleBinding"),
    ("/api/v1", "configmaps", "ConfigMap"),
)
CLUSTER_RESOURCES = (
    ("/apis/rbac.authorization.k8s.io/v1", "clusterroles", "ClusterRole"),
    ("/apis/rbac.authorization.k8s.io/v1", "clusterrolebindings", "ClusterRoleBinding"),
    ("/apis/admissionregistration.k8s.io/v1", "validatingwebhookconfigurations", "ValidatingWebhookConfiguration"),
    ("/apis/admissionregistration.k8s.io/v1", "mutatingwebhookconfigurations", "MutatingWebhookConfiguration"),
)


RESOURCE_ALIASES = dict(zip(
    "po,deploy,sts,ds,job,cronjob,svc,ingress,networkpolicy,sa,role,rolebinding,cm".split(","),
    (resource for _, resource, _ in NS_RESOURCES)))
RESOURCE_ALIASES.update({"clusterrole": "clusterroles", "clusterrolebinding": "clusterrolebindings",
                         "validatingwebhookconfiguration": "validatingwebhookconfigurations",
                         "mutatingwebhookconfiguration": "mutatingwebhookconfigurations"})


def select_resources(resources, selection, scope):
    """Resolve comma-separated plural names, kinds, baseline aliases or resource.group."""
    if not selection.strip():
        return resources
    selected = []
    for token in selection.split(","):
        name = token.strip().lower()
        if not name:
            continue
        name = RESOURCE_ALIASES.get(name, name)
        matches = []
        for resource in resources:
            version, plural, kind = resource
            group = version.split("/")[2] if version.startswith("/apis/") else "core"
            if name in (plural.lower(), kind.lower(), f"{plural}.{group}".lower()):
                matches.append(resource)
        if not matches:
            raise ValueError(f"Unknown or non-listable {scope} resource type: {token.strip()}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous {scope} resource type: {token.strip()}; use resource.group")
        if matches[0] not in selected:
            selected.append(matches[0])
    return tuple(selected)


def configured_resources(api, all_resources):
    if all_resources:
        print("collectAllResources enabled: namespaceResources and clusterResources are ignored", flush=True)
        return api.discover_resources()
    ns_selection = os.environ.get("NAMESPACE_RESOURCES", "")
    cluster_selection = os.environ.get("CLUSTER_RESOURCES", "")
    try:
        return (select_resources(NS_RESOURCES, ns_selection, "namespace"),
                select_resources(CLUSTER_RESOURCES, cluster_selection, "cluster"))
    except ValueError:
        # Custom types and types outside the baseline need served-version discovery.
        namespaced, cluster = api.discover_resources()
        return (select_resources(namespaced, ns_selection, "namespace") if ns_selection.strip() else NS_RESOURCES,
                select_resources(cluster, cluster_selection, "cluster") if cluster_selection.strip() else CLUSTER_RESOURCES)


def publish_completed(report, directory, name):
    """Publish only complete reports, atomically, including across mounted volumes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (name + "-report.json")
    with tempfile.NamedTemporaryFile(prefix=".publishing-", dir=directory, delete=False) as out:
        temporary = Path(out.name)
        try:
            with Path(report).open("rb") as source:
                shutil.copyfileobj(source, out, length=BLOCK_SIZE)
            out.close()
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Completed report available: {destination}", flush=True)
    return destination


def publish_scan_status(status, directory=None):
    """Notify the uploader only after all completed reports are published."""
    output = Path(os.environ.get("OUTPUT_PATH", "/data"))
    directory = Path(directory or os.environ.get("COMPLETED_REPORTS_PATH") or output / "completed")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".scan-status-", dir=directory, delete=False) as out:
        temporary = Path(out.name)
        try:
            out.write((status + "\n").encode())
            out.close()
            os.replace(temporary, directory / status)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Scanner message: {status}", flush=True)


def encode(value):
    return _merge_module.encode(value)


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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ManifestReader:
    """Remove YAML document markers while reading bounded chunks of JSON."""
    def __init__(self, source):
        self.source = source
        self.line_start = True
        self.pending = b""

    def read(self, size=-1):
        if size == 0:
            return b""
        if size < 0:
            size = BLOCK_SIZE
        parts = []
        remaining = size
        while remaining:
            if self.line_start and not self.pending:
                self.pending = self.source.readline(4)
                if self.pending == b"---\n":
                    self.pending = b""
                    continue
            if self.pending:
                part, self.pending = self.pending[:remaining], self.pending[remaining:]
            else:
                part = self.source.readline(remaining)
            if not part:
                break
            self.line_start = part.endswith(b"\n")
            parts.append(part)
            remaining -= len(part)
        return b"".join(parts)


def manifest_objects(path, project=False):
    """Stream disk-backed documents; project namespace references without data/spec."""
    if not Path(path).exists() or Path(path).stat().st_size == 0:
        return
    with Path(path).open("rb") as source:
        reader = ManifestReader(source)
        if not project:
            yield from ijson.items(reader, "", multiple_values=True)
            return
        events = iter(ijson.parse(reader, multiple_values=True))
        obj = None
        for prefix, event, value in events:
            if prefix == "" and event == "start_map":
                obj = {"metadata": {}}
            elif prefix == "" and event == "end_map":
                yield obj
            elif prefix in ("kind", "apiVersion") and event == "string":
                obj[prefix] = value
            elif prefix in ("metadata.name", "metadata.namespace") and event == "string":
                obj["metadata"][prefix.split(".")[1]] = value
            elif prefix == "metadata.labels" and event == "start_map":
                obj["metadata"]["labels"] = _merge_module.value_from(events, (prefix, event, value))
            elif prefix in ("roleRef", "subjects") and event in ("start_map", "start_array"):
                obj[prefix] = _merge_module.value_from(events, (prefix, event, value))
            elif prefix == "metadata.uid" and event == "string":
                obj["metadata"]["uid"] = value
            elif prefix == "metadata.ownerReferences" and event == "start_array":
                obj.setdefault("_refs", []).extend(_merge_module.value_from(events, (prefix,event,value)))
            elif prefix.startswith("spec.") and (prefix.endswith("Ref") or prefix.endswith("reference")) and event == "start_map":
                reference = _merge_module.value_from(events, (prefix,event,value))
                if reference.get("kind") and reference.get("name") and not reference.get("namespace"):
                    obj.setdefault("_refs", []).append(reference)
            elif prefix.startswith("spec.") and event == "string" and prefix.rsplit(".",1)[-1] in (
                "volumeName", "storageClassName", "ingressClassName", "priorityClassName", "runtimeClassName", "nodeName"):
                target_kind = {"volumeName":"PersistentVolume", "storageClassName":"StorageClass",
                               "ingressClassName":"IngressClass", "priorityClassName":"PriorityClass",
                               "runtimeClassName":"RuntimeClass", "nodeName":"Node"}[prefix.rsplit(".",1)[-1]]
                if value:
                    obj.setdefault("_refs", []).append({"kind":target_kind,"name":value})
            elif prefix in ("spec.names.kind", "spec.group") and event == "string":
                obj["_definedKind" if prefix == "spec.names.kind" else "_definedGroup"] = value
            elif prefix.startswith("spec.") and prefix.endswith("serviceAccountName") and event == "string":
                obj["_account"] = value
            elif prefix.startswith("spec.") and prefix.endswith("template.metadata.labels") and event == "start_map":
                obj["_podLabels"] = _merge_module.value_from(events, (prefix, event, value))


def selector_matches(selector, labels):
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        key, operation = expression["key"], expression["operator"]
        values = expression.get("values") or []
        present = key in labels
        if operation == "In" and (not present or labels[key] not in values):
            return False
        if operation == "NotIn" and present and labels[key] in values:
            return False
        if operation == "Exists" and not present:
            return False
        if operation == "DoesNotExist" and present:
            return False
        if operation not in ("In", "NotIn", "Exists", "DoesNotExist"):
            raise ValueError(f"Unsupported label selector operator: {operation}")
    return True


def namespace_subject(subject, namespace, accounts):
    kind, name = subject.get("kind"), subject.get("name", "")
    if kind == "ServiceAccount":
        return subject.get("namespace") == namespace and name in accounts
    if kind == "User":
        return any(name == f"system:serviceaccount:{namespace}:{account}" for account in accounts)
    if kind == "Group":
        return bool(accounts) and name in ("system:serviceaccounts", "system:serviceaccounts:" + namespace,
                                          "system:authenticated")
    return False


def webhook_applies(webhook, obj, resource, namespace, namespace_labels):
    service = (webhook.get("clientConfig") or {}).get("service") or {}
    if obj.get("kind") == "Service" and service.get("namespace") == namespace and service.get("name") == obj.get("metadata", {}).get("name"):
        return True
    if not selector_matches(webhook.get("namespaceSelector") or {}, namespace_labels):
        return False
    if not selector_matches(webhook.get("objectSelector") or {}, obj.get("metadata", {}).get("labels") or {}):
        return False
    api_version = obj.get("apiVersion", "v1")
    group = api_version.split("/")[0] if "/" in api_version else ""
    for rule in webhook.get("rules") or []:
        if rule.get("scope", "*") == "Cluster":
            continue
        groups = rule.get("apiGroups") or []
        # Equivalent API versions can also trigger admission. Keep these conservatively.
        if group not in groups and "*" not in groups:
            continue
        if not set(rule.get("operations") or []).intersection(("*", "CREATE", "UPDATE", "DELETE", "CONNECT")):
            continue
        if set(rule.get("resources") or []).intersection((resource, "*", "*/*")):
            return True
    return False


def append_cluster_context(manifest, context, namespace, resource, namespace_labels, resource_types=NS_RESOURCES):
    """Resolve actual RBAC references and applicable webhooks from this scan input.

    Only one object is parsed at a time. Selected IDs and identities live in SQLite
    so they do not accumulate in memory for a large namespace.
    """
    import sqlite3
    with sqlite3.connect(Path(manifest).parent / "context.sqlite") as db:
        db.execute("PRAGMA cache_size=-1024")
        db.execute("PRAGMA temp_store=FILE")
        db.execute("CREATE TABLE accounts(name TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE roles(name TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE selected(kind TEXT, name TEXT, PRIMARY KEY(kind,name))")
        db.execute("CREATE TABLE refs(kind TEXT, name TEXT, uid TEXT, UNIQUE(kind,name,uid))")
        db.execute("CREATE TABLE namespace_types(api_group TEXT, kind TEXT, PRIMARY KEY(api_group,kind))")
        def remember_refs(obj):
            added = 0
            for ref in obj.get("_refs") or []:
                if ref.get("kind") and ref.get("name"):
                    added += db.execute("INSERT OR IGNORE INTO refs VALUES (?,?,?)", (ref["kind"],ref["name"],ref.get("uid", ""))).rowcount
            return added

        for obj in manifest_objects(manifest, project=True):
            kind = obj.get("kind")
            remember_refs(obj)
            api_version = obj.get("apiVersion", "v1")
            api_group = api_version.split("/")[0] if "/" in api_version else ""
            db.execute("INSERT OR IGNORE INTO namespace_types VALUES (?,?)", (api_group,kind))
            if kind == "RoleBinding" and obj.get("roleRef", {}).get("kind") == "ClusterRole":
                db.execute("INSERT OR IGNORE INTO roles VALUES (?)", (obj["roleRef"]["name"],))
            account = None
            if kind == "ServiceAccount":
                account = obj["metadata"]["name"]
            elif kind == "Pod":
                account = obj.get("_account") or "default"
            elif kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
                account = obj.get("_account") or "default"
            if account:
                db.execute("INSERT OR IGNORE INTO accounts VALUES (?)", (account,))
        # SQL-backed membership keeps account enumeration bounded.
        class Accounts:
            def __contains__(self, name):
                return db.execute("SELECT 1 FROM accounts WHERE name=?", (name,)).fetchone() is not None
            def __iter__(self):
                return (row[0] for row in db.execute("SELECT name FROM accounts"))
            def __bool__(self):
                return db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None
        accounts = Accounts()
        for obj in manifest_objects(Path(context) / "clusterrolebindings.yaml"):
            if any(namespace_subject(subject, namespace, accounts) for subject in obj.get("subjects") or []):
                db.execute("INSERT OR IGNORE INTO selected VALUES (?,?)", (obj["kind"], obj["metadata"]["name"]))
                if obj.get("roleRef", {}).get("kind") == "ClusterRole":
                    db.execute("INSERT OR IGNORE INTO roles VALUES (?)", (obj["roleRef"]["name"],))
        # Follow aggregation dependencies until no new role is selected.
        changed = True
        while changed:
            changed = False
            for obj in manifest_objects(Path(context) / "clusterroles.yaml"):
                if not db.execute("SELECT 1 FROM roles WHERE name=?", (obj["metadata"]["name"],)).fetchone():
                    continue
                for selector in obj.get("aggregationRule", {}).get("clusterRoleSelectors") or []:
                    for candidate in manifest_objects(Path(context) / "clusterroles.yaml"):
                        if selector_matches(selector, candidate.get("metadata", {}).get("labels") or {}):
                            added = db.execute("INSERT OR IGNORE INTO roles VALUES (?)", (candidate["metadata"]["name"],)).rowcount
                            changed = changed or bool(added)
        for obj in manifest_objects(Path(context) / "clusterroles.yaml"):
            if db.execute("SELECT 1 FROM roles WHERE name=?", (obj["metadata"]["name"],)).fetchone():
                db.execute("INSERT OR IGNORE INTO selected VALUES (?,?)", (obj["kind"], obj["metadata"]["name"]))
        for filename in ("validatingwebhookconfigurations.yaml", "mutatingwebhookconfigurations.yaml"):
            for obj in manifest_objects(Path(context) / filename):
                applies = False
                for item in manifest_objects(manifest, project=True):
                    api_resource = resource or next((name for _, name, kind in resource_types if kind == item.get("kind")), "")
                    candidates = [(item, api_resource)]
                    if item.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
                        template = {"apiVersion": "v1", "kind": "Pod",
                                    "metadata": {"labels": item.get("_podLabels") or {}}}
                        candidates.append((template, "pods"))
                    if any(webhook_applies(webhook, candidate, api_resource, namespace, namespace_labels)
                           for webhook in obj.get("webhooks") or [] for candidate, api_resource in candidates):
                        applies = True
                        break
                if applies:
                    db.execute("INSERT OR IGNORE INTO selected VALUES (?,?)", (obj["kind"], obj["metadata"]["name"]))
        # Resolve explicit storage/scheduling/custom refs and their cluster dependencies.
        changed = True
        while changed:
            changed = False
            for context_file in sorted(Path(context).glob("*.yaml")):
                for obj in manifest_objects(context_file, project=True):
                    kind, name = obj.get("kind"), obj.get("metadata", {}).get("name")
                    uid = obj.get("metadata", {}).get("uid", "")
                    related = (kind == "Namespace" and name == namespace) or db.execute(
                        "SELECT 1 FROM refs WHERE kind=? AND name=? AND (uid='' OR uid=?)", (kind,name,uid)).fetchone()
                    if kind == "CustomResourceDefinition":
                        related = related or db.execute("SELECT 1 FROM namespace_types WHERE api_group=? AND kind=?",
                            (obj.get("_definedGroup", ""),obj.get("_definedKind", ""))).fetchone()
                    existing = db.execute("SELECT 1 FROM selected WHERE kind=? AND name=?", (kind,name)).fetchone()
                    if related or existing:
                        added = db.execute("INSERT OR IGNORE INTO selected VALUES (?,?)", (kind,name)).rowcount
                        references_added = remember_refs(obj)
                        changed = changed or bool(added) or bool(references_added)
        count = 0
        with Path(manifest).open("a", encoding="utf-8") as out:
            for context_file in sorted(Path(context).glob("*.yaml")):
                for obj in manifest_objects(context_file):
                    if db.execute("SELECT 1 FROM selected WHERE kind=? AND name=?", (obj["kind"], obj["metadata"]["name"])).fetchone():
                        out.write("---\n" + encode(obj) + "\n")
                        count += 1
        return count


def audit_scan(manifest, report, directory, namespace):
    """Compare input identities with raw and relationship objects in report output."""
    import sqlite3
    from collections import Counter
    input_counts = Counter()
    with sqlite3.connect(Path(directory) / "coverage.sqlite") as db:
        db.execute("PRAGMA cache_size=-1024")
        db.execute("CREATE TABLE inputs(kind TEXT, namespace TEXT, name TEXT, represented INTEGER DEFAULT 0, PRIMARY KEY(kind,namespace,name))")
        namespaced_kinds = {kind for _, _, kind in NS_RESOURCES}
        def identity(obj):
            metadata = obj.get("metadata") or {}
            kind = obj.get("kind")
            name = metadata.get("name") or obj.get("name")
            scope = metadata.get("namespace") or obj.get("namespace") or (namespace if kind in namespaced_kinds else "")
            return kind, scope or "", name
        for obj in manifest_objects(manifest, project=True):
            kind, scope, name = identity(obj)
            if name and db.execute("INSERT OR IGNORE INTO inputs(kind,namespace,name) VALUES (?,?,?)", (kind,scope,name)).rowcount:
                input_counts[kind] += 1
        def observed(obj):
            if not isinstance(obj, dict):
                return
            kind, scope, name = identity(obj)
            if name:
                db.execute("UPDATE inputs SET represented=1 WHERE kind=? AND namespace=? AND name=?", (kind,scope,name))
            related = obj.get("relatedObjects") or []
            if isinstance(related, dict):
                observed(related)
            else:
                for item in related:
                    observed(item)
        with Path(report).open("rb") as source:
            for resource in ijson.items(source, "resources.item"):
                observed(resource.get("object") or {})
        represented = dict(db.execute("SELECT kind,count(*) FROM inputs WHERE represented=1 GROUP BY kind"))
        missing = db.execute("SELECT count(*) FROM inputs WHERE represented=0").fetchone()[0]
        examples = [dict(zip(("kind","namespace","name"), row)) for row in db.execute(
            "SELECT kind,namespace,name FROM inputs WHERE represented=0 ORDER BY kind,namespace,name LIMIT 20")]
    return {"namespace": namespace, "inputResourcesByKind": dict(input_counts),
            "representedInputResourcesByKind": represented, "unrepresentedInputCount": missing,
            "unrepresentedInputExamples": examples,
            "note": "Output representation is not proof of control evaluation; inputs with no applicable controls may not appear in results."}


def add_report_field(report, field, value):
    replacement = Path(report).with_name("annotated.json")
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
            first = next(events)
            if token[2] == field:
                copy_value(events, first, Discard())
                continue
            out.write(separator + encode(token[2]) + ":")
            copy_value(events, first, out)
            separator = ","
        if next(events, None) is not None:
            raise ValueError("Trailing report data")
        out.write(separator + encode(field) + ":" + encode(value) + "}\n")
    os.replace(replacement, report)


def resource_filename(version, resource):
    # Retain baseline filenames; distinguish same-named resources from other groups.
    if any(v == version and r == resource for v, r, _ in CLUSTER_RESOURCES):
        return resource
    group = version.removeprefix("/apis/").split("/")[0] if version.startswith("/apis/") else "core"
    return resource + "." + group


class KubernetesAPI:
    """Read paginated lists with rotating in-cluster service-account tokens."""
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

    def discover_resources(self):
        versions = ["/api/v1"]
        with self.open("/apis") as response:
            groups = json.load(response)["groups"]
        versions.extend("/apis/" + group["preferredVersion"]["groupVersion"] for group in groups)
        namespaced, cluster = [], []
        for version in versions:
            with self.open(version) as response:
                resources = json.load(response)["resources"]
            for item in resources:
                if version == "/api/v1" and item["name"] == "secrets":
                    continue
                if "/" in item["name"] or "list" not in item.get("verbs", []):
                    continue
                target = namespaced if item.get("namespaced") else cluster
                target.append((version, item["name"], item["kind"]))
        return tuple(namespaced), tuple(cluster)

    def snapshot_cluster(self, resources, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for version, resource, kind in resources:
            path = directory / (resource_filename(version, resource) + ".yaml")
            print(f"Collecting cluster context {resource} from {version}", flush=True)
            with path.open("w", encoding="utf-8") as out:
                self.list_into(version + "/" + resource, out,
                               version.removeprefix("/apis/").removeprefix("/api/"), kind, documents=True)

    def list_into(self, path, out, api_version, kind, exclude_owned=False, documents=False):
        """Write a JSON List, spooling each object on disk before owner filtering.

        Even a large ConfigMap or list page is never materialized in memory.
        """
        continuation = ""
        count = fetched = excluded = 0
        if not documents:
            out.write('{"apiVersion":' + encode(api_version) + ',"kind":"List","items":[')
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as item:
            while True:
                query = urllib.parse.urlencode({"limit": kubernetes_page_size(), "continue": continuation})
                with self.open(path + "?" + query) as response:
                    owned = False
                    object_name = ""
                    owner_kinds = set()
                    def observed():
                        nonlocal owned, object_name
                        for token in ijson.parse(response):
                            if token[0].startswith("items.item.metadata.ownerReferences.item"):
                                owned = True
                            if token[:2] == ("items.item.metadata.ownerReferences.item.kind", "string"):
                                owner_kinds.add(token[2])
                            if token[:2] == ("items.item.metadata.name", "string"):
                                object_name = token[2]
                            yield token
                    events = iter(observed())
                    continuation = ""
                    for token in events:
                        if token[:2] == ("items.item", "start_map"):
                            owned = False
                            object_name = ""
                            owner_kinds.clear()
                            fetched += 1
                            item.seek(0)
                            item.truncate()
                            item.write('{"apiVersion":' + encode(api_version) + ',"kind":' + encode(kind))
                            for field in events:
                                if field[1] == "end_map":
                                    break
                                if field[1] != "map_key":
                                    raise ValueError("Invalid Kubernetes resource object")
                                value = next(events)
                                if field[2] in ("apiVersion", "kind"):
                                    copy_value(events, value, Discard())
                                else:
                                    item.write("," + encode(field[2]) + ":")
                                    copy_value(events, value, item)
                            item.write("}")
                            workload_parent = kind in ("Deployment", "StatefulSet", "DaemonSet", "CronJob") or (
                                kind == "Job" and "CronJob" not in owner_kinds)
                            filtered = exclude_owned and owned and not workload_parent
                            if exclude_owned and owned and workload_parent:
                                print(f"Retaining {kind}/{object_name}: owned workload has its own spec to scan", flush=True)
                            if filtered:
                                excluded += 1
                                if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
                                    print(f"Filtered {kind}/{object_name}: metadata.ownerReferences is nonempty", flush=True)
                            if not filtered:
                                if documents:
                                    out.write("---\n")
                                elif count:
                                    out.write(",")
                                item.seek(0)
                                shutil.copyfileobj(item, out, length=BLOCK_SIZE)
                                if documents:
                                    out.write("\n")
                                count += 1
                        elif token[:2] == ("metadata.continue", "string"):
                            continuation = token[2]
                if not continuation:
                    break
        if not documents:
            out.write("]}\n")
        print(f"Collection [{path}]: fetched={fetched}, excluded_owned={excluded}, retained={count}", flush=True)
        return count

    def scan_manifest(self, manifest, destination, scratch, cache, extra):
        report = Path(scratch) / "report.json"
        worker_cache = Path(scratch) / "cache"
        worker_cache.mkdir()
        command = ["kubescape", "scan", "framework", ",".join(FRAMEWORKS), str(manifest),
                   "--keep-local", "--use-default", "--enable-streaming",
                   "--format", "json", "--format-version", "v2", "--cache-dir", str(worker_cache),
                   "--use-artifacts-from", str(cache), "--output", str(report),
                   "--cluster-name", os.environ.get("CLUSTER_NAME", "")] + list(extra)
        print(f"Scanning {destination}: {Path(manifest).stat().st_size} manifest bytes", flush=True)
        scan_with_memory_retries(command, report, scratch, cache, destination)
        if os.environ.get("VALIDATE_REPORTS", "true").lower() == "true":
            with report.open("rb") as source:
                for _ in ijson.parse(source):
                    pass
        namespace = None if Path(destination).parent.name == "clusterscoped" else Path(destination).parent.name
        audit = audit_scan(manifest, report, scratch, namespace)
        add_report_field(report, "collectionAudit", audit)
        print(f"Coverage [{namespace or 'clusterscoped'}]: input={audit['inputResourcesByKind']}, "
              f"represented={audit['representedInputResourcesByKind']}, "
              f"unrepresented={audit['unrepresentedInputCount']}", flush=True)
        if audit["unrepresentedInputCount"]:
            print("Unrepresented input examples: " + encode(audit["unrepresentedInputExamples"]), flush=True)
        os.replace(report, destination)

    def scan_namespace(self, resources, directory, cache, namespace, extra, cluster_context, namespace_labels):
        """Collect all retained namespace types before a single relationship-aware scan."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "report.json"
        with tempfile.TemporaryDirectory(prefix=".scan-", dir=directory) as scratch:
            scratch = Path(scratch)
            manifest = scratch / "resources.yaml"
            total = len(resources)
            count = 0
            with manifest.open("w", encoding="utf-8") as out:
                for index, (version, resource, kind) in enumerate(resources, 1):
                    path = version + "/namespaces/" + urllib.parse.quote(namespace, safe="") + "/" + resource
                    print(f"Progress [{namespace} collection]: fetching {resource} ({index}/{total})", flush=True)
                    retained = self.list_into(path, out, version.removeprefix("/apis/").removeprefix("/api/"),
                                              kind, exclude_owned=True, documents=True)
                    count += retained
                    print(f"Progress [{namespace} collection]: completed={index}/{total}, "
                          f"pending={total - index}, retained={count}", flush=True)
            if not count:
                destination.unlink(missing_ok=True)
                print(f"Progress [{namespace} scan]: skipped; no eligible resources", flush=True)
                return []
            selected = 0
            if cluster_context is not None:
                selected = append_cluster_context(manifest, cluster_context, namespace, None,
                                                  namespace_labels or {"kubernetes.io/metadata.name": namespace}, resource_types=resources)
                print(f"Selected {selected} cluster context objects for namespace {namespace}", flush=True)
            print(f"Resources [{namespace}]: total={count + selected}, "
                  f"namespace={count}, clusterContext={selected}", flush=True)
            print(f"Progress [{namespace} scan]: starting combined scan of {count} retained namespace resources", flush=True)
            self.scan_manifest(manifest, destination, scratch, cache, extra)
        print(f"Progress [{namespace} scan]: completed; report saved to {destination}", flush=True)
        return [destination]

    def scan(self, resources, directory, cache, namespace=None, extra=(), cluster_context=None, namespace_labels=None,
             completed_directory=None):
        if namespace is not None:
            return self.scan_namespace(resources, directory, cache, namespace, extra, cluster_context, namespace_labels)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        reports = []
        total = len(resources)
        scope = namespace or "clusterscoped"
        scanned = skipped = 0
        for index, (version, resource, kind) in enumerate(resources, 1):
            print(f"Progress [{scope}]: starting {resource} ({index}/{total}); "
                  f"scanned={scanned}, skipped={skipped}, pending={total - index + 1}", flush=True)
            path = version + "/" + resource
            filename = resource_filename(version, resource)
            destination = directory / (filename + ".json")
            # Raw inputs and partial reports are private and removed after each scan.
            with tempfile.TemporaryDirectory(prefix=".scan-", dir=directory) as scratch:
                scratch = Path(scratch)
                manifest = scratch / "resources.yaml"
                snapshot = Path(cluster_context) / (filename + ".yaml") if cluster_context is not None else None
                if snapshot is not None and snapshot.exists():
                    shutil.copyfile(snapshot, manifest)
                    count = sum(1 for _ in manifest_objects(manifest, project=True))
                else:
                    with manifest.open("w", encoding="utf-8") as out:
                        count = self.list_into(path, out, version.removeprefix("/apis/").removeprefix("/api/"),
                                               kind, documents=True)
                if not count:
                    # Kubescape requires at least one input object. Remove stale results.
                    destination.unlink(missing_ok=True)
                    skipped += 1
                    print(f"Skipping {scope}/{resource}: no eligible resources", flush=True)
                    print(f"Progress [{scope}]: completed={index}/{total}, scanned={scanned}, "
                          f"skipped={skipped}, pending={total - index}", flush=True)
                    continue
                print(f"Resources [{scope}/{resource}]: total={count}, clusterScoped={count}", flush=True)
                self.scan_manifest(manifest, destination, scratch, cache, extra)
            reports.append(destination)
            if completed_directory is not None:
                publish_completed(destination, completed_directory, filename)
            scanned += 1
            print(f"Saved Kubescape results for {count} resources to {destination}", flush=True)
            print(f"Progress [{scope}]: completed={index}/{total}, scanned={scanned}, "
                  f"skipped={skipped}, pending={total - index}", flush=True)
        return reports

    def namespaces(self, directory, labels_directory=None):
        # Stream namespace names from a disk-backed list rather than retaining all.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=directory) as out:
            self.list_into("/api/v1/namespaces", out, "v1", "Namespace")
            out.seek(0)
            for metadata in ijson.items(out.buffer, "items.item.metadata"):
                name = metadata["name"]
                if labels_directory is not None:
                    labels = dict(metadata.get("labels") or {})
                    labels.setdefault("kubernetes.io/metadata.name", name)
                    (Path(labels_directory) / (name + ".json")).write_text(encode(labels))
                yield name


def kubernetes_page_size():
    value = os.environ.get("KUBERNETES_PAGE_SIZE", "100")
    if not value.isdecimal() or int(value) < 1:
        raise ValueError("KUBERNETES_PAGE_SIZE must be a positive integer")
    return int(value)


def namespace_concurrency():
    value = os.environ.get("NAMESPACE_CONCURRENCY", "5")
    if not value.isdecimal() or int(value) < 1:
        raise ValueError("NAMESPACE_CONCURRENCY must be a positive integer")
    return int(value)


def maximum_namespace_concurrency(initial):
    if os.environ.get("AUTO_NAMESPACE_CONCURRENCY", "true").lower() != "true":
        return initial
    value = os.environ.get("MAX_NAMESPACE_CONCURRENCY", str(max(5, initial)))
    if not value.isdecimal() or int(value) < initial:
        raise ValueError("MAX_NAMESPACE_CONCURRENCY must be a positive integer >= NAMESPACE_CONCURRENCY")
    return int(value)


def control_batch_size():
    value = os.environ.get("CONTROL_BATCH_SIZE", "0")
    if not value.isdecimal():
        raise ValueError("CONTROL_BATCH_SIZE must be a nonnegative integer (0 disables batching)")
    return int(value)


def framework_control_ids(cache):
    """Deduplicate overlapping frameworks without dropping any selected controls."""
    controls = set()
    for framework in FRAMEWORKS:
        with (Path(cache) / (framework + ".json")).open("rb") as source:
            ids = [control.get("controlID") for control in ijson.items(source, "controls.item")]
        if not ids or any(not isinstance(cid, str) or not cid.strip() for cid in ids):
            raise ValueError(f"Framework {framework} has missing or invalid control IDs")
        controls.update(ids)
    return sorted(controls)


def scan_with_memory_retries(command, report, scratch, cache, destination):
    """Halve control batches on memory pressure; never partition resource context."""
    controls = framework_control_ids(cache)
    configured_size = control_batch_size()
    ceiling = min(configured_size or len(controls), len(controls))
    state_path = Path(destination).with_name("." + Path(destination).name + ".memory-retry.json")
    allow_combined = configured_size == 0

    def save(in_flight=False, active_width=0, terminal=False, failed_control=None):
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(encode({"batchSize": ceiling, "inFlight": in_flight,
                                     "activeWidth": active_width, "terminal": terminal,
                                     "failedControl": failed_control}))
        os.replace(temporary, state_path)

    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get("terminal"):
            raise ScanMemoryExceeded(f"A single control previously exceeded memory for {destination} "
                                     f"({state.get('failedControl')}); "
                                     f"see {state_path}. No smaller control batch is possible")
        ceiling = min(ceiling, max(1, int(state["batchSize"])))
        if state.get("inFlight"):
            active_width = int(state["activeWidth"])
            if active_width <= 1:
                raise ScanMemoryExceeded(f"A single-control scan was interrupted for {destination}; "
                                         f"see {state_path}. Cannot halve it further")
            ceiling = min(ceiling, max(1, active_width // 2))
            allow_combined = False
            print(f"Memory retry [{destination}]: previous scan interrupted; "
                  f"resuming with at most {ceiling} controls per process", flush=True)
        allow_combined = allow_combined and ceiling == len(controls)

    def attempt(scan_command, selected):
        save(in_flight=True, active_width=len(selected))
        try:
            while True:
                try:
                    run_command(scan_command, check=True)
                    break
                except ScanConcurrencyReduced as error:
                    Path(scan_command[scan_command.index("--output") + 1]).unlink(missing_ok=True)
                    print(f"Memory retry [{destination}]: {error}; keeping the same {len(selected)} controls", flush=True)
        except subprocess.CalledProcessError as error:
            if error.returncode in (-signal.SIGKILL, 128 + signal.SIGKILL):
                raise ScanMemoryExceeded("Kubescape received SIGKILL (possible OOM)") from error
            save()
            raise
        except ScanMemoryExceeded:
            raise
        except Exception:
            save()
            raise
        save()

    def shrink(selected, error):
        nonlocal ceiling
        if len(selected) == 1:
            save(terminal=True, failed_control=selected[0])
            raise ScanMemoryExceeded(f"Control {selected[0]} exceeded memory for {destination}; "
                                     "cannot split below one control; no complete report published") from error
        ceiling = max(1, len(selected) // 2)
        save()
        print(f"Memory retry [{destination}]: {error}; halving {len(selected)} controls "
              f"to at most {ceiling} per process; full resource context retained", flush=True)

    if allow_combined:
        print(f"Progress [controls {destination}]: completed=0/{len(controls)}, "
              f"remaining={len(controls)}, batchSize={len(controls)}, mode=combined", flush=True)
        try:
            attempt(command, controls)
            print(f"Progress [controls {destination}]: completed={len(controls)}/{len(controls)}, "
                  "remaining=0, mode=combined", flush=True)
            return
        except ScanMemoryExceeded as error:
            Path(report).unlink(missing_ok=True)
            shrink(controls, error)

    def batch_reports():
        offset = 0
        while offset < len(controls):
            selected = controls[offset:offset + ceiling]
            batch_report = Path(scratch) / "control-batch.json"
            with tempfile.TemporaryDirectory(prefix="control-cache-", dir=scratch) as batch_cache:
                batch_command = command.copy()
                batch_command[2:4] = ["control", ",".join(selected)]
                batch_command[batch_command.index("--output") + 1] = str(batch_report)
                batch_command[batch_command.index("--cache-dir") + 1] = batch_cache
                print(f"Progress [controls {destination}]: completed={offset}/{len(controls)}, "
                      f"remaining={len(controls) - offset}, batchSize={len(selected)}, "
                      f"controls={','.join(selected)}", flush=True)
                try:
                    attempt(batch_command, selected)
                except ScanMemoryExceeded as error:
                    batch_report.unlink(missing_ok=True)
                    shrink(selected, error)
                    continue
                # The merger ingests each successful batch before advancing this iterator.
                yield batch_report
            batch_report.unlink()
            offset += len(selected)
            print(f"Progress [controls {destination}]: completed={offset}/{len(controls)}, "
                  f"remaining={len(controls) - offset}, batch completed and merged", flush=True)

    # Failed attempts are never merge inputs. Publish only if every control succeeds.
    with closing(batch_reports()) as reports:
        merge_reports(reports, report)


def run_namespaces(namespaces, worker, concurrency, total=None, maximum=None, concurrency_target=None):
    """Bound both active workers and queued futures to the configured limit."""
    namespaces = iter(namespaces)
    maximum = maximum or concurrency
    def submission_limit():
        return min(maximum, max(concurrency, concurrency_target() if concurrency_target else concurrency))
    completed = failed = scheduled = 0
    def log_progress(active):
        if total is not None:
            finished = completed + failed
            print(f"Progress [namespaces]: completed={completed}/{total}, failed={failed}, "
                  f"active={active}, pending={total - scheduled}, remaining={total - finished}, "
                  f"finished={finished}/{total} ({100 * finished / total if total else 100:.1f}%)", flush=True)
    log_progress(0)
    with ThreadPoolExecutor(max_workers=maximum) as pool:
        pending = set()
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < submission_limit():
                try:
                    namespace = next(namespaces)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(pool.submit(worker, namespace))
                scheduled += 1
            log_progress(len(pending))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                if future.result():
                    completed += 1
                else:
                    failed += 1
            log_progress(len(pending))
    return completed, failed


def main(data_dir=None, artifact_dir="/opt/kubescape/artifacts"):
    global SCAN_GOVERNOR, SCAN_MEMORY_BUDGET
    started_at = time.monotonic()
    concurrency = namespace_concurrency()
    maximum = maximum_namespace_concurrency(concurrency)
    SCAN_GOVERNOR = ScanGovernor(maximum)
    SCAN_MEMORY_BUDGET = ScanMemoryBudget(memory_size(os.environ.get("INITIAL_MEMORY_BUDGET", "1Gi")),
                                         os.environ.get("AUTO_GROW_MEMORY", "true").lower() == "true")
    batch_size = control_batch_size()
    kubernetes_page_size()
    print(f"Namespace concurrency: initial={concurrency}, maximum={maximum}; "
          "shared-memory scan scheduling starts at 1", flush=True)
    print(f"Memory budget: autoGrow={SCAN_MEMORY_BUDGET.enabled}, "
          f"initial={SCAN_MEMORY_BUDGET.initial / 1048576:.1f} MiB; "
          "growth is bounded by the configured container limit", flush=True)
    environment = kubescape_environment()
    print(f"Control batch size: {batch_size} (0 = combined frameworks); "
          f"GOMEMLIMIT={environment['GOMEMLIMIT']}; "
          f"GOGC={environment['GOGC']}", flush=True)
    directory = Path(data_dir if data_dir is not None else os.environ.get("OUTPUT_PATH", "/data"))
    directory.mkdir(parents=True, exist_ok=True)
    namespace_failures = NamespaceFailures(directory)
    print(f"Output directory: {directory.resolve()}", flush=True)
    completed_directory = Path(os.environ.get("COMPLETED_REPORTS_PATH") or directory / "completed")
    completed_directory.mkdir(parents=True, exist_ok=True)
    print(f"Completed reports directory: {completed_directory.resolve()}", flush=True)
    # Artifacts and optional configuration are inputs, never final scan outputs.
    with tempfile.TemporaryDirectory(prefix=".policies-", dir=directory) as policies:
        # Keep control artifacts on the shared volume for streaming SaaS uploads.
        cache = directory / "kubescape-cache"
        cache.mkdir(exist_ok=True)
        if os.environ.get("AIRGAPPED", "false").lower() == "true":
            shutil.copytree(artifact_dir, cache, dirs_exist_ok=True)
        else:
            run_command(["kubescape", "download", "artifacts", "--output", str(cache)], check=True)
            run_command(["kubescape", "download", "framework", "clusterscan", "--output",
                            str(cache / "clusterscan.json")], check=True)
        extra = []
        config_url = os.environ.get("CONTROLS_CONFIG_URL", "")
        if config_url:
            config = Path(policies) / "controls.json"
            with urllib.request.urlopen(config_url, timeout=60) as response, config.open("wb") as out:
                shutil.copyfileobj(response, out, length=BLOCK_SIZE)
            extra = ["--controls-config", str(config)]
        cluster_context = None
        if os.environ.get("INCLUDE_CLUSTER_CONTEXT", "false").lower() == "true":
            cluster_context = Path(policies) / "cluster-context"
            cluster_context.mkdir()
        print(f"Cluster context in namespace scans: {cluster_context is not None}", flush=True)
        api = KubernetesAPI()
        all_resources = os.environ.get("COLLECT_ALL_RESOURCES", "false").lower() == "true"
        namespace_resources, cluster_resources = configured_resources(api, all_resources)
        print(f"Collection mode: {'all discoverable' if all_resources else 'selected'}; "
              f"{len(namespace_resources)} namespace types, {len(cluster_resources)} cluster types", flush=True)
        if cluster_context is not None:
            api.snapshot_cluster(cluster_resources, cluster_context)
        labels_directory = Path(policies) / "namespace-labels"
        labels_directory.mkdir()
        def process_namespace(namespace):
            try:
                # API clients and writable caches are private to each worker.
                labels_path = labels_directory / (namespace + ".json")
                labels = json.loads(labels_path.read_text()) if labels_path.exists() else {"kubernetes.io/metadata.name": namespace}
                namespace_reports = KubernetesAPI().scan(namespace_resources, directory / namespace, cache, namespace, extra,
                                                         cluster_context=cluster_context, namespace_labels=labels)
                for report in namespace_reports:
                    publish_completed(report, completed_directory, namespace)
                return True
            except Exception as error:
                namespace_failures.record(namespace, error)
                return False
        # Count and queue names on disk so totals are exact without retaining a namespace list.
        namespace_queue = Path(policies) / "namespaces.txt"
        total_namespaces = 0
        print("Discovering namespaces for progress totals", flush=True)
        with namespace_queue.open("w", encoding="utf-8") as out:
            for namespace in api.namespaces(directory, labels_directory):
                out.write(namespace + "\n")
                total_namespaces += 1
        with namespace_queue.open(encoding="utf-8") as source:
            completed, failed = run_namespaces((line.strip() for line in source), process_namespace,
                                              concurrency, total=total_namespaces, maximum=maximum,
                                              concurrency_target=lambda: SCAN_GOVERNOR.target)
        print(f"Namespace scans finished: {completed} completed, {failed} failed", flush=True)
        # Assess even unused cluster objects after all namespace scans.
        print("Namespace work finished; starting standalone cluster scans", flush=True)
        SCAN_GOVERNOR = ScanGovernor(1)
        api.scan(cluster_resources, directory / "clusterscoped", cache, extra=extra,
                 cluster_context=cluster_context, completed_directory=completed_directory)
        if failed:
            raise RuntimeError(f"{failed} namespace(s) failed; all remaining namespaces were attempted; "
                               f"{namespace_failures.summary()}")
    scans_finished_at = time.monotonic()
    result = directory / "report.json"
    reports = sorted(completed_directory.glob("*-report.json"))
    print(f"Progress [consolidation]: merging {len(reports)} reports into {result}", flush=True)
    merge_started_at = time.monotonic()
    merge_reports(sorted(reports), result)
    finished_at = time.monotonic()
    print("Progress [consolidation]: completed", flush=True)
    print(f"Timing: preparation, collection and scans={scans_finished_at - started_at:.2f}s; "
          f"report merge={finished_at - merge_started_at:.2f}s; "
          f"total={finished_at - started_at:.2f}s "
          f"({(finished_at - started_at) / 60:.2f} minutes)", flush=True)
    publish_scan_status("scan-done", completed_directory)
    print(f"All scans complete; consolidated report saved to {result}", flush=True)


if __name__ == "__main__":
    install_signal_handlers()
    try:
        main()
    except Exception:
        publish_scan_status("scan-failed")
        raise
