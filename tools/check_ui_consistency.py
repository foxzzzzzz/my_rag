"""Exercise a built frontend in Edge with local fixtures. Requires Python Playwright."""

import argparse
import json
import re
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


class StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def serve(build):
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(StaticHandler, directory=str(build))) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


class Fixture:
    """A new, disposable backend state for each browser context."""

    def __init__(self):
        self.topic = {"id": "topic", "name": "智能体", "kind": "topic", "aliases": ["Agent"], "revision": 1}
        self.tags = [
            {"id": f"tag-{i}", "name": name, "kind": "tag", "aliases": [], "revision": 1}
            for i, name in enumerate(("知识工程", "用户反馈", "源码阅读", "离线评测", "系统设计"))
        ]
        self.sources = [
            {
                "id": f"s{i}", "current_version_id": f"v{i}", "title": title, "kind": kind,
                "original_name": f"{i}.{extension}", "review_status": state, "eligible": state == "approve",
                "created_at": f"2026-11-{19-i:02}T02:30:00Z", "content_status": "synced",
                "classification": {
                    "revision": 3, "topics": [self.topic] if i < 5 else [],
                    "tags": self.tags if i == 0 else self.tags[:2] if i < 5 else [],
                },
            }
            for i, (title, kind, extension, state) in enumerate((
                ("从用户反馈改进知识库检索：结合长中文标题、系统架构、引用定位和离线评估复盘完整流程", "video", "mp4", "pending"),
                ("OpenManus 源码拆解：主循环与工具调用", "html", "html", "approve"),
                ("开源绘图工具与日常知识整理", "video", "mp4", "rework"),
                ("smolagents 源码拆解：实现与边界", "html", "html", "approve"),
                ("从灵感到归档：图文笔记", "douyin_album", "json", "reject"),
                ("待分类的网页资料", "html", "html", "pending"),
            ))
        ]
        self.trash = [{
            "id": "trashed", "title": "可撤销的网页资料", "deleted_at": "2026-11-18T02:00:00Z",
            "expires_at": "2026-11-25T02:00:00Z", "can_restore": True,
        }]
        self.tasks = [
            {"id": f"task{i}", "source": source, "source_id": source["id"], "status": "succeeded",
             "stage": "text", "archived": i == 2, "can_archive": i != 2, "updated_at": source["created_at"]}
            for i, source in enumerate(self.sources)
        ]
        self.review = None
        self.writes = []
        self.unexpected = []
        self.logged_in = True
        self.fail_read = False
        self.live_video_enabled = False
        self.poll_interval_ms = 60000
        self.hold_sources = False
        self.pending_sources = None
        self.budget = {
            'limit_cny': '100', 'reserved_cny': '99.440718', 'available_cny': '0.559282',
            'estimated_cost_cny': '0.25', 'unknown_count': 1, 'revision': 0,
            'run_limits': {'video':'5', 'html':'2', 'rag':'2', 'classification':'2'}, 'changes': [],
            'entries': [{'request_id':'rag-run:answer', 'run_id':'rag-run', 'label':'知识库检索与问答',
                         'stage':'生成回答', 'reserved_cny':'1', 'reserved_limit_cny':'1.25', 'estimated_cost_cny':'0.25'},
                        {'request_id':'task4:text', 'run_id':'task4', 'label':'从灵感到归档：图文笔记',
                         'stage':'生成文本', 'reserved_cny':'98.440718', 'estimated_cost_cny':None}],
        }
        self.citation = {"chunk_id": "a" * 64, "source_id": "s1", "version_id": "v1", "text": "离线复核证据。",
                         "locator": {"type": "text", "offset": 0, "end_offset": 7}}

    def respond(self, route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix("/api")
        method = request.method

        def reply(value, status=200):
            route.fulfill(status=status, json=value)

        if method != "GET":
            body = request.post_data_json if request.headers.get("content-type") == "application/json" else None
            self.writes.append((method, path, body))
            if path == "/auth/login":
                self.logged_in = True
                return reply({})
            if path == "/auth/activity":
                return reply({})
            if path == '/budget' and method == 'PATCH':
                assert body == {'limit_cny':'150.25', 'expected_revision':0}, body
                if self.budget['revision'] != body['expected_revision']:
                    return reply({'error':'budget_revision_conflict'}, 409)
                self.budget.update(limit_cny='150.25', available_cny='50.809282', revision=1,
                                   changes=[{'previous_limit_cny':'100', 'limit_cny':'150.25', 'changed_at':'2026-11-20T06:30:00Z'}])
                return reply(self.budget)
            if path == '/tasks/task0/retry' and method == 'POST':
                assert body == {'allow_paid': True, 'processing_mode': 'preview'}, body
                self.tasks[0].update(status='queued', error_code=None, dispatch={'state': 'pending'})
                return reply({'dispatch_state': 'pending'})
            if method == 'POST' and re.fullmatch(r'/tasks/task[02]/(visual-only|rebuild-media)', path):
                assert body == {'allow_paid': True}, body
                task = next(t for t in self.tasks if t['id'] == path.split('/')[2])
                task.update(dispatch={'state': 'pending'})
                return reply({'dispatch_state': 'pending'})
            if path == "/classifications/bulk":
                updates = []
                for entry in body["items"]:
                    source = next(item for item in self.sources if item["id"] == entry["source_id"])
                    old = source["classification"]
                    assert entry["expected_revision"] == old["revision"]
                    source["classification"] = {**old, "revision": old["revision"] + 1, "topics": [self.topic]}
                    updates.append({"source_id": source["id"], "status": "success", "classification": source["classification"]})
                return reply({"items": updates})
            if path == "/sources/s0/reviews":
                assert body["version_id"] == "v0"
                assert body["score"] == 98 and body["decision"] == "approve"
                self.review = {**body, "created_at": self.sources[0]["created_at"]}
                return reply({})
            if path == "/imports":
                assert "rights_confirmed=true" in request.url
                return reply({"duplicate": False})
            if path == "/trash/trashed/restore":
                self.trash.clear()
                return reply({})
            if path == "/rag/stream":
                assert body["allow_paid"] is True and body["mode"] == "lexical"
                assert body["filters"]["sources"] == ["s1"]
                chunks = [{"type": "answer", "answer": f"问答用于查找证据。[{self.citation['chunk_id']}]",
                           "citations": [self.citation]}, {"type": "done"}]
                return route.fulfill(content_type="text/event-stream", body="".join(f"data: {json.dumps(x)}\n\n" for x in chunks))
        else:
            if path == "/session":
                if self.fail_read:
                    return route.abort("failed")
                if not self.logged_in:
                    return reply({"error": "login_required"}, 401)
                return reply({"csrf_token": "isolated", "config": {
                    "auth_enabled": True, "poll_interval_ms": self.poll_interval_ms, "quality_target": 98,
                    "display_timezone": "Asia/Shanghai", "live_html_enabled": False, "live_video_enabled": self.live_video_enabled,
                    "max_upload_bytes": 1048576, "max_html_bytes": 1048576,
                }})
            if path == "/sources":
                if self.hold_sources:
                    self.pending_sources = route
                    return
                return reply({"items": self.sources})
            if path == "/tasks":
                return reply({"items": self.tasks})
            if path == '/budget':
                return reply(self.budget)
            if path == "/classifications":
                return reply({"items": [self.topic, *self.tags]})
            if path == "/classification-suggestions/status":
                return reply({"enabled": False})
            if path == "/trash":
                return reply({"items": self.trash, "retention_days": 7})
            if path.startswith("/sources/"):
                if path.endswith("/classification/suggestions"):
                    return reply({})
                source = next((item for item in self.sources if path == "/sources/" + item["id"]), None)
                if source:
                    return reply({
                        "source": source, "eligible": source["eligible"],
                        "current": {"id": source["current_version_id"], "content_sha256": "b" * 64,
                                    "result": {"summary": "摘要说明。", "notes": "## 阅读笔记\n\n一段可核对的笔记。",
                                               "body": "## 正文内容\n\n原文保留。", "visual": "画面中的步骤。",
                                               "transcript_status": source.get('transcript_status')}} if source["current_version_id"] else None,
                        "review": self.review if source["id"] == "s0" else None,
                    })
            if path == "/rag/status":
                return reply({"enabled": True, "ready": True, "indexed_sources": 2,
                              "eligible_source_ids": ["s1", "s3"], "indexed_source_ids": ["s1", "s3"]})
            if path == "/rag/citations/" + self.citation["chunk_id"]:
                return reply(self.citation)
            if path == "/douyin/status":
                return reply({"enabled": False})
            if path == "/douyin/jobs":
                return reply({"items": []})
            if path == "/douyin/favorites/sync":
                return reply({"enabled": True, "state": "ready", "download_limit": 10, "manual_video_budget_cny": "0.3",
                              "items": [{"work_id": "fav-1", "title": "收藏视频样例", "kind": "video",
                                         "status": "available", "selectable": True}]})
        self.unexpected.append((method, path))
        reply({"error": "unexpected_browser_request"}, 500)


def open_page(browser, address, fixture, width, height):
    page = browser.new_page(viewport={"width": width, "height": height}, has_touch=width <= 390)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(re.compile(re.escape(address) + "/api/"), fixture.respond)
    page.goto(address)
    return page, errors


def nav(page, label):
    page.get_by_role("navigation", name="主导航").get_by_role("button", name=label, exact=True).click()


def screenshot(page, output, name):
    assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth"), name
    full_page = name in {"detail", "ask", "import", "trash"}
    page.screenshot(path=output / f"{name}-{page.viewport_size['width']}.png", full_page=full_page)


def verify_library(page, output):
    rows = page.locator(".library-source-row")
    expect(rows).to_have_count(6)
    screenshot(page, output, "library")
    styles = page.locator(".library-source-row .media-type-badge").evaluate_all("""nodes =>
        nodes.map(badge => {
            const style = getComputedStyle(badge), icon = badge.querySelector('svg');
            return [badge.dataset.kind, style.backgroundColor, style.color, getComputedStyle(icon).stroke,
                    style.fontSize, icon.getBoundingClientRect().width];
        })""")
    colors = {"web": "rgb(29, 78, 216)", "video": "rgb(194, 65, 12)", "album": "rgb(4, 120, 87)"}
    assert {tuple(style) for style in styles} == {
        (kind, "rgba(0, 0, 0, 0)", color, color, "12px", 14) for kind, color in colors.items()
    }, styles
    controls = page.locator(".library-view .list-page-controls")
    list_region = page.get_by_role("region", name="资料列表")
    search = controls.get_by_role("textbox", name="查找")
    kind = controls.get_by_role("combobox", name=re.compile("^类型 "))
    review = controls.get_by_role("combobox", name=re.compile("^审核 "))
    clear = controls.get_by_role("button", name="清空筛选", exact=True)
    tags = controls.locator("summary")
    search.focus()
    for next_control in (kind, review, clear, tags):
        page.keyboard.press("Tab")
        expect(next_control).to_be_focused()
    for trigger, label, option, image in ((kind, "类型", "网页", "type"), (review, "审核", "待审核", "review")):
        trigger.click()
        menu = page.get_by_role("listbox", name=label)
        expect(menu).to_be_visible()
        assert menu.evaluate("(e) => e.getBoundingClientRect().bottom <= document.querySelector('.library-scroll').getBoundingClientRect().top")
        screenshot(page, output, f"library-{image}")
        menu.get_by_role("option", name=option, exact=True).click()
        expect(rows).to_have_count(3 if option == "网页" else 2)
        clear.click()
        expect(rows).to_have_count(6)
    kind.press("Space")
    kind.press("ArrowDown")
    kind.press("Escape")
    expect(kind).to_be_focused()
    expect(rows).to_have_count(6)
    tags.click()
    controls.get_by_role("checkbox", name="源码阅读").check()
    expect(rows).to_have_count(1)
    clear.click()
    tags.click()
    search.fill("找不到的字符串")
    expect(list_region.get_by_text("没有匹配的资料")).to_be_visible()
    list_region.get_by_role("button", name="清空筛选").click()
    expect(rows).to_have_count(6)
    sort = list_region.get_by_role("button", name=re.compile("^按导入时间排序"))
    sort.click()
    expect(rows.first).to_contain_text("待分类的网页资料")
    sort.click()
    expect(rows.first).to_contain_text("从用户反馈改进知识库检索")
    first_type = rows.first.locator(".library-row-select").bounding_box()
    assert first_type["width"] >= 24 and first_type["height"] >= 24
    rows.first.get_by_role("checkbox").check()
    select_all = page.get_by_role("checkbox", name="全选匹配结果")
    expect(select_all).to_have_js_property("indeterminate", True)
    select_all.check()
    expect(page.locator(".library-source-row input:checked")).to_have_count(6)
    select_all.uncheck()
    expect(page.locator(".library-source-row input:checked")).to_have_count(0)
    rows.first.get_by_role("checkbox").check()
    screenshot(page, output, "library-selection")
    page.get_by_role("button", name="批量分类", exact=True).click()
    batch = page.locator(".library-batch")
    batch.get_by_role("checkbox", name="智能体").check()
    batch.get_by_role("button", name="应用到已选资料").click()
    expect(batch.get_by_text("已完成")).to_be_visible()
    page.get_by_role("button", name="取消选择").click()


def verify_library_version_gate(browser, address, width, height):
    fixture = Fixture()
    fixture.poll_interval_ms = 500
    fixture.sources[-1]["classification"]["topics"] = [fixture.topic]
    fixture.tasks[0].update(status="failed", reprocess=True, error_code="budget_invalid_or_exceeded")
    for status, title in (("failed", "首次处理失败"), ("running", "首次处理进行中"), ("queued", "首次处理等待中")):
        source = {**fixture.sources[0], "id": f"first-{status}", "title": title, "original_name": f"{status}.mp4",
                  "current_version_id": None, "eligible": False, "classification": {"revision": 0, "topics": [], "tags": []}}
        fixture.sources.append(source)
        fixture.tasks.append({"id": f"task-{status}", "source_id": source["id"], "status": status,
                              "error_code": "budget_invalid_or_exceeded" if status == "failed" else None})

    page, errors = open_page(browser, address, fixture, width, height)
    library = page.locator('.library-view')
    rows = library.locator('.library-source-row')
    expect(rows).to_have_count(6)
    unclassified = page.get_by_role('group', name='主题筛选').get_by_role('button', name='未分类', exact=True)
    expect(unclassified).to_have_count(0)
    search = library.get_by_role('textbox', name='查找')
    search.fill('首次处理')
    expect(library.get_by_text('没有匹配的资料')).to_be_visible()
    search.clear()
    library.get_by_role('combobox', name=re.compile('^审核 ')).click()
    page.get_by_role('listbox', name='审核').get_by_role('option', name='待审核', exact=True).click()
    expect(rows).to_have_count(2)
    library.get_by_role('checkbox', name='全选匹配结果').check()
    expect(rows.locator('input:checked')).to_have_count(2)
    library.get_by_role('button', name='清空筛选', exact=True).click()
    rows.filter(has_text='从用户反馈改进知识库检索').get_by_role('button').click()
    expect(page.get_by_role('heading', name=re.compile('从用户反馈改进知识库检索'))).to_be_visible()
    expect(page.get_by_text('摘要说明。', exact=True)).to_be_visible()

    nav(page, '任务')
    failed = page.locator('.task-item').filter(has_text='首次处理失败')
    expect(failed.get_by_text('任务或累计预算不足，无法自动重试。')).to_be_visible()
    expect(failed.get_by_role('button', name='重试')).to_be_disabled()
    expect(failed.locator('.task-retry-hint')).to_have_count(0)
    failed.get_by_role('button', name='查看资料', exact=True).click()
    expect(page.get_by_text('尚未生成可审核内容。')).to_be_visible()
    page.get_by_role('button', name='到任务页处理', exact=True).click()
    expect(failed.get_by_role('button', name='详情')).to_be_visible()

    nav(page, '资料库')
    expect(rows).to_have_count(6)
    new_source = fixture.sources[-1]
    new_source['current_version_id'] = 'first-result'
    fixture.tasks[-1]['status'] = 'succeeded'
    expect(rows).to_have_count(7)
    expect(rows.filter(has_text=new_source['title'])).to_contain_text('待审核')
    unclassified.click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text(new_source['title'])
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px library first-version gate, task access and polling passed')
    page.close()


def verify_detail(page, fixture, output):
    search = page.locator(".library-view").get_by_role("textbox", name="查找")
    search.fill("用户反馈")
    expect(page.locator(".library-source-row")).to_have_count(1)
    page.locator(".library-source-row .source").first.click()
    expect(page.get_by_role("heading", name=re.compile("从用户反馈改进知识库检索"))).to_be_visible()
    expect(page.locator('.source-heading .media-type-badge[data-kind="video"]')).to_have_css("background-color", "rgb(194, 65, 12)")
    screenshot(page, output, "detail")
    page.get_by_role("button", name="画面证据", exact=True).click()
    expect(page.get_by_text("画面中的步骤。")).to_be_visible()
    page.get_by_role("button", name="笔记", exact=True).click()
    expect(page.get_by_text("一段可核对的笔记。")).to_be_visible()
    score = page.get_by_role("spinbutton", name="评分", exact=True)
    draft = page.get_by_role("button", name="保存评分草稿")
    approve = page.get_by_role("button", name="提交批准")
    score.fill("97")
    draft.click()
    expect(approve).to_be_disabled()
    assert not any(path.endswith("/reviews") for _, path, _ in fixture.writes)
    score.fill("98")
    draft.click()
    expect(approve).to_be_enabled()
    approve.click()
    expect(page.get_by_text("审核已提交。")).to_be_visible()
    page.get_by_role("button", name=re.compile("返回资料库")).click()
    expect(search).to_have_value("用户反馈")
    expect(page.locator(".library-source-row")).to_have_count(1)
    search.fill("")
    expect(page.locator(".library-source-row")).to_have_count(6)


def verify_ask(page, output, *, baseline=False):
    nav(page, "问答")
    if baseline:
        expect(page.get_by_text("索引可用", exact=True)).to_be_visible()
    else:
        settings = page.locator(".rag-settings")
        expect(settings.locator("summary")).to_contain_text("全部已批准资料")
        expect(page.get_by_role("radio", name="自定义范围")).to_be_hidden()
        settings.locator("summary").press("Enter")
    page.get_by_role("radio", name="自定义范围").check()
    page.get_by_role("searchbox", name="搜索资料标题").fill("OpenManus")
    page.get_by_role("button", name="全选搜索结果").click()
    page.locator(".rag-retrieval-mode select").select_option("lexical")
    page.get_by_role("textbox", name="问题").fill("知识库问答怎么使用？")
    submit = page.get_by_role("button", name="生成回答")
    expect(submit).to_be_disabled()
    page.get_by_role("checkbox", name="我同意本次操作可能产生模型费用").check()
    submit.click()
    page.get_by_role("button", name="查看引用 ①").first.click()
    expect(page.get_by_text("离线复核证据。")).to_be_visible()
    if not baseline:
        expect(page.get_by_role("checkbox", name="我同意本次操作可能产生模型费用")).not_to_be_checked()
        expect(submit).to_be_disabled()
        settings.locator("summary").click()
        expect(settings.locator("summary")).to_contain_text("本地关键词")
    screenshot(page, output, "ask")


def verify_mobile_review_feedback(browser, address, output, width):
    fixture = Fixture()
    fixture.sources[5]["current_version_id"] = None
    fixture.tasks[5]["status"] = "queued"
    height = 844
    page, errors = open_page(browser, address, fixture, width, height)
    outcome = "conflict"
    versions = [{"id": "v-old", "created_at": "2026-11-17T02:00:00Z", "output_kind": "human_edited"},
                {"id": "v0", "created_at": "2026-11-19T02:00:00Z"}]

    def detail_route(route):
        is_history = "version_id=v-old" in route.request.url
        if outcome == "refresh_failure" and fixture.review and not is_history:
            return route.abort("failed")
        route.fulfill(json={"source": fixture.sources[0], "eligible": False,
                            "current": {"id": "v-old" if is_history else "v0", "content_sha256": "b" * 64,
                                        "result": {"notes": "\n\n".join(["核对长篇正文中的来源证据。"] * 48)}},
                            "versions": versions, "viewing_history": is_history, "review": fixture.review})

    def review_route(route):
        if outcome == "conflict":
            return route.fulfill(status=409, json={"error": "version_conflict"})
        fixture.respond(route)

    page.route(re.compile(r"/api/sources/s0(?:\?[^/]+)?$"), detail_route)
    page.route(re.compile(r"/api/sources/s0/reviews$"), review_route)
    nav_button = page.get_by_role("button", name="问答", exact=True)
    assert nav_button.bounding_box()["height"] >= 44
    row_target = page.locator(".library-row-select").first
    assert all(row_target.bounding_box()[dimension] >= 44 for dimension in ("width", "height"))
    row_target.click(position={"x": 3, "y": 3})
    expect(row_target.locator("input")).to_be_checked()
    page.locator(".library-source-row .source").first.click()
    notes = page.get_by_role("button", name="笔记", exact=True)
    assert notes.bounding_box()["height"] >= 44
    notes.click()
    page.get_by_role("combobox", name="查看版本").select_option("v-old")
    history_jump = page.get_by_role("button", name="查看审核记录", exact=True)
    expect(history_jump).to_be_visible()
    history_jump.press("Enter")
    expect(page.get_by_role("heading", name="审核记录", exact=True)).to_be_focused()
    expect(page.get_by_role("button", name="提交批准")).to_have_count(0)
    page.get_by_role("combobox", name="查看版本").select_option("")
    notes.click()
    heading = page.get_by_role("heading", name="审核", exact=True)
    assert heading.bounding_box()["y"] > height
    page.get_by_role("button", name="前往审核").press("Enter")
    expect(heading).to_be_focused()
    expect(heading).to_be_in_viewport()
    score = page.get_by_role("spinbutton", name="评分")
    score.fill("98")
    page.get_by_role("button", name="保存评分草稿").click()
    expect(page.locator(".review-panel").get_by_role("status")).to_contain_text("评分草稿已保存")
    submit = page.get_by_role("button", name="提交批准")
    assert submit.bounding_box()["height"] >= 44
    submit.click()
    local = page.locator(".review-panel").get_by_role("alert")
    expect(local).to_contain_text("资料版本已更新")
    expect(local).to_be_in_viewport()
    expect(score).to_have_value("98")
    expect(page.locator(".app-feedback.error")).to_have_count(0)
    screenshot(page, output, "review-local-error")
    outcome = "refresh_failure"
    submit.click()
    expect(page.locator(".review-panel").get_by_role("status")).to_have_text("审核已提交，页面状态暂未刷新。")
    expect(submit).to_be_disabled()
    assert len([write for write in fixture.writes if write[1].endswith("/reviews")]) == 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    nav(page, "任务")
    pending = page.locator(".task-item").filter(has_text=fixture.sources[5]["title"])
    pending.get_by_role("button", name="查看资料", exact=True).click()
    expect(page.get_by_text("尚未生成可审核内容。")).to_be_visible()
    expect(page.locator(".review-jump")).to_have_count(0)
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    page.close()


def verify_login_errors(browser, address):
    fixture = Fixture()
    fixture.logged_in = False
    page, errors = open_page(browser, address, fixture, 390, 844)
    for status, code, message in (
        (401, "invalid_credentials", "密码错误，请重试。"),
        (429, "rate_limited", "尝试次数过多，请稍后再试。"),
        (403, "csrf_invalid", "登录请求未能完成，请刷新页面后重试。"),
        (413, "body_too_large", "登录请求过大，请检查输入后重试。"),
        (503, "internal_error", "登录服务暂时不可用，请稍后重试。"),
        (502, None, "登录服务暂时不可用，请稍后重试。"),
        (0, None, "无法连接服务。"),
    ):
        def handle(route):
            if status == 0:
                route.abort("failed")
            elif code:
                route.fulfill(status=status, json={"error": code})
            else:
                route.fulfill(status=status, content_type="text/html", body="Bad gateway")
        page.route("**/api/auth/login", handle)
        page.locator("input[type=password]").fill("mock-password")
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.locator(".app-feedback.error")).to_have_text(message)
        page.unroute("**/api/auth/login", handle)
    page.locator("input[type=password]").fill("mock-password")
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.locator(".library-source-row")).to_have_count(6)
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    page.close()


