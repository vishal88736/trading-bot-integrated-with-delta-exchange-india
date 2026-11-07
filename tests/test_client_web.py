import hashlib
import hmac
import json
import time

import pytest
import requests
from fastapi.testclient import TestClient

from bot.web import create_app
from clients.delta import DEMO_URL, Delta, DeltaError, UncertainOrder, tick_price


class Session:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.sent = []

    def send(self, request, **kwargs):
        self.sent.append((request, kwargs))
        if self.error:
            raise self.error
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(self.response or {"success": True, "result": {}}).encode()
        return response


def test_signature_matches_actual_encoded_query_and_body():
    session = Session()
    client = Delta("fixture-key", "fixture-secret", session)
    client.request("GET", "/v2/orders", params={"states": "open,pending"}, auth=True)
    request, options = session.sent[0]
    assert request.url.startswith(DEMO_URL)
    message = "GET" + request.headers["timestamp"] + request.path_url
    expected = hmac.new(b"fixture-secret", message.encode(), hashlib.sha256).hexdigest()
    assert request.headers["signature"] == expected
    assert "%2C" in request.path_url and options["allow_redirects"] is False


def test_order_timeout_never_retries():
    session = Session(error=requests.Timeout("fixture timeout"))
    client = Delta("fixture-key", "fixture-secret", session)
    with pytest.raises(UncertainOrder):
        client.market_order(84, "buy", 4, "fixture-id", "80.0")
    assert len(session.sent) == 1


def test_reduce_only_and_initial_bracket_are_explicit():
    session = Session()
    client = Delta("fixture-key", "fixture-secret", session)
    client.market_order(84, "buy", 4, "entry-id", "80.0")
    client.market_order(84, "sell", 2, "exit-id")
    entry, exit_order = [json.loads(row[0].body) for row in session.sent]
    assert entry["bracket_stop_loss_price"] == "80.0" and entry["reduce_only"] is False
    assert exit_order["reduce_only"] is True and "product_symbol" not in entry


def test_old_ticker_is_rejected():
    client = Delta(
        session=Session(
            {"success": True, "result": {"close": 100, "timestamp": (time.time() - 200) * 1000000}}
        )
    )
    with pytest.raises(DeltaError, match="stale"):
        client.ticker("BTCUSD")


def test_tick_precision_is_not_float_rounding():
    assert tick_price(100.13, "0.25") == "100.25"
    assert tick_price(100.11, "0.25") == "100.00"


def test_dashboard_settings_and_credentials_roundtrip(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        status = client.get("/api/status").json()
        assert status["settings"]["mode"] == "paper"
        settings = status["settings"]
        settings.update(symbol="ETHUSD", tp_atr=[1.5, 3.0, 5.0])
        assert client.post("/api/settings", json=settings).status_code == 200
        assert client.get("/api/status").json()["settings"]["symbol"] == "ETHUSD"
        assert (
            client.post(
                "/api/credentials", json={"api_key": "fixture-key", "api_secret": "fixture-secret"}
            ).status_code
            == 200
        )
        result = client.get("/api/status")
        assert result.json()["credentials_configured"] is True
        assert "fixture-secret" not in result.text and "fixture-key" not in result.text
        assert (
            client.get("/").status_code == 200 and client.get("/static/app.js").status_code == 200
        )


def test_secret_validation_does_not_echo_input(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/credentials",
            json={
                "api_key": "fixture-key",
                "api_secret": "sensitive-input",
                "extra": "hidden-secret",
            },
        )
        assert response.status_code == 422
        assert "sensitive-input" not in response.text and "hidden-secret" not in response.text


def test_cross_site_start_and_bad_host_blocked(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert (
            client.post(
                "/api/start", json={}, headers={"Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/start", content="{}").status_code == 415
        assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400


def test_production_execution_cannot_be_selected(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        settings = client.get("/api/status").json()["settings"]
        settings["mode"] = "live"
        assert client.post("/api/settings", json=settings).status_code == 422
