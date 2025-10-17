import asyncio
import json
import os
from typing import AsyncIterator, Optional, Dict, Any
from pydantic import BaseModel
from loguru import logger

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

from common.types import BBO, Fill, Side
from common.utils import now_ms


class HyperliquidConfig(BaseModel):
    private_key: str
    account_address: Optional[str] = None  # If None, derived from private_key
    pair: str
    env: str = "mainnet"


class HyperliquidAdapter:
    """Hyperliquid exchange adapter for market making"""

    # Class constants
    QUEUE_TIMEOUT_SEC = 1.0
    DISCONNECT_WAIT_SEC = 0.2

    def __init__(self, cfg: HyperliquidConfig):
        self.cfg = cfg
        self.base_url = self._get_base_url(cfg.env)

        # Hyperliquid clients
        self.account: Optional[LocalAccount] = None
        self.address: Optional[str] = None
        self.info: Optional[Info] = None
        self.exchange: Optional[Exchange] = None

        # Data queues
        self._bbo_queue: Optional[asyncio.Queue[BBO]] = None
        self._fill_queue: Optional[asyncio.Queue[Fill]] = None
        self._position_cache: Dict[str, Dict[str, Any]] = {}  # Cache positions by coin

        self._connected = False

    def _get_base_url(self, env: str) -> str:
        """Get API URL for environment"""
        if env == "mainnet":
            return constants.MAINNET_API_URL
        else:
            return constants.TESTNET_API_URL

    def _format_coin(self, pair: str) -> str:
        """Convert pair format to Hyperliquid coin format

        Examples:
            SOL-USDT-PERP -> SOL
            ETH-USDT-PERP -> ETH
            BTC-USDT-PERP -> BTC
        """
        # Extract base coin from pair
        parts = pair.split("-")
        if parts:
            return parts[0]
        return pair

    async def connect(self) -> bool:
        """Initialize both WebSocket and REST connections"""
        try:
            # STEP 1: Initialize account from private key
            logger.info("[HYPERLIQUID] Initializing account...")
            self.account = eth_account.Account.from_key(self.cfg.private_key)

            # Use provided address or derive from private key
            if self.cfg.account_address:
                self.address = self.cfg.account_address
            else:
                self.address = self.account.address

            logger.info(f"[HYPERLIQUID] Account address: {self.address}")
            if self.address != self.account.address:
                logger.info(f"[HYPERLIQUID] Agent address: {self.account.address}")

            # STEP 2: Initialize Info client (market data + WebSocket)
            logger.info("[HYPERLIQUID] Initializing Info client...")
            self.info = Info(self.base_url, skip_ws=False)

            # Verify account has equity
            user_state = self.info.user_state(self.address)
            spot_user_state = self.info.spot_user_state(self.address)
            margin_summary = user_state["marginSummary"]

            account_value = float(margin_summary["accountValue"])
            logger.info(f"[HYPERLIQUID] Account value: ${account_value:.2f}")

            if account_value == 0 and len(spot_user_state["balances"]) == 0:
                logger.error(
                    f"[HYPERLIQUID] Account {self.address} has no equity. "
                    f"Please fund the account on {self.base_url.split('.', 1)[1]}"
                )
                return False

            # STEP 3: Initialize Exchange client (order operations)
            logger.info("[HYPERLIQUID] Initializing Exchange client...")
            self.exchange = Exchange(
                self.account,
                self.base_url,
                account_address=self.address
            )

            # STEP 4: Initialize data queues
            self._bbo_queue = asyncio.Queue()
            self._fill_queue = asyncio.Queue()

            # STEP 5: Subscribe to WebSocket streams
            logger.info("[HYPERLIQUID] Starting WebSocket streams...")
            await self._subscribe_websocket_streams()

            self._connected = True
            logger.info("[HYPERLIQUID] ✅ Successfully connected to Hyperliquid")
            return True

        except Exception as e:
            logger.error(f"[HYPERLIQUID] ❌ Connection failed: {e}")
            return False

    async def disconnect(self):
        """Clean up connections"""
        logger.info("[HYPERLIQUID] Disconnecting...")

        # Stop WebSocket streams
        self._connected = False

        # Give background tasks time to exit
        await asyncio.sleep(self.DISCONNECT_WAIT_SEC)

        # Cleanup clients
        self.info = None
        self.exchange = None
        self.account = None

        logger.info("[HYPERLIQUID] ✅ Disconnected")

    async def _subscribe_from_queue(
        self,
        queue: asyncio.Queue,
        require_private_key: bool = False
    ) -> AsyncIterator:
        """Helper method to yield items from a queue"""
        if not self._connected:
            raise RuntimeError("Not connected to Hyperliquid")
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
        async for bbo in self._subscribe_from_queue(self._bbo_queue):
            yield bbo

    async def subscribe_fills(self) -> AsyncIterator[Fill]:
        """Subscribe to private fill stream"""
        async for fill in self._subscribe_from_queue(self._fill_queue, require_private_key=True):
            yield fill

    async def _subscribe_websocket_streams(self):
        """Subscribe to all WebSocket streams (BBO, fills, positions)"""
        try:
            coin = self._format_coin(self.cfg.pair)

            # 1. Subscribe to BBO stream
            def bbo_callback(message: dict):
                try:
                    # BBO message format: {"coin": "ETH", "bid": 2500.0, "ask": 2501.0, ...}
                    if "data" in message:
                        data = message["data"]
                        if "levels" in data and len(data["levels"]) >= 2:
                            # levels format: [[bid_prices, bid_sizes], [ask_prices, ask_sizes]]
                            bid_levels = data["levels"][0]
                            ask_levels = data["levels"][1]

                            if bid_levels and ask_levels:
                                # First level is best bid/ask
                                bid_price = float(bid_levels[0]["px"])
                                ask_price = float(ask_levels[0]["px"])

                                bbo = BBO(
                                    bid=bid_price,
                                    ask=ask_price,
                                    ts_ms=now_ms()
                                )

                                # Non-blocking put
                                try:
                                    self._bbo_queue.put_nowait(bbo)
                                except asyncio.QueueFull:
                                    pass

                    elif message.get("channel") == "l2Book":
                        # L2 book format
                        data = message.get("data", {})
                        if "levels" in data and len(data["levels"]) >= 2:
                            bids = data["levels"][0]  # [[price, size], ...]
                            asks = data["levels"][1]  # [[price, size], ...]

                            if bids and asks:
                                bid_price = float(bids[0]["px"])
                                ask_price = float(asks[0]["px"])

                                bbo = BBO(
                                    bid=bid_price,
                                    ask=ask_price,
                                    ts_ms=int(data.get("time", now_ms()))
                                )

                                try:
                                    self._bbo_queue.put_nowait(bbo)
                                except asyncio.QueueFull:
                                    pass

                except Exception as e:
                    logger.error(f"[HYPERLIQUID] BBO callback error: {e}")

            self.info.subscribe({"type": "l2Book", "coin": coin}, bbo_callback)
            logger.info(f"[HYPERLIQUID] Subscribed to BBO stream for {coin}")

            # 2. Subscribe to user fills
            if self.cfg.private_key:
                def fill_callback(message: dict):
                    try:
                        # userFills message format
                        if message.get("channel") == "user" and "data" in message:
                            data = message["data"]
                            if data.get("type") == "fill":
                                fill_data = data.get("data", {})

                                # Extract fill details
                                is_buy = fill_data.get("side", "") == "B"
                                side = Side.BID if is_buy else Side.ASK
                                px = float(fill_data.get("px", 0))
                                sz = float(fill_data.get("sz", 0))
                                fee = float(fill_data.get("fee", 0))
                                oid = fill_data.get("oid", "")

                                fill = Fill(
                                    side=side,
                                    px=px,
                                    qty=sz,
                                    ts_ms=int(fill_data.get("time", now_ms())),
                                    order_id=str(oid),
                                    client_order_id=fill_data.get("cloid", ""),
                                    fee=fee
                                )

                                logger.info(
                                    f"[HYPERLIQUID] Fill detected: {fill.side} {fill.qty}@{fill.px} | "
                                    f"oid={oid} | Fee=${fee:.4f}"
                                )

                                try:
                                    self._fill_queue.put_nowait(fill)
                                except asyncio.QueueFull:
                                    pass

                    except Exception as e:
                        logger.error(f"[HYPERLIQUID] Fill callback error: {e}")

                self.info.subscribe({"type": "userFills", "user": self.address}, fill_callback)
                logger.info(f"[HYPERLIQUID] Subscribed to fill stream for {self.address}")

            # 3. Subscribe to user events (positions, account updates)
            if self.cfg.private_key:
                def user_events_callback(message: dict):
                    try:
                        # Update position cache when positions change
                        if message.get("channel") == "user":
                            data = message.get("data", {})
                            if "assetPositions" in data:
                                for asset_pos in data["assetPositions"]:
                                    position = asset_pos.get("position", {})
                                    coin_symbol = position.get("coin", "")

                                    if coin_symbol:
                                        size = float(position.get("szi", 0))
                                        entry_px = float(position.get("entryPx", 0)) if size != 0 else 0
                                        unrealized_pnl = float(position.get("unrealizedPnl", 0))

                                        self._position_cache[coin_symbol] = {
                                            'qty': size,
                                            'avg_price': entry_px,
                                            'symbol': coin_symbol,
                                            'unrealized_pnl': unrealized_pnl
                                        }

                                        logger.debug(
                                            f"[HYPERLIQUID] Position update: {coin_symbol} "
                                            f"size={size} entry={entry_px}"
                                        )
                    except Exception as e:
                        logger.error(f"[HYPERLIQUID] User events callback error: {e}")

                self.info.subscribe({"type": "userEvents", "user": self.address}, user_events_callback)
                logger.info(f"[HYPERLIQUID] Subscribed to user events for {self.address}")

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Failed to subscribe to WebSocket streams: {e}")

    def _validate_order_connection(self):
        """Validate connection and private key for order placement"""
        if not self._connected or not self.cfg.private_key:
            raise RuntimeError("Not connected or no private key")

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
            post_only: If True, order will only be maker (default: True)
            reduce_only: If True, order can only reduce position (default: False)
            client_order_id: Optional client order ID

        Returns:
            Order ID if successful
        """
        self._validate_order_connection()

        coin = self._format_coin(self.cfg.pair)
        is_buy = (side == Side.BID)

        try:
            # Prepare order parameters
            order_params = {
                "limit": {
                    "tif": "Gtc"  # Good-til-cancel
                }
            }

            if post_only:
                order_params["limit"]["tif"] = "Alo"  # Add liquidity only (post-only)

            if reduce_only:
                order_params["reduceOnly"] = True

            if client_order_id:
                order_params["cloid"] = client_order_id

            # Place order
            order_result = self.exchange.order(
                coin,
                is_buy,
                qty,
                price,
                order_params
            )

            if order_result.get("status") == "ok":
                response_data = order_result.get("response", {}).get("data", {})
                statuses = response_data.get("statuses", [])

                if statuses and len(statuses) > 0:
                    status = statuses[0]

                    if "resting" in status:
                        oid = status["resting"]["oid"]
                        logger.info(
                            f"[HYPERLIQUID] Order ACCEPTED: {side} {qty}@{price} | "
                            f"oid={oid} cloid={client_order_id}"
                        )
                        return str(oid)
                    elif "filled" in status:
                        logger.info(
                            f"[HYPERLIQUID] Order FILLED immediately: {side} {qty}@{price}"
                        )
                        return "filled"
                    else:
                        logger.warning(f"[HYPERLIQUID] Unclear order status: {status}")
                        return ""
            else:
                error_msg = order_result.get("response", "Unknown error")
                logger.error(f"[HYPERLIQUID] Order REJECTED: {error_msg}")
                raise RuntimeError(f"Order rejected: {error_msg}")

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Order placement failed: {e}")
            raise

    async def place_market_order(
        self,
        side: Side,
        qty: float,
        slippage_bps: float = 100,
        reduce_only: bool = False
    ) -> str:
        """Place market order (IOC)

        Args:
            side: Order side (BID/ASK)
            qty: Order quantity
            slippage_bps: Max slippage in basis points (default: 100 = 1%)
            reduce_only: If True, order can only reduce position

        Returns:
            Order ID if successful
        """
        self._validate_order_connection()

        coin = self._format_coin(self.cfg.pair)
        is_buy = (side == Side.BID)

        try:
            # Get current mid price for slippage calculation
            user_state = self.info.user_state(self.address)

            # Find current mark price for the coin
            mark_px = None
            for asset_pos in user_state.get("assetPositions", []):
                position = asset_pos.get("position", {})
                if position.get("coin") == coin:
                    mark_px = float(position.get("markPx", 0))
                    break

            if not mark_px:
                # Fallback: get from all mids
                all_mids = self.info.all_mids()
                mark_px = float(all_mids.get(coin, 0))

            if not mark_px:
                raise RuntimeError(f"Could not determine price for {coin}")

            # Calculate limit price with slippage
            slippage_factor = slippage_bps / 10000.0
            if is_buy:
                limit_price = mark_px * (1 + slippage_factor)
            else:
                limit_price = mark_px * (1 - slippage_factor)

            # Market order = IOC (Immediate or Cancel)
            order_params = {
                "limit": {
                    "tif": "Ioc"  # Immediate or cancel
                }
            }

            if reduce_only:
                order_params["reduceOnly"] = True

            # Place order
            order_result = self.exchange.order(
                coin,
                is_buy,
                qty,
                limit_price,
                order_params
            )

            if order_result.get("status") == "ok":
                response_data = order_result.get("response", {}).get("data", {})
                statuses = response_data.get("statuses", [])

                if statuses and len(statuses) > 0:
                    status = statuses[0]

                    if "filled" in status:
                        logger.info(
                            f"[HYPERLIQUID] Market order FILLED: {side} {qty}"
                        )
                        return "filled"
                    else:
                        logger.warning(f"[HYPERLIQUID] Market order unclear: {status}")
                        return ""
            else:
                error_msg = order_result.get("response", "Unknown error")
                logger.error(f"[HYPERLIQUID] Market order REJECTED: {error_msg}")
                raise RuntimeError(f"Market order rejected: {error_msg}")

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Market order failed: {e}")
            raise

    async def cancel_order(self, coin: str, oid: int) -> bool:
        """Cancel a specific order

        Args:
            coin: Trading pair coin (e.g., "ETH", "BTC")
            oid: Order ID to cancel

        Returns:
            True if successful
        """
        self._validate_order_connection()

        try:
            cancel_result = self.exchange.cancel(coin, oid)

            if cancel_result.get("status") == "ok":
                logger.info(f"[HYPERLIQUID] Order cancelled: {coin} oid={oid}")
                return True
            else:
                error_msg = cancel_result.get("response", "Unknown error")
                logger.error(f"[HYPERLIQUID] Cancel failed: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Cancel failed: {e}")
            return False

    async def cancel_all_orders(self, coin: Optional[str] = None):
        """Cancel all open orders (optionally for specific coin)

        Args:
            coin: Optional coin to cancel orders for. If None, cancels all.
        """
        self._validate_order_connection()

        try:
            # Get all open orders
            open_orders = self.info.open_orders(self.address)

            cancel_coin = coin if coin else self._format_coin(self.cfg.pair)

            cancelled_count = 0
            for order in open_orders:
                order_coin = order.get("coin", "")
                oid = order.get("oid")

                if order_coin == cancel_coin:
                    await self.cancel_order(order_coin, oid)
                    cancelled_count += 1

            logger.info(f"[HYPERLIQUID] Cancelled {cancelled_count} orders for {cancel_coin}")

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Cancel all failed: {e}")
            raise

    async def get_position(self, coin: Optional[str] = None) -> Dict[str, Any]:
        """Get current position for coin

        Args:
            coin: Optional coin symbol. If None, uses configured pair.

        Returns:
            Position dictionary with keys: qty, avg_price, symbol, unrealized_pnl
        """
        if not self._connected:
            raise RuntimeError("Not connected")

        symbol = coin if coin else self._format_coin(self.cfg.pair)

        # Try cached position first
        if symbol in self._position_cache:
            return self._position_cache[symbol]

        # Fallback: query REST API
        try:
            user_state = self.info.user_state(self.address)

            for asset_pos in user_state.get("assetPositions", []):
                position = asset_pos.get("position", {})
                if position.get("coin") == symbol:
                    size = float(position.get("szi", 0))
                    entry_px = float(position.get("entryPx", 0)) if size != 0 else 0
                    unrealized_pnl = float(position.get("unrealizedPnl", 0))

                    pos_data = {
                        'qty': size,
                        'avg_price': entry_px,
                        'symbol': symbol,
                        'unrealized_pnl': unrealized_pnl
                    }

                    # Update cache
                    self._position_cache[symbol] = pos_data
                    return pos_data

            # No position found
            return {'qty': 0.0, 'avg_price': 0.0, 'symbol': symbol, 'unrealized_pnl': 0.0}

        except Exception as e:
            logger.error(f"[HYPERLIQUID] Failed to get position: {e}")
            return {'qty': 0.0, 'avg_price': 0.0, 'symbol': symbol, 'unrealized_pnl': 0.0}