def verify_revision_editor(browser, address, output, width, height):
    fixture = Fixture()
    page, errors = open_page(browser, address, fixture, width, height)
    original = {field: "\n".join(f"{i:02d} {field}：逐段核对内容、引用和时间位置。" for i in range(1, 41))
                for field in ("summary", "notes", "body", "transcript", "visual")}
    saves = []

    def detail(route):
        route.fulfill(json={"source": fixture.sources[0], "eligible": False, "current": {
            "id": "v1-edited" if saves else "v0", "content_sha256": "b" * 64,
            "result": {**original, **(saves[-1] if saves else {})},
        }})

    def save(route):
        assert route.request.method == "POST"
        saves.append(route.request.post_data_json)
        route.fulfill(json={})

    page.route(f"{address}/api/sources/s0", detail)
    page.route(f"{address}/api/sources/s0/revisions", save)
    page.locator(".library-source-row .source").first.click()
    page.get_by_role("button", name="资料管理", exact=True).click()
    revision = page.locator("#source-management details").filter(has=page.get_by_text("人工修订", exact=True))
    revision.locator("summary").click()
    revision.get_by_role("button", name="编辑内容").click()
    fields = revision.locator("textarea")
    expect(fields).to_have_count(5)
    sizes = fields.evaluate_all("""fields => fields.map(e => {
        const style = getComputedStyle(e);
        return {height:e.getBoundingClientRect().height, size:style.fontSize, resize:style.resize,
                scrollable:e.scrollHeight > e.clientHeight};
    })""")
    assert all(s['height'] >= 450 and s['size'] == '16px' and s['resize'] == 'vertical' and s['scrollable'] for s in sizes), sizes
    expect(page.get_by_role("textbox", name="审核意见")).to_have_css("min-height", "72px")
    transcript = revision.get_by_role("textbox", name="语音转录")
    expect(transcript).to_have_value(original["transcript"])
    if width <= 390:
        revision.locator("summary").evaluate("e => e.scrollIntoView({block:'start'})")
    screenshot(page, output, "revision-editor")
    transcript.fill("准备放弃的修订")
    revision.get_by_role("button", name="放弃修订").click()
    page.get_by_role("dialog", name="放弃修订").get_by_role("button", name="确认操作").click()
    expect(fields).to_have_count(0)
    expect(revision.locator("summary")).to_be_visible()
    if not revision.evaluate("e => e.open"):
        revision.locator("summary").click()
    revision.get_by_role("button", name="编辑内容").click()
    expect(transcript).to_have_value(original["transcript"])
    assert not saves
    updated = original["transcript"] + "\n补齐一段语音转录。"
    transcript.fill(updated)
    revision.get_by_role("button", name="保存新版本").click()
    expect(page.get_by_text("已生成新版本，请重新审核。", exact=True)).to_be_visible()
    assert saves == [{**original, "expected_version_id": "v0", "transcript": updated}], saves
    page.get_by_role("button", name=re.compile("返回资料库")).click()
    page.get_by_role("button", name=re.compile("OpenManus 源码拆解")).click()
    page.get_by_role("button", name="资料管理", exact=True).click()
    revision.locator("summary").click()
    revision.get_by_role("button", name="编辑内容").click()
    expect(fields).to_have_count(3)
    assert all(height >= 450 for height in fields.evaluate_all("fields => fields.map(e => e.offsetHeight)"))
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f"{width}px revision editors: {sizes[0]['height']:g}px, long text, discard and save passed")
    page.close()


