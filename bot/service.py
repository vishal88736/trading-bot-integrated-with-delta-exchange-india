import json
import os
import threading
from pathlib import Path

from bot.account import Account
from bot.backtest import Backtests
from bot.engine import Engine
from bot.models import State
from bot.settings import atomic_json, read_settings
from clients.delta import Delta, DeltaError


class Service:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.engine = None
        self.error = None
        self.account = Account(self.credentials)
        self.backtests = Backtests(reference_root=root / "references")

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def credentials(self):
        path = self.root / "credentials.json"
        stored = json.loads(path.read_text()) if path.exists() else {}
        return (
            stored.get("api_key") or os.getenv("DELTA_API_KEY", ""),
            stored.get("api_secret") or os.getenv("DELTA_API_SECRET", ""),
        )

    def state(self, settings=None):
        settings = settings or read_settings(self.root)
        path = self.root / f"{settings.mode}-{settings.symbol}.json"
        return State.parse(json.loads(path.read_text())) if path.exists() else State()

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
        if self.running and read_settings(self.root).mode == "demo":
            raise DeltaError("Pause the demo runner before changing its account credentials")
        for path in self.root.glob("demo-*.json"):
            data = json.loads(path.read_text())
            if data.get("position") or data.get("pending"):
                raise DeltaError("Resolve the existing demo position before changing credentials")

    def start(self):
        with self.lock:
            if self.running:
                raise DeltaError("Runner is already active")
            settings = read_settings(self.root)
            self.error = None
            self.stop_event.clear()

            def work():
                client = Delta(*self.credentials())
                try:
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
                        for credential in self.credentials():
                            if credential:
                                self.error = self.error.replace(credential, "[redacted]")
                finally:
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
                if int(client.position(product["id"]).get("size", 0)) or client.open_orders(
                    product["id"]
                ):
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
        settings = read_settings(self.root)
        state = self.engine.state if self.engine else self.state(settings)
        key, secret = self.credentials()
        return {
            "running": self.running,
            "error": self.error,
            "settings": settings.model_dump(),
            "credentials_configured": bool(key and secret),
            "state": state.to_dict(),
            "price": self.engine.price if self.engine else None,
            "quote": self.engine.quote if self.engine else None,
            "candles": [vars(c) for c in self.engine.candles[-100:]] if self.engine else [],
        }
