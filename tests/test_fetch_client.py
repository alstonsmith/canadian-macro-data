from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from canadian_macro.sources.client import FetchClient, FetchError

URL = "https://example.test/data.csv"


class FakeTime:
    """Deterministic clock: ``sleep`` advances time instead of waiting."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Server:
    """Scripted responses; records every request that reaches the 'network'."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def ok(body: bytes = b"a,b\n1,2\n", **headers: str) -> httpx.Response:
    return httpx.Response(200, content=body, headers=headers)


MakeClient = Callable[..., tuple[FetchClient, Server, FakeTime]]


@pytest.fixture
def make_client(tmp_path: Path) -> MakeClient:
    def _make(
        *responses: httpx.Response | Exception, **options: object
    ) -> tuple[FetchClient, Server, FakeTime]:
        server = Server(*responses)
        fake = FakeTime()
        defaults: dict[str, object] = {"min_interval": 0.0, "backoff_base": 1.0}
        client = FetchClient(
            tmp_path / "cache",
            transport=httpx.MockTransport(server),
            clock=fake.clock,
            wall_clock=fake.clock,
            sleep=fake.sleep,
            **(defaults | options),  # type: ignore[arg-type]
        )
        return client, server, fake

    return _make


# --- basic fetch and cache ----------------------------------------------------------------


def test_returns_body_from_network(make_client: MakeClient) -> None:
    client, server, _ = make_client(ok(b"hello"))
    result = client.get(URL)
    assert result.content == b"hello"
    assert result.from_cache is False
    assert len(server.requests) == 1


def test_cache_hit_makes_no_network_call(make_client: MakeClient) -> None:
    client, server, _ = make_client(ok(b"hello"))
    first = client.get(URL)
    second = client.get(URL)
    assert len(server.requests) == 1
    assert second.from_cache is True
    assert second.content == first.content == b"hello"
    assert second.fetched_at == first.fetched_at


def test_cache_survives_a_new_client(tmp_path: Path, make_client: MakeClient) -> None:
    client, _, _ = make_client(ok(b"hello"))
    client.get(URL)
    client2, server2, _ = make_client(httpx.Response(500))
    result = client2.get(URL)
    assert result.from_cache is True
    assert result.content == b"hello"
    assert server2.requests == []


def test_params_are_part_of_the_cache_key_but_their_order_is_not(
    make_client: MakeClient,
) -> None:
    client, server, _ = make_client(ok(b"one"), ok(b"two"))
    one = client.get(URL, params={"a": "1", "b": "2"})
    again = client.get(URL, params={"b": "2", "a": "1"})
    other = client.get(URL, params={"a": "9"})
    assert (one.content, again.content, other.content) == (b"one", b"one", b"two")
    assert len(server.requests) == 2


def test_expired_entry_is_refetched(make_client: MakeClient) -> None:
    client, server, fake = make_client(ok(b"old"), ok(b"new"), cache_ttl=60.0)
    assert client.get(URL).content == b"old"
    fake.now += 59
    assert client.get(URL).content == b"old"
    fake.now += 2
    result = client.get(URL)
    assert result.content == b"new"
    assert result.from_cache is False
    assert len(server.requests) == 2


def test_ttl_none_never_expires(make_client: MakeClient) -> None:
    client, server, fake = make_client(ok(b"old"), cache_ttl=None)
    client.get(URL)
    fake.now += 10**9
    assert client.get(URL).from_cache is True
    assert len(server.requests) == 1


def test_refresh_bypasses_the_cache_and_updates_it(make_client: MakeClient) -> None:
    client, server, _ = make_client(ok(b"old"), ok(b"new"))
    client.get(URL)
    assert client.get(URL, refresh=True).content == b"new"
    assert client.get(URL).content == b"new"
    assert len(server.requests) == 2