def verify_management(page, output):
    nav(page, "导入")
    upload = page.get_by_role("button", name="上传文件")
    page.locator(".drop input").set_input_files({"name": "sample.html", "mimeType": "text/html", "buffer": b"<p>sample</p>"})
    expect(upload).to_be_disabled()
    page.get_by_role("checkbox", name="我确认有权导入并处理这些文件").check()
    expect(upload).to_be_enabled()
    upload.click()
    expect(page.get_by_text("sample.html：已导入，请到任务页启动处理")).to_be_visible()
    for name in ("抖音分享链接", "上传Obsidian更新", "抖音收藏"):
        page.locator(".import-panel summary").get_by_text(name, exact=True).click()
    expect(page.get_by_text("收藏视频样例", exact=True)).to_be_visible()
    badge = page.locator('.favorites-list .media-type-badge[data-kind="video"]')
    expect(badge).to_have_css("background-color", "rgba(0, 0, 0, 0)")
    expect(badge).to_have_css("color", "rgb(194, 65, 12)")
    expect(badge.locator("svg")).to_have_css("stroke", "rgb(194, 65, 12)")
    screenshot(page, output, "import")
    nav(page, "任务")
    tasks = page.locator(".task-item")
    expect(tasks).to_have_count(5)
    for kind, color in (("album", "rgb(4, 120, 87)"), ("video", "rgb(194, 65, 12)"), ("web", "rgb(29, 78, 216)")):
        badge = tasks.locator(f'.media-type-badge[data-kind="{kind}"]').first
        expect(badge).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        expect(badge).to_have_css("color", color)
        expect(badge.locator("svg")).to_have_css("stroke", color)
    screenshot(page, output, "tasks")
    task_sort = page.get_by_role("button", name=re.compile("^按更新时间排序"))
    task_sort.click()
    expect(tasks.first).to_contain_text("待分类的网页资料")
    task_sort.click()
    expect(tasks.first).to_contain_text("从用户反馈改进知识库检索")
    page.get_by_role("button", name="已归档", exact=True).click()
    expect(tasks).to_have_count(1)
    page.locator(".task-search input").fill("不匹配")
    expect(page.get_by_text("没有符合筛选条件的任务。")).to_be_visible()
    nav(page, "分类")
    expect(page.get_by_role("rowheader", name="智能体")).to_be_visible()
    page.get_by_role("searchbox", name="搜索名称或别名").fill("Agent")
    edit = page.get_by_role("button", name="编辑 智能体")
    edit.click()
    editor = page.get_by_role("dialog", name="编辑分类")
    expect(editor).to_be_visible()
    screenshot(page, output, "catalog-editor")
    page.keyboard.press("Escape")
    expect(editor).to_be_hidden()
    expect(edit).to_be_focused()
    screenshot(page, output, "catalog")
    nav(page, "资料库")
    page.get_by_role("button", name="回收站", exact=True).click()
    expect(page.get_by_text("可撤销的网页资料")).to_be_visible()
    screenshot(page, output, "trash")
    page.get_by_role("button", name="撤销删除").click()
    expect(page.get_by_text("回收站为空。")).to_be_visible()


