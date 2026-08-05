"""Static contracts for the public VELO website and Garmin application pages."""

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"
LEGAL_NAME = "湖南湘江新区共演纪软件开发有限责任公司"
ICP_RECORD = "湘ICP备2026023052号-1"
ICP_QUERY_URL = "https://beian.miit.gov.cn/"
SITE_STYLESHEET_URL = "/assets/site.css?v=20260805a"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.stylesheets: list[str] = []
        self.lang: str | None = None
        self.has_title = False
        self.has_viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "link" and values.get("href"):
            self.links.append(values["href"])
            rel_tokens = (values.get("rel") or "").lower().split()
            if "stylesheet" in rel_tokens:
                self.stylesheets.append(values["href"])
        if tag == "img" and values.get("src"):
            self.links.append(values["src"])
        if tag == "meta" and values.get("name") == "viewport":
            self.has_viewport = True
        if tag == "title":
            self.has_title = True


def _html_files() -> list[Path]:
    return sorted(WEBSITE.rglob("*.html"))


def _resolve_site_path(url_path: str) -> Path:
    relative = url_path.lstrip("/")
    candidate = WEBSITE / relative
    if url_path.endswith("/"):
        return candidate / "index.html"
    if candidate.suffix:
        return candidate
    return candidate / "index.html"


def test_website_has_required_public_pages():
    expected = {
        "index.html",
        "company/index.html",
        "privacy/index.html",
        "privacy/garmin/index.html",
        "en/index.html",
        "en/company/index.html",
        "en/privacy/index.html",
        "en/privacy/garmin/index.html",
        "404.html",
        "robots.txt",
        "sitemap.xml",
        "favicon.svg",
        "assets/site.css",
        "assets/fonts/OFL.txt",
        "assets/fonts/README.md",
        "assets/fonts/velo-sans-zh-regular-v1.woff",
        "assets/fonts/velo-sans-zh-medium-v1.woff",
        "assets/fonts/velo-sans-zh-bold-v1.woff",
    }
    actual = {
        str(path.relative_to(WEBSITE))
        for path in WEBSITE.rglob("*")
        if path.is_file()
    }
    assert expected <= actual


def test_all_html_pages_are_mobile_ready_and_have_valid_internal_links():
    assert _html_files()
    for page in _html_files():
        source = page.read_text(encoding="utf-8")
        parser = _LinkParser()
        parser.feed(source)

        assert parser.lang in {"zh-CN", "en"}, page
        assert parser.has_title, page
        assert parser.has_viewport, page
        assert 'href="/favicon.svg"' in source, page
        assert SITE_STYLESHEET_URL in parser.stylesheets, page

        for href in parser.links:
            if href.startswith(("mailto:", "tel:", "#")):
                continue
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                continue
            target = _resolve_site_path(parsed.path)
            assert target.exists(), f"{page}: missing {href} -> {target}"


def test_mobile_navigation_and_footer_links_have_full_touch_targets():
    css = (WEBSITE / "assets/site.css").read_text(encoding="utf-8")
    for selector in [r"\.brand", r"\.nav-links a"]:
        rule = re.search(rf"{selector}\s*\{{(?P<body>[^}}]+)\}}", css)
        assert rule, selector
        assert re.search(r"min-height:\s*44px", rule.group("body")), selector

    footer_rule = re.search(
        r"\.footer-links a,\s*\.footer-record a\s*\{(?P<body>[^}]+)\}",
        css,
    )
    assert footer_rule
    assert re.search(r"min-height:\s*44px", footer_rule.group("body"))