def test_corrupt_cache_entry_is_treated_as_a_miss(tmp_path: Path, make_client: MakeClient) -> None:
    client, server, _ = make_client(ok(b"good"))
    client.get(URL)
    for body in (tmp_path / "cache").glob("*.body"):
        body.write_bytes(b"tampered")
    result = client.get(URL)
    assert result.content == b"good"
    assert result.from_cache is False
    assert len(server.requests) == 2


def test_truncated_meta_is_treated_as_a_miss(tmp_path: Path, make_client: MakeClient) -> None:
    client, server, _ = make_client(ok(b"good"))
    client.get(URL)
    for meta in (tmp_path / "cache").glob("*.json"):
        meta.write_text("{not json")
    assert client.get(URL).content == b"good"
    assert len(server.requests) == 2


# --- throttle -----------------------------------------------------------------------------


def test_network_requests_are_spaced_by_min_interval(make_client: MakeClient) -> None:
    client, _, fake = make_client(ok(), min_interval=1.0)
    client.get("https://example.test/a")
    assert fake.sleeps == []
    client.get("https://example.test/b")
    assert fake.sleeps == [1.0]


def test_elapsed_time_counts_towards_the_interval(make_client: MakeClient) -> None:
    client, _, fake = make_client(ok(), min_interval=1.0)
    client.get("https://example.test/a")
    fake.now += 0.4
    client.get("https://example.test/b")
    assert fake.sleeps == [pytest.approx(0.6)]


def test_cache_hits_are_not_throttled(make_client: MakeClient) -> None:
    client, _, fake = make_client(ok(), min_interval=1.0)
    client.get(URL)
    client.get(URL)
    client.get(URL)
    assert fake.sleeps == []


def test_default_throttle_is_one_request_per_second(tmp_path: Path) -> None:
    assert FetchClient(tmp_path).min_interval == 1.0


# --- retry and backoff --------------------------------------------------------------------


@pytest.mark.parametrize("status", [409, 429, 500, 502, 503, 504])
def test_retryable_status_is_retried_until_success(make_client: MakeClient, status: int) -> None:
    client, server, fake = make_client(httpx.Response(status), ok(b"fine"))
    assert client.get(URL).content == b"fine"
    assert len(server.requests) == 2
    assert fake.sleeps == [1.0]


def test_backoff_doubles_each_attempt(make_client: MakeClient) -> None:
    client, server, fake = make_client(
        httpx.Response(503), httpx.Response(503), httpx.Response(503), ok(b"fine"), max_retries=3
    )
    client.get(URL)
    assert len(server.requests) == 4
    assert fake.sleeps == [1.0, 2.0, 4.0]


def test_backoff_is_capped(make_client: MakeClient) -> None:
    client, _, fake = make_client(
        httpx.Response(503), httpx.Response(503), httpx.Response(503), ok(),
        max_retries=3, backoff_max=3.0,
    )  # fmt: skip
    client.get(URL)
    assert fake.sleeps == [1.0, 2.0, 3.0]


def test_retry_after_seconds_is_honoured(make_client: MakeClient) -> None:
    client, _, fake = make_client(httpx.Response(429, headers={"Retry-After": "5"}), ok())
    client.get(URL)
    assert fake.sleeps == [5.0]


def test_retry_after_is_capped(make_client: MakeClient) -> None:
    client, _, fake = make_client(
        httpx.Response(503, headers={"Retry-After": "99999"}), ok(), backoff_max=30.0
    )
    client.get(URL)
    assert fake.sleeps == [30.0]


def test_unparseable_retry_after_falls_back_to_backoff(make_client: MakeClient) -> None:
    client, _, fake = make_client(
        httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), ok()
    )
    client.get(URL)
    assert fake.sleeps == [1.0]


def test_transport_errors_are_retried(make_client: MakeClient) -> None:
    client, server, _ = make_client(httpx.ConnectTimeout("slow"), ok(b"fine"))
    assert client.get(URL).content == b"fine"
    assert len(server.requests) == 2


def test_gives_up_with_a_clear_error_and_caches_nothing(
    tmp_path: Path, make_client: MakeClient
) -> None:
    client, server, _ = make_client(httpx.Response(503), max_retries=2)
    with pytest.raises(FetchError) as info:
        client.get(URL)
    error = info.value
    assert len(server.requests) == 3
    assert error.url == URL
    assert error.status_code == 503
    assert error.attempts == 3
    assert "503" in str(error) and URL in str(error) and "3 attempts" in str(error)
    assert list((tmp_path / "cache").glob("*")) == []


def test_gives_up_on_repeated_transport_errors(make_client: MakeClient) -> None:
    client, server, _ = make_client(httpx.ConnectError("down"), max_retries=1)
    with pytest.raises(FetchError) as info:
        client.get(URL)
    assert info.value.status_code is None
    assert "down" in str(info.value)
    assert len(server.requests) == 2


def test_max_retries_zero_means_one_attempt(make_client: MakeClient) -> None:
    client, server, fake = make_client(httpx.Response(503), max_retries=0)
    with pytest.raises(FetchError):
        client.get(URL)
    assert len(server.requests) == 1
    assert fake.sleeps == []


def test_retries_respect_the_throttle_too(make_client: MakeClient) -> None:
    client, _, fake = make_client(httpx.Response(503), ok(), min_interval=10.0, backoff_base=1.0)
    client.get(URL)
    assert fake.sleeps == [1.0, 9.0]  # backoff, then the rest of the 10 s interval


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_other_client_errors_fail_fast(
    tmp_path: Path, make_client: MakeClient, status: int
) -> None:
    client, server, fake = make_client(httpx.Response(status))
    with pytest.raises(FetchError) as info:
        client.get(URL)
    assert info.value.status_code == status
    assert len(server.requests) == 1
    assert fake.sleeps == []
    assert list((tmp_path / "cache").glob("*")) == []


def test_redirects_are_an_error_not_followed(make_client: MakeClient) -> None:
    redirect = httpx.Response(302, headers={"Location": "https://elsewhere.test/"})
    client, server, _ = make_client(redirect)
    with pytest.raises(FetchError) as info:
        client.get(URL)
    assert info.value.status_code == 302
    assert len(server.requests) == 1


# --- input and response hygiene -----------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.test/x", "example.test/x", ""]
)
def test_only_http_urls_are_accepted(make_client: MakeClient, url: str) -> None:
    client, server, _ = make_client(ok())
    with pytest.raises(FetchError):
        client.get(url)
    assert server.requests == []


def test_oversized_body_is_rejected_and_not_cached(tmp_path: Path, make_client: MakeClient) -> None:
    client, _, _ = make_client(ok(b"x" * 11), max_bytes=10)
    with pytest.raises(FetchError, match="larger than"):
        client.get(URL)
    assert list((tmp_path / "cache").glob("*")) == []


def test_oversized_body_without_content_length_is_still_rejected(make_client: MakeClient) -> None:
    def chunks() -> httpx.SyncByteStream:
        class Stream(httpx.SyncByteStream):
            def __iter__(self):  # type: ignore[no-untyped-def]
                yield b"x" * 6
                yield b"x" * 6

        return Stream()

    client, _, _ = make_client(httpx.Response(200, stream=chunks()), max_bytes=10)
    with pytest.raises(FetchError, match="larger than"):
        client.get(URL)


def test_user_agent_is_generic_and_has_no_contact_details(make_client: MakeClient) -> None:
    client, server, _ = make_client(ok())
    client.get(URL)
    agent = server.requests[0].headers["user-agent"]
    assert agent.startswith("canadian-macro")
    assert "@" not in agent


def test_params_reach_the_server(make_client: MakeClient) -> None:
    client, server, _ = make_client(ok())
    client.get(URL, params={"b": "2", "a": "1"})
    assert str(server.requests[0].url) == f"{URL}?a=1&b=2"