def verify_task_failure_priority(browser, address, output):
    fixture = Fixture()
    budget_error = 'budget_invalid_or_exceeded'
    model_error = 'provider_http_402'
    blocked, original = fixture.tasks[4], fixture.tasks[1]
    for task, code in ((blocked, budget_error), (original, model_error)):
        task.update(status='needs_attention', stage='text', error_code=code,
                    resume_blocked_reason='unknown_submission', dispatch={'state': 'error', 'error_code': code},
                    model_diagnostic={'stage': 'text', 'code': model_error})
    blocked['model_recovery'] = {'stage': 'text', 'mode': 'restore', 'attempt': 1, 'amount': None,
                                 'reason': None, 'authorized_amount': '0.705536'}
    blocked['budget_block'] = {'required_cny':'0.705536', 'available_cny':'0.559282'}

    page, errors = open_page(browser, address, fixture, 1440, 900)
    nav(page, '任务')
    blocked_row = page.locator('.task-item').filter(has_text=blocked['source']['title'])
    original_row = page.locator('.task-item').filter(has_text=original['source']['title'])
    expect(blocked_row.locator('.task-line')).to_have_text('任务或累计预算不足，无法自动重试。')
    expect(original_row.locator('.task-line')).to_contain_text(model_error)
    blocked_row.get_by_role('button', name='处理模型请求').click()
    details = blocked_row.locator('.task-details')
    expect(details.locator('dt:text-is("当前原因") + dd')).to_contain_text(budget_error)
    expect(details.locator('dt:text-is("上次模型失败原因") + dd')).to_contain_text(model_error)
    expect(details.locator('dt:text-is("恢复限制") + dd')).to_contain_text('unknown_submission')
    expect(blocked_row.get_by_role('button', name='继续已授权的重试')).to_be_visible()
    screenshot(page, output, 'task-current-error')
    expect(blocked_row.get_by_text('本次需预留 ¥0.705536，项目当前可用 ¥0.559282')).to_be_visible()
    blocked_row.get_by_role('button', name='查看预算').click()
    expect(page.get_by_role('heading', name='预算', exact=True)).to_be_visible()
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    assert not any(path.endswith('/recover-model') for _, path, _ in fixture.writes)
    print('Task rows prioritize the latest blocking error and retain the previous model error in details')
    page.close()


