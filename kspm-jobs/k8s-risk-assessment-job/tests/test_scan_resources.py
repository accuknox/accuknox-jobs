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

    def test_namespace_scans_then_download_scan_and_report_each_cluster_type(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);data=temp/'data';(data/'config').mkdir(parents=True)
            (data/'config/uploader.json').write_text('{"jobs":{"authTokenFile":"/secrets/tokens/AUTH_TOKEN"}}')
            artifacts=temp/'artifacts';artifacts.mkdir()
            events=[]
            cluster_resources=[('/apis/rbac.authorization.k8s.io/v1','clusterroles','ClusterRole',False),
                               ('/apis/rbac.authorization.k8s.io/v1','clusterrolebindings','ClusterRoleBinding',False),
                               ('/api/v1','namespaces','Namespace',False),
                               ('/apis/admissionregistration.k8s.io/v1','validatingwebhookconfigurations','ValidatingWebhookConfiguration',False),
                               ('/apis/admissionregistration.k8s.io/v1','mutatingwebhookconfigurations','MutatingWebhookConfiguration',False)]
            def snapshot(namespace, resources, output):
                if namespace is None:
                    self.assertEqual(len(resources),1)
                    kind=resources[0][2]
                    if events:
                        previous=events[-1][1].lower()
                        self.assertTrue((data/(previous+'.json')).exists())
                    events.append(('download',kind))
                    manifest(output,[obj(kind,'example')])
                else:
                    manifest(output,[obj('RoleBinding','binding',namespace,roleRef={'kind':'ClusterRole','name':'reader'})])
                return 1
            def scan(source,report,cache,scratch,extra,concurrent_scans=1):
                docs=list(m.documents(source))
                kind=docs[0]['kind']
                if kind!='RoleBinding':
                    self.assertTrue((data/'first.json').exists())
                    self.assertTrue((data/'second.json').exists())
                    events.append(('scan',kind))
                    self.assertTrue(all('namespace' not in d['metadata'] for d in docs))
                self.assertTrue(all(d['kind']==kind for d in docs))
                report.write_text(json.dumps({'resources':docs}))
            with patch.dict(os.environ,{'AIRGAPPED':'true','NAMESPACE_CONCURRENCY':'2','INCLUDE_CLUSTER_SCOPED':'true'}),patch.object(m,'KubernetesAPI') as api,patch.object(m,'scan_manifest',side_effect=scan):
                api.return_value.resources.return_value=[('/api/v1','configmaps','ConfigMap',True)]+cluster_resources
                api.return_value.namespaces.return_value=iter(['first','second'])
                api.return_value.snapshot.side_effect=snapshot
                m.main(data,artifacts)
            self.assertEqual(events,[('download','ClusterRole'),('scan','ClusterRole'),
                                     ('download','ClusterRoleBinding'),('scan','ClusterRoleBinding'),
                                     ('download','ValidatingWebhookConfiguration'),('scan','ValidatingWebhookConfiguration'),
                                     ('download','MutatingWebhookConfiguration'),('scan','MutatingWebhookConfiguration')])
            for name in ('first','second','clusterrole','clusterrolebinding',
                         'validatingwebhookconfiguration','mutatingwebhookconfiguration'):
                self.assertTrue((data/(name+'.json')).exists())
                conf=json.loads((data/'upload-configs'/(name+'.json')).read_text())
                self.assertEqual(conf['jobs']['reportFile'],str(data/(name+'.json')))
            self.assertFalse((data/'cluster.resources.json').exists())
            self.assertFalse((data/'namespace.json').exists())
            self.assertFalse((data/'upload-configs/namespace.json').exists())
            api.return_value.referenced_context.assert_not_called()
            self.assertFalse(list(data.glob('resource-scans-*')))
            self.assertFalse((data/'scan-failures.txt').exists())

    def test_disabled_cluster_scope_collects_and_scans_only_namespace_objects(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);data=temp/'data';(data/'config').mkdir(parents=True)
            (data/'config/uploader.json').write_text('{"jobs":{}}')
            artifacts=temp/'artifacts';artifacts.mkdir()
            def snapshot(namespace,resources,output):
                self.assertEqual(namespace,'first')
                self.assertTrue(all(resource[3] for resource in resources))
                manifest(output,[obj('ConfigMap','cm',namespace)])
            def scan(source,report,cache,scratch,extra,concurrent_scans=1):
                self.assertEqual([d['kind'] for d in m.documents(source)],['ConfigMap'])
                report.write_text('{"results":[]}')
            with patch.dict(os.environ,{'AIRGAPPED':'true','NAMESPACE_CONCURRENCY':'1','INCLUDE_CLUSTER_SCOPED':'false'}),patch.object(m,'KubernetesAPI') as api,patch.object(m,'scan_manifest',side_effect=scan) as scanning:
                api.return_value.resources.return_value=[('/api/v1','configmaps','ConfigMap',True),('/api/v1','namespaces','Namespace',False)]
                api.return_value.namespaces.return_value=iter(['first'])
                api.return_value.snapshot.side_effect=snapshot
                m.main(data,artifacts)
                api.return_value.referenced_context.assert_not_called()
                self.assertEqual(scanning.call_count,1)
            self.assertTrue((data/'first.json').exists())
            self.assertFalse((data/'cluster.resources.json').exists())
            self.assertFalse((data/'upload-configs/cluster.resources.json').exists())

    def test_scan_failure_still_hands_successful_reports_to_uploader(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);data=temp/'data';(data/'config').mkdir(parents=True)
            (data/'config/uploader.json').write_text('{"jobs":{}}')
            artifacts=temp/'artifacts';artifacts.mkdir()
            def snapshot(namespace,resources,output):
                manifest(output,[obj('Namespace','first'),obj('Namespace','second')] if namespace is None else [obj('ConfigMap','cm',namespace)])
            def scan(source,report,cache,scratch,extra,concurrent_scans=1):
                if source.name=='first.manifest.yaml':
                    raise RuntimeError('scan failed')
                report.write_text('{"results":[]}')
            with patch.dict(os.environ,{'AIRGAPPED':'true','NAMESPACE_CONCURRENCY':'1','INCLUDE_CLUSTER_SCOPED':'true'}),patch.object(m,'KubernetesAPI') as api,patch.object(m,'scan_manifest',side_effect=scan):
                api.return_value.resources.return_value=[('/api/v1','configmaps','ConfigMap',True),('/api/v1','namespaces','Namespace',False)]
                api.return_value.namespaces.return_value=iter(['first','second'])
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

    def test_memory_budget_divides_across_concurrent_scans(self):
        with patch.dict(os.environ, {'SCANNER_MEMORY_LIMIT_BYTES':str(1024**3),
                                     'SCANNER_MEMORY_PERCENT':'60','SCANNER_GOGC':'20'}, clear=True):
            single=m.scanner_environment(1)
            multiple=m.scanner_environment(3)
            self.assertEqual(single['GOGC'],'20')
            self.assertEqual(single['GOMEMLIMIT'],str(1024**3*60//100)+'B')
            self.assertEqual(multiple['GOMEMLIMIT'],str(1024**3*60//100//3)+'B')
        with patch.dict(os.environ,{'SCANNER_MEMORY_PERCENT':'100'},clear=True):
            with self.assertRaisesRegex(ValueError,'1 to 90'):
                m.scanner_environment(1)

    def test_scan_passes_budget_and_reports_killed_process(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'SCANNER_MEMORY_LIMIT_BYTES':str(1024**3)},clear=True):
            temp=Path(temp);source=temp/'input.yaml';source.write_text('---\n{}\n')
            with patch.object(m.subprocess,'run',side_effect=subprocess.CalledProcessError(-9,['kubescape'])) as run:
                with self.assertRaisesRegex(RuntimeError,'SIGKILL'):
                    m.scan_manifest(source,temp/'report.json',temp,temp,[],2)
                self.assertEqual(run.call_args.kwargs['env']['GOMEMLIMIT'],str(1024**3*60//100//2)+'B')


if __name__=='__main__':
    unittest.main()
