from dataclasses import asdict, dataclass, field
from math import isfinite

RESOLUTIONS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
}


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    def __post_init__(self):
        prices = (self.open, self.high, self.low, self.close)
        if (
            type(self.time) is not int
            or self.time < 0
            or any(not isfinite(p) or p <= 0 for p in prices)
            or not isfinite(self.volume)
            or self.volume < 0
            or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
        ):
            raise ValueError("Invalid candle data")

    @classmethod
    def parse(cls, row):
        return cls(
            time=int(row["time"]),
            **{k: float(row[k]) for k in ("open", "high", "low", "close")},
            volume=float(row.get("volume", 0)),
        )


@dataclass(frozen=True)
class Signal:
    side: str
    atr: float
    time: int
    reason: str

    def __post_init__(self):
        if self.side not in ("buy", "sell") or not isfinite(self.atr) or self.atr <= 0:
            raise ValueError("Invalid strategy signal")


@dataclass
class Position:
    side: str
    entry: float
    stop: float
    targets: list[float]
    quantities: list[int]
    remaining: int
    stage: int = 0


@dataclass
class State:
    signature: str = ""
    last_candle: int = 0
    position: Position | None = None
    pending: dict | None = None
    realized_quote: float = 0
    events: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, data):
        data = dict(data)
        if data.get("position"):
            data["position"] = Position(**data["position"])
        return cls(**data)
