#!/usr/bin/env python3
"""Scan frameworks per namespace and cluster, with deferred control batching."""
from contextlib import nullcontext
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import urllib.request


def load_merger(script_dir):
    spec = importlib.util.spec_from_file_location('dump_merger', script_dir / 'scan-control-namespaces.py')
    merger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merger)
    return merger


class MemoryPressure(RuntimeError):
    pass


def memory_usage(pid, cgroup=Path('/sys/fs/cgroup')):
    """Sample RSS and cgroup working memory (excluding reclaimable inactive cache)."""
    rss = 0
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                rss = int(line.split()[1]) * 1024
    except (FileNotFoundError, ProcessLookupError):
        pass
    try:
        maximum = (cgroup / 'memory.max').read_text().strip()
        if maximum != 'max':
            usage = int((cgroup / 'memory.current').read_text())
            stats = dict(line.split() for line in (cgroup / 'memory.stat').read_text().splitlines())
            return max(rss, usage - int(stats.get('inactive_file', 0))), int(maximum)
    except (OSError, ValueError):
        pass
    # cgroup v1, as used by some older Kubernetes nodes.
    try:
        root = cgroup / 'memory'
        maximum = int((root / 'memory.limit_in_bytes').read_text())
        if maximum < 1 << 60:
            usage = int((root / 'memory.usage_in_bytes').read_text())
            stats = dict(line.split() for line in (root / 'memory.stat').read_text().splitlines())
            return max(rss, usage - int(stats.get('total_inactive_file', 0))), maximum
    except (OSError, ValueError):
        pass
    return rss, None


def guarded_scan(command, environment, metric, ceiling):
    peak = 0
    stopped = False
    started = last_log = time.monotonic()
    process = subprocess.Popen(command, env=environment, start_new_session=True)
    try:
        while True:
            usage, limit = memory_usage(process.pid)
            peak = max(peak, usage)
            effective_ceiling = min(ceiling, int(limit * 0.8)) if limit else ceiling
            now = time.monotonic()
            if now - last_log >= 30:
                print(f'Scan running: {int(now - started)}s elapsed, '
                      f'memory {usage // (1024 * 1024)} MiB, peak {peak // (1024 * 1024)} MiB, '
                      f'ceiling {effective_ceiling // (1024 * 1024)} MiB', flush=True)
                last_log = now
            if usage >= effective_ceiling:
                stopped = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        status = process.wait()
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        metric.write_text(json.dumps({'sampled_peak_bytes': peak, 'watchdog_stopped': stopped,
                                      'exit_code': process.returncode}) + '\n')
    if stopped:
        raise MemoryPressure(f'Scan stopped by memory watchdog; current {usage // (1024 * 1024)} MiB, '
                             f'sampled peak {peak // (1024 * 1024)} MiB, '
                             f'effective ceiling {effective_ceiling // (1024 * 1024)} MiB, '
                             f'configured ceiling {ceiling // (1024 * 1024)} MiB, '
                             f'container limit {str(limit // (1024 * 1024)) + " MiB" if limit else "unknown"}')
    if status in (-signal.SIGKILL, 137):
        raise MemoryPressure(f'Scan exited with SIGKILL/137 (possible OOM or external kill); '
                             f'watchdog did not stop it; sampled peak {peak // (1024 * 1024)} MiB')
    if status:
        raise subprocess.CalledProcessError(status, command)
    return peak


def framework_batches_signature(environment):
    return json.loads(environment.get('DUMP_FRAMEWORK_BATCHES',
        '{"mitre":{"initialControls":5,"growthStep":2},"nsa":{"initialControls":20,"growthStep":0}}'))


def resource_stats(path):
    """Count List items without materializing resource objects."""
    import ijson
    with path.open('rb') as source:
        count = sum(1 for prefix, event, _ in ijson.parse(source)
                    if prefix == 'items.item' and event == 'start_map')
    return {'resources': count, 'bytes': path.stat().st_size}


def announce_report(queue, scope, report, report_name=None, depends_on=None):
    """Publish an immutable report before atomically announcing it to the uploader."""
    queue.mkdir(parents=True, exist_ok=True)
    name = scope.replace(':', '-')
    ready = queue / f'{name}.ready.json'
    if ready.exists():
        return
    target = queue / (report_name or f'{name}.json')
    temporary = target.with_name(target.name + '.tmp')
    temporary.unlink(missing_ok=True)
    os.link(report, temporary)
    os.replace(temporary, target)
    digest = hashlib.sha256()
    with target.open('rb') as source:
        for chunk in iter(lambda: source.read(64 * 1024), b''):
            digest.update(chunk)
    announcement = {'scope': scope, 'report': target.name, 'sha256': digest.hexdigest()}
    if depends_on:
        announcement['dependsOn'] = depends_on
    ready_temp = ready.with_suffix('.json.tmp')
    ready_temp.write_text(json.dumps(announcement) + '\n')
    os.replace(ready_temp, ready)
    print(f'Report ready for upload: {scope}: {target}', flush=True)


def upload_acknowledged(queue, scope):
    ready = queue / f'{scope.replace(":", "-")}.ready.json'
    try:
        metadata = json.loads(ready.read_text())
        return ready.with_name(ready.name + '.uploaded').read_text() == metadata['sha256']
    except FileNotFoundError:
        return False


def cleanup_uploaded_scopes(run_dir, work, queue, merger):
    """Remove acknowledged scope files only after their findings are durably merged."""
    database = work / 'final-merge.sqlite'
    if not database.exists():
        return 0
    db = merger.open_database(database)
    try:
        merged = {row[0][len('scope:'):] for row in db.execute(
            "SELECT key FROM state WHERE key LIKE 'scope:%'")}
    finally:
        db.close()
    namespaces = list(dict.fromkeys(n for n in (run_dir / 'namespaces.txt').read_text().splitlines() if n))
    scopes = [(f'namespace:{n}', run_dir / 'reports/namespaces' / n,
               run_dir / f'dumps/dump-{n}.yaml') for n in namespaces]
    scopes.append(('cluster', run_dir / 'reports/cluster', run_dir / 'dumps/dump-cluster-scoped.yaml'))
    uploaded = 0
    for scope, directory, dump in scopes:
        if scope not in merged:
            continue
        ready = queue / f'{scope.replace(":", "-")}.ready.json'
        ack = ready.with_name(ready.name + '.uploaded')
        try:
            metadata = json.loads(ready.read_text())
            acknowledged = ack.read_text() == metadata['sha256']
        except FileNotFoundError:
            continue
        if not acknowledged:
            continue
        if metadata.get('scope') != scope or metadata.get('report') != f'{scope.replace(":", "-")}.json':
            raise ValueError(f'Invalid cleanup announcement for {scope}')
        uploaded += 1
        # Unlink both hard-link names so acknowledged scope reports release space.
        (queue / metadata['report']).unlink(missing_ok=True)
        if directory.exists():
            shutil.rmtree(directory)
            print(f'Cleaned uploaded scan files: {scope}', flush=True)
        if scope != 'cluster' or len(merged) == len(scopes):
            if dump.exists():
                input_file = work / 'input' / ('cluster.yaml' if scope == 'cluster' else 'namespace.yaml')
                if input_file.exists() and os.path.samefile(dump, input_file):
                    input_file.unlink()
                dump.unlink()
    return uploaded


