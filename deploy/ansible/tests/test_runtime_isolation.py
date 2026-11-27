"""Application isolation contracts; no live app imports, listeners, or dispatch."""

import ast
from html import escape
from html.parser import HTMLParser
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from flask import Flask, Response, render_template_string


ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / "src/py_phone_caller_ui"
SWAGGER = ROOT / "src/py-phone-caller-utils/py_phone_caller_utils/web/swagger.py"
SERVICES = (
    "asterisk_caller",
    "caller_address_book",
    "caller_prometheus_webhook",
    "caller_register",
    "caller_scheduler",
    "caller_sms",
    "generate_audio",
)


def load_swagger_helper():
    spec = importlib.util.spec_from_file_location("runtime_isolation_swagger", SWAGGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_function(path, name, namespace):
    tree = ast.parse(path.read_text(), filename=str(path))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, attrs))
        for name, value in attrs:
            if name in ("src", "href"):
                self.urls.append(value)


class RuntimeIsolationTests(unittest.TestCase):
    def configure_offline(self, app, value):
        path = UI / "app.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        target = ast.dump(ast.parse('app.config["PPC_OFFLINE"] = None').body[0].targets[0])
        assignments = [
            node for node in tree.body
            if isinstance(node, ast.Assign) and any(ast.dump(item) == target for item in node.targets)
        ]
        self.assertEqual(len(assignments), 1, "Expected one explicit PPC_OFFLINE config assignment")
        with patch.dict(os.environ):
            os.environ.pop("PPC_OFFLINE", None)
            if value is not None:
                os.environ["PPC_OFFLINE"] = value
            exec(
                compile(ast.Module(body=assignments, type_ignores=[]), str(path), "exec"),
                {"app": app, "os": os},
            )

    def render_head(self, app):
        source = (UI / "templates/base.html").read_text()
        self.assertIn("</head>", source)
        with app.test_request_context():
            return render_template_string(
                source.split("</head>", 1)[0] + "</head>",
                current_locale="en",
                current_locale_meta=None,
            )

    def test_bind_host_environment_and_legacy_default(self):
        for service in SERVICES:
            path = ROOT / "src" / service / f"{service}.py"
            tree = ast.parse(path.read_text(), filename=str(path))
            calls = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "web" and node.func.attr == "run_app"
            ]
            with self.subTest(service=service):
                self.assertEqual(len(calls), 1)
                hosts = [keyword.value for keyword in calls[0].keywords if keyword.arg == "host"]
                self.assertEqual(len(hosts), 1, "run_app must explicitly use PPC_HTTP_BIND_HOST")
                expression = compile(ast.Expression(body=hosts[0]), str(path), "eval")
                for value in (None, "127.0.0.1", "10.20.30.40", "::1", "0.0.0.0", ""):
                    with self.subTest(value=value), patch.dict(os.environ):
                        os.environ.pop("PPC_HTTP_BIND_HOST", None)
                        if value is not None:
                            os.environ["PPC_HTTP_BIND_HOST"] = value
                        self.assertEqual(eval(expression, {"os": os}), value)

    def test_offline_config_is_explicit_opt_in(self):
        for value in (None, "", "0", "1", "true", "false", "yes", " 1 "):
            with self.subTest(value=value):
                app = Flask(__name__)
                self.configure_offline(app, value)
                self.assertIs(app.config["PPC_OFFLINE"], value == "1")

    def test_offline_head_has_only_local_assets(self):
        app = Flask(__name__)
        self.configure_offline(app, "1")
        html = self.render_head(app)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)
        resources = ResourceParser()
        resources.feed(html)
        self.assertEqual(resources.urls, [
            "/static/css/bootstrap.min.css",
            "/static/css/custom.css",
            "/static/css/bootstrap-icons.css",
        ])
        for url in resources.urls:
            self.assertTrue((UI / url.lstrip("/")).is_file())

    def test_online_and_missing_config_preserve_google_fonts(self):
        for config in ({}, {"PPC_OFFLINE": False}):
            with self.subTest(config=config):
                app = Flask(__name__)
                app.config.update(config)
                html = self.render_head(app)
                resources = ResourceParser()
                resources.feed(html)
                self.assertIn("https://fonts.googleapis.com", resources.urls)
                self.assertIn("https://fonts.gstatic.com", resources.urls)
                self.assertEqual(sum(url.startswith("https://fonts.googleapis.com/css2?") for url in resources.urls), 3)
                self.assertIn("<noscript>", html)

    def test_offline_docs_explain_unavailability_without_cdn(self):
        app = Flask(__name__)
        self.configure_offline(app, "1")
        generator = Mock(side_effect=AssertionError("Offline docs must not generate CDN markup"))
        namespace = {"app": app, "Response": Response, "generate_swagger_ui_html": generator}
        load_function(UI / "app.py", "ui_swagger_docs", namespace)
        response = app.test_client().get("/docs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.mimetype, "text/html")
        html = response.get_data(as_text=True)
        self.assertIn("offline", html.lower())
        self.assertIn("unavailable", html.lower())
        self.assertNotIn("<script", html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        resources = ResourceParser()
        resources.feed(html)
        self.assertEqual(resources.urls, ["/docs/swagger.json"])
        generator.assert_not_called()

    def test_online_docs_preserve_swagger_response(self):
        for config in ({}, {"PPC_OFFLINE": False}):
            with self.subTest(config=config), patch.dict(os.environ, {"PPC_OFFLINE": "0"}):
                app = Flask(__name__)
                app.config.update(config)
                namespace = {
                    "app": app,
                    "Response": Response,
                    "generate_swagger_ui_html": load_swagger_helper().generate_swagger_ui_html,
                }
                load_function(UI / "app.py", "ui_swagger_docs", namespace)
                response = app.test_client().get("/docs")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "text/html")
                self.assertEqual(response.get_data(as_text=True), namespace["generate_swagger_ui_html"](
                    title="py-phone-caller Web UI API", openapi_url="/docs/swagger.json",
                ))


class SharedSwaggerIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.swagger = load_swagger_helper()

    def generators(self, title="Test API", url="/docs/swagger.json", **kwargs):
        return (
            self.swagger.generate_swagger_ui_html(title, openapi_url=url, **kwargs),
            self.swagger.generate_unified_swagger_portal_html(
                title, services=[{"name": title, "url": url}], **kwargs,
            ),
        )

    def assert_static_offline_html(self, html, urls):
        self.assertIn("offline", html.lower())
        self.assertIn("unavailable", html.lower())
        self.assertNotIn("cdn.jsdelivr.net", html)
        parser = ResourceParser()
        parser.feed(html)
        self.assertEqual(parser.urls, urls)
        allowed = {"html", "head", "meta", "title", "body", "h1", "p", "ul", "li", "a", "code"}
        for tag, attrs in parser.elements:
            self.assertIn(tag, allowed)
            self.assertTrue(set(dict(attrs)) <= {"lang", "charset", "href"})

    def test_offline_defaults_have_only_same_origin_json_links(self):
        with patch.dict(os.environ, {"PPC_OFFLINE": "1"}):
            self.assert_static_offline_html(
                self.swagger.generate_swagger_ui_html("Test API"), ["/docs/swagger.json"],
            )
            self.assert_static_offline_html(self.swagger.generate_unified_swagger_portal_html(), [
                "/docs/swagger.json",
                "/api/v1/alerts/docs/swagger.json",
                "/api/v1/telephony/docs/swagger.json",
                "/api/v1/sms/docs/swagger.json",
                "/api/v1/contacts/docs/swagger.json",
                "/api/v1/schedules/docs/swagger.json",
                "/api/v1/audio/docs/swagger.json",
                "/api/v1/registry/docs/swagger.json",
            ])

    def test_offline_escapes_titles_names_and_local_urls_and_ignores_assets(self):
        title = '</title><script>alert("title")</script><img src="https://evil.invalid/x">&'
        url = '/docs/swagger.json?name="quoted"&value=<unsafe>'
        with patch.dict(os.environ, {"PPC_OFFLINE": "1"}):
            for html in self.generators(
                title, url, swagger_js_url="https://assets.invalid/bundle.js",
                swagger_css_url="https://assets.invalid/style.css",
            ):
                self.assert_static_offline_html(html, [url])
                self.assertIn(escape(title), html)
                self.assertIn(escape(url), html)
                self.assertNotIn("assets.invalid", html)

    def test_offline_never_activates_external_or_ambiguous_urls(self):
        urls = (
            'https://evil.invalid/spec.json?x="<unsafe>"&y=1',
            "http://evil.invalid/spec.json", "//evil.invalid/spec.json", "///evil.invalid/spec.json",
            "javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
            "\\\\evil.invalid/spec.json", "/\\evil.invalid/spec.json",
            " /docs/swagger.json", "/\t/evil.invalid/spec.json", "/\n/evil.invalid/spec.json",
            "/\r/evil.invalid/spec.json", "/\x00/spec.json", "/\x7f/spec.json",
            "docs/swagger.json", "",
        )
        with patch.dict(os.environ, {"PPC_OFFLINE": "1"}):
            for url in urls:
                with self.subTest(url=url):
                    for html in self.generators(url=url):
                        self.assert_static_offline_html(html, [])
                        self.assertIn(escape(url), html)

    def test_offline_empty_portal_is_static(self):
        with patch.dict(os.environ, {"PPC_OFFLINE": "1"}):
            self.assert_static_offline_html(
                self.swagger.generate_unified_swagger_portal_html(services=[]), [],
            )

    def test_online_behavior_and_strict_opt_in(self):
        with patch.dict(os.environ):
            os.environ.pop("PPC_OFFLINE", None)
            baseline = self.generators()
            for html in baseline:
                self.assertIn("https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js", html)
                self.assertIn("https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css", html)
                self.assertIn("SwaggerUIBundle", html)
                self.assertIn("/docs/swagger.json", html)
            for value in ("", "0", "true", "false", "yes", " 1 "):
                with self.subTest(value=value):
                    os.environ["PPC_OFFLINE"] = value
                    self.assertEqual(self.generators(), baseline)
            for html in self.generators(
                url="https://spec.invalid/openapi.json",
                swagger_js_url="https://assets.invalid/bundle.js",
                swagger_css_url="https://assets.invalid/style.css",
            ):
                self.assertIn("https://spec.invalid/openapi.json", html)
                self.assertIn('<script src="https://assets.invalid/bundle.js">', html)
                self.assertIn('href="https://assets.invalid/style.css"', html)


if __name__ == "__main__":
    unittest.main()