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

    def __post_init__(self):
        prices = [self.entry, self.stop, *self.targets]
        if (
            self.side not in ("buy", "sell")
            or len(self.targets) != 3
            or len(self.quantities) != 3
            or any(
                isinstance(p, bool) or not isinstance(p, (int, float)) or not isfinite(p) or p <= 0
                for p in prices
            )
            or any(type(q) is not int or q <= 0 for q in self.quantities)
            or type(self.remaining) is not int
            or self.remaining <= 0
            or type(self.stage) is not int
            or not 0 <= self.stage < 3
            or self.remaining != sum(self.quantities[self.stage :])
        ):
            raise ValueError("Invalid saved position")
        direction = 1 if self.side == "buy" else -1
        if any(
            direction * (b - a) <= 0
            for a, b in zip([self.entry] + self.targets, self.targets, strict=False)
        ):
            raise ValueError("Invalid saved target levels")


@dataclass
class State:
    signature: str = ""
    last_candle: int = 0
    position: Position | None = None
    pending: dict | None = None
    realized_quote: float = 0
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if (
            not isinstance(self.signature, str)
            or self.position is not None
            and not isinstance(self.position, Position)
            or type(self.last_candle) is not int
            or self.last_candle < 0
            or isinstance(self.realized_quote, bool)
            or not isinstance(self.realized_quote, (int, float))
            or not isfinite(self.realized_quote)
            or self.pending is not None
            and (not isinstance(self.pending, dict) or not self.pending)
            or not isinstance(self.events, list)
            or any(not isinstance(e, dict) for e in self.events)
        ):
            raise ValueError("Invalid saved state")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, data):
        data = dict(data)
        if data.get("position") is not None:
            data["position"] = Position(**data["position"])
        return cls(**data)
