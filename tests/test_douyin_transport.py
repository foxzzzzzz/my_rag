import io, socket, threading, time
from unittest.mock import Mock, patch
import pytest
from personalkb import douyin_http as h
from personalkb.douyin import load_douyin_config
from personalkb.workflow_store import WorkflowError

def test_dns_deadline():
 event=threading.Event(); started=threading.Event()
 def blocked(*args,**kwargs):
  started.set(); event.wait(2); return []
 try:
  with patch.object(socket,'getaddrinfo',side_effect=blocked):
   start=time.monotonic()
   with pytest.raises(WorkflowError,match='douyin_timeout'): h._resolve('example.com',start+1,.03)
   assert started.is_set() and time.monotonic()-start<.5
 finally: event.set()

def test_canonical_no_dns():
 cfg=load_douyin_config('config/douyin.json')
 with patch.object(socket,'getaddrinfo',side_effect=AssertionError('DNS used')):
  assert h.resolve_share_url('https://www.douyin.com/video/123',cfg)=='123'

def test_private_dns_rejected():
 with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,0,'',('127.0.0.1',443))]):
  with pytest.raises(WorkflowError,match='douyin_unsafe_url'): h._resolve('example.com',time.monotonic()+1,1)

def test_pinned_ip_and_original_tls():
 raw=Mock(); tls=Mock(); context=Mock(); context.wrap_socket.return_value=tls
 with patch.object(socket,'socket',return_value=raw), patch.object(socket,'getaddrinfo',side_effect=AssertionError('DNS used')):
  conn=h._PinnedHTTPSConnection('example.com',ip='8.8.8.8',deadline=time.monotonic()+10,timeout=3,context=context); conn.connect()
 raw.connect.assert_called_once_with(('8.8.8.8',443)); context.wrap_socket.assert_called_once_with(raw,server_hostname='example.com')
 assert conn.sock.sock is tls

def test_deadline_raw_checks_every_read():
 raw=Mock(); raw.readinto.return_value=1; sock=Mock()
 with patch.object(h.time,'monotonic',side_effect=[1,4,5]):
  r=h._DeadlineRaw(raw,sock,5,2); b=bytearray(2)
  assert r.readinto(b)==1; sock.settimeout.assert_called_with(2)
  assert r.readinto(b)==1; sock.settimeout.assert_called_with(1)
  with pytest.raises(WorkflowError,match='douyin_timeout'): r.readinto(b)
  assert raw.readinto.call_count==2

def test_makefile_wraps_raw():
 sock=Mock(); sock.makefile.return_value=io.BytesIO(b'abc')
 with patch.object(h.time,'monotonic',return_value=1):
  f=h._DeadlineSocket(sock,3,5).makefile(); assert f.read()==b'abc'; sock.settimeout.assert_called_with(2)
 sock.makefile.assert_called_once_with('rb',buffering=0)

@pytest.mark.parametrize('body,length',[(b'12','4'),(b'','0')])
def test_truncated_or_empty_removed(tmp_path,body,length):
 cfg=load_douyin_config('config/douyin.json'); cfg['min_free_bytes']=0
 response=Mock(); response.headers={'Content-Length':length}; response.read.side_effect=[body,b'']
 target=tmp_path/'out.mp4'
 with patch.object(h,'_open',return_value=('https://example.com',response)):
  with pytest.raises(WorkflowError,match='douyin_download_failed'): h.download_stream('https://example.com',target,cfg)
 assert not target.exists(); response.close.assert_called_once()