def verify_video_recovery(browser, address, output, width, height):
    fixture = Fixture()
    fixture.live_video_enabled = True
    visual, cache = fixture.tasks[0], fixture.tasks[2]
    visual.update(status='needs_attention', error_code='asr_remote_failed', resume_blocked_reason='asr_remote_failed', failure_stage='asr_result',
                  video_recovery={'mode':'visual-only', 'amount_cny':'1.20'}, dispatch={'state':'error'})
    cache.update(status='failed', archived=False, error_code='invalid_frame', retry_blocked_reason='attempts_exhausted',
                 attempts=3, max_attempts=3, video_recovery={'mode':'rebuild-media'}, dispatch={'state':'error'})
    page, errors = open_page(browser, address, fixture, width, height)
    nav(page, '任务')
    visual_row = page.locator('.task-item').filter(has_text=visual['source']['title'])
    cache_row = page.locator('.task-item').filter(has_text=cache['source']['title'])
    expect(visual_row.locator('.task-line')).to_contain_text('语音识别服务未返回可用转录')
    expect(cache_row.locator('.task-line')).to_contain_text('画面帧无效')
    expect(cache_row.get_by_role('button', name='重试', exact=True)).to_have_count(0)
    expect(visual_row.get_by_role('button', name='恢复', exact=True)).to_have_count(0)
    expect(cache_row.get_by_text('已尝试 3 次 · 常规上限 3 次')).to_be_visible()
    visual_row.get_by_role('button', name='详情', exact=True).click()
    expect(visual_row.locator('.task-details dt:text-is("失败阶段") + dd')).to_have_text('获取转录结果')
    expect(visual_row.locator('.task-details dt:text-is("下一步") + dd')).to_contain_text('已提取的画面')
    expect(visual_row.get_by_text('剩余步骤预计预留 ¥1.20。', exact=False)).to_be_visible()
    expect(visual_row.get_by_role('button', name='仅按画面和原文继续')).to_be_disabled()
    screenshot(page, output, 'video-recovery')
    page.get_by_text('处理设置', exact=True).click()
    page.get_by_role('checkbox', name='我同意所选视频或网页模型处理产生费用').check()
    visual_row.get_by_role('button', name='仅按画面和原文继续').click()
    expect(visual_row.get_by_text('已排队', exact=True)).to_be_visible()
    expect(visual_row.get_by_role('button', name='仅按画面和原文继续')).to_have_count(0)
    cache_row.get_by_role('button', name='重建缓存并重试').click()
    expect(cache_row.get_by_text('已排队', exact=True)).to_be_visible()
    assert ('POST', '/tasks/task0/visual-only', {'allow_paid':True}) in fixture.writes
    assert ('POST', '/tasks/task2/rebuild-media', {'allow_paid':True}) in fixture.writes
    fixture.sources[0]['transcript_status'] = 'no_speech'
    visual_row.get_by_role('button', name='查看资料', exact=True).click()
    page.get_by_role('button', name='语音转录', exact=True).click()
    expect(page.get_by_text('未检测到可转录语音。', exact=True)).to_be_visible()
    expect(page.get_by_text('暂无此项内容', exact=True)).to_have_count(0)
    print(f'{width}px video recovery actions and no-speech reading state passed')
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    page.close()


def verify_retry_consent(browser, address, output, width, height):
    fixture = Fixture()
    fixture.live_video_enabled = True
    video, webpage = fixture.tasks[:2]
    video.update(status='failed', error_code='budget_invalid_or_exceeded')
    webpage.update(status='failed', error_code='empty_output')
    page, errors = open_page(browser, address, fixture, width, height)
    nav(page, '任务')
    video_row = page.locator('.task-item').filter(has_text=video['source']['title'])
    web_row = page.locator('.task-item').filter(has_text=webpage['source']['title'])
    retry = video_row.get_by_role('button', name='重试', exact=True)
    icon = video_row.get_by_role('button', name='查看重试提示')
    hint = video_row.locator('.task-retry-hint')
    budget = video_row.get_by_role('button', name='查看预算')
    expect(retry).to_be_disabled()
    expect(icon).to_be_visible()
    expect(hint).to_be_hidden()
    expect(retry).to_have_accessible_description('重试前，请在「处理设置」勾选同意模型费用。')
    expect(budget).to_be_enabled()
    expect(web_row.get_by_role('button', name='重试', exact=True)).to_be_enabled()
    expect(web_row.locator('.task-retry-hint')).to_have_count(0)
    icon_box, button_box = icon.bounding_box(), retry.bounding_box()
    assert abs(icon_box['x'] - button_box['x'] - button_box['width']) <= 1
    assert video_row.locator('.task-actions').evaluate('el => el.scrollWidth === el.clientWidth')
    screenshot(page, output, 'task-retry-icon')

    if width <= 390:
        icon.tap()
    else:
        icon.hover()
    expect(hint).to_be_visible()
    hint_box, icon_box = hint.bounding_box(), icon.bounding_box()
    assert 0 <= hint_box['x'] <= hint_box['x'] + hint_box['width'] <= width
    assert 0 <= hint_box['y'] <= hint_box['y'] + hint_box['height'] <= height
    assert hint_box['y'] + hint_box['height'] <= icon_box['y'] or icon_box['y'] + icon_box['height'] <= hint_box['y']
    screenshot(page, output, 'task-retry-tooltip')
    if width <= 390:
        page.get_by_role('heading', name='任务', exact=True).tap()
    else:
        hint.hover()
        expect(hint).to_be_visible()
        budget.hover()
    expect(hint).to_be_hidden()

    budget.focus()
    page.keyboard.press('Tab')
    expect(icon).to_be_focused()
    expect(hint).to_be_visible()
    page.keyboard.press('Escape')
    expect(hint).to_be_hidden()
    expect(icon).to_be_focused()

    page.get_by_text('处理设置', exact=True).click()
    consent = page.get_by_role('checkbox', name='我同意所选视频或网页模型处理产生费用')
    consent.check()
    expect(retry).to_be_enabled()
    expect(hint).to_have_count(0)
    expect(icon).to_have_count(0)
    expect(retry).not_to_have_attribute('aria-describedby', re.compile('.+'))
    consent.uncheck()
    expect(retry).to_be_disabled()
    expect(icon).to_be_visible()
    expect(hint).to_be_hidden()
    assert not any(path.endswith('/retry') for _, path, _ in fixture.writes)
    consent.check()
    retry.click()
    expect(video_row.get_by_text('已排队', exact=True)).to_be_visible()
    assert [write for write in fixture.writes if write[1].endswith('/retry')] == [
        ('POST', '/tasks/task0/retry', {'allow_paid': True, 'processing_mode': 'preview'})]
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px retry consent hint and explicit retry passed')
    page.close()


