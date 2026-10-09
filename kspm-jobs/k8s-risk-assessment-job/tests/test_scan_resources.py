import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scanner', Path(__file__).parents[1]/'scripts/scan-resources.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def obj(kind, name, namespace=None, **fields):
    metadata = {'name':name,'uid':name+'-uid'}
    if namespace:
        metadata['namespace'] = namespace
    return dict(apiVersion='v1',kind=kind,metadata=metadata,**fields)


def manifest(path, objects):
    with Path(path).open('w') as out:
        for item in objects:
            m.write_object(out,item)


class ResourceTests(unittest.TestCase):
    def test_filters_only_orphan_pods_and_non_cronjob_jobs(self):
        self.assertTrue(m.selected_object('pods',{'metadata':{}}))
        self.assertFalse(m.selected_object('pods',{'metadata':{'ownerReferences':[{'kind':'ReplicaSet'}]}}))
        self.assertFalse(m.selected_object('jobs',{'metadata':{'ownerReferences':[{'kind':'CronJob'}]}}))
        self.assertTrue(m.selected_object('jobs',{'metadata':{'ownerReferences':[{'kind':'Other'}]}}))
        self.assertTrue(m.selected_object('cronjobs',{'metadata':{}}))
        self.assertNotIn(('', 'secrets'),m.NAMESPACED)
        self.assertNotIn(('apps','replicasets'),m.NAMESPACED)

    def test_pagination_filters_objects_and_adds_typemeta(self):
        api = object.__new__(m.KubernetesAPI)
        pages = [{'metadata':{'continue':'next'},'items':[
            {'metadata':{'name':'orphan','namespace':'ns'}},
            {'metadata':{'name':'owned','ownerReferences':[{'kind':'Job'}]}}]},
            {'metadata':{},'items':[{'metadata':{'name':'second','namespace':'ns'}}]}]
        paths=[]
        def open_page(path):
            paths.append(path)
            return io.BytesIO(json.dumps(pages.pop(0)).encode())
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'SCAN_DATA_DIR':temp}), patch.object(api,'open',side_effect=open_page):
            out = io.StringIO()
            self.assertEqual(api.list_into('/api/v1/namespaces/ns/pods',out,'v1','Pod','pods'),2)
            docs=[json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{')]
            self.assertEqual([d['metadata']['name'] for d in docs],['orphan','second'])
            self.assertEqual(docs[0]['kind'],'Pod')
            self.assertEqual(docs[0]['apiVersion'],'v1')
            self.assertIn('continue=next',paths[1])

    def test_shared_context_preserves_rbac_webhook_and_namespace_references(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            role=obj('ClusterRole','reader',rules=[{'resources':['pods'],'verbs':['get']}])
            binding=obj('RoleBinding','reader-binding','ns',roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'reader'},subjects=[{'kind':'ServiceAccount','name':'app','namespace':'ns'}])
            service=obj('Service','admission','ns',spec={'selector':{'app':'admission'}})
            account=obj('ServiceAccount','app','ns')
            webhook=obj('ValidatingWebhookConfiguration','validation',webhooks=[{'clientConfig':{'service':{'namespace':'ns','name':'admission'}}}])
            namespace=obj('Namespace','ns',spec={})
            local=temp/'local.yaml';shared=temp/'shared.yaml';combined=temp/'combined.yaml'
            manifest(local,[binding,service,account])
            manifest(shared,[role,namespace,webhook,service,account])
            self.assertEqual(m.combine_manifests([local,shared],combined),6)
            docs=list(m.documents(combined))
            self.assertIn(binding,docs)
            self.assertIn(role,docs)
            self.assertIn(webhook,docs)
            self.assertIn(namespace,docs)
            self.assertEqual(sum(d['kind']=='ServiceAccount' for d in docs),1)
            self.assertFalse(Path(str(combined)+'.sqlite').exists())

    def test_cluster_references_resolve_serviceaccounts_and_services(self):
        api=object.__new__(m.KubernetesAPI)
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);cluster=temp/'cluster.yaml';context=temp/'context.yaml'
            manifest(cluster,[obj('ClusterRoleBinding','binding',subjects=[{'kind':'ServiceAccount','namespace':'other','name':'app'}]),
                              obj('MutatingWebhookConfiguration','hook',webhooks=[{'clientConfig':{'service':{'namespace':'other','name':'admission'}}}])])
            paths=[]
            def opened(path):
                paths.append(path)
                return io.BytesIO(json.dumps(obj('ServiceAccount' if path.endswith('/app') else 'Service',path.rsplit('/',1)[1],'other')).encode())
            with patch.object(api,'open',side_effect=opened):
                api.referenced_context(cluster,context)
            self.assertEqual(len(paths),2)
            self.assertEqual({d['kind'] for d in m.documents(context)},{'Service','ServiceAccount'})

    def test_pipeline_writes_namespace_and_cluster_reports_and_keeps_context(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);data=temp/'data';(data/'config').mkdir(parents=True)
            (data/'config/uploader.json').write_text('{"jobs":{"authTokenFile":"/secrets/tokens/AUTH_TOKEN"}}')
            artifacts=temp/'artifacts';artifacts.mkdir()
            cluster_objects=[obj('Namespace','first'),obj('Namespace','second'),obj('ClusterRole','reader')]
            scans=[]
            def snapshot(namespace, resources, output):
                manifest(output,cluster_objects if namespace is None else [obj('RoleBinding','binding',namespace,roleRef={'kind':'ClusterRole','name':'reader'})])
            def references(cluster,output):
                manifest(output,[])
            def scan(source,report,cache,scratch,extra):
                docs=list(m.documents(source));scans.append(docs)
                self.assertTrue(any(d['kind']=='ClusterRole' for d in docs))
                report.write_text(json.dumps({'resources':docs}))
            with patch.dict(os.environ,{'AIRGAPPED':'true','NAMESPACE_CONCURRENCY':'2'}),patch.object(m,'KubernetesAPI') as api,patch.object(m,'scan_manifest',side_effect=scan):
                api.return_value.resources.return_value=[]
                api.return_value.snapshot.side_effect=snapshot
                api.return_value.referenced_context.side_effect=references
                m.main(data,artifacts)
            self.assertEqual(len(scans),3)
            for name in ('first','second','cluster.resources'):
                self.assertTrue((data/(name+'.json')).exists())
                conf=json.loads((data/'upload-configs'/(name+'.json')).read_text())
                self.assertEqual(conf['jobs']['reportFile'],str(data/(name+'.json')))
            self.assertFalse(list(data.glob('resource-scans-*')))
            self.assertFalse((data/'scan-failures.txt').exists())

    def test_scan_failure_still_hands_successful_reports_to_uploader(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);data=temp/'data';(data/'config').mkdir(parents=True)
            (data/'config/uploader.json').write_text('{"jobs":{}}')
            artifacts=temp/'artifacts';artifacts.mkdir()
            def snapshot(namespace,resources,output):
                manifest(output,[obj('Namespace','first'),obj('Namespace','second')] if namespace is None else [obj('ConfigMap','cm',namespace)])
            def scan(source,report,cache,scratch,extra):
                if source.name=='first.manifest.yaml':
                    raise RuntimeError('scan failed')
                report.write_text('{"results":[]}')
            with patch.dict(os.environ,{'AIRGAPPED':'true','NAMESPACE_CONCURRENCY':'1'}),patch.object(m,'KubernetesAPI') as api,patch.object(m,'scan_manifest',side_effect=scan):
                api.return_value.resources.return_value=[]
                api.return_value.snapshot.side_effect=snapshot
                api.return_value.referenced_context.side_effect=lambda cluster,output:manifest(output,[])
                m.main(data,artifacts)
            self.assertFalse((data/'first.json').exists())
            self.assertTrue((data/'second.json').exists())
            self.assertTrue((data/'scan-failures.txt').exists())

    def test_uploader_continues_after_failure_and_deletes_only_successful_report(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);(temp/'upload-configs').mkdir()
            for name in ('first','second'):
                (temp/(name+'.json')).write_text('{}')
                (temp/'upload-configs'/(name+'.json')).write_text('{}')
            binary=temp/'knoxjobs'
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$2" >> "$SCAN_DATA_DIR/calls"\ncase "$2" in *first.json) exit 1;; esac\nexit 0\n')
            binary.chmod(0o700)
            env=dict(os.environ,SCAN_DATA_DIR=str(temp),KNOXJOBS_BINARY=str(binary))
            result=subprocess.run(['/bin/sh',str(Path(__file__).parents[1]/'scripts/upload-reports.sh')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(len((temp/'calls').read_text().splitlines()),2)
            self.assertTrue((temp/'first.json').exists())
            self.assertFalse((temp/'second.json').exists())
            self.assertIn('retaining report and continuing',result.stdout)


if __name__=='__main__':
    unittest.main()
