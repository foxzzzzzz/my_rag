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
        self.hold_sources = False
        self.pending_sources = None
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
                    "auth_enabled": True, "poll_interval_ms": 60000, "quality_target": 98,
                    "display_timezone": "Asia/Shanghai", "live_html_enabled": False, "live_video_enabled": False,
                    "max_upload_bytes": 1048576, "max_html_bytes": 1048576,
                }})
            if path == "/sources":
                if self.hold_sources:
                    self.pending_sources = route
                    return
                return reply({"items": self.sources})
            if path == "/tasks":
                return reply({"items": self.tasks})
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
                                               "body": "## 正文内容\n\n原文保留。", "visual": "画面中的步骤。"}},
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


def verify_ask(page, output):
    nav(page, "问答")
    expect(page.get_by_text("索引可用", exact=True)).to_be_visible()
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
    screenshot(page, output, "ask")


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
    expect(page.locator('.favorites-list .media-type-badge[data-kind="video"]')).to_have_css("background-color", "rgb(194, 65, 12)")
    screenshot(page, output, "import")
    nav(page, "任务")
    tasks = page.locator(".task-item")
    expect(tasks).to_have_count(5)
    expect(tasks.locator('.media-type-badge[data-kind="album"]').first).to_have_css("background-color", "rgb(4, 120, 87)")
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
            verify_ask(page, output)
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
        verify_connection(browser, address, args.screenshots)
        verify_scroll(browser, address)
        print("Connection, retry and login assertions passed")
        print("List scroll restoration and sticky header focus assertions passed")
        if args.baseline:
            with serve(args.baseline) as baseline_address:
                snapshot_baseline(browser, baseline_address, args.screenshots / "before")
            print("Same-state baseline screenshots captured")


if __name__ == "__main__":
    main()
