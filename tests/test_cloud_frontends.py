"""Cloud mode, checked in the source: every tab that calls its backend by port
must go through the cloud switch, and must load /config.js before it.

In Azure Container Apps only the frontends are public, so a tab that still
calls http://<host>:50xx would be calling an address the browser cannot reach
(and, from an HTTPS page, mixed content). See deploy/nginx/feature.conf.template.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_FILES = [p for p in ROOT.glob("services/*/frontend/**/*") if p.suffix in (".html", ".js")]
PORT_CALL = re.compile(r"\$\{window\.location\.hostname\}:50\d\d")
SWITCH = re.compile(r"window\.SMARTBANK_SAME_ORIGIN_API \? window\.location\.origin : `http://\$\{window\.location\.hostname\}:50\d\d`")


def test_tabs_use_the_cloud_switch():
    offenders = [f"{p.relative_to(ROOT)}:{n}" for p in FRONTEND_FILES
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if PORT_CALL.search(line) and not SWITCH.search(line)]
    assert offenders == []


def test_switching_tabs_load_config_js_first():
    for p in FRONTEND_FILES:
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".html" and "SMARTBANK_SAME_ORIGIN_API" in text:
            assert text.index('<script src="/config.js"></script>') < text.index("SMARTBANK_SAME_ORIGIN_API"), p


def test_loans_page_loads_config_js_before_its_scripts():
    # Loans keeps its API switch in js/*.js, so the page itself must load the
    # cloud config before the first of those scripts.
    pages = [p for p in (ROOT / "services/loans/frontend/tabs").glob("*.html") if "/loans-js/" in p.read_text(encoding="utf-8")]
    assert pages
    for p in pages:
        text = p.read_text(encoding="utf-8")
        assert '<script src="/config.js"></script>' in text, p
        assert text.index('<script src="/config.js"></script>') < text.index('<script src="/loans-js/'), p
