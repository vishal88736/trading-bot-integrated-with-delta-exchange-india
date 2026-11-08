import json
import os
import threading
from pathlib import Path

from bot.account import Account
from bot.backtest import Backtests
from bot.engine import Engine
from bot.models import State
from bot.settings import atomic_json, read_settings
from clients.delta import Delta, DeltaError, contract_size


class Service:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.engine = None
        self.active_settings = None
        self.error = None
        self.account = Account(self.credentials)
        self.backtests = Backtests(
            reference_root=root / "references",
            cache_path=root / "history.sqlite3",
            artifact_root=root / "research",
        )

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def execution_settings(self, configured=None):
        configured = configured or read_settings(self.root)
        if self.running:
            return self.active_settings or (self.engine.settings if self.engine else configured)
        return configured

    def credentials(self):
        path = self.root / "credentials.json"
        try:
            stored = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(stored, dict):
                raise ValueError
            credentials = (
                stored.get("api_key") or os.getenv("DELTA_API_KEY", ""),
                stored.get("api_secret") or os.getenv("DELTA_API_SECRET", ""),
            )
            if not all(isinstance(value, str) for value in credentials):
                raise ValueError
            return credentials
        except (OSError, ValueError, TypeError):
            raise DeltaError(
                "Saved demo credentials are unreadable; save them again in Connection settings"
            ) from None

    def state(self, settings=None):
        settings = settings or read_settings(self.root)
        path = self.root / f"{settings.mode}-{settings.symbol}.json"
        try:
            return State.parse(json.loads(path.read_text())) if path.exists() else State()
        except (OSError, ValueError, TypeError):
            raise DeltaError(
                "Saved trade state is invalid; inspect the runtime before restarting"
            ) from None

    def assert_editable(self):
        if self.running:
            raise DeltaError("Stop the runner before changing settings")
        # Check every mode/product, so switching symbol cannot hide an unfinished trade.
        for path in self.root.glob("*.json"):
            if path.name in ("settings.json", "credentials.json"):
                continue
            data = json.loads(path.read_text())
            if data.get("position") or data.get("pending"):
                raise DeltaError(
                    "Resolve the existing position before changing settings or credentials"
                )

    def assert_credentials_editable(self):
        # Account reads can be connected while a paper simulation is active.
        # Existing demo orders keep their original credentials for recovery.
        if self.running and self.execution_settings().mode == "demo":
            raise DeltaError("Pause the demo runner before changing its account credentials")
        for path in self.root.glob("demo-*.json"):
            data = json.loads(path.read_text())
            if data.get("position") or data.get("pending"):
                raise DeltaError("Resolve the existing demo position before changing credentials")

    def start(self, confirm_demo=False, expected_mode=None):
        with self.lock:
            if self.running:
                raise DeltaError("Runner is already active")
            settings = read_settings(self.root)
            if expected_mode is not None and settings.mode != expected_mode:
                raise DeltaError("Execution mode changed; review settings before starting")
            if settings.mode == "demo" and confirm_demo is not True:
                raise DeltaError("Confirm demo execution before starting exchange orders")
            self.active_settings = settings
            self.error = None
            self.stop_event.clear()

            def work():
                client = None
                credentials = ("", "")
                try:
                    credentials = self.credentials() if settings.mode == "demo" else ("", "")
                    client = Delta(*credentials)
                    engine = Engine(settings, client, self.root)
                    with self.lock:
                        self.engine = engine
                    engine.check_account()
                    while not self.stop_event.is_set():
                        engine.step()
                        self.stop_event.wait(settings.poll_seconds)
                except Exception as exc:
                    # Only known exceptions are safe to show; never expose request/secret objects.
                    with self.lock:
                        self.error = (
                            str(exc)
                            if isinstance(exc, DeltaError)
                            else "Runner failed; check configuration and market data"
                        )
                        for credential in credentials:
                            if credential:
                                self.error = self.error.replace(credential, "[redacted]")
                finally:
                    if client is not None:
                        client.close()

            self.engine = None
            self.thread = threading.Thread(target=work, name="delta-demo-runner", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread:
            thread.join(timeout=60)
        if self.running:
            raise DeltaError("Runner is finishing a request; wait before changing settings")

    def reconcile(self):
        if self.running:
            raise DeltaError("Stop the runner before reconciliation")
        settings = read_settings(self.root)
        if settings.mode == "demo":
            client = Delta(*self.credentials())
            try:
                product = client.product(settings.symbol)
                position = client.position(product["id"])
                if not isinstance(position, dict) or "size" not in position:
                    raise DeltaError("Demo position response cannot confirm a flat account")
                if contract_size(position["size"]) or client.open_orders(product["id"]):
                    raise DeltaError(
                        "Demo account must be flat with no open orders on this product"
                    )
            finally:
                client.close()
        state = self.state(settings)
        state.position, state.pending = None, None
        state.signature = settings.signature()
        state.events = (
            state.events
            + [{"kind": "reconciled", "note": "Local position cleared after flat check"}]
        )[-200:]
        atomic_json(self.root / f"{settings.mode}-{settings.symbol}.json", state.to_dict())
        self.engine = None
        self.error = None

    def snapshot(self):
        configured = read_settings(self.root)
        settings = self.execution_settings(configured)
        # Read the atomically persisted record, not a half-mutated worker object.
        state = self.state(settings)
        engine_matches = (
            self.engine is not None and self.engine.settings.signature() == settings.signature()
        )
        credential_error = None
        try:
            key, secret = self.credentials()
        except DeltaError as exc:
            key, secret = "", ""
            credential_error = str(exc)
        return {
            "running": self.running,
            "error": self.error,
            "settings": settings.model_dump(),
            "credentials_configured": bool(key and secret),
            "credentials_error": credential_error,
            "execution": {
                "mode": settings.mode,
                "simulation": settings.mode == "paper",
                "order_destination": "local_simulation"
                if settings.mode == "paper"
                else "delta_demo",
                "position_source": "local_paper" if settings.mode == "paper" else "demo_runner",
                "state_file": f"{settings.mode}-{settings.symbol}.json",
                "configured_settings_match": settings.signature() == configured.signature(),
            },
            "state": state.to_dict(),
            "price": self.engine.price if engine_matches else None,
            "quote": self.engine.quote if engine_matches else None,
            "candles": [vars(c) for c in self.engine.candles[-100:]] if engine_matches else [],
        }