def verify_budget(browser, address, output, width, height):
    fixture = Fixture()
    page, errors = open_page(browser, address, fixture, width, height)
    nav(page, '预算')
    panel = page.locator('.budget-page')
    expect(panel.get_by_text('¥0.559282', exact=True)).to_be_visible()
    expect(panel.get_by_text('待核对 1 项', exact=True)).to_be_visible()
    expect(panel.get_by_role('row').filter(has_text='图文笔记')).to_contain_text('待核对')
    expect(panel.get_by_role('row').filter(has_text='知识库检索与问答')).to_contain_text('预留上限 ¥1.25')
    assert panel.locator('.budget-table-wrap').evaluate('element => element.scrollWidth === element.clientWidth')
    assert page.get_by_role('navigation', name='主导航').evaluate('element => element.scrollWidth === element.clientWidth')
    amount = panel.get_by_role('textbox', name='项目累计上限（元）')
    save = panel.get_by_role('button', name='保存上限')
    amount.fill('150.251')
    expect(save).to_be_disabled()
    amount.fill('150.25')
    expect(panel.get_by_text('当前上限 ¥100，调整后 ¥150.25，预计可用 ¥50.809282。')).to_be_visible()
    screenshot(page, output, 'budget')
    save.click()
    expect(panel.get_by_text('预算上限已保存。')).to_be_visible()
    expect(panel.get_by_text('¥50.809282', exact=True)).to_be_visible()
    expect(panel.get_by_text(re.compile('¥100 → ¥150.25'))).to_be_visible()
    assert [path for _, path, _ in fixture.writes if path != '/auth/activity'] == ['/budget']
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px budget totals, edit preview and save passed')
    page.close()


def verify_favorites_budget(browser, address, output, width, height):
    class FavoritesBudgetFixture(Fixture):
        def respond(self, route):
            request = route.request
            path = urlsplit(request.url).path.removeprefix('/api')
            if path == '/budget/favorites-limits' and request.method == 'PATCH':
                body = request.post_data_json
                self.writes.append(('PATCH', path, body))
                limits = self.budget['favorites_limits']
                assert body == {'max_images': 40, 'download_limit': 6, 'expected_revision': 1,
                                'video_budget_cny': '4.20', 'daily_budget_cny': '13.31'}
                limits.update(body)
                limits.update(revision=2, conversion_remaining_cny='2.57', changes=[{
                    'previous_max_images': 40, 'max_images': 40, 'previous_download_limit': 5,
                    'download_limit': 6, 'previous_video_budget_cny': '4.05', 'video_budget_cny': '4.20',
                    'previous_daily_budget_cny': '12.15', 'daily_budget_cny': '13.31', 'changed_at': '2026-11-25T02:00:00Z',
                }])
                route.fulfill(json=limits)
            elif path == '/tasks/task0/reauthorize-favorites' and request.method == 'POST':
                body = request.post_data_json
                self.writes.append(('POST', path, body))
                assert re.fullmatch(r'[0-9a-f-]{36}', body['request_id'])
                assert body == {'allow_paid': True, 'amount_cny': '4.12', 'request_id': body['request_id'],
                                'expected_ceiling_cny': '4.05', 'expected_required_cny': '4.12'}
                self.budget['favorites_reauthorizations'] = [
                    item for item in self.budget['favorites_reauthorizations'] if item['task_id'] != 'task0'
                ]
                self.tasks[0].pop('favorites_reauthorization')
                self.tasks[0].update(status='queued', error_code=None, dispatch={'state': 'pending'})
                route.fulfill(json={'task_id': 'task0', 'dispatch_state': 'pending', 'duplicate': False})
            else:
                super().respond(route)

    fixture = FavoritesBudgetFixture()
    fixture.live_video_enabled = True
    quote = {'authorized_cny': '4.05', 'required_cny': '4.12', 'available_cny': '5'}
    fixture.tasks[0].update(status='failed', error_code='favorites_budget_exceeded',
                            retry_blocked_reason='favorites_budget_exceeded', favorites_reauthorization=quote)
    wait = {'required_cny': '2.57', 'available_cny': '1.41'}
    fixture.tasks[4].update(status='queued', conversion_wait={'code': 'favorites_daily_budget_limit', **wait})
    fixture.tasks[5].update(status='queued', conversion_wait={'code': 'favorites_daily_count_limit'})
    fixture.budget.update(limit_cny='150.25', available_cny='50.809282', favorites_limits={
        'day': '2026-11-25', 'max_images': 40, 'download_limit': 5, 'downloads_used': 4, 'conversions_used': 3,
        'video_budget_cny': '4.05', 'daily_budget_cny': '12.15', 'conversion_reserved_cny': '10.74',
        'conversion_remaining_cny': '1.41', 'revision': 1, 'changes': [],
    }, favorites_reauthorizations=[
        {'task_id': 'task0', 'title': fixture.sources[0]['title'], **quote},
        {'task_id': 'old-strategy', 'title': '旧策略视频', 'authorized_cny': '4.05', 'required_cny': None,
         'blocked_reason': 'favorites_reauthorization_strategy_changed'},
    ])

    page, errors = open_page(browser, address, fixture, width, height)
    nav(page, '任务')
    expect(page.get_by_text('等待每日转换预算', exact=False)).to_be_visible()
    expect(page.get_by_text('等待每日转换名额', exact=True)).to_be_visible()
    failed = page.locator('.task-item').filter(has_text=fixture.sources[0]['title'])
    expect(failed.get_by_text('原授权 ¥4.05 · 所需预留 ¥4.12')).to_be_visible()
    expect(failed.get_by_role('button', name='重试', exact=True)).to_have_count(0)
    screenshot(page, output, 'favorites-budget-waits')
    failed.get_by_role('button', name='查看预算').click()
    panel = page.locator('.budget-page')
    expect(panel.get_by_text('转换已用 3 / 5 条', exact=False)).to_be_visible()
    panel.get_by_role('spinbutton', name='每日定时处理上限（条/天）').fill('6')
    panel.get_by_role('textbox', name='单视频预留上限（元）').fill('4.20')
    panel.get_by_role('textbox', name='每日转换预算（元）').fill('13.31')
    panel.get_by_role('button', name='保存限制').click()
    expect(panel.get_by_text('收藏处理限制已保存。')).to_be_visible()
    expect(panel.get_by_text('转换已用 3 / 6 条', exact=False)).to_be_visible()
    expect(panel.get_by_text('每日转换 ¥12.15 → ¥13.31', exact=False)).to_be_visible()
    screenshot(page, output, 'favorites-budget-settings')

    blocked = panel.get_by_role('listitem').filter(has_text='旧策略视频')
    expect(blocked).to_contain_text('无法用当前视频处理策略继续原任务')
    expect(blocked.get_by_role('button', name='重新授权', exact=True)).to_be_disabled()
    button = panel.get_by_role('listitem').filter(has_text=fixture.sources[0]['title']).get_by_role('button', name='重新授权', exact=True)
    button.click()
    dialog = page.get_by_role('dialog', name='确认重新授权')
    submit = dialog.get_by_role('button', name='确认授权', exact=True)
    amount = dialog.get_by_role('textbox', name='本次授权上限（元）')
    expect(amount).to_have_value('4.12')
    expect(submit).to_be_disabled()
    dialog.get_by_role('button', name='取消').click()
    expect(button).to_be_focused()
    assert not any(path.endswith('/reauthorize-favorites') for _, path, _ in fixture.writes)
    button.click()
    dialog.get_by_role('checkbox', name='我同意本次转换可能产生的模型费用').check()
    amount.fill('4.11')
    expect(submit).to_be_disabled()
    amount.fill('5.01')
    expect(submit).to_be_disabled()
    amount.fill('4.12')
    expect(submit).to_be_enabled()
    screenshot(page, output, 'favorites-budget-reauthorize')
    submit.click()
    expect(panel.get_by_text('已重新授权，任务已排队。')).to_be_visible()
    expect(button).to_have_count(0)
    assert sum(path.endswith('/reauthorize-favorites') for _, path, _ in fixture.writes) == 1
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px shared favorites limits, wait reasons and reauthorization passed')
    page.close()


