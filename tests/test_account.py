from bot.account import Account, normalize
from clients.delta import DeltaError


class AccountClient:
    def __init__(self, *credentials):
        self.fail = False
        self.closed = False

    def balances(self):
        if self.fail:
            raise DeltaError("fixture-secret: invalid_api_key")
        return [
            {
                "asset_symbol": "USD",
                "balance": "1000",
                "available_balance": "850",
                "blocked_margin": "150",
                "api_secret": "should-never-escape",
            },
            {"asset_symbol": "BTC", "balance": "0.1", "available_balance": "0.1"},
        ]

    def positions(self):
        return [
            {
                "product_symbol": "BTCUSD",
                "size": 4,
                "unrealized_pnl": "-4",
                "product": {"settling_asset": {"symbol": "USD"}},
            }
        ]

    def account_orders(self):
        return {"rows": [], "truncated": False}

    def recent_fills(self):
        return []

    def close(self):
        self.closed = True


def test_account_disconnected_without_keys_makes_no_requests():
    account = Account(
        lambda: ("", ""), factory=lambda *args: (_ for _ in ()).throw(AssertionError())
    )
    assert account.snapshot()["status"] == "disconnected"


def test_wallet_keeps_assets_separate_and_does_not_expose_unknown_fields():
    rows = normalize("balances", AccountClient().balances())
    assert rows[0]["balance"] == 1000 and rows[1]["balance"] == 0.1
    assert rows[1]["blocked_margin"] is None
    assert "api_secret" not in rows[0]
    assert normalize("positions", AccountClient().positions())[0]["unrealized_pnl"] == -4


def test_refresh_retains_failed_data_as_stale_and_redacts_secrets():
    client = AccountClient()
    account = Account(lambda: ("fixture-key", "fixture-secret"), factory=lambda *args: client)
    account._refresh(("fixture-key", "fixture-secret"), 0)
    assert account.sections["balances"]["rows"][0]["balance"] == 1000
    client.fail = True
    account._refresh(("fixture-key", "fixture-secret"), 0)
    assert account.sections["balances"]["rows"][0]["balance"] == 1000
    assert account.sections["balances"]["updated_at"]
    assert "fixture-secret" not in account.sections["balances"]["error"]
    assert client.closed


def test_old_account_refresh_cannot_overwrite_new_credentials():
    account = Account(lambda: ("fixture-key", "fixture-secret"), factory=AccountClient)
    account.invalidate()
    account._refresh(("fixture-key", "fixture-secret"), 0)
    assert account.sections == {}


def test_slow_wallet_does_not_block_positions_orders_or_fills():
    import threading
    import time

    release_wallet = threading.Event()
    clients = []

    class SlowWallet(AccountClient):
        def __init__(self, *credentials):
            super().__init__(*credentials)
            clients.append(self)

        def balances(self):
            assert release_wallet.wait(5)
            return super().balances()

    account = Account(lambda: ("fixture-key", "fixture-secret"), factory=SlowWallet)
    try:
        account.snapshot()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = account.snapshot()
            if all(name in snapshot["sections"] for name in ("positions", "orders", "fills")):
                break
            time.sleep(0.005)
        assert snapshot["sections"]["positions"]["rows"][0]["symbol"] == "BTCUSD"
        assert "orders" in snapshot["sections"] and "fills" in snapshot["sections"]
        assert "balances" not in snapshot["sections"] and snapshot["refreshing"]
    finally:
        release_wallet.set()
        account.thread.join(timeout=5)
    assert not account.thread.is_alive()
    assert account.snapshot()["status"] == "connected"
    assert len(clients) == 4 and all(client.closed for client in clients)


def test_client_initialization_failure_is_reported_instead_of_loading_forever():
    def unavailable(*credentials):
        raise DeltaError("fixture-secret: unavailable")

    account = Account(lambda: ("fixture-key", "fixture-secret"), factory=unavailable)
    account.snapshot()
    account.thread.join(timeout=5)
    snapshot = account.snapshot()
    assert snapshot["status"] == "error" and not snapshot["refreshing"]
    assert len(snapshot["sections"]) == 4
    assert all("fixture-secret" not in s["error"] for s in snapshot["sections"].values())


def test_connecting_account_does_not_require_discarding_paper_positions(tmp_path):
    from bot.service import Service
    from bot.settings import atomic_json

    atomic_json(tmp_path / "paper-BTCUSD.json", {"position": {"remaining": 4}})
    Service(tmp_path).assert_credentials_editable()


def test_demo_recovery_keeps_its_original_credentials(tmp_path):
    import pytest

    from bot.service import Service
    from bot.settings import atomic_json

    atomic_json(tmp_path / "demo-BTCUSD.json", {"pending": {"operation": "entry"}})
    with pytest.raises(DeltaError, match="existing demo position"):
        Service(tmp_path).assert_credentials_editable()