def scan_batches(run_dir, work, options, environment, frameworks, merger, run=guarded_scan):
    """Save combined framework reports per scope, then merge all completed reports."""
    input_dir = work / 'input'
    input_dir.mkdir(exist_ok=True)
    frameworks = list(dict.fromkeys(frameworks))
    namespaces = list(dict.fromkeys(n for n in (run_dir / 'namespaces.txt').read_text().splitlines() if n))
    # Paths separate the cluster scope from any namespace named "cluster".
    scopes = [(f'namespace:{n}', run_dir / 'reports/namespaces' / n) for n in namespaces]
    scopes.append(('cluster', run_dir / 'reports/cluster'))
    tasks = [(scope, framework, directory / 'frameworks' / framework)
             for scope, directory in scopes for framework in frameworks]
    ceiling = int(environment.get('DUMP_MEMORY_CEILING_MIB', '800')) * 1024 * 1024
    if ceiling <= 0:
        raise ValueError('Memory ceiling must be positive')
    max_resources = int(environment.get('DUMP_FULL_SCAN_MAX_RESOURCES', '200'))
    max_bytes = int(environment.get('DUMP_FULL_SCAN_MAX_BYTES', str(2 * 1024 * 1024)))
    initial_batch = int(environment.get('DUMP_BATCH_CONTROLS', '8'))
    maximum_batch = int(environment.get('DUMP_BATCH_MAX_CONTROLS', '0'))
    if maximum_batch < 0:
        raise ValueError('Maximum batch controls must be nonnegative')
    if max_resources < 0 or max_bytes < 0 or initial_batch < 1:
        raise ValueError('Invalid preflight scan thresholds')
    framework_batches = json.loads(environment.get('DUMP_FRAMEWORK_BATCHES',
        '{"mitre":{"initialControls":5,"growthStep":2},"nsa":{"initialControls":20,"growthStep":0}}'))
    if not isinstance(framework_batches, dict):
        raise ValueError('DUMP_FRAMEWORK_BATCHES must be an object')
    for name, settings in framework_batches.items():
        if not isinstance(settings, dict) or any(type(settings.get(key, default)) is not int
                for key, default in [('initialControls', initial_batch), ('growthStep', 2)]):
            raise ValueError(f'Invalid batch settings for framework {name}')
        if settings.get('initialControls', initial_batch) < 1 or settings.get('growthStep', 2) < 0:
            raise ValueError(f'Invalid batch settings for framework {name}')
    tuning_path = run_dir / 'framework-batch-tuning.json'
    tuning = json.loads(tuning_path.read_text()) if tuning_path.exists() else {}

    def save_tuning():
        temporary = tuning_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(tuning, indent=2) + '\n')
        os.replace(temporary, tuning_path)

    final_database = work / 'final-merge.sqlite'
    db = merger.open_database(final_database)
    try:
        merged_scopes = {row[0][len('scope:'):] for row in db.execute(
            "SELECT key FROM state WHERE key LIKE 'scope:%'")}
    finally:
        db.close()
    cluster_dump = run_dir / 'dumps/dump-cluster-scoped.yaml'
    cluster_stats = resource_stats(cluster_dump) if cluster_dump.exists() else {'resources': 0, 'bytes': 0}
    if not cluster_dump.exists() and len(merged_scopes) != len(scopes):
        raise ValueError('Cluster dump is missing while scans are pending')
    decisions = {}
    for scope, _ in scopes:
        stats = dict(cluster_stats)
        if scope.startswith('namespace:') and scope not in merged_scopes:
            own = resource_stats(run_dir / f'dumps/dump-{scope.split(":", 1)[1]}.yaml')
            stats = {key: stats[key] + own[key] for key in stats}
        stats['mode'] = 'batch' if stats['resources'] > max_resources or stats['bytes'] > max_bytes else 'full'
        decisions[scope] = stats
    decision_path = run_dir / 'scan-decisions.json'
    if decision_path.exists():
        previous = json.loads(decision_path.read_text())
        for scope in decisions:
            if previous.get(scope, {}).get('memory_pressure'):
                decisions[scope]['mode'] = 'batch'
                decisions[scope]['memory_pressure'] = True
    decision_path.write_text(json.dumps(decisions, indent=2) + '\n')
    report = work / 'batch.json'
    scan_peak = 0
    scans = 0

    def open_scope(directory):
        directory.mkdir(parents=True, exist_ok=True)
        db = merger.open_database(directory / 'results.sqlite')
        db.execute('CREATE TABLE IF NOT EXISTS completed_controls(id TEXT PRIMARY KEY)')
        db.execute('CREATE TABLE IF NOT EXISTS scan_settings(name TEXT PRIMARY KEY, value INTEGER)')
        return db

    def has_state(db, key):
        return db.execute('SELECT 1 FROM state WHERE key=?', (key,)).fetchone() is not None

    def select_input(scope):
        for name in ('namespace.yaml', 'cluster.yaml'):
            (input_dir / name).unlink(missing_ok=True)
        os.link(run_dir / 'dumps/dump-cluster-scoped.yaml', input_dir / 'cluster.yaml')
        if scope.startswith('namespace:'):
            os.link(run_dir / f'dumps/dump-{scope.split(":", 1)[1]}.yaml', input_dir / 'namespace.yaml')

    def progress(scope):
        completed = queued = 0
        for task_scope, _, directory in tasks:
            if task_scope in merged_scopes:
                completed += 1
                continue
            db = open_scope(directory)
            try:
                completed += has_state(db, 'complete')
                queued += has_state(db, 'deferred') and not has_state(db, 'complete')
            finally:
                db.close()
        status = {'scope': scope, 'frameworks': frameworks, 'completed_scopes': completed,
                  'remaining_scopes': len(tasks) - completed, 'queued_scopes': queued,
                  'total_scopes': len(tasks)}
        temporary = run_dir / 'progress.json.tmp'
        temporary.write_text(json.dumps(status) + '\n')
        os.replace(temporary, run_dir / 'progress.json')
        print(f'Progress: {scope}: {completed}/{len(tasks)} namespace/framework scans completed, {queued} queued', flush=True)

    def scan(scope, mode, selection):
        nonlocal scan_peak, scans
        if environment.get('REPORT_UPLOAD_DIR'):
            cleanup_uploaded_scopes(run_dir, work, Path(environment['REPORT_UPLOAD_DIR']), merger)
        report.unlink(missing_ok=True)
        command = ['kubescape', 'scan', mode, selection, str(input_dir), *options, '--output', str(report)]
        metric = run_dir / f'metrics/scan-{scope.replace(":", "-")}-{time.time_ns()}.json'
        try:
            peak = run(command, environment, metric, ceiling)
        except BaseException:
            report.unlink(missing_ok=True)
            raise
        scan_peak = max(scan_peak, peak)
        scans += 1
        return peak

    def label_for(scope):
        return f'namespace {scope.split(":", 1)[1]}' if scope.startswith('namespace:') else 'cluster-scoped resources'

    def publish_scope_if_complete(scope):
        directory = dict(scopes)[scope]
        queue_name = environment.get('REPORT_UPLOAD_DIR', '')
        if scope in merged_scopes:
            if queue_name and not (Path(queue_name) / f'{scope.replace(":", "-")}.ready.json').exists():
                announce_report(Path(queue_name), scope, directory / 'report.json')
            return True
        for framework in frameworks:
            db = open_scope(directory / 'frameworks' / framework)
            try:
                if not has_state(db, 'complete'):
                    return False
                merger.publish_report(db, directory / 'frameworks' / framework / 'report.json')
            finally:
                db.close()
        scope_database = directory / 'merged.sqlite'
        scope_database.unlink(missing_ok=True)
        db = merger.open_database(scope_database)
        try:
            for framework in frameworks:
                merger.ingest(db, directory / 'frameworks' / framework / 'report.json')
            merger.publish_report(db, directory / 'report.json')
        finally:
            db.close()
        db = merger.open_database(final_database)
        try:
            merger.ingest(db, directory / 'report.json', commit=False)
            db.execute('INSERT INTO state VALUES (?)', ('scope:' + scope,))
            db.commit()
        finally:
            db.close()
        merged_scopes.add(scope)
        if queue_name:
            announce_report(Path(queue_name), scope, directory / 'report.json')
            cleanup_uploaded_scopes(run_dir, work, Path(queue_name), merger)
        return True

    def commit_result(directory, controls=None, settings=None):
        db = open_scope(directory)
        try:
            merger.ingest(db, report, commit=False)
            if controls is None:
                db.execute("INSERT OR IGNORE INTO state VALUES ('complete')")
            else:
                db.executemany('INSERT INTO completed_controls VALUES (?)', ((c,) for c in controls))
            if settings is not None:
                db.executemany('INSERT OR REPLACE INTO scan_settings VALUES (?, ?)', settings)
            db.commit()
        finally:
            db.close()
            report.unlink(missing_ok=True)
        gc.collect()

    def batch_scan(scope, framework, directory):
        db = open_scope(directory)
        try:
            db.execute('DELETE FROM scan_controls')
            merger.add_controls(db, [Path(environment['DUMP_ARTIFACT_CACHE']) / f'{framework}.json'])
            controls = [row[0] for row in db.execute('SELECT id FROM scan_controls ORDER BY id')]
            done = {row[0] for row in db.execute('SELECT id FROM completed_controls')}
            cooldown_row = db.execute("SELECT value FROM scan_settings WHERE name='growth-cooldown'").fetchone()
            saved_size = db.execute("SELECT value FROM scan_settings WHERE name='batch-size'").fetchone()
            db.execute("INSERT OR IGNORE INTO state VALUES ('deferred')")
            db.commit()
        finally:
            db.close()
        if not controls:
            raise ValueError(f'No controls in framework {framework}')
        pending = [control for control in controls if control not in done]
        settings = framework_batches.get(framework, {})
        start = settings.get('initialControls', initial_batch)
        step = settings.get('growthStep') # Missing: retain doubling for other frameworks.
        learned = tuning.get(framework, {})
        # Learned pressure sizes are starting points, never permanent hard caps.
        legacy_bound = learned.pop('upper_bound', None)
        cap = maximum_batch or len(controls)
        size = min(cap, saved_size[0] if saved_size else learned.get('confirmed_size', start))
        cooldown = cooldown_row[0] if cooldown_row else learned.get('cooldown', 0)
        if legacy_bound is not None:
            cooldown = max(cooldown, 2)
            save_tuning()
        print(f'Batch sizing {label_for(scope)}, framework {framework}: starting {size}, '
              f'learned size {learned.get("confirmed_size", "none")}, cap {cap}', flush=True)
        _, container_limit = memory_usage(os.getpid())
        effective_ceiling = min(ceiling, int(container_limit * 0.8)) if container_limit else ceiling
        select_input(scope)
        while pending:
            batch = pending[:size]
            print(f'=== Revisiting {label_for(scope)}, framework {framework}: '
                  f'{len(batch)} controls, {len(pending)} remaining ===', flush=True)
            try:
                peak = scan(scope, 'control', ','.join(batch))
            except MemoryPressure as error:
                if len(batch) == 1:
                    raise MemoryPressure(f'Control {batch[0]}, framework {framework}, in {label_for(scope)} '
                                         'exceeds the memory budget even alone; increase scanner memory.') from error
                reduced = max(1, len(batch) // 2)
                size = reduced
                cooldown = 2
                learned = tuning.setdefault(framework, {})
                learned['confirmed_size'] = min(learned.get('confirmed_size', size), size)
                learned['cooldown'] = cooldown
                save_tuning()
                print(f'Memory pressure in {label_for(scope)}, framework {framework}: '
                      f'reducing batch {len(batch)} -> {size} controls; reason: {error}', flush=True)
                db = open_scope(directory)
                try:
                    db.execute("INSERT OR REPLACE INTO scan_settings VALUES ('batch-size', ?)", (size,))
                    db.execute("INSERT OR REPLACE INTO scan_settings VALUES ('growth-cooldown', ?)", (cooldown,))
                    db.commit()
                finally:
                    db.close()
                continue
            previous_size = size
            reason = 'holding size'
            if peak < effective_ceiling * 0.85:
                if cooldown:
                    cooldown -= 1
                if cooldown == 0:
                    size = min(cap, min(size + step, size * 2) if step is not None else size * 2)
                    reason = ('low memory: growing' if size > previous_size else
                              'growth disabled by growthStep=0' if step == 0 else
                              'holding configured maximum size')
                else:
                    reason = 'low memory: waiting for another recovery success'
            elif peak >= effective_ceiling * 0.9:
                size = max(1, len(batch) // 2)
                cooldown = 2
                reason = 'near memory ceiling: shrinking'
            else:
                cooldown = 2
            commit_result(directory, batch, [('batch-size', size), ('growth-cooldown', cooldown)])
            learned = tuning.setdefault(framework, {})
            if len(batch) == previous_size:
                # Save measured successful sizes, never an untried growth proposal or short tail.
                learned['confirmed_size'] = min(len(batch), size) if size < previous_size else len(batch)
            learned['cooldown'] = cooldown
            save_tuning()
            print(f'Completed {label_for(scope)}, framework {framework}: {len(batch)} controls, '
                  f'peak {peak // (1024 * 1024)} MiB; {reason}, size {previous_size} -> {size}; '
                  f'next batch {min(size, len(pending) - len(batch))} controls', flush=True)
            del pending[:len(batch)]
        db = open_scope(directory)
        try:
            db.execute("INSERT OR IGNORE INTO state VALUES ('complete')")
            db.commit()
        finally:
            db.close()
        publish_scope_if_complete(scope)
        progress(scope)


    try:
        for scope, framework, directory in tasks:
            if scope in merged_scopes:
                continue
            db = open_scope(directory)
            try:
                complete = has_state(db, 'complete')
                deferred = has_state(db, 'deferred')
            finally:
                db.close()
            if complete or deferred:
                continue
            decision = decisions[scope]
            print(f'Preflight {label_for(scope)}, framework {framework}: '
                  f'{decision["resources"]} resources, {decision["bytes"]} bytes; '
                  f'{decision["mode"]} scan', flush=True)
            if decision['mode'] == 'batch':
                batch_scan(scope, framework, directory)
                continue
            select_input(scope)
            print(f'=== Scanning {label_for(scope)}, framework {framework} ===', flush=True)
            try:
                scan(scope, 'framework', framework)
            except MemoryPressure as error:
                db = open_scope(directory)
                try:
                    db.execute("INSERT OR IGNORE INTO state VALUES ('deferred')")
                    db.commit()
                finally:
                    db.close()
                # Avoid another whole-framework attempt for this scope.
                decisions[scope]['mode'] = 'batch'
                decisions[scope]['memory_pressure'] = True
                (run_dir / 'scan-decisions.json').write_text(json.dumps(decisions, indent=2) + '\n')
                print(f'Queued {label_for(scope)}, framework {framework} after memory pressure; '
                      f'reason: {error}', flush=True)
                progress(scope)
                continue
            commit_result(directory)
            publish_scope_if_complete(scope)
            progress(scope)
        for scope, framework, directory in tasks:
            if scope in merged_scopes:
                continue
            db = open_scope(directory)
            try:
                queued = has_state(db, 'deferred') and not has_state(db, 'complete')
            finally:
                db.close()
            if queued:
                batch_scan(scope, framework, directory)
        for scope, _ in scopes:
            if not publish_scope_if_complete(scope):
                raise ValueError(f'Incomplete scan: {scope}')
        # All findings have been ingested exactly once as scopes completed.
        db = merger.open_database(final_database)
        try:
            merger.publish_report(db, work / 'report.json')
        finally:
            db.close()
        progress('finished')
    finally:
        (run_dir / 'memory-summary.txt').write_text(
            f'dump_peak_rss_kib={(run_dir / "metrics/dump-peak.rss-kib").read_text().strip()}\n'
            f'successful_scan_sampled_peak_bytes={scan_peak}\ncompleted_scans_this_attempt={scans}\n'
            'Samples use cgroup working memory when available, otherwise process RSS. Failed metrics are retained.\n')


def main(data=Path('/data'), artifacts=Path('/opt/kubescape/artifacts')):
    data.mkdir(parents=True, exist_ok=True)
    persistent_work = data / '.namespace-dump-scan'
    persistent_work.mkdir(mode=0o700, exist_ok=True)
    resuming = (persistent_work / 'dump-run.txt').exists()
    cache = data / 'kubescape-cache'
    if not resuming:
        shutil.copytree(artifacts, cache, dirs_exist_ok=True)
        if os.environ.get('AIRGAPPED', 'false').lower() != 'true':
            subprocess.run(['kubescape', 'download', 'artifacts', '--output', str(cache)], check=True)

    script_dir = Path(__file__).resolve().parent
    names = json.loads(os.environ.get('SCAN_NAMESPACES', '[]'))
    if not isinstance(names, list):
        raise ValueError('SCAN_NAMESPACES must be a JSON array')
    frameworks = json.loads(os.environ.get('DUMP_SCAN_FRAMEWORKS', '["mitre","nsa"]'))
    if not isinstance(frameworks, list) or not frameworks or any(
            not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', name)
            for name in frameworks):
        raise ValueError('DUMP_SCAN_FRAMEWORKS must be a nonempty JSON array of framework names')
    environment = dict(os.environ)
    environment.setdefault('GOMEMLIMIT', '500MiB')
    environment.setdefault('GOGC', '50')
    environment['DUMP_ARTIFACT_CACHE'] = str(cache)
    merger = load_merger(script_dir)
    # Preserve snapshots and successful checkpoints across init-container restarts.
    with nullcontext(persistent_work) as temporary:
        work = Path(temporary)
        signature = {'mode': 'preflight-framework-per-scope-v1', 'namespaces': names, 'frameworks': frameworks,
                     'cluster': os.environ.get('CLUSTER_NAME', ''),
                     'config': os.environ.get('CONTROLS_CONFIG_URL', ''),
                     'full_max_resources': environment.get('DUMP_FULL_SCAN_MAX_RESOURCES', '200'),
                     'full_max_bytes': environment.get('DUMP_FULL_SCAN_MAX_BYTES', '2097152'),
                     'batch_controls': environment.get('DUMP_BATCH_CONTROLS', '8'),
                     'batch_max_controls': environment.get('DUMP_BATCH_MAX_CONTROLS', '0'),
                     'framework_batches': framework_batches_signature(environment),
                     'upload_dir': environment.get('REPORT_UPLOAD_DIR', '')}
        plan = work / 'plan.json'
        if resuming and json.loads(plan.read_text()) != signature:
            raise ValueError('Dump scan configuration changed during resume; start a fresh pod')
        if not resuming:
            plan.write_text(json.dumps(signature))
        if not names and not resuming:
            discovery = work / 'discovered-namespaces.txt'
            with discovery.open('w') as out:
                subprocess.run(['kubectl', 'get', 'ns', '-o',
                                'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}'],
                               check=True, stdout=out)
            names = discovery.read_text().splitlines()
        namespace_file = work / 'namespaces.txt'
        count = 0
        with (namespace_file.open('w') if not resuming else nullcontext(None)) as out:
            for name in names:
                if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', name):
                    raise ValueError(f'Invalid namespace name: {name!r}')
                if name != 'openshift-ovn-kubernetes' and out is not None:
                    out.write(name + '\n')
                    count += 1
        if not count and not resuming:
            raise ValueError('No namespaces available to scan')
        report = work / 'report.json'
        options = ['--format', 'json', '--format-version', 'v2', '--enable-streaming',
                   '--cache-dir', str(cache), '--use-artifacts-from', str(cache),
                   '--cluster-name', os.environ.get('CLUSTER_NAME', '')]
        url = os.environ.get('CONTROLS_CONFIG_URL', '')
        if url:
            config = work / 'controls-config.json'
            if not resuming:
                with urllib.request.urlopen(url, timeout=60) as response, config.open('wb') as out:
                    shutil.copyfileobj(response, out, length=64 * 1024)
            options += ['--controls-config', str(config)]
        run_file = work / 'dump-run.txt'
        if not resuming:
            subprocess.run(['bash', str(script_dir / 'scan-per-namespace.sh'), str(data / 'namespace-dumps')],
                           check=True, env=dict(environment, NAMESPACE_FILE=str(namespace_file),
                                                DUMP_ONLY='true', DUMP_RUN_FILE=str(run_file)))
        scan_batches(Path(run_file.read_text().strip()), work, options, environment, frameworks, merger)
        if not report.is_file() or report.stat().st_size == 0:
            raise ValueError('Kubescape did not produce a report')
        os.replace(report, data / 'report.json')
        queue_name = environment.get('REPORT_UPLOAD_DIR', '')
        if queue_name:
            queue = Path(queue_name)
            expected = [f'namespace-{name}.ready.json' for name in dict.fromkeys(namespace_file.read_text().splitlines()) if name]
            expected.append('cluster.ready.json')
            announce_report(queue, 'consolidated', data / 'report.json',
                            report_name='report.json', depends_on=list(expected))
            scope_count = len(expected)
            expected.append('consolidated.ready.json')
            completion = queue / 'scan-complete.json.tmp'
            completion.write_text(json.dumps({'reports': expected}) + '\n')
            os.replace(completion, queue / 'scan-complete.json')
            print('Scanning finished; waiting for successful uploads before final file cleanup', flush=True)
            run_dir = Path(run_file.read_text().strip())
            while (cleanup_uploaded_scopes(run_dir, work, queue, merger) < scope_count
                   or not upload_acknowledged(queue, 'consolidated')):
                time.sleep(2)
            (queue / 'report.json').unlink(missing_ok=True)
            print('All scope reports and the consolidated report uploaded; scan files cleaned', flush=True)
    shutil.rmtree(persistent_work)


if __name__ == '__main__':
    main()
