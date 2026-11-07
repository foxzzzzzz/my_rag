import unittest
from personalkb.douyin import normalize_share
from personalkb.workflow_store import WorkflowError

class ShareTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(normalize_share('看看 https://v.douyin.com/abc12/ 复制'), 'https://v.douyin.com/abc12/')
        self.assertEqual(normalize_share('https://www.douyin.com/video/123?foo=bar'), 'https://www.douyin.com/video/123')
    def test_reject(self):
        for value in ('http://v.douyin.com/a/', 'https://v.douyin.com:443/a/', 'https://x@v.douyin.com/a/', 'https://evil.com/video/1', 'https://v.douyin.com/a/ https://v.douyin.com/b/'):
            with self.subTest(value=value), self.assertRaises(WorkflowError): normalize_share(value)

class MetadataTests(unittest.TestCase):
    def test_permission_and_known_paths(self):
        from tools.douyin_resolver import metadata
        detail = {'aweme_id': '123', 'video_control': {'allow_download': True}, 'video': {'play_addr': {'url_list': ['https://cdn.example/a']}}}
        self.assertEqual(metadata({'aweme_detail': detail}, '123')['media_url'], 'https://cdn.example/a')
        for control in ({}, {'allow_download': False}, {'prevent_download_type': True}):
            detail['video_control'] = control
            with self.assertRaises(ValueError): metadata({'aweme_detail': detail}, '123')
    def test_disabled_and_missing_cookie(self):
        from personalkb.douyin import load_douyin_config, resolve_with_f2
        cfg = load_douyin_config('config/douyin.json')
        with self.assertRaises(WorkflowError): resolve_with_f2('123', 'secret', cfg)
        cfg['enabled'] = True
        with self.assertRaises(WorkflowError): resolve_with_f2('123', '', cfg)

class ResolverProcessTests(unittest.TestCase):
    def test_secret_not_in_argv_or_environment(self):
        import io, json
        from unittest.mock import patch
        from personalkb.douyin import load_douyin_config, resolve_with_f2
        cfg=load_douyin_config('config/douyin.json'); cfg.update(enabled=True,resolver_python='python')
        class Input(io.BytesIO):
            def close(self): self.saved=self.getvalue()
        class Fake:
            def __init__(self):
                self.stdin=Input(); self.stdout=io.BytesIO(json.dumps({'work_id':'123','title':'x','media_url':'https://example.com/a'}).encode()); self.stderr=io.BytesIO(); self.returncode=0
            def wait(self, timeout): return 0
            def kill(self): pass
        p=Fake()
        with patch('subprocess.Popen',return_value=p) as launch:
            resolve_with_f2('123','secret-value',cfg)
        self.assertNotIn('secret-value',str(launch.call_args))
        self.assertEqual(json.loads(p.stdin.saved)['cookie'],'secret-value')
    def test_output_limit_and_timeout(self):
        import io, subprocess
        from unittest.mock import patch
        from personalkb.douyin import load_douyin_config, resolve_with_f2
        cfg=load_douyin_config('config/douyin.json'); cfg.update(enabled=True,resolver_python='python',max_resolver_output_bytes=4)
        class Fake:
            def __init__(self, timeout=False): self.stdin=io.BytesIO(); self.stdout=io.BytesIO(b'12345'); self.stderr=io.BytesIO(); self.returncode=0; self.timeout=timeout
            def wait(self, timeout):
                if self.timeout: raise subprocess.TimeoutExpired('fake',timeout)
                return 0
            def kill(self): pass
        for timeout in (False, True):
            with self.subTest(timeout=timeout), patch('subprocess.Popen',return_value=Fake(timeout)):
                with self.assertRaises(WorkflowError): resolve_with_f2('123','secret',cfg)

