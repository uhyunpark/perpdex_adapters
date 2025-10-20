"""
Common data types for the trading system
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class Side(Enum):
    """Order side"""
    BID = "bid"
    ASK = "ask"


@dataclass
class BBO:
    """Best Bid/Offer"""
    bid: float
    ask: float
    ts_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class Fill:
    """Order fill/execution"""
    side: Side
    px: float
    qty: float
    ts_ms: int
    order_id: str = ""
    client_order_id: str = ""
    realized_pnl: float = 0.0  # Realized PnL from this fill (GRVT only)
    fee: float = 0.0  # Fee paid for this fill


@dataclass
class HedgeResult:
    """Result of hedge operation"""
    ok: bool
    avg_px: float = 0.0
    filled: float = 0.0
    err: str = ""


@dataclass
class OrderRequest:
    """Order placement request"""
    side: Side
    price: float
    qty: float
    client_order_id: Optional[str] = None
    post_only: bool = True


@dataclass
class Position:
    """Position information"""
    symbol: str
    size: float  # Positive for long, negative for short
    avg_px: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class OrderbookLevel:
    """Single price level in orderbook"""
    price: str  # Price as string from exchange
    size: str   # Size as string from exchange

    @property
    def price_float(self) -> float:
        return float(self.price)
    
    @property
    def size_float(self) -> float:
        return float(self.size)


@dataclass
class Orderbook:
    """Full orderbook snapshot"""
    code: int
    asks: List[OrderbookLevel]
    bids: List[OrderbookLevel]
    offset: int

    @property
    def best_bid(self) -> Optional[OrderbookLevel]:
        """Get best bid (highest price)"""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderbookLevel]:
        """Get best ask (lowest price)"""
        return self.asks[0] if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        """Get mid price between best bid and ask"""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price_float + self.best_ask.price_float) / 2.0
        return None


@dataclass
class MarketInfo:
    """Market information from ticker stream (funding, OI, volume)"""
    instrument: str
    funding_rate: float
    open_interest: float
    volume_24h: float
    mark_price: float
    index_price: float
    ts_ms: int