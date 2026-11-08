import json

import pytest

from bot.engine import Engine
from bot.settings import Settings
from clients.delta import DeltaError


@pytest.mark.parametrize(
    "change",
    [
        {"realized_quote": float("nan")},
        {"pending": []},
        {"position": 0},
        {
            "position": {
                "side": "buy",
                "entry": 100,
                "stop": 80,
                "targets": [110, 120, 140],
                "quantities": [-2, 1, 1],
                "remaining": 4,
            }
        },
        {
            "position": {
                "side": "buy",
                "entry": 100,
                "stop": 80,
                "targets": [110, 120, 140],
                "quantities": [2, 1, 1],
                "remaining": 3,
            }
        },
        {
            "position": {
                "side": "buy",
                "entry": 100,
                "stop": 80,
                "targets": [110, 120, 140],
                "quantities": [2, 1, 1],
                "remaining": 4,
                "stage": 3,
            }
        },
    ],
)
def test_corrupt_state_halts_before_any_exchange_request(tmp_path, change):
    settings = Settings()
    original = json.dumps({"signature": settings.signature(), **change})
    path = tmp_path / "paper-BTCUSD.json"
    path.write_text(original)
    with pytest.raises(DeltaError, match="Saved trade state is invalid"):
        Engine(settings, object(), tmp_path)
    assert path.read_text() == original