class SafetyRegressionTests(unittest.TestCase):
    def test_detail_fallback_and_status(self):
        from tools.douyin_resolver import metadata
        d={'aweme_id':'1','prevent_download':False,'video':{'play_addr':{'url_list':['https://x/a']}}}
        self.assertEqual(metadata({'aweme_detail':d,'status_code':'0'},'1')['work_id'],'1')
        for status in (1, 'failure'):
            with self.assertRaises(ValueError): metadata({'aweme_detail':d,'status_code':status},'1')
        d.pop('prevent_download'); d['video_control']={'prevent_download':False}
        with self.assertRaises(ValueError): metadata({'aweme_detail':d},'1')
    def test_config_rejects_invalid_types_and_hosts(self):
        import json, tempfile
        from pathlib import Path
        from personalkb.douyin import load_douyin_config
        cfg=load_douyin_config('config/douyin.json')
        self.assertEqual(cfg['min_free_bytes'],8589934592)
        for key, value in [('max_redirects', False),('download_chunk_bytes', 1.5),('media_hosts',['-bad.example']),('max_download_bytes',True)]:
            bad=dict(cfg); bad[key]=value
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'cfg.json'; p.write_text(json.dumps(bad),encoding='utf-8')
                with self.subTest(key=key), self.assertRaises(WorkflowError): load_douyin_config(p)
    def test_isolated_python_and_environment(self):
        import io, json, os
        from unittest.mock import patch
        from personalkb.douyin import load_douyin_config, resolve_with_f2
        cfg=load_douyin_config('config/douyin.json'); cfg.update(enabled=True,resolver_python='python')
        class Input(io.BytesIO):
            def close(self): pass
        class Fake:
            def __init__(self): self.stdin=Input(); self.stdout=io.BytesIO(json.dumps({'work_id':'1','title':'','media_url':'https://x/a'}).encode()); self.stderr=io.BytesIO(); self.returncode=0
            def wait(self, timeout): return 0
            def kill(self): pass
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY':'secret', 'PYTHONPATH':'malicious'}), patch('subprocess.Popen',return_value=Fake()) as launch:
            resolve_with_f2('1','cookie',cfg)
        args, kwargs=launch.call_args
        self.assertEqual(args[0][1],'-I')
        self.assertNotIn('PYTHONPATH',kwargs['env']); self.assertNotIn('DASHSCOPE_API_KEY',kwargs['env'])

class ResolverLoggingTests(unittest.TestCase):
    def test_safe_parser_and_logging_disabled(self):
        import logging, sys, types
        from unittest.mock import patch, Mock
        from tools.douyin_resolver import disable_logging, safe_parse_json
        fake=Mock(); module=types.ModuleType('loguru'); module.logger=fake
        old=logging.root.manager.disable
        try:
            with patch.dict(sys.modules, {'loguru':module}): disable_logging()
            self.assertEqual(logging.root.manager.disable, logging.CRITICAL)
            fake.remove.assert_called_once(); fake.disable.assert_called_once_with('f2')
        finally: logging.disable(old)
        response=Mock(status_code=200); response.json.return_value={'ok':True}
        self.assertEqual(safe_parse_json(response), {'ok':True})
        response.status_code=403
        with self.assertRaises(ValueError): safe_parse_json(response)

