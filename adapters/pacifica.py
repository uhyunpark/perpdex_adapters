"""
Pacifica Adapter - WebSocket-based trading adapter
Handles connection, BBO subscriptions, order execution, and position tracking
"""
import asyncio
import json
import time
import uuid
import base58
from typing import AsyncIterator, Optional, Dict, Any
from pydantic import BaseModel
from loguru import logger
import websockets

from solders.keypair import Keypair

from common.types import BBO, Fill, Side
from common.utils import now_ms


class PacificaConfig(BaseModel):
    private_key: str
    pair: str
    env: str = "testnet"


class PacificaAdapter:
    """Pacifica exchange adapter for trading"""

    # Class constants
    QUEUE_TIMEOUT_SEC = 1.0
    DISCONNECT_WAIT_SEC = 0.2
    WS_RECONNECT_DELAY_SEC = 1.0
    CANCEL_TIMEOUT_SEC = 5.0
    ORDER_RESPONSE_TIMEOUT_SEC = 10.0

    # WebSocket URLs
    WS_URL_MAINNET = "wss://ws.pacifica.fi/ws"
    WS_URL_TESTNET = "wss://test-ws.pacifica.fi/ws"

    # REST URLs (for potential future use)
    REST_URL_MAINNET = "https://api.pacifica.fi/api/v1"
    REST_URL_TESTNET = "https://test-api.pacifica.fi/api/v1"

    # Message expiry window
    EXPIRY_WINDOW_MS = 5_000

    def __init__(self, cfg: PacificaConfig):
        self.cfg = cfg
        self.ws_url = self._get_ws_url(cfg.env)
        self.rest_url = self._get_rest_url(cfg.env)

        # Solana keypair for signing
        self.keypair: Optional[Keypair] = None
        self.public_key: Optional[str] = None

        # WebSocket connection
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

        # Data queues
        self._bbo_queue: Optional[asyncio.Queue[BBO]] = None
        self._fill_queue: Optional[asyncio.Queue[Fill]] = None
        self._position_cache: Dict[str, Dict[str, Any]] = {}

        self._connected = False
        self._ws_task: Optional[asyncio.Task] = None

    def _get_ws_url(self, env: str) -> str:
        """Get WebSocket URL for environment"""
        if env == "mainnet":
            return self.WS_URL_MAINNET
        else:
            return self.WS_URL_TESTNET

    def _get_rest_url(self, env: str) -> str:
        """Get REST API URL for environment"""
        if env == "mainnet":
            return self.REST_URL_MAINNET
        else:
            return self.REST_URL_TESTNET

    def _format_symbol(self, pair: str) -> str:
        """Convert pair format to Pacifica symbol format

        Examples:
            SOL-USDT-PERP -> SOL
            ETH-USDT-PERP -> ETH
            BTC-USDT-PERP -> BTC
        """
        parts = pair.split("-")
        if parts:
            return parts[0]
        return pair

    def _sign_message(self, header: dict, payload: dict) -> tuple[str, str]:
        """Sign message using Solana keypair

        Returns:
            (message, signature) tuple
        """
        # Prepare message
        data = {
            **header,
            "data": payload,
        }

        # Sort keys recursively
        sorted_data = self._sort_json_keys(data)

        # Compact JSON (no spaces)
        message = json.dumps(sorted_data, separators=(",", ":"))

        # Sign message
        message_bytes = message.encode("utf-8")
        signature = self.keypair.sign_message(message_bytes)
        signature_b58 = base58.b58encode(bytes(signature)).decode("ascii")

        return (message, signature_b58)

    def _sort_json_keys(self, value):
        """Recursively sort JSON keys"""
        if isinstance(value, dict):
            sorted_dict = {}
            for key in sorted(value.keys()):
                sorted_dict[key] = self._sort_json_keys(value[key])
            return sorted_dict
        elif isinstance(value, list):
            return [self._sort_json_keys(item) for item in value]
        else:
            return value

    async def connect(self) -> bool:
        """Initialize WebSocket connection"""
        try:
            # STEP 1: Initialize keypair
            logger.info("[PACIFICA] Initializing keypair...")
            self.keypair = Keypair.from_base58_string(self.cfg.private_key)
            self.public_key = str(self.keypair.pubkey())
            logger.info(f"[PACIFICA] Public key: {self.public_key}")

            # STEP 2: Initialize data queues
            self._bbo_queue = asyncio.Queue()
            self._fill_queue = asyncio.Queue()

            # STEP 3: Connect to WebSocket
            logger.info(f"[PACIFICA] Connecting to {self.ws_url}...")
            self.ws = await websockets.connect(self.ws_url, ping_interval=30)

            # STEP 4: Start WebSocket message handler
            self._ws_task = asyncio.create_task(self._handle_ws_messages())

            # STEP 5: Subscribe to streams
            await self._subscribe_streams()

            self._connected = True
            logger.info("[PACIFICA] ✅ Successfully connected")
            return True

        except Exception as e:
            logger.error(f"[PACIFICA] ❌ Connection failed: {e}")
            return False

    async def disconnect(self):
        """Clean up connections"""
        logger.info("[PACIFICA] Disconnecting...")

        self._connected = False

        # Cancel WebSocket task
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self.ws:
            await self.ws.close()
            self.ws = None

        # Give background tasks time to exit
        await asyncio.sleep(self.DISCONNECT_WAIT_SEC)

        logger.info("[PACIFICA] ✅ Disconnected")

    def _validate_connection(self):
        """Validate connection state"""
        if not self._connected or not self.ws:
            raise RuntimeError("Not connected to Pacifica")

    async def _subscribe_streams(self):
        """Subscribe to market data and user streams"""
        try:
            symbol = self._format_symbol(self.cfg.pair)

            # Subscribe to order book (for BBO)
            subscribe_msg = {
                "method": "subscribe",
                "params": {
                    "source": "book",
                    "symbol": symbol,
                    "agg_level": 1
                }
            }
            await self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"[PACIFICA] Subscribed to orderbook for {symbol}")

            # Subscribe to account positions
            account_positions_msg = {
                "method": "subscribe",
                "params": {
                    "source": "account_positions",
                    "account": self.public_key
                }
            }
            await self.ws.send(json.dumps(account_positions_msg))
            logger.info(f"[PACIFICA] Subscribed to account positions for {self.public_key}")

        except Exception as e:
            logger.error(f"[PACIFICA] Failed to subscribe to streams: {e}")

    async def _handle_ws_messages(self):
        """Handle incoming WebSocket messages"""
        while self._connected and self.ws:
            try:
                message = await self.ws.recv()
                data = json.loads(message)

                # Handle different message types
                channel = data.get("channel", "")

                if channel == "book":
                    # Order book update (extract BBO)
                    await self._handle_orderbook_update(data.get("data", {}))

                elif channel == "account_positions":
                    # Position update
                    await self._handle_position_update(data.get("data", []))

                elif "result" in data or "error" in data:
                    # Subscription confirmation or error response
                    logger.debug(f"[PACIFICA] Response: {data}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[PACIFICA] WebSocket connection closed")
                if self._connected:
                    await self._reconnect()
                break

            except Exception as e:
                logger.error(f"[PACIFICA] Error handling message: {e}")
                continue

    async def _handle_orderbook_update(self, data: dict):
        """Handle orderbook update and extract BBO

        Format: {"l": [[bids], [asks]], "s": "SOL", "t": timestamp}
        Each level: {"p": price, "a": amount, "n": num_orders}
        """
        try:
            levels = data.get("l", [])

            if len(levels) >= 2:
                bids = levels[0]  # First array = bids
                asks = levels[1]  # Second array = asks

                if bids and asks:
                    # Extract best bid/ask
                    best_bid = float(bids[0]["p"])
                    best_ask = float(asks[0]["p"])

                    if best_bid > 0 and best_ask > 0:
                        bbo = BBO(
                            bid=best_bid,
                            ask=best_ask,
                            ts_ms=int(data.get("t", now_ms()))
                        )

                        try:
                            self._bbo_queue.put_nowait(bbo)
                        except asyncio.QueueFull:
                            pass  # Skip if queue is full

        except Exception as e:
            logger.error(f"[PACIFICA] Error handling orderbook: {e}")

    async def _handle_fill_update(self, data: dict):
        """Handle fill update"""
        try:
            # Parse fill data
            side_str = data.get("side", "").lower()
            side = Side.BID if side_str == "bid" or side_str == "buy" else Side.ASK

            px = float(data.get("price", 0))
            qty = float(data.get("amount", 0))
            fee = float(data.get("fee", 0))
            order_id = str(data.get("order_id", ""))
            client_order_id = data.get("client_order_id", "")

            fill = Fill(
                side=side,
                px=px,
                qty=qty,
                ts_ms=int(data.get("timestamp", now_ms())),
                order_id=order_id,
                client_order_id=client_order_id,
                fee=fee
            )

            logger.info(
                f"[PACIFICA] Fill detected: {fill.side} {fill.qty}@{fill.px} | "
                f"oid={order_id} | Fee=${fee:.4f}"
            )

            try:
                self._fill_queue.put_nowait(fill)
            except asyncio.QueueFull:
                pass

        except Exception as e:
            logger.error(f"[PACIFICA] Error handling fill: {e}")

    async def _handle_position_update(self, data: list):
        """Handle position update

        Format: [{"a": amount, "d": direction, "p": entry_price, "s": symbol, ...}, ...]
        """
        try:
            # Clear existing cache
            self._position_cache.clear()

            # Process all positions
            for position in data:
                symbol = position.get("s", "")
                amount = float(position.get("a", 0))
                direction = position.get("d", "")
                entry_price = float(position.get("p", 0))
                funding = float(position.get("f", 0))

                # Convert direction to signed quantity
                # "bid" = long (positive), "ask" = short (negative)
                qty = amount if direction == "bid" else -amount

                self._position_cache[symbol] = {
                    'qty': qty,
                    'avg_price': entry_price,
                    'symbol': symbol,
                    'unrealized_pnl': 0.0,  # Not provided in this stream
                    'funding': funding
                }

                logger.debug(
                    f"[PACIFICA] Position update: {symbol} "
                    f"qty={qty} entry={entry_price}"
                )

        except Exception as e:
            logger.error(f"[PACIFICA] Error handling position: {e}")

    async def _reconnect(self):
        """Reconnect WebSocket"""
        logger.info("[PACIFICA] Attempting to reconnect...")
        await asyncio.sleep(self.WS_RECONNECT_DELAY_SEC)

        try:
            if self.ws:
                await self.ws.close()

            self.ws = await websockets.connect(self.ws_url, ping_interval=30)
            await self._subscribe_streams()
            logger.info("[PACIFICA] ✅ Reconnected successfully")

        except Exception as e:
            logger.error(f"[PACIFICA] Reconnection failed: {e}")

    async def subscribe_bbo(self) -> AsyncIterator[BBO]:
        """Subscribe to best bid/offer stream"""
        self._validate_connection()

        while self._connected:
            try:
                bbo = await asyncio.wait_for(self._bbo_queue.get(), timeout=self.QUEUE_TIMEOUT_SEC)
                yield bbo
            except asyncio.TimeoutError:
                continue

    async def subscribe_fills(self) -> AsyncIterator[Fill]:
        """Subscribe to fill stream"""
        self._validate_connection()

        while self._connected:
            try:
                fill = await asyncio.wait_for(self._fill_queue.get(), timeout=self.QUEUE_TIMEOUT_SEC)
                yield fill
            except asyncio.TimeoutError:
                continue

    async def place_limit_order(
        self,
        side: Side,
        price: float,
        qty: float,
        post_only: bool = True,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None
    ) -> str:
        """Place limit order

        Args:
            side: Order side (BID/ASK)
            price: Limit price
            qty: Order quantity
            post_only: If True, order will only be maker
            reduce_only: If True, order can only reduce position
            client_order_id: Optional client order ID

        Returns:
            Order ID or client_order_id if successful
        """
        self._validate_connection()

        symbol = self._format_symbol(self.cfg.pair)

        if not client_order_id:
            client_order_id = str(uuid.uuid4())

        # Prepare signature header
        timestamp = int(time.time() * 1_000)
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": self.EXPIRY_WINDOW_MS,
            "type": "create_order",
        }

        # Prepare signature payload
        tif = "GTC"  # Good-til-cancel by default
        if post_only:
            tif = "ALO"  # Add liquidity only (post-only)

        signature_payload = {
            "symbol": symbol,
            "price": str(price),
            "reduce_only": reduce_only,
            "amount": str(qty),
            "side": side.value,
            "tif": tif,
            "client_order_id": client_order_id,
        }

        # Sign message
        message, signature = self._sign_message(signature_header, signature_payload)

        # Construct request
        request_header = {
            "account": self.public_key,
            "signature": signature,
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
        }

        message_to_send = {
            **request_header,
            **signature_payload,
        }

        # Send via WebSocket
        ws_message = {
            "id": str(uuid.uuid4()),
            "params": {"create_order": message_to_send},
        }

        try:
            await self.ws.send(json.dumps(ws_message))

            # Wait for response (simplified - in production you'd track request IDs)
            response = await asyncio.wait_for(
                self.ws.recv(),
                timeout=self.ORDER_RESPONSE_TIMEOUT_SEC
            )
            response_data = json.loads(response)

            # Check for success
            if "result" in response_data:
                result = response_data["result"]
                order_id = result.get("order_id", client_order_id)

                logger.info(
                    f"[PACIFICA] Order ACCEPTED: {side} {qty}@{price} | "
                    f"oid={order_id} cloid={client_order_id}"
                )
                return str(order_id)
            else:
                error_msg = response_data.get("error", "Unknown error")
                logger.error(f"[PACIFICA] Order REJECTED: {error_msg}")
                raise RuntimeError(f"Order rejected: {error_msg}")

        except asyncio.TimeoutError:
            logger.error("[PACIFICA] Order response timeout")
            raise RuntimeError("Order response timeout")
        except Exception as e:
            logger.error(f"[PACIFICA] Order placement failed: {e}")
            raise

    async def place_market_order(
        self,
        side: Side,
        qty: float,
        slippage_percent: float = 0.5,
        reduce_only: bool = False
    ) -> str:
        """Place market order

        Args:
            side: Order side (BID/ASK)
            qty: Order quantity
            slippage_percent: Max slippage percentage (default: 0.5%)
            reduce_only: If True, order can only reduce position

        Returns:
            Order ID if successful
        """
        self._validate_connection()

        symbol = self._format_symbol(self.cfg.pair)
        client_order_id = str(uuid.uuid4())

        # Prepare signature header
        timestamp = int(time.time() * 1_000)
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": self.EXPIRY_WINDOW_MS,
            "type": "create_market_order",
        }

        # Prepare signature payload
        signature_payload = {
            "symbol": symbol,
            "reduce_only": reduce_only,
            "amount": str(qty),
            "side": side.value,
            "slippage_percent": str(slippage_percent),
            "client_order_id": client_order_id,
        }

        # Sign message
        message, signature = self._sign_message(signature_header, signature_payload)

        # Construct request
        request_header = {
            "account": self.public_key,
            "signature": signature,
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
        }

        message_to_send = {
            **request_header,
            **signature_payload,
        }

        # Send via WebSocket
        ws_message = {
            "id": str(uuid.uuid4()),
            "params": {"create_market_order": message_to_send},
        }

        try:
            await self.ws.send(json.dumps(ws_message))

            reduce_flag = " [REDUCE-ONLY]" if reduce_only else ""
            logger.info(
                f"[PACIFICA] Market order sent: {side} {qty}{reduce_flag} | "
                f"cloid={client_order_id}"
            )

            # Wait for response
            response = await asyncio.wait_for(
                self.ws.recv(),
                timeout=self.ORDER_RESPONSE_TIMEOUT_SEC
            )
            response_data = json.loads(response)

            if "result" in response_data:
                logger.info(f"[PACIFICA] Market order ACCEPTED: {response_data['result']}")
                return client_order_id
            else:
                error_msg = response_data.get("error", "Unknown error")
                logger.error(f"[PACIFICA] Market order REJECTED: {error_msg}")
                raise RuntimeError(f"Market order rejected: {error_msg}")

        except asyncio.TimeoutError:
            logger.error("[PACIFICA] Market order response timeout")
            raise RuntimeError("Market order response timeout")
        except Exception as e:
            logger.error(f"[PACIFICA] Market order failed: {e}")
            raise

    async def cancel_order(
        self,
        order_id: Optional[int] = None,
        client_order_id: Optional[str] = None
    ) -> bool:
        """Cancel a specific order

        Args:
            order_id: Order ID to cancel (either this or client_order_id required)
            client_order_id: Client order ID to cancel

        Returns:
            True if successful
        """
        self._validate_connection()

        if not order_id and not client_order_id:
            raise ValueError("Must provide either order_id or client_order_id")

        symbol = self._format_symbol(self.cfg.pair)

        # Prepare signature header
        timestamp = int(time.time() * 1_000)
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": self.EXPIRY_WINDOW_MS,
            "type": "cancel_order",
        }

        # Prepare signature payload
        signature_payload = {
            "symbol": symbol,
        }

        if order_id:
            signature_payload["order_id"] = order_id
        else:
            signature_payload["client_order_id"] = client_order_id

        # Sign message
        message, signature = self._sign_message(signature_header, signature_payload)

        # Construct request
        request_header = {
            "account": self.public_key,
            "signature": signature,
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
        }

        message_to_send = {
            **request_header,
            **signature_payload,
        }

        # Send via WebSocket
        ws_message = {
            "id": str(uuid.uuid4()),
            "params": {"cancel_order": message_to_send},
        }

        try:
            await self.ws.send(json.dumps(ws_message))

            response = await asyncio.wait_for(
                self.ws.recv(),
                timeout=self.CANCEL_TIMEOUT_SEC
            )
            response_data = json.loads(response)

            if "result" in response_data:
                logger.info(f"[PACIFICA] Order cancelled: oid={order_id} cloid={client_order_id}")
                return True
            else:
                error_msg = response_data.get("error", "Unknown error")
                logger.error(f"[PACIFICA] Cancel failed: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"[PACIFICA] Cancel failed: {e}")
            return False

    async def cancel_all_orders(
        self,
        symbol: Optional[str] = None,
        exclude_reduce_only: bool = False
    ):
        """Cancel all open orders

        Args:
            symbol: Optional symbol to cancel orders for. If None, cancels all symbols.
            exclude_reduce_only: If True, don't cancel reduce-only orders
        """
        self._validate_connection()

        # Prepare signature header
        timestamp = int(time.time() * 1_000)
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": self.EXPIRY_WINDOW_MS,
            "type": "cancel_all_orders",
        }

        # Prepare signature payload
        signature_payload = {
            "all_symbols": symbol is None,
            "exclude_reduce_only": exclude_reduce_only,
        }

        if symbol:
            signature_payload["symbol"] = symbol

        # Sign message
        message, signature = self._sign_message(signature_header, signature_payload)

        # Construct request
        request_header = {
            "account": self.public_key,
            "signature": signature,
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
        }

        message_to_send = {
            **request_header,
            **signature_payload,
        }

        # Send via WebSocket
        ws_message = {
            "id": str(uuid.uuid4()),
            "params": {"cancel_all_orders": message_to_send},
        }

        try:
            await self.ws.send(json.dumps(ws_message))

            response = await asyncio.wait_for(
                self.ws.recv(),
                timeout=self.CANCEL_TIMEOUT_SEC
            )
            response_data = json.loads(response)

            logger.info(f"[PACIFICA] Cancel all response: {response_data}")

        except Exception as e:
            logger.error(f"[PACIFICA] Cancel all failed: {e}")
            raise

    async def get_position(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get current position for symbol

        Args:
            symbol: Optional symbol. If None, uses configured pair.

        Returns:
            Position dictionary with keys: qty, avg_price, symbol, unrealized_pnl
        """
        self._validate_connection()

        sym = symbol if symbol else self._format_symbol(self.cfg.pair)

        # Return cached position
        if sym in self._position_cache:
            return self._position_cache[sym]

        # No position
        return {'qty': 0.0, 'avg_price': 0.0, 'symbol': sym, 'unrealized_pnl': 0.0}
