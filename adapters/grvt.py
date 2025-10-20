"""
GRVT Adapter - Market making and WebSocket streaming
Handles connection, BBO subscriptions, and post-only order placement
"""
import asyncio
import os
from typing import AsyncIterator, Optional, Dict, TypeVar, Any
from pydantic import BaseModel
from loguru import logger as loguru_logger

from pysdk.grvt_ccxt_env import GrvtEnv, GrvtWSEndpointType
from pysdk.grvt_ccxt_ws import GrvtCcxtWS
from pysdk.grvt_ccxt_pro import GrvtCcxtPro
from pysdk.grvt_ccxt_types import GrvtOrderSide
from pysdk.grvt_ccxt_utils import rand_uint32
from pysdk.grvt_ccxt_logging_selector import logger as grvt_logger

from common.types import BBO, Fill, Side, MarketInfo
from common.utils import now_ms
from config import CFG

T = TypeVar('T')


class GrvtConfig(BaseModel):
    api_key: str
    private_key: Optional[str] = None
    trading_account_id: str
    pair: str
    env: str = "prod"


class GrvtAdapter:
    """GRVT exchange adapter for market making"""
    
    # Class constants
    DEFAULT_TICK_SIZE = 0.01
    QUEUE_TIMEOUT_SEC = 1.0
    DISCONNECT_WAIT_SEC = 0.2
    NANOSECONDS_TO_MS = 1_000_000

    def __init__(self, cfg: GrvtConfig):
        self.cfg = cfg
        self.env = GrvtEnv(cfg.env)
        self.ws_client: Optional[GrvtCcxtWS] = None
        self.rest_client: Optional[GrvtCcxtPro] = None
        self._fill_queue: Optional[asyncio.Queue[Fill]] = None
        self._ticker_queue: Optional[asyncio.Queue[BBO]] = None
        self._market_info_queue: Optional[asyncio.Queue[MarketInfo]] = None  # Market info from ticker.d
        self._position_cache: Dict[str, Dict[str, Any]] = {}  # Cache positions from WebSocket
        self._order_state_queue: Optional[asyncio.Queue[Dict[str, Any]]] = None  # Order state updates
        self._connected = False

    def _format_instrument(self, pair: str) -> str:
        """Convert pair format to GRVT instrument format"""
        return pair.replace("-", "_").replace("PERP", "Perp")

    async def connect(self) -> bool:
        """Initialize both WebSocket and REST connections"""
        try:
            loop = asyncio.get_event_loop()

            # STEP 1: Initialize WebSocket client
            loguru_logger.info("[GRVT] Initializing WebSocket client...")
            ws_params = {
                "api_key": self.cfg.api_key,
                "trading_account_id": self.cfg.trading_account_id,
                "api_ws_version": "v1"
            }
            if self.cfg.private_key:
                ws_params["private_key"] = self.cfg.private_key

            self.ws_client = GrvtCcxtWS(self.env, loop, grvt_logger, parameters=ws_params)
            await self.ws_client.initialize()

            # STEP 2: Initialize REST client
            loguru_logger.info("[GRVT] Initializing REST API client...")
            rest_params = {
                "api_key": self.cfg.api_key,
                "trading_account_id": self.cfg.trading_account_id,
            }
            if self.cfg.private_key:
                rest_params["private_key"] = self.cfg.private_key

            self.rest_client = GrvtCcxtPro(self.env, grvt_logger, parameters=rest_params)
            await self.rest_client.load_markets()

            # STEP 3: Initialize data queues
            self._fill_queue = asyncio.Queue()
            self._ticker_queue = asyncio.Queue()
            self._market_info_queue = asyncio.Queue()
            self._order_state_queue = asyncio.Queue()

            # STEP 4: Subscribe to all WebSocket streams
            loguru_logger.info("[GRVT] Starting WebSocket streams...")
            await self._subscribe_websocket_streams()

            self._connected = True
            loguru_logger.info("[GRVT] ✅ Successfully connected to GRVT")
            return True

        except Exception as e:
            loguru_logger.error(f"[GRVT] ❌ Connection failed: {e}")
            return False

    async def disconnect(self):
        """Clean up connections"""
        loguru_logger.info("[GRVT] Disconnecting...")

        # Stop WebSocket streams
        self._connected = False

        # Give background tasks time to exit
        await asyncio.sleep(self.DISCONNECT_WAIT_SEC)

        # Cleanup WebSocket client
        if self.ws_client:
            del self.ws_client

        # Close REST client
        if self.rest_client and hasattr(self.rest_client, 'close'):
            try:
                await self.rest_client.close()
            except Exception as e:
                loguru_logger.warning(f"[GRVT] Error closing REST client: {e}")

        loguru_logger.info("[GRVT] ✅ Disconnected")

    async def _subscribe_from_queue(self, queue: asyncio.Queue[T], require_private_key: bool = False) -> AsyncIterator[T]:
        """Helper method to yield items from a queue"""
        if not self._connected:
            raise RuntimeError("Not connected to GRVT")
        if require_private_key and not self.cfg.private_key:
            raise RuntimeError("Not connected or no private key")

        while self._connected:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=self.QUEUE_TIMEOUT_SEC)
                yield item
            except asyncio.TimeoutError:
                continue

    async def subscribe_bbo(self) -> AsyncIterator[BBO]:
        """Subscribe to best bid/offer stream"""
        async for bbo in self._subscribe_from_queue(self._ticker_queue):
            yield bbo

    async def subscribe_fills(self) -> AsyncIterator[Fill]:
        """Subscribe to private fill stream"""
        async for fill in self._subscribe_from_queue(self._fill_queue, require_private_key=True):
            yield fill

    async def subscribe_order_states(self) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to order state stream (for rejection detection)"""
        async for order_state in self._subscribe_from_queue(self._order_state_queue, require_private_key=True):
            yield order_state

    async def subscribe_market_info(self) -> AsyncIterator[MarketInfo]:
        """Subscribe to market info stream (funding rate, OI, volume from ticker.d)"""
        async for market_info in self._subscribe_from_queue(self._market_info_queue):
            yield market_info

    def _prepare_order_params(self, side: Side, price: float, qty: float, client_order_id: Optional[str] = None) -> tuple[str, str, float, str]:
        """Helper method to prepare common order parameters"""
        if not client_order_id:
            client_order_id = str(rand_uint32())

        symbol = self._format_instrument(self.cfg.pair)
        grvt_side = "buy" if side == Side.BID else "sell"
        rounded_price = round(price / self.DEFAULT_TICK_SIZE) * self.DEFAULT_TICK_SIZE

        return symbol, grvt_side, rounded_price, client_order_id

    def _validate_order_connection(self):
        """Validate connection and private key for order placement"""
        if not self._connected or not self.cfg.private_key:
            raise RuntimeError("Not connected or no private key")

    async def place_postonly_limit(self, side: Side, price: float, qty: float, client_order_id: Optional[str] = None) -> str:
        """Place post-only limit order using REST API"""
        self._validate_order_connection()
        symbol, grvt_side, rounded_price, client_order_id = self._prepare_order_params(side, price, qty, client_order_id)

        try:
            # Use REST API for order placement
            order = await self.rest_client.create_order(
                symbol=symbol,
                order_type="limit",
                side=grvt_side,
                amount=qty,
                price=rounded_price,
                params={
                    "client_order_id": client_order_id,
                    "time_in_force": "GOOD_TILL_TIME",
                    "post_only": True
                }
            )

            # ccxt returns order object with 'id' field
            if order and "id" in order:
                order_id = order["id"]
                loguru_logger.info(
                    f"[GRVT] Order ACCEPTED: {side} {qty}@{rounded_price} | "
                    f"oid={order_id} coid={client_order_id}"
                )
                return client_order_id
            else:
                loguru_logger.warning(f"[GRVT] Unclear response: {order}")
                return client_order_id

        except Exception as e:
            loguru_logger.error(f"[GRVT] Order placement failed: {e}")
            raise

    async def place_postonly_limit_ws(self, side: Side, price: float, qty: float, client_order_id: Optional[str] = None) -> str:
        """Place post-only limit order using WebSocket RPC"""
        self._validate_order_connection()
        symbol, grvt_side, rounded_price, client_order_id = self._prepare_order_params(side, price, qty, client_order_id)

        try:
            # Use WebSocket RPC for order placement
            await self.ws_client.rpc_create_order(
                symbol=symbol,
                order_type="limit",
                side=grvt_side,
                amount=qty,
                price=str(rounded_price),
                params={
                    "client_order_id": client_order_id,
                    "time_in_force": "GOOD_TILL_TIME",
                    "post_only": True
                }
            )

            loguru_logger.info(
                f"[GRVT-WS] Order sent: {side} {qty}@{rounded_price} | coid={client_order_id}"
            )
            return client_order_id

        except Exception as e:
            loguru_logger.error(f"[GRVT-WS] Order placement failed: {e}")
            raise

    async def cancel_all_orders(self):
        """Cancel all open orders"""
        self._validate_order_connection()

        try:
            await self.ws_client.rpc_cancel_all_orders()
            loguru_logger.info("[GRVT] Cancelled all orders")
        except Exception as e:
            loguru_logger.error(f"[GRVT] Cancel all failed: {e}")
            raise

    async def _subscribe_websocket_streams(self):
        """Subscribe to all WebSocket streams (BBO, fills, positions)"""
        try:
            instrument = self._format_instrument(self.cfg.pair)

            # 1. Subscribe to BBO stream (mini.d - delta stream for faster updates)
            # Rate options: 0 (raw), 50, 100, 200, 500, 1000, 5000 (milliseconds)
            rate = "50"  # raw feed somehow not working, set to 50

            async def ticker_callback(message: dict):
                try:
                    feed = message.get("feed", {})
                    if "best_bid_price" in feed and "best_ask_price" in feed:
                        bbo = BBO(
                            bid=float(feed["best_bid_price"]),
                            ask=float(feed["best_ask_price"]),
                            ts_ms=int(feed.get("event_time", now_ms())) // self.NANOSECONDS_TO_MS
                        )
                        await self._ticker_queue.put(bbo)
                except Exception as e:
                    loguru_logger.error(f"[GRVT] BBO callback error: {e}")

            await self.ws_client.subscribe(
                stream="mini.d",
                callback=ticker_callback,
                ws_end_point_type=None,
                params={"instrument": instrument, "rate": rate}
            )
            loguru_logger.info(f"[GRVT] Subscribed to BBO delta stream: {instrument}@{rate}")

            # 2. Subscribe to market info stream (ticker.d - for funding, OI, volume)
            # Use slower rate since this data changes less frequently
            market_info_rate = "1000"  # 1 second interval

            async def market_info_callback(message: dict):
                try:
                    feed = message.get("feed", {})
                    if "funding_rate" in feed:
                        market_info = MarketInfo(
                            instrument=feed.get("instrument", instrument),
                            funding_rate=float(feed.get("funding_rate", 0)),
                            open_interest=float(feed.get("open_interest", 0)),
                            volume_24h=float(feed.get("volume_24h", 0)),
                            mark_price=float(feed.get("mark_price", 0)),
                            index_price=float(feed.get("index_price", 0)),
                            ts_ms=int(feed.get("event_time", now_ms())) // self.NANOSECONDS_TO_MS
                        )
                        await self._market_info_queue.put(market_info)
                except Exception as e:
                    loguru_logger.error(f"[GRVT] Market info callback error: {e}")

            await self.ws_client.subscribe(
                stream="ticker.d",
                callback=market_info_callback,
                ws_end_point_type=None,
                params={"instrument": instrument, "rate": market_info_rate}
            )
            loguru_logger.info(f"[GRVT] Subscribed to market info stream: {instrument}@{market_info_rate}")

            # 3. Subscribe to fill stream (private fills)
            if self.cfg.private_key:
                async def fill_callback(message: dict):
                    try:
                        feed = message.get("feed", {})
                        if feed and "price" in feed:
                            is_buyer = feed.get("is_buyer", False)
                            side = Side.BID if is_buyer else Side.ASK
                            realized_pnl = float(feed.get("realized_pnl", 0.0))
                            fee = float(feed.get("fee", 0.0))

                            fill = Fill(
                                side=side,
                                px=float(feed["price"]),
                                qty=float(feed["size"]),
                                ts_ms=int(feed.get("event_time", now_ms())) // self.NANOSECONDS_TO_MS,
                                order_id=feed.get("order_id", ""),
                                client_order_id=feed.get("client_order_id", ""),
                                realized_pnl=realized_pnl,
                                fee=fee
                            )

                            loguru_logger.info(
                                f"[GRVT] Fill detected: {fill.side} {fill.qty}@{fill.px} | "
                                f"coid={fill.client_order_id} | PnL=${realized_pnl:.4f} | Fee=${fee:.4f}"
                            )
                            await self._fill_queue.put(fill)
                    except Exception as e:
                        loguru_logger.error(f"[GRVT] Fill callback error: {e}")

                await self.ws_client.subscribe(
                    stream="fill",
                    callback=fill_callback,
                    ws_end_point_type=GrvtWSEndpointType.TRADE_DATA_RPC_FULL,
                    params={"instrument": instrument}
                )
                loguru_logger.info(f"[GRVT] Subscribed to fill stream for {instrument}")

            # 3. Subscribe to position stream (all instruments)
            if self.cfg.private_key:
                await self.ws_client.subscribe(
                    stream="position",
                    callback=self._position_callback,
                    ws_end_point_type=GrvtWSEndpointType.TRADE_DATA_RPC_FULL,
                    params={}  # Empty params = all instruments
                )
                loguru_logger.info("[GRVT] Subscribed to position stream")

            # 4. Subscribe to order state stream (for rejection detection)
            if self.cfg.private_key:
                async def order_state_callback(message: dict):
                    try:
                        feed = message.get("feed", {})
                        order_state = feed.get("order_state", {})

                        if order_state:
                            # Put entire order state update in queue for strategy to handle
                            await self._order_state_queue.put({
                                "order_id": feed.get("order_id", ""),
                                "client_order_id": feed.get("client_order_id", ""),
                                "status": order_state.get("status", ""),
                                "reject_reason": order_state.get("reject_reason", ""),
                                "book_size": order_state.get("book_size", []),
                                "traded_size": order_state.get("traded_size", []),
                                "avg_fill_price": order_state.get("avg_fill_price", []),
                                "update_time": order_state.get("update_time", "")
                            })
                    except Exception as e:
                        loguru_logger.error(f"[GRVT] Order state callback error: {e}")

                await self.ws_client.subscribe(
                    stream="state",
                    callback=order_state_callback,
                    ws_end_point_type=GrvtWSEndpointType.TRADE_DATA_RPC_FULL,
                    params={"instrument": instrument}
                )
                loguru_logger.info(f"[GRVT] Subscribed to order state stream for {instrument}")

        except Exception as e:
            loguru_logger.error(f"[GRVT] Failed to subscribe to WebSocket streams: {e}")

    async def _position_callback(self, message: dict):
        """Callback for position updates from WebSocket"""
        try:
            feed = message.get("feed", {})
            if not feed:
                return

            instrument = feed.get("instrument", "")
            size = float(feed.get("size", 0))
            entry_price = float(feed.get("entry_price", 0))

            # Update position cache
            self._position_cache[instrument] = {
                'qty': size,
                'avg_price': entry_price,
                'symbol': instrument,
                'unrealized_pnl': float(feed.get("unrealized_pnl", 0)),
                'realized_pnl': float(feed.get("realized_pnl", 0)),
            }

            loguru_logger.debug(
                f"[GRVT] Position update: {instrument} size={size} entry={entry_price}"
            )

        except Exception as e:
            loguru_logger.error(f"[GRVT] Position callback error: {e}")

    async def get_position(self, instrument: str) -> Dict[str, Any]:
        """Get current position for instrument from WebSocket cache"""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Convert instrument format: SOL-USDT-PERP -> SOL_USDT_Perp
        symbol = self._format_instrument(instrument)

        # Return cached position from WebSocket stream
        if symbol in self._position_cache:
            return self._position_cache[symbol]

        # Not in cache = no position
        return {'qty': 0.0, 'avg_price': 0.0, 'symbol': symbol}