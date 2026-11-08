from types import SimpleNamespace

import pytest

from bot.models import State
from bot.service import Service
from bot.settings import Settings, atomic_json
from clients.delta import DeltaError


def test_client_startup_error_is_reported_in_status(tmp_path, monkeypatch):
    def unavailable(*args):
        raise DeltaError("fixture client unavailable")

    monkeypatch.setattr("bot.service.Delta", unavailable)
    service = Service(tmp_path)
    service.start()
    service.thread.join(timeout=5)
    assert not service.running
    assert service.snapshot()["error"] == "fixture client unavailable"


def test_active_engine_settings_remain_the_status_authority(tmp_path):
    active = Settings(mode="paper", symbol="ETHUSD")
    atomic_json(tmp_path / "settings.json", Settings(mode="demo").model_dump())
    atomic_json(tmp_path / "paper-ETHUSD.json", State(signature=active.signature()).to_dict())
    service = Service(tmp_path)
    service.engine = SimpleNamespace(
        settings=active, state=State(), price=None, quote="USD", candles=[]
    )
    service.thread = SimpleNamespace(is_alive=lambda: True)
    snapshot = service.snapshot()
    assert snapshot["settings"]["mode"] == "paper"
    assert snapshot["settings"]["symbol"] == "ETHUSD"
    assert snapshot["execution"]["simulation"] is True
    assert snapshot["execution"]["configured_settings_match"] is False


def test_active_demo_credentials_cannot_change_when_saved_mode_is_edited(tmp_path):
    service = Service(tmp_path)
    service.active_settings = Settings(mode="demo")
    service.thread = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(DeltaError, match="Pause the demo runner"):
        service.assert_credentials_editable()


def test_unpersisted_worker_mutations_do_not_leak_into_status(tmp_path):
    settings = Settings()
    saved = State(signature=settings.signature(), realized_quote=10)
    atomic_json(tmp_path / "paper-BTCUSD.json", saved.to_dict())
    service = Service(tmp_path)
    service.engine = SimpleNamespace(
        settings=settings, state=State(realized_quote=999), price=None, quote="USD", candles=[]
    )
    service.thread = SimpleNamespace(is_alive=lambda: True)
    assert service.snapshot()["state"]["realized_quote"] == 10


def test_invalid_credentials_do_not_break_the_status_or_expose_contents(tmp_path):
    (tmp_path / "credentials.json").write_text('{"api_secret": "fixture-private-value"')
    service = Service(tmp_path)
    snapshot = service.snapshot()
    assert snapshot["credentials_configured"] is False
    assert "unreadable" in snapshot["credentials_error"]
    assert "fixture-private-value" not in str(snapshot)
    assert service.account.snapshot()["status"] == "error"


def test_reconciliation_rejects_fractional_position_data(tmp_path, monkeypatch):
    atomic_json(tmp_path / "settings.json", Settings(mode="demo").model_dump())
    client = SimpleNamespace(
        product=lambda symbol: {"id": 84},
        position=lambda product: {"size": 0.9},
        open_orders=lambda product: [],
        close=lambda: None,
    )
    monkeypatch.setattr("bot.service.Delta", lambda *args: client)
    service = Service(tmp_path)
    with pytest.raises(DeltaError, match="contract quantity"):
        service.reconcile()
    assert not (tmp_path / "demo-BTCUSD.json").exists()


def test_demo_start_requires_explicit_confirmation(tmp_path):
    atomic_json(tmp_path / "settings.json", Settings(mode="demo").model_dump())
    service = Service(tmp_path)
    with pytest.raises(DeltaError, match="Confirm demo execution"):
        service.start()
    assert service.thread is None


def test_start_rejects_a_changed_mode_before_initializing_client(tmp_path):
    service = Service(tmp_path)
    with pytest.raises(DeltaError, match="mode changed"):
        service.start(expected_mode="demo", confirm_demo=True)
    assert service.thread is None


def test_paper_start_does_not_load_exchange_credentials(tmp_path, monkeypatch):
    atomic_json(
        tmp_path / "credentials.json", {"api_key": "fixture-key", "api_secret": "fixture-secret"}
    )
    observed = []

    def unavailable(*credentials):
        observed.append(credentials)
        raise DeltaError("fixture client unavailable")

    monkeypatch.setattr("bot.service.Delta", unavailable)
    service = Service(tmp_path)
    service.start(expected_mode="paper")
    service.thread.join(timeout=5)
    assert observed == [("", "")]