def verify_task_favorites_reauthorization(browser, address, output, width, height):
    class ReauthorizationFixture(Fixture):
        def __init__(self):
            super().__init__()
            self.live_video_enabled = True
            self.authorizations = []
            self.accepted_request = None
            self.tasks[0].update(
                status='failed', error_code='favorites_budget_exceeded',
                retry_blocked_reason='favorites_budget_exceeded',
                favorites_reauthorization={'authorized_cny': '4.05', 'required_cny': '4.12', 'available_cny': '5.0001'},
            )
            self.tasks[2].update(
                status='failed', archived=False, error_code='favorites_budget_exceeded',
                retry_blocked_reason='favorites_budget_exceeded',
                favorites_reauthorization={'authorized_cny': '4.05', 'required_cny': None,
                                           'blocked_reason': 'favorites_reauthorization_strategy_changed'},
            )

        def respond(self, route):
            request = route.request
            path = urlsplit(request.url).path.removeprefix('/api')
            if request.method != 'POST' or path != '/tasks/task0/reauthorize-favorites':
                return super().respond(route)
            payload = request.post_data_json
            self.authorizations.append(payload)
            assert re.fullmatch(r'[0-9a-f-]{36}', payload['request_id'])
            assert payload == {'allow_paid': True, 'amount_cny': '4.12', 'request_id': payload['request_id'],
                               'expected_ceiling_cny': '4.05', 'expected_required_cny': '4.12'}
            if len(self.authorizations) == 1:
                return route.fulfill(status=409, json={'error': 'favorites_reauthorization_conflict'})
            if len(self.authorizations) == 2:
                self.accepted_request = payload
                self.tasks[0].pop('favorites_reauthorization')
                self.tasks[0].pop('retry_blocked_reason')
                self.tasks[0].update(status='queued', error_code=None, dispatch={'state': 'pending'})
                return route.abort('failed')
            assert payload == self.accepted_request
            return route.fulfill(json={'task_id': 'task0', 'dispatch_state': 'pending', 'duplicate': True})

    fixture = ReauthorizationFixture()
    page, errors = open_page(browser, address, fixture, width, height)
    nav(page, '任务')
    row = page.locator('.task-item').filter(has_text=fixture.sources[0]['title'])
    blocked = page.locator('.task-item').filter(has_text=fixture.sources[2]['title'])
    button = row.get_by_role('button', name='重新授权并重试', exact=True)
    expect(blocked.get_by_role('button', name='重新授权并重试', exact=True)).to_have_count(0)
    expect(blocked.get_by_role('button', name='查看预算', exact=True)).to_be_visible()
    expect(row.get_by_role('button', name='查看预算', exact=True)).to_be_visible()
    expect(button).to_be_enabled()
    button.scroll_into_view_if_needed()
    screenshot(page, output, 'task-reauthorize-entry')

    dialog = page.get_by_role('dialog', name='确认重新授权')
    submit = dialog.get_by_role('button', name='确认授权', exact=True)
    amount = dialog.get_by_role('textbox', name='本次授权上限（元）')
    consent = dialog.get_by_role('checkbox', name='我同意本次转换可能产生的模型费用')
    button.click()
    expect(page.locator('.budget-page')).to_have_count(0)
    expect(dialog).to_contain_text('原授权 ¥4.05')
    expect(dialog).to_contain_text('本次至少需预留 ¥4.12')
    expect(amount).to_have_value('4.12')
    expect(submit).to_be_disabled()
    dialog.get_by_role('button', name='取消', exact=True).click()
    expect(dialog).to_be_hidden()
    expect(button).to_be_focused()
    button.click()
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(button).to_be_focused()
    assert not fixture.authorizations

    button.click()
    consent.check()
    for value in ('4.11', '5.01'):
        amount.fill(value)
        expect(submit).to_be_disabled()
    amount.fill('4.12')
    screenshot(page, output, 'task-reauthorize-dialog')
    submit.click()
    expect(dialog.get_by_role('alert')).to_contain_text('任务状态或预留金额已更新')
    dialog.get_by_role('button', name='取消', exact=True).click()

    button.click()
    consent.check()
    submit.click()
    expect(dialog.get_by_role('alert')).to_be_visible()
    expect(submit).to_be_enabled()
    # Simulate two submissions before React can render the disabled button.
    submit.evaluate('button => { button.form.requestSubmit(button); button.form.requestSubmit(button); }')
    expect(dialog).to_be_hidden()
    expect(row.get_by_text('已排队', exact=True)).to_be_visible()
    expect(button).to_have_count(0)
    assert len(fixture.authorizations) == 3
    assert fixture.authorizations[0]['request_id'] != fixture.authorizations[1]['request_id']
    assert fixture.authorizations[1] == fixture.authorizations[2]
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px task reauthorization, cancel and retry guards passed')
    page.close()


def verify_favorites_filters(browser, address, output, width, height):
    fixture = Fixture()
    page, errors = open_page(browser, address, fixture, width, height)
    items = [dict(work_id=f'available-{i}', title=f'可导入作品 {i}', kind='video',
                  status=None, selectable=True) for i in range(87)]
    items += [dict(work_id=f'available-image-{i}', title=f'可导入图文 {i}', kind='image',
                   status=None, selectable=True, image_count=1, image_quote_cny='1.61') for i in range(19)]
    items += [dict(work_id=f'imported-{i}', title=f'已导入作品 {i}', kind='video',
                   status='converted', selectable=False) for i in range(15)]
    items += [dict(work_id=f'image-failed-{i}', title=f'图文异常 {i}', kind='image',
                   status='conversion_failed', selectable=False, image_count=1, image_quote_cny='1.61') for i in range(7)]
    items += [dict(work_id=f'video-failed-{i}', title=f'视频异常 {i}', kind='video',
                   status='conversion_failed', selectable=False) for i in range(3)]
    items += [dict(work_id=f'image-limit-{i}', title=f'图片超限 {i}', kind='image',
                   status=None, selectable=False, image_count=41, image_quote_error='album_image_limit') for i in range(2)]
    # A selectable flag without a valid quote must still stay out of the import selection.
    items[-1]['selectable'] = True

    def favorites(route):
        route.fulfill(json={'enabled':True, 'state':'ready', 'download_limit':3,
                            'manual_video_budget_cny':'0.30', 'items':items})
    page.route(f'{address}/api/douyin/favorites/sync', favorites)
    nav(page, '导入')
    page.locator('.import-panel summary').get_by_text('抖音收藏', exact=True).click()
    filters = page.get_by_role('group', name='按导入状态筛选')
    rows = page.locator('.favorites-row')
    for label, count in [('全部',133), ('可导入',106), ('已导入',15), ('其他状态',12)]:
        button = filters.get_by_role('button', name=f'{label} {count}', exact=True)
        button.click()
        expect(button).to_have_attribute('aria-pressed', 'true')
        expect(rows).to_have_count(count)
    expect(rows.filter(has_text='转换异常，请查看任务详情')).to_have_count(10)
    expect(rows.filter(has_text='图片数量超限')).to_have_count(2)
    expect(rows.locator('.favorites-checkbox')).to_have_count(0)
    expect(page.get_by_role('button', name='全选可导入作品')).to_have_count(0)
    for kind, color in [('video','rgb(194, 65, 12)'), ('album','rgb(4, 120, 87)')]:
        badge = rows.locator(f'.media-type-badge[data-kind="{kind}"]').first
        expect(badge).to_have_css('background-color','rgba(0, 0, 0, 0)')
        expect(badge).to_have_css('color',color)
        expect(badge.locator('svg')).to_have_css('stroke',color)
    screenshot(page, output, 'favorites-other')
    filters.get_by_role('button', name='全部 133', exact=True).click()
    page.get_by_role('button', name='全选可导入作品').click()
    expect(rows.locator('input:checked')).to_have_count(106)
    expect(rows.filter(has_text='转换异常').locator('input:checked')).to_have_count(0)
    filters.get_by_role('button', name='可导入 106', exact=True).click()
    expect(rows).to_have_count(106)
    expect(rows.locator('input:checked')).to_have_count(106)
    expect(rows.filter(has_text='可导入图文').locator('input:checked')).to_have_count(19)
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}px favorites partition, type colors, selection passed')
    page.close()


