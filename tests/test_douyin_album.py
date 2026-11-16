from decimal import Decimal
import pytest
from personalkb.douyin_album import quote
from personalkb.workflow_store import WorkflowError


def test_quote_includes_each_image_and_automatic_retry():
    config = {'strategy': {'vision_max_tokens': 3072, 'text_max_tokens': 8192},
              'prices': {'vision': [1, 10], 'text': [2, 8]},
              'vision_input_token_bound': 65536, 'album_text_input_token_bound': 320000,
              'chat_timeout_retries': 1}
    assert quote(2, config) == Decimal('1.80')
    with pytest.raises(WorkflowError):
        quote(0, config)

from types import SimpleNamespace
from pathlib import Path
from personalkb.douyin_album import DouyinAlbum
from personalkb.workflow_store import WorkflowStore


def service_for(tmp_path):
    root = tmp_path / 'data'
    root.mkdir()
    wc = {'data_dir': str(root), 'min_free_bytes': 1}
    pc = {'strategy': {'vision_max_tokens': 3072, 'text_max_tokens': 8192},
          'prices': {'vision': [1, 10], 'text': [2, 8]},
          'vision_input_token_bound': 65536, 'chat_timeout_retries': 1}
    dc = {'max_download_bytes': 1024, 'download_chunk_bytes': 64, 'min_free_bytes': 1}
    return SimpleNamespace(wc=wc, pc=pc, webcfg={},
                           store=WorkflowStore(root / 'workflow.sqlite3', data_root=root),
                           douyin=SimpleNamespace(cfg=dc))


def test_download_checkpoint_order_and_integrity(tmp_path):
    service = service_for(tmp_path)
    config = {'max_images': 3, 'max_image_bytes': 1000, 'max_album_bytes': 3000,
              'album_text_input_token_bound': 320000, 'media_hosts': ['douyinpic.com'],
              'vision_prompt': '提取图片', 'text_prompt_suffix': '引用图号'}
    calls = []
    def downloader(url, path, cfg):
        calls.append(url)
        if url == 'two' and calls.count('two') == 1:
            raise WorkflowError('douyin_timeout')
        path.write_bytes(b'\xff\xd8\xff' + url.encode())
    album = DouyinAlbum(service, config=config, downloader=downloader)
    with pytest.raises(WorkflowError):
        album.download('123', 'title', ['one', 'two'])
    result = album.download('123', 'title', ['one', 'two'])
    assert calls == ['one', 'two', 'two']
    sid = result['source']['id']
    assert result['source']['original_name'] == 'douyin-123.album.json'
    assert [item['index'] for item in album.manifest(sid)['images']] == [1, 2]
    path, mime = album.original_image(sid, 2)
    assert mime == 'image/jpeg' and path.read_bytes().endswith(b'two')
    assert album.download('123', 'title', ['one', 'two'])['duplicate']
    path.write_bytes(b'bad')
    with pytest.raises(WorkflowError, match='source_integrity'):
        album.original_image(sid, 2)


def test_image_limit_and_invalid_image_never_create_source(tmp_path):
    service = service_for(tmp_path)
    config = {'max_images': 1, 'max_image_bytes': 1000, 'max_album_bytes': 3000,
              'album_text_input_token_bound': 320000, 'media_hosts': ['douyinpic.com'],
              'vision_prompt': '提取图片', 'text_prompt_suffix': '引用图号'}
    def downloader(url, path, cfg):
        path.write_bytes(b'<html>not image</html>')
    album = DouyinAlbum(service, config=config, downloader=downloader)
    with pytest.raises(WorkflowError, match='album_image_limit'):
        album.download('123', 'title', ['one', 'two'])
    with pytest.raises(WorkflowError, match='album_invalid_image'):
        album.download('123', 'title', ['one'])
    assert service.store.list_sources() == []
