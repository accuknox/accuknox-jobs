import base64
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
import importlib.util
import io
import json
import os
import subprocess
from unittest.mock import patch
from pathlib import Path
import ssl
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest

spec = importlib.util.spec_from_file_location("scan_upload", Path(__file__).parents[1] / "scripts/scan-and-upload.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@contextmanager
def server(statuses):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append((dict(self.headers), body))
            status = statuses[min(len(requests)-1, len(statuses)-1)]
            self.send_response(status); self.end_headers()
            self.wfile.write(b'{"detail":"File received successfully"}')
        def log_message(self, *args):
            pass
    instance = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{instance.server_port}/api/v1/artifact/', requests
    finally:
        instance.shutdown(); instance.server_close(); thread.join()


class UploadTests(unittest.TestCase):
    def setup_report(self, directory):
        directory = Path(directory)
        report = directory / 'report.json'
        report.write_text(json.dumps({'results': [{'resourceID': 'r', 'controls': [
            {'controlID': f'C-{i:04d}'} for i in range(601)]}],
            'attributes': None, 'exactNumber': 9007199254740993,
            'summary': {'old': True}, 'accuknox_metadata': {'old': True}}))
        paths = []
        for name in module.FRAMEWORKS:
            path = directory / f'{name}.json'
            path.write_text(json.dumps({'controls': [{'controlID': 'C-0001', 'name': name}]}))
            paths.append(path)
        module.augment_report(report, paths, {'cluster_name': 'test', 'cluster_id': 42, 'label_name': 'label'}, directory)
        return report

    def test_augmentation_preserves_findings_and_deduplicates_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            result = json.loads(self.setup_report(temp).read_text())
            self.assertEqual(len(result['results'][0]['controls']), 601)
            self.assertEqual(result['exactNumber'], 9007199254740993)
            self.assertIsNone(result['attributes'])
            self.assertEqual(result['summary']['controls'], [{'controlID':'C-0001','name':'mitre'}])
            self.assertEqual(result['accuknox_metadata']['cluster_id'], 42)
            self.assertIn('generationTime', result)

    def test_archive_and_upload_match_knoxjobs(self):
        with tempfile.TemporaryDirectory() as temp, server([200]) as (url, requests):
            report = self.setup_report(temp)
            body, content_type = module.prepare_body(report, temp)
            module.upload(body, content_type, url, 'test-token', '10', ssl.create_default_context(), sleep=lambda _:None)
            headers, uploaded = requests[0]
            self.assertEqual(headers['Authorization'], 'Bearer test-token')
            self.assertEqual(headers['Tenant-Id'], '10')
            mime = BytesParser(policy=default).parsebytes(('Content-Type: '+headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+uploaded)
            part = list(mime.iter_parts())[0]
            self.assertEqual(part.get_param('name', header='content-disposition'), 'file')
            self.assertEqual(part.get_filename(), 'report.json.tar.gz')
            with tarfile.open(fileobj=io.BytesIO(part.get_payload(decode=True)),mode='r:gz') as archive:
                self.assertEqual(archive.getnames(), ['report.json'])
                self.assertEqual(json.load(archive.extractfile('report.json')), json.loads(report.read_text()))

    def test_retry_reopens_complete_body(self):
        with tempfile.TemporaryDirectory() as temp, server([500, 200]) as (url, requests):
            body, content_type = module.prepare_body(self.setup_report(temp), temp)
            module.upload(body, content_type, url, 'token', '10', ssl.create_default_context(), sleep=lambda _:None)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0][1], requests[1][1])

    def test_upload_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp, server([403]) as (url, requests):
            body, content_type = module.prepare_body(self.setup_report(temp), temp)
            with self.assertRaisesRegex(RuntimeError,'HTTP 403'):
                module.upload(body, content_type, url, 'token', '10', ssl.create_default_context(), attempts=2, sleep=lambda _:None)
            self.assertEqual(len(requests), 2)

    def test_invalid_json_does_not_replace_original(self):
        with tempfile.TemporaryDirectory() as temp:
            report = self.setup_report(temp)
            (Path(temp) / 'controls.sqlite').unlink()
            report.write_text('{"broken":')
            path = Path(temp)/'controls.json'
            path.write_text('{"controls":[{"controlID":"C-0001"}]}')
            with self.assertRaises(Exception):
                module.augment_report(report,[path],{},temp)
            self.assertEqual(report.read_text(),'{"broken":')

    def test_namespace_pipeline_uploads_sequentially_and_cleans_each_namespace(self):
        with tempfile.TemporaryDirectory() as temp, server([200]) as (url, requests):
            artifacts = Path(temp) / 'artifacts'; artifacts.mkdir()
            for framework in module.FRAMEWORKS:
                (artifacts / (framework+'.json')).write_text('{"controls":[{"controlID":"C-0001"}]}')
            token = Path(temp) / 'AUTH_TOKEN'; token.write_text('test-token')
            data = Path(temp) / 'data'
            calls = []
            def scan(command, check):
                calls.append(command)
                self.assertTrue(check)
                self.assertEqual(command[:4], ['kubescape','scan','framework','allcontrols,clusterscan,nsa,mitre'])
                self.assertNotIn('--include-namespaces', command)
                self.assertEqual(len(requests), len(calls)-1)
                self.assertTrue(Path(command[4]).exists())
                Path(command[command.index('--output')+1]).write_text('{"results":[],"summaryDetails":{"frameworks":[]}}')
            env = {'ARTIFACT_URL':url, 'AUTH_TOKEN_PATH':str(token), 'TENANT_ID':'10',
                   'LABEL_NAME':'label','CLUSTER_NAME':'test','CLUSTER_ID':'42','AIRGAPPED':'true'}
            with patch.dict(os.environ,env,clear=True), patch.object(module.subprocess,'run',side_effect=scan), patch.object(module, 'KubernetesAPI') as api:
                api.return_value.resources.return_value = [('/api/v1', 'pods')]
                api.return_value.namespaces.return_value = iter(['first', 'second'])
                def snapshot(namespace, resources, manifest):
                    self.assertFalse(list(data.glob('scan-upload-*/namespace-*/report.json')))
                    manifest.write_text('---\n{"apiVersion":"v1","kind":"Pod"}\n')
                    return 1
                api.return_value.snapshot.side_effect = snapshot
                module.main(data, artifacts)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(requests), 2)
            self.assertFalse((data/'report.json').exists())
            self.assertFalse(list(data.glob('scan-upload-*')))

    def test_scan_failure_prevents_upload(self):
        with tempfile.TemporaryDirectory() as temp, server([200]) as (url, requests):
            artifacts=Path(temp)/'artifacts'; artifacts.mkdir()
            token=Path(temp)/'AUTH_TOKEN'; token.write_text('test-token')
            env={'ARTIFACT_URL':url,'AUTH_TOKEN_PATH':str(token),'TENANT_ID':'10','LABEL_NAME':'label','AIRGAPPED':'true'}
            def scan(command,check):
                raise subprocess.CalledProcessError(1,command)
            with patch.dict(os.environ,env,clear=True), patch.object(module.subprocess,'run',side_effect=scan), patch.object(module, 'KubernetesAPI') as api:
                api.return_value.resources.return_value = []
                api.return_value.namespaces.return_value = iter(['first', 'second'])
                with self.assertRaisesRegex(RuntimeError, '2 namespace'):
                    module.main(Path(temp)/'data',artifacts)
            self.assertEqual(requests,[])
            self.assertEqual(api.return_value.snapshot.call_count, 2)
            self.assertFalse(list((Path(temp)/'data').glob('scan-upload-*')))

    def test_failed_upload_does_not_stop_next_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp)/'artifacts'; artifacts.mkdir()
            for framework in module.FRAMEWORKS:
                (artifacts/(framework+'.json')).write_text('{"controls":[{"controlID":"C-0001"}]}')
            token = Path(temp)/'AUTH_TOKEN'; token.write_text('token')
            data = Path(temp)/'data'
            env = {'ARTIFACT_URL':'https://example.com/artifact/', 'AUTH_TOKEN_PATH':str(token),
                   'TENANT_ID':'10','LABEL_NAME':'label','AIRGAPPED':'true'}
            def scan(command, check):
                Path(command[command.index('--output')+1]).write_text('{"results":[]}')
            def snapshot(namespace, resources, manifest):
                self.assertFalse(list(data.glob('scan-upload-*/namespace-*/report.json')))
                manifest.write_text('---\n{"kind":"Pod"}\n')
                return 1
            with patch.dict(os.environ,env,clear=True), patch.object(module,'KubernetesAPI') as api, \
                    patch.object(module.subprocess,'run',side_effect=scan), \
                    patch.object(module,'upload',side_effect=[RuntimeError('failed upload'),None]) as upload:
                api.return_value.resources.return_value = []
                api.return_value.namespaces.return_value = iter(['first','second'])
                api.return_value.snapshot.side_effect = snapshot
                with self.assertRaisesRegex(RuntimeError,'1 namespace'):
                    module.main(data,artifacts)
                self.assertEqual(upload.call_count,2)
            self.assertFalse(list(data.glob('scan-upload-*')))

    def test_streamed_snapshot_pagination_and_all_resource_types(self):
        api = object.__new__(module.KubernetesAPI)
        pages = [
            {"metadata":{"continue":"next"}, "items":[{"apiVersion":"v1","kind":"Secret","data":{"password":"abc"}}]},
            {"items":[{"apiVersion":"v1","kind":"Secret","metadata":{"name":"second"}}],"metadata":{}},
            {"items":[{"apiVersion":"rbac.authorization.k8s.io/v1","kind":"Role"}],"metadata":{}}
        ]
        paths = []
        def open_page(path):
            paths.append(path)
            return io.BytesIO(json.dumps(pages.pop(0)).encode())
        with tempfile.TemporaryDirectory() as temp, patch.object(api, 'open', side_effect=open_page):
            manifest = Path(temp)/'ns.yaml'
            count = api.snapshot('ns', [('/api/v1','secrets'),('/apis/rbac.authorization.k8s.io/v1','roles')],manifest)
            docs = [json.loads(line) for line in manifest.read_text().splitlines() if line.startswith('{')]
            self.assertEqual(count, 3)
            self.assertEqual(docs[0]['data']['password'], 'abc')
            self.assertIn('continue=next',paths[1])
            self.assertIn('/namespaces/ns/roles?',paths[2])

    def test_discovery_includes_crds_but_skips_cluster_scope_and_subresources(self):
        api = object.__new__(module.KubernetesAPI)
        def discovery(path):
            if path == '/apis':
                return {'groups':[{'preferredVersion':{'groupVersion':'example.io/v1'}}]}
            return {'resources':[
                {'name':'widgets','namespaced':True,'verbs':['list']},
                {'name':'widgets/status','namespaced':True,'verbs':['list']},
                {'name':'nodes','namespaced':False,'verbs':['list']},
                {'name':'reviews','namespaced':True,'verbs':['create']}]}
        with patch.object(api,'discovery',side_effect=discovery):
            self.assertEqual(list(api.resources()),[('/api/v1','widgets'),('/apis/example.io/v1','widgets')])

    def test_token_tenant_and_configured_fallback(self):
        payload = base64.urlsafe_b64encode(b'{"tenant-id":42}').decode().rstrip('=')
        url, tenant = module.tenant_settings('https://example.com/?tenant_id=', 'header.'+payload+'.signature', '1')
        self.assertEqual(tenant, '42'); self.assertIn('tenant_id=42', url)
        self.assertEqual(module.tenant_settings('https://example.com/', 'not-jwt', '10')[1], '10')
        with self.assertRaises(ValueError):
            module.tenant_settings('https://example.com/', 'not-jwt', '')


if __name__ == '__main__':
    unittest.main()