def verify_favorites_confirmation(browser, address, output, width, height):
    fixture = Fixture()
    fixture.poll_interval_ms = 500
    page, errors = open_page(browser, address, fixture, width, height)
    video_title = '约束解码与 JSON Schema 结构化输出'
    album_title = '浏览器自动化的版本答案：ego lite'
    items = [
        dict(work_id='101', title=video_title, kind='video', status=None, selectable=True),
        dict(work_id='102', title=album_title, kind='image', status=None,
             selectable=True, image_count=4, image_quote_cny='2.19'),
        *[dict(work_id=str(i), title=f'测试收藏作品 {i}', kind='video', status=None, selectable=True)
          for i in range(103, 119)],
    ]
    submissions = []

    def favorites(route):
        route.fulfill(json=dict(enabled=True, state='ready', download_limit=3, baseline_limit=100,
                               active_account=dict(id='test-account', label='隔离账号'),
                               manual_conversion_available=True, manual_video_budget_cny='4.05', items=items))

    def enqueue(route):
        payload = route.request.post_data_json
        submissions.append(payload)
        for item in items:
            if item['work_id'] in payload['work_ids']:
                item.update(status='queued', selectable=False)
        route.fulfill(json={'queued': 2})

    page.route(f'{address}/api/douyin/favorites/sync', favorites)
    page.route(f'{address}/api/douyin/favorites/import', enqueue)
    nav(page, '导入')
    summary = page.get_by_text('抖音收藏', exact=True)
    summary.click()
    list_box = page.locator('.favorites-fieldset')
    dock = page.get_by_role('region', name='已选作品')
    first = page.get_by_role('checkbox', name=video_title)
    expect(first).to_be_visible()
    expect(dock).to_have_count(0)
    assert list_box.evaluate("node => Math.abs(node.getBoundingClientRect().width - node.parentElement.clientWidth) <= 1")
    first.check()
    expect(dock.get_by_text('¥4.05')).to_be_visible()
    screenshot(page, output, 'favorites-dock')
    last = page.get_by_role('checkbox', name='测试收藏作品 118')
    last.focus()
    last.scroll_into_view_if_needed()
    assert last.evaluate("""node => node.getBoundingClientRect().bottom <=
        document.querySelector('.favorites-batch-bar').getBoundingClientRect().top""")
    page.get_by_role('checkbox', name=album_title).check()
    expect(dock.get_by_text('¥6.24')).to_be_visible()
    trigger = dock.get_by_role('button', name='确认导入')
    trigger.click()
    dialog = page.get_by_role('dialog', name='导入确认')
    expect(dialog.get_by_text(video_title, exact=True)).to_be_visible()
    expect(dialog.get_by_text(album_title, exact=True)).to_be_visible()
    expect(dialog.get_by_text('¥6.24')).to_be_visible()
    assert dialog.get_by_role('list', name='本次导入作品').get_by_role('listitem').count() == 2
    rights = dialog.get_by_role('checkbox', name=re.compile('我确认有权'))
    paid = dialog.get_by_role('checkbox', name=re.compile('我同意所选作品'))
    submit = dialog.get_by_role('button', name='下载并转换所选作品')
    expect(submit).to_be_disabled()
    rights.check()
    expect(submit).to_be_disabled()
    paid.check()
    expect(submit).to_be_enabled()
    screenshot(page, output, 'favorites-confirmation')
    assert not submissions
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    expect(dock.get_by_text('¥6.24')).to_be_visible()
    trigger.click()
    expect(rights).not_to_be_checked()
    expect(paid).not_to_be_checked()
    rights.check()
    paid.check()
    items[1]['image_quote_cny'] = '2.38'
    expect(dialog.get_by_text('¥6.43')).to_be_visible()
    expect(paid).not_to_be_checked()
    expect(submit).to_be_disabled()
    paid.check()
    submit.click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_text('已将 2 条作品排队下载和转换。', exact=True)).to_be_visible()
    expect(dock).to_have_count(0)
    assert submissions == [dict(account_id='test-account', work_ids=['101', '102'], rights_confirmed=True,
                                allow_paid=True, video_budget_cny='4.05', image_quotes={'102': '2.38'})]
    page.get_by_role('checkbox', name='测试收藏作品 103').check()
    page.get_by_role('button', name='清空选择').click()
    expect(dock).to_have_count(0)
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    print(f'{width}×{height} favorites full width, dock, consent and queue passed')
    page.close()


def verify_connection(browser, address, output):
    fixture = Fixture()
    fixture.logged_in = False
    fixture.fail_read = True
    page, errors = open_page(browser, address, fixture, 390, 844)
    expect(page.get_by_role("alert")).to_be_visible()
    screenshot(page, output, "disconnected")
    fixture.fail_read = False
    page.get_by_role("button", name="重试连接").click()
    expect(page.get_by_role("heading", name="登录个人知识库")).to_be_visible()
    screenshot(page, output, "login")
    page.get_by_label("密码").fill("isolated")
    fixture.hold_sources = True
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_text("正在读取资料与分类…")).to_be_visible()
    screenshot(page, output, "loading")
    fixture.pending_sources.fulfill(json={"items": fixture.sources})
    expect(page.locator(".library-source-row")).to_have_count(6)
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    page.close()


def verify_scroll(browser, address):
    fixture = Fixture()
    page, errors = open_page(browser, address, fixture, 1280, 480)
    rows = page.locator(".library-source-row")
    expect(rows).to_have_count(6)
    region = page.locator(".library-scroll")
    region.evaluate("e => {e.scrollTop=150}")
    sticky = page.locator(".library-column-head")
    assert abs(sticky.bounding_box()["y"] - region.bounding_box()["y"] - 1) <= 1
    target = rows.nth(2).locator(".source")
    pane = region.bounding_box()
    title = target.bounding_box()
    assert sticky.bounding_box()["y"] + sticky.bounding_box()["height"] <= title["y"] < pane["y"] + pane["height"]
    scroll_position = region.evaluate("e => e.scrollTop")
    target.click()
    page.get_by_role("button", name=re.compile("返回资料库")).click()
    assert region.evaluate("e => e.scrollTop") == scroll_position
    last = rows.last.locator(".source")
    last.focus()
    page.keyboard.press("Shift+Tab")
    focused = page.locator(".library-source-row input:focus").bounding_box()
    assert focused["y"] >= sticky.bounding_box()["y"] + sticky.bounding_box()["height"]
    assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
    page.close()


def snapshot_baseline(browser, address, output):
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1440, 900), (861, 800), (768, 800), (390, 844)):
        fixture = Fixture()
        page, errors = open_page(browser, address, fixture, width, height)
        expect(page.locator(".library-source-row")).to_have_count(6)
        screenshot(page, output, "library")
        if width in (1440, 390):
            verify_detail(page, fixture, output)
            verify_ask(page, output, baseline=True)
            verify_management(page, output)
        assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
        page.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--screenshots", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Optional build from before the changes")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=3500)
    with serve(args.build) as address, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        for width, height in ((1440, 900), (861, 800), (768, 800), (390, 844)):
            fixture = Fixture()
            page, errors = open_page(browser, address, fixture, width, height)
            verify_library(page, args.screenshots)
            if width in (1440, 768, 390):
                verify_detail(page, fixture, args.screenshots)
                verify_ask(page, args.screenshots)
                verify_management(page, args.screenshots)
            assert not fixture.unexpected and not errors, (fixture.unexpected, errors)
            print(f"{width}px browser assertions passed")
            page.close()
            verify_retry_consent(browser, address, args.screenshots, width, height)
        verify_connection(browser, address, args.screenshots)
        verify_login_errors(browser, address)
        for width in (390, 320):
            verify_mobile_review_feedback(browser, address, args.screenshots, width)
        verify_scroll(browser, address)
        verify_task_failure_priority(browser, address, args.screenshots)
        for width, height in ((1440, 900), (390, 844)):
            verify_video_recovery(browser, address, args.screenshots, width, height)
            verify_budget(browser, address, args.screenshots, width, height)
            verify_favorites_budget(browser, address, args.screenshots, width, height)
            verify_task_favorites_reauthorization(browser, address, args.screenshots, width, height)
            verify_library_version_gate(browser, address, width, height)
            verify_revision_editor(browser, address, args.screenshots, width, height)
            verify_favorites_filters(browser, address, args.screenshots, width, height)
        for width, height in ((1874, 676), (390, 844)):
            verify_favorites_confirmation(browser, address, args.screenshots, width, height)
        print("Connection, retry and login assertions passed")
        print("List scroll restoration and sticky header focus assertions passed")
        if args.baseline:
            with serve(args.baseline) as baseline_address:
                snapshot_baseline(browser, baseline_address, args.screenshots / "before")
            print("Same-state baseline screenshots captured")


if __name__ == "__main__":
    main()