class SafeErrorTests(unittest.TestCase):
    def test_permission_codes_and_priority(self):
        from tools.douyin_resolver import metadata
        for control, expected in [({'allow_download':False,'prevent_download_type':0},'download_denied'), ({},'download_permission_unknown')]:
            with self.subTest(control=control), self.assertRaisesRegex(ValueError, expected):
                metadata({'aweme_detail':{'aweme_id':'1','video_control':control}},'1')

    def test_bridge_error_whitelist(self):
        import io, json
        from unittest.mock import patch
        from personalkb.douyin import load_douyin_config, resolve_with_f2
        cfg=load_douyin_config('config/douyin.json'); cfg.update(enabled=True,resolver_python='python')
        class Fake:
            def __init__(self, data): self.stdin=io.BytesIO(); self.stdout=io.BytesIO(json.dumps(data).encode()); self.stderr=io.BytesIO(); self.returncode=0
            def wait(self, timeout): return 0
            def kill(self): pass
        for data, expected in [({'error':'download_denied'},'download_denied'),({'error':'download_permission_unknown'},'download_permission_unknown'),({'error':'secret'},'douyin_resolver_failed'),({'error':'download_denied','secret':'x'},'douyin_resolver_failed')]:
            with self.subTest(data=data), patch('subprocess.Popen',return_value=Fake(data)), self.assertRaises(WorkflowError) as raised:
                resolve_with_f2('1','secret',cfg)
            self.assertEqual(raised.exception.code,expected)

    def test_main_safe_codes_and_conflicts(self):
        import io, json
        from unittest.mock import patch
        from tools.douyin_resolver import main, metadata
        for control, detail, expected in [({'allow_download':True,'prevent_download_type':1},{},'download_denied'), ({'allow_download':True},{'prevent_download':True},'download_denied'), ('invalid',{'prevent_download':False},'download_permission_unknown')]:
            with self.subTest(control=control), self.assertRaisesRegex(ValueError, expected):
                metadata({'aweme_detail':{'aweme_id':'1','video_control':control,**detail}},'1')
        for error, expected in [('download_denied','download_denied'),('download_permission_unknown','download_permission_unknown'),('secret cookie','resolver_failed')]:
            async def fail(data): raise ValueError(error)
            output=io.StringIO()
            with patch('tools.douyin_resolver.fetch',fail), patch('sys.stdin',io.StringIO('{}')), patch('sys.stdout',output): main()
            self.assertEqual(json.loads(output.getvalue()), {'error':expected})

    def test_invalid_permission_types_never_allow(self):
        from tools.douyin_resolver import metadata
        cases = [({'allow_download':'false','prevent_download_type':0},{},'download_permission_unknown'),
                 ({'allow_download':True,'prevent_download_type':'2'},{},'download_permission_unknown'),
                 ({'allow_download':True},{'prevent_download':'true'},'download_permission_unknown'),
                 ({'allow_download':False,'prevent_download_type':'0'},{},'download_denied'),
                 ({'allow_download':'false','prevent_download_type':1},{},'download_denied')]
        for control, extra, expected in cases:
            with self.subTest(control=control, extra=extra), self.assertRaisesRegex(ValueError, expected):
                metadata({'aweme_detail':{'aweme_id':'1','video_control':control,**extra}},'1')

    def test_detail_chunk_config_limit(self):
        import json, tempfile
        from pathlib import Path
        from personalkb.douyin import load_douyin_config
        cfg=load_douyin_config('config/douyin.json')
        for mode in ('f2','minimal_detail'):
            cfg.update(resolver_mode=mode,max_detail_response_bytes=cfg['download_chunk_bytes']-1)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'config.json'; path.write_text(json.dumps(cfg),encoding='utf-8')
                with self.subTest(mode=mode), self.assertRaises(WorkflowError): load_douyin_config(path)

    def test_playback_policy_and_missing_policy(self):
        from tools.douyin_resolver import metadata
        detail={'aweme_id':'1','video_control':{'allow_download':False},'video':{'play_addr':{'url_list':['https://cdn.example/video']}}}
        self.assertEqual(metadata({'aweme_detail':detail},'1','authorized_playback')['work_id'],'1')
        with self.assertRaisesRegex(ValueError,'download_denied'): metadata({'aweme_detail':detail},'1','strict')
        with self.assertRaisesRegex(ValueError,'invalid_policy'): metadata({'aweme_detail':detail},'1',None)
        with self.assertRaises(ValueError): metadata({'aweme_detail':detail},'2','authorized_playback')
        detail['video']={}
        with self.assertRaisesRegex(ValueError,'missing_media'): metadata({'aweme_detail':detail},'1','authorized_playback')
