"""Tests for web search — provider abstraction, the tool, and config resolution.

No network: a FakeProvider is injected; third-party key handling and the REST config path
are exercised without hitting DuckDuckGo/Tavily/Brave/Serper/Exa/Firecrawl.
"""

from __future__ import annotations

import pytest

from coworker.sandbox.network_profiles import SEARCH_APIS
from coworker.secrets import SecretStore
from coworker.web import (
    SearchResult,
    build_provider,
    make_web_search_tool,
    provider_names,
)
from coworker.web.providers import (
    _PROVIDERS,
    BraveProvider,
    DuckDuckGoProvider,
    ExaProvider,
    FirecrawlProvider,
    SerperProvider,
    TavilyProvider,
    WebSearchProvider,
    YouProvider,
)
from coworker.web.tool import PROVIDER_HOSTS


class FakeProvider(WebSearchProvider):
    name = "fake"

    def __init__(self):
        self.calls = []

    def search(self, query, max_results=5):
        self.calls.append((query, max_results))
        return [
            SearchResult(title=f"r{i}", url=f"https://x/{i}", snippet="s")
            for i in range(max_results)
        ]


def test_tool_returns_results():
    fake = FakeProvider()
    tool = make_web_search_tool(provider=fake)
    out = tool(query="anthropic", max_results=3)
    assert out["provider"] == "fake"
    assert [r["title"] for r in out["results"]] == ["r0", "r1", "r2"]
    assert fake.calls == [("anthropic", 3)]
    # metadata + schema for the registry
    assert tool.__aisuite_tool_metadata__.category == "web"
    assert tool.__coworker_schema__["function"]["name"] == "web_search"


def test_tool_clamps_max_results():
    fake = FakeProvider()
    make_web_search_tool(provider=fake)(query="q", max_results=99)
    assert fake.calls[0][1] == 10  # clamped to 10
    make_web_search_tool(provider=fake)(query="q", max_results=0)
    assert fake.calls[1][1] == 1  # clamped to >=1


def test_tool_reports_search_errors():
    class Boom(WebSearchProvider):
        name = "boom"

        def search(self, query, max_results=5):
            raise RuntimeError("network down")

    out = make_web_search_tool(provider=Boom())(query="q")
    assert "web search failed" in out["error"] and out["provider"] == "boom"


def test_build_provider_default_is_keyless_duckduckgo():
    assert isinstance(build_provider("duckduckgo"), DuckDuckGoProvider)
    assert isinstance(build_provider("unknown-thing"), DuckDuckGoProvider)  # falls back
    assert "duckduckgo" in provider_names()


def test_build_provider_third_party_requires_key():
    with pytest.raises(ValueError):
        build_provider("tavily")  # no key
    with pytest.raises(ValueError):
        build_provider("serper")  # no key
    assert isinstance(build_provider("tavily", "tvly-x"), TavilyProvider)
    assert isinstance(build_provider("brave", "brv-x"), BraveProvider)
    assert isinstance(build_provider("serper", "srp-x"), SerperProvider)
    assert "serper" in provider_names()
    with pytest.raises(ValueError):
        build_provider("exa")  # no key
    assert isinstance(build_provider("exa", "exa-x"), ExaProvider)
    with pytest.raises(ValueError):
        build_provider("firecrawl")  # no key
    assert isinstance(build_provider("firecrawl", "fc-x"), FirecrawlProvider)


def test_serper_sends_correct_request_and_maps_organic_results(monkeypatch):
    """Verify the Serper API request shape and response mapping without a network call."""
    import httpx

    sent = {}

    class _Resp:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {
                "organic": [
                    {
                        "title": "Example Title",
                        "link": "https://example.com",
                        "snippet": "An example snippet.",
                    }
                ]
            }

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)

    results = build_provider("serper", "srp-test-key").search("anthropic", max_results=3)

    assert sent["url"] == "https://google.serper.dev/search"
    assert sent["headers"]["X-API-KEY"] == "srp-test-key"
    assert sent["json"]["q"] == "anthropic"
    assert sent["json"]["num"] == 3
    assert len(results) == 1
    assert results[0].title == "Example Title"
    assert results[0].url == "https://example.com"
    assert results[0].snippet == "An example snippet."