def test_public_page_footers_show_the_verified_icp_record():
    footer_pages = [
        page for page in _html_files() if page.name != "404.html"
    ]
    assert footer_pages
    for page in footer_pages:
        source = page.read_text(encoding="utf-8")
        footer = re.search(r"<footer\b[^>]*>(?P<body>.*?)</footer>", source, re.DOTALL)
        assert footer, page
        body = footer.group("body")
        record_row = re.search(
            r'<div\b[^>]*class="footer-record"[^>]*>(?P<body>.*?)</div>',
            body,
            re.DOTALL,
        )
        assert record_row, page
        record_body = record_row.group("body")
        assert ICP_RECORD in record_body, page
        assert re.search(
            rf'<a\b[^>]*href="{re.escape(ICP_QUERY_URL)}"[^>]*>'
            rf'\s*{re.escape(ICP_RECORD)}\s*</a\s*>',
            record_body,
            re.DOTALL,
        ), page

    css = (WEBSITE / "assets/site.css").read_text(encoding="utf-8")
    record_rule = re.search(r"\.footer-record\s*\{(?P<body>[^}]+)\}", css)
    assert record_rule
    assert re.search(r"grid-column:\s*1\s*/\s*-1", record_rule.group("body"))
    assert re.search(r"justify-content:\s*center", record_rule.group("body"))


def test_homepage_uses_local_chinese_web_fonts_without_synthetic_weights():
    homepage = (WEBSITE / "index.html").read_text(encoding="utf-8")
    css = (WEBSITE / "assets/site.css").read_text(encoding="utf-8")
    font_files = {
        "regular": (
            WEBSITE / "assets/fonts/velo-sans-zh-regular-v1.woff",
            400,
            "4b531112cef78e73d00cba2b4530a7771f186bd4c50af52d2ceb827603cb1326",
        ),
        "medium": (
            WEBSITE / "assets/fonts/velo-sans-zh-medium-v1.woff",
            500,
            "8e8ee2ad10ba54c7a987c873715a8d2c3d37ad90ca14dd54d0e7436552e97b60",
        ),
        "bold": (
            WEBSITE / "assets/fonts/velo-sans-zh-bold-v1.woff",
            700,
            "fa4edd15a008d0decb995a51a01d6deb4263b7a24cc1f53c04218442d62dd77e",
        ),
    }

    for font_file, weight, expected_sha256 in font_files.values():
        payload = font_file.read_bytes()
        assert payload[:4] == b"wOFF", font_file
        assert 10_000 < len(payload) < 200_000, font_file
        assert hashlib.sha256(payload).hexdigest() == expected_sha256, font_file
        assert re.search(
            rf'@font-face\s*\{{[^}}]*url\("/assets/fonts/{re.escape(font_file.name)}"\)'
            rf'[^}}]*font-weight:\s*{weight}\s*;',
            css,
        ), font_file

    assert 'font-family: "VELO Sans"' in css
    assert "font-synthesis: none" in css
    assert 'type="font/woff"' in homepage
    assert "/assets/fonts/velo-sans-zh-regular-v1.woff" in homepage
    assert "/assets/fonts/velo-sans-zh-medium-v1.woff" in homepage

    home_css = css.split(".home-v2 {", 1)[1]
    assert not re.search(r"font-weight:\s*(650|750|800)\b", home_css)


def test_public_pages_identify_the_legal_operator_without_private_identifiers():
    public_sources = [
        *[page.read_text(encoding="utf-8") for page in _html_files()],
        (ROOT / "Caddyfile").read_text(encoding="utf-8"),
        (ROOT / "docker-compose.yml").read_text(encoding="utf-8"),
    ]
    combined = " ".join(
        "\n".join(public_sources).split()
    )
    assert LEGAL_NAME in combined
    assert re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", combined) is None
    assert re.search(r"(?<![0-9A-Z])[0-9A-Z]{18}(?![0-9A-Z])", combined) is None
    assert "Garmin 用户名、密码" in combined
    assert "not ask for or store a Garmin username, password" in combined


def test_garmin_policies_are_narrow_truthful_and_bilingual():
    zh = " ".join(
        (WEBSITE / "privacy/garmin/index.html").read_text(encoding="utf-8").split()
    )
    en = " ".join(
        (WEBSITE / "en/privacy/garmin/index.html").read_text(encoding="utf-8").split()
    )

    for required in [
        "申请和开发阶段",
        "官方 OAuth 2.0",
        "首版不提供向 Garmin 写入",
        "默认设为私密",
        "最多保留 30 天",
        "解绑后立即",
        "中国大陆以外",
        "外部 AI / LLM",
    ]:
        assert required in zh

    for required in [
        "application and development stage",
        "OAuth 2.0 authorization flow",
        "review the requested data scope",
        "private by default",
        "cannot download a user's raw Garmin activity file",
        "no more than 30 days",
        "outside Mainland China",
        "external AI or LLM",
        "obtain separate consent where required",
        "question or complaint",
        "security incident affects Garmin data",
    ]:
        assert required in en

    combined = zh + en
    assert "PKCE" not in combined
    assert "Works with Garmin" not in combined
    assert "Powered by Garmin" not in combined
    assert "Garmin logo" not in combined


def test_privacy_policy_matches_current_and_planned_data_boundaries():
    zh = " ".join(
        (WEBSITE / "privacy/index.html").read_text(encoding="utf-8").split()
    )
    en = " ".join(
        (WEBSITE / "en/privacy/index.html").read_text(encoding="utf-8").split()
    )
    assert "微信 OpenID" in zh
    assert "FIT/GPX" in zh
    assert "仅自己可见" in zh
    assert "分别隐藏功率和心率" in zh
    assert "可能残留，直至我们人工核查并删除" in zh
    assert "路书以及已开放的约骑内容" in zh
    assert "已开放约骑等没有自助入口" in zh
    assert "Garmin 原始活动文件在成功解析后最多保留 30 天" in zh
    assert "Garmin 正式接入前还会完成令牌静态加密" in zh
    for required in [
        "competent judicial or administrative authority",
        "storage failure may leave a residual file until VELO manually reviews and deletes it",
        "published meetup content",
        "published meetups and other content without such controls",
        "request review and deletion",
        "security incident may affect user rights",
        "Children",
        "Policy changes",
        "obtain new consent",
    ]:
        assert required in en


def test_account_deletion_copy_matches_deidentified_shared_content_retention():
    account_js = (ROOT / "miniprogram/pages/account-settings/account-settings.js").read_text(
        encoding="utf-8"
    )
    account_wxml = (ROOT / "miniprogram/pages/account-settings/account-settings.wxml").read_text(
        encoding="utf-8"
    )
    api_js = (ROOT / "miniprogram/utils/api.js").read_text(encoding="utf-8")
    router = (ROOT / "app/user/router.py").read_text(encoding="utf-8")
    service = (ROOT / "app/user/service.py").read_text(encoding="utf-8")
    combined = "\n".join([account_js, account_wxml, api_js, router, service])

    assert "彻底删除你的全部数据" not in combined
    assert "你创建的路书都会解除关联后保留" in account_js
    assert "已开放约骑会取消并解除关联后保留" in account_js
    assert "官网隐私邮箱申请" in account_js
    assert "创建的全部路书和已开放约骑按后端规则去标识保留" in api_js
    assert "创建的全部路书和已开放约骑去标识保留" in router
    assert "所有路线定义保留为无主" in service
    assert "已开放约骑取消后保留给参与者查看" in service


def test_caddy_serves_website_without_exposing_private_uploads():
    caddy = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "weiluai.top {" in caddy
    assert "www.weiluai.top {" in caddy
    assert "root * /srv/website" in caddy
    assert "handle_errors" in caddy
    assert "rewrite * /404.html" in caddy
    assert "script-src 'none'" in caddy
    assert "form-action 'none'" in caddy
    assert "redir https://weiluai.top{uri} permanent" in caddy
    assert "api.weiluai.top {" in caddy
    assert "reverse_proxy api:8000" in caddy
    assert "./website:/srv/website:ro" in compose

    website_block = caddy.split("(velo_website) {", 1)[1].split(
        "weiluai.top {", 1
    )[0]
    assert "/srv/uploads" not in website_block
    assert not any(path.is_symlink() for path in WEBSITE.rglob("*"))


def test_sitemap_lists_all_canonical_pages():
    sitemap = (WEBSITE / "sitemap.xml").read_text(encoding="utf-8")
    for path in [
        "/",
        "/company/",
        "/privacy/",
        "/privacy/garmin/",
        "/en/",
        "/en/company/",
        "/en/privacy/",
        "/en/privacy/garmin/",
    ]:
        assert f"<loc>https://weiluai.top{path}</loc>" in sitemap
