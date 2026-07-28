"""Static contracts for the public VELO website and Garmin application pages."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"
LEGAL_NAME = "湖南湘江新区共演纪软件开发有限责任公司"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
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
        "assets/site.css",
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
        assert 'href="/assets/site.css"' in source, page

        for href in parser.links:
            if href.startswith(("mailto:", "tel:", "#")):
                continue
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                continue
            target = _resolve_site_path(parsed.path)
            assert target.exists(), f"{page}: missing {href} -> {target}"


def test_public_pages_identify_the_legal_operator_without_private_identifiers():
    combined = " ".join(
        "\n".join(
            page.read_text(encoding="utf-8") for page in _html_files()
        ).split()
    )
    assert LEGAL_NAME in combined
    assert re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", combined) is None
    assert re.search(r"(?<![0-9A-Z])[0-9A-Z]{18}(?![0-9A-Z])", combined) is None
    assert "Garmin 用户名、密码" in combined
    assert "not ask for or store a Garmin username, password" in combined


def test_garmin_policies_are_narrow_truthful_and_bilingual():
    zh = (WEBSITE / "privacy/garmin/index.html").read_text(encoding="utf-8")
    en = (WEBSITE / "en/privacy/garmin/index.html").read_text(encoding="utf-8")

    for required in [
        "申请和开发阶段",
        "OAuth 2.0 / PKCE",
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
        "OAuth 2.0 / PKCE",
        "private by default",
        "no more than 30 days",
        "outside Mainland China",
        "external AI or LLM",
    ]:
        assert required in en

    combined = zh + en
    assert "Works with Garmin" not in combined
    assert "Powered by Garmin" not in combined
    assert "Garmin logo" not in combined


def test_privacy_policy_matches_current_and_planned_data_boundaries():
    zh = " ".join(
        (WEBSITE / "privacy/index.html").read_text(encoding="utf-8").split()
    )
    assert "微信 OpenID" in zh
    assert "FIT/GPX" in zh
    assert "仅自己可见" in zh
    assert "分别隐藏功率和心率" in zh
    assert "手动上传文件随活动或账号删除而删除" in zh
    assert "Garmin 原始活动文件在成功解析后最多保留 30 天" in zh
    assert "Garmin 正式接入前还会完成令牌静态加密" in zh


def test_caddy_serves_website_without_exposing_private_uploads():
    caddy = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "weiluai.top {" in caddy
    assert "www.weiluai.top {" in caddy
    assert "root * /srv/website" in caddy
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