def test_exa_provider_parses_highlights(monkeypatch):
    import httpx

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "results": [
                    {
                        "title": "Exa",
                        "url": "https://exa.ai",
                        "highlights": ["neural search", "for AI"],
                    },
                    {"title": None, "url": "https://exa.ai/docs"},
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    results = ExaProvider("exa-x").search("what is exa", max_results=2)

    assert captured["url"] == "https://api.exa.ai/search"
    assert captured["headers"]["x-api-key"] == "exa-x"
    assert captured["headers"]["x-exa-integration"] == "andrewyng/openworker-integration"
    assert captured["json"]["numResults"] == 2
    assert captured["json"]["contents"] == {"highlights": True}
    assert [r.to_dict() for r in results] == [
        {
            "title": "Exa",
            "url": "https://exa.ai",
            "snippet": "neural search for AI",
        },
        {"title": "", "url": "https://exa.ai/docs", "snippet": ""},
    ]


def test_firecrawl_maps_v2_search_response(monkeypatch):
    import httpx

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "success": True,
                "data": {
                    "web": [
                        {"title": "t0", "url": "https://x/0", "description": "d0"},
                        {"title": "t1", "url": "https://x/1", "description": "d1"},
                    ]
                },
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    results = FirecrawlProvider("fc-key").search("claude api", max_results=2)

    assert captured["url"] == "https://api.firecrawl.dev/v2/search"
    assert captured["headers"]["Authorization"] == "Bearer fc-key"
    assert captured["json"] == {"query": "claude api", "limit": 2}
    assert [(r.title, r.url, r.snippet) for r in results] == [
        ("t0", "https://x/0", "d0"),
        ("t1", "https://x/1", "d1"),
    ]


def test_keyed_providers_raise_on_http_errors(monkeypatch):
    """A 401/429/5xx surfaces as an error instead of an empty result list."""
    import httpx

    def denied(url, **kwargs):
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", denied)
    monkeypatch.setattr(httpx, "get", denied)
    for provider in (
        TavilyProvider("k"),
        BraveProvider("k"),
        SerperProvider("k"),
        ExaProvider("k"),
        FirecrawlProvider("k"),
        YouProvider(),
        YouProvider("k"),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            provider.search("q")


def test_every_provider_has_a_name_and_a_key_page():
    for name, cls in _PROVIDERS.items():
        assert cls.name == name and cls.display_name, name
        assert cls.key_mode in ("none", "optional", "required"), name
        assert bool(cls.key_url) == (cls.key_mode != "none"), name  # keyless: no key page
        # The one-flag views agree with the tri-state.
        assert cls.requires_key == (cls.key_mode == "required"), name
        assert cls.accepts_key == (cls.key_mode == "optional"), name
    assert DuckDuckGoProvider.key_mode == "none"
    assert YouProvider.key_mode == "optional"
    assert TavilyProvider.key_mode == "required"


def test_every_provider_is_known_to_the_site_wall():
    """`web_search` has no url argument: the sandbox's allowed-sites wall checks the
    provider's host (PROVIDER_HOSTS), and the Access page offers it under Search."""
    for name in provider_names():
        hosts = PROVIDER_HOSTS[name]
        for host in [hosts] if isinstance(hosts, str) else hosts:
            assert host in SEARCH_APIS, (name, host)


def test_build_provider_you_is_keyless_with_optional_key(monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "ignored")  # providers never read the environment
    assert "you" in provider_names()
    keyless = build_provider("you")  # no key needed
    assert isinstance(keyless, YouProvider) and keyless.api_key is None
    assert build_provider("you", "ydc-x").api_key == "ydc-x"  # key is passed through


def _you_env(monkeypatch, **values):
    for var in ("YOU_API_KEY", "YDC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var, value in values.items():
        monkeypatch.setenv(var, value)


def test_resolve_provider_reads_the_you_key_from_either_env_name(tmp_path, monkeypatch):
    from coworker.web import resolve_provider

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("web_search:default", {"provider": "you"})
    _you_env(monkeypatch)
    assert resolve_provider(secrets).api_key is None
    _you_env(monkeypatch, YDC_API_KEY="from-ydc")  # the name You.com's own docs use
    assert resolve_provider(secrets).api_key == "from-ydc"
    _you_env(monkeypatch, YOU_API_KEY="from-you", YDC_API_KEY="from-ydc")
    assert resolve_provider(secrets).api_key == "from-you"  # the uniform name wins
    secrets.put("web_search:default", {"provider": "you", "api_key": "from-store"})
    assert resolve_provider(secrets).api_key == "from-store"  # the store wins over both


def test_provider_host_follows_the_you_key(tmp_path, monkeypatch):
    """You.com talks to one host keyless and another with a key; the site wall checks the
    one the next search will use."""
    from coworker.web import provider_host

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("web_search:default", {"provider": "you"})
    _you_env(monkeypatch)
    assert provider_host(secrets) == "api.you.com"
    _you_env(monkeypatch, YDC_API_KEY="k")
    assert provider_host(secrets) == "ydc-index.io"
    _you_env(monkeypatch)
    secrets.put("web_search:default", {"provider": "you", "api_key": "k"})
    assert provider_host(secrets) == "ydc-index.io"
    secrets.put("web_search:default", {"provider": "brave", "api_key": "k"})
    assert provider_host(secrets) == "api.search.brave.com"  # single-host providers as before


def _fake_you_get(captured, payload):
    """Stand-in for httpx.get that records the request and replays a canned response."""

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    def get(url, **kw):
        captured.update(url=url, **kw)
        return Resp()

    return get


def test_you_provider_keyless_request_and_parsing(monkeypatch):
    import httpx

    monkeypatch.delenv("YDC_API_KEY", raising=False)
    got = {}
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_you_get(
            got,
            {
                "results": {
                    "web": [
                        {"title": "w", "url": "https://w", "description": "wd"},
                        {"title": "s", "url": "https://s", "snippets": ["a", "b"]},
                    ],
                    "news": [{"title": "n", "url": "https://n", "description": "nd"}],
                }
            },
        ),
    )

    out = YouProvider().search("openworker", max_results=3)
    assert got["url"] == YouProvider._KEYLESS_URL  # free tier, no key
    assert "X-API-Key" not in got["headers"]
    assert got["headers"]["User-Agent"] == "youdotcom-integration/andrewyng-openworker"
    assert got["params"] == {"query": "openworker", "count": 3}
    assert [(r.title, r.url, r.snippet) for r in out] == [
        ("w", "https://w", "wd"),
        ("s", "https://s", "a b"),  # falls back to snippets when description is absent
        ("n", "https://n", "nd"),  # web first, news fills the remainder
    ]


def test_you_provider_with_key_uses_search_api(monkeypatch):
    import httpx

    got = {}
    monkeypatch.setattr(httpx, "get", _fake_you_get(got, {"results": {}}))

    assert YouProvider("ydc-123").search("q", max_results=2) == []
    assert got["url"] == YouProvider._KEYED_URL
    assert got["headers"]["X-API-Key"] == "ydc-123"


def test_you_provider_truncates_to_max_results(monkeypatch):
    import httpx

    rows = [{"title": f"r{i}", "url": f"https://x/{i}"} for i in range(10)]
    monkeypatch.setattr(
        httpx, "get", _fake_you_get({}, {"results": {"web": rows, "news": rows}})
    )
    assert len(YouProvider().search("q", max_results=4)) == 4


def test_tool_surfaces_missing_key_error(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("web_search:default", {"provider": "tavily"})  # no api_key
    out = make_web_search_tool(secrets)(
        query="q"
    )  # resolve_provider raises ValueError → error dict
    assert "needs an API key" in out["error"]


def test_resolve_provider_from_secretstore(tmp_path):
    from coworker.web import resolve_provider

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("web_search:default", {"provider": "tavily", "api_key": "tvly-123"})
    p = resolve_provider(secrets)
    assert p.name == "tavily" and p.api_key == "tvly-123"


def test_web_search_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    client = TestClient(create_app(SessionManager(data_dir=tmp_path / "data")))

    assert client.get("/v1/web-search").json()["provider"] == "duckduckgo"
    assert (
        client.post(
            "/v1/web-search", json={"provider": "tavily", "api_key": "sk-secret-xyz"}
        ).json()["ok"]
        is True
    )
    got = client.get("/v1/web-search").json()
    assert got["provider"] == "tavily" and got["has_key"] is True
    assert (
        "sk-secret-xyz" not in client.get("/v1/web-search").text
    )  # key never returned
    assert (
        client.post("/v1/web-search", json={"provider": "nope"}).json()["ok"] is False
    )


def test_engine_registers_web_search(tmp_path):
    from coworker.agent import build_engine
    from coworker.agents import chat_agent

    eng = build_engine(
        agent=chat_agent(),
        provider=_StubProvider(),
        secrets=SecretStore(tmp_path / "s.json"),
    )
    assert "web_search" in eng.registry.names()


class _StubProvider:
    def complete(self, **_kw):
        from coworker.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):
        from coworker.providers.base import ModelCapabilities

        return ModelCapabilities()

    def stream(self, **_kw):
        from coworker.providers.base import StreamChunk

        yield StreamChunk(turn=self.complete())
