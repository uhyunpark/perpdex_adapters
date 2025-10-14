"""
Lighter Adapter - Hedging and order execution
Handles connection, BBO subscriptions, and IOC order execution
"""
import asyncio
import json
import websockets
from typing import AsyncIterator, Optional, Dict, Any
from pydantic import BaseModel
from loguru import logger

import lighter

from common.types import BBO, Side
from common.utils import now_ms


class LighterConfig(BaseModel):
    private_key: str
    account_index: int
    api_key_index: int
    pair: str
    env: str = "testnet"


class LighterAdapter:
    """Lighter exchange adapter for hedging"""
    
    # Class constants
    QUEUE_TIMEOUT_SEC = 1.0
    CANCEL_TIMEOUT_SEC = 5.0
    DISCONNECT_WAIT_SEC = 0.2
    WS_RECONNECT_DELAY_SEC = 1.0
    WS_PING_RETRY_DELAY_SEC = 0.1
    
    # Quantity scaling factors
    QTY_SCALE_SOL = 1000      # 1000 = 0.1 SOL
    QTY_SCALE_ETH = 10000     # 1000 = 0.1 ETH? check sdk example
    QTY_SCALE_BTC = 10000     # Same as ETH
    QTY_SCALE_DEFAULT = 100   # Default fallback
    
    # Price bounds (scaled by 100)
    PRICE_SCALE = 100
    MAX_PRICE = 1_000_000 * PRICE_SCALE  # $1M
    MIN_PRICE = 1 * PRICE_SCALE           # $0.01
    
    # Client order ID modulo
    ORDER_ID_MODULO = 1_000_000

    def __init__(self, cfg: LighterConfig):
        self.cfg = cfg
        self.base_url = self._get_base_url(cfg.env)

        self.signer_client: Optional[lighter.SignerClient] = None
        self.api_client: Optional[lighter.ApiClient] = None
        self.order_api: Optional[lighter.OrderApi] = None
        self.transaction_api: Optional[lighter.TransactionApi] = None
        self.account_api: Optional[lighter.AccountApi] = None
        self.ws_client: Optional[lighter.WsClient] = None

        self._bbo_queue: Optional[asyncio.Queue[BBO]] = None
        self._position_cache: Dict[int, Dict[str, Any]] = {}  # Cache positions from account WS stream
        self._connected = False

    def _get_base_url(self, env: str) -> str:
        """Get API URL for environment"""
        if env == "mainnet":
            return "https://mainnet.zklighter.elliot.ai"
        else:
            return "https://testnet.zklighter.elliot.ai"

    def _get_market_id(self, pair: str) -> int:
        """Map trading pair to Lighter market ID"""
        # This should be fetched dynamically in production
        pair_clean = pair.replace("-", "_").replace("_PERP", "").replace("-PERP", "")

        market_mapping = {
            "ETH_USDT": 0,
            "BTC_USDT": 1,
            "SOL_USDT": 2,
        }

        return market_mapping.get(pair_clean, 0)  # Default to 0 (BTC)

    async def connect(self) -> bool:
        """Initialize connections"""
        try:
            # STEP 1: Initialize SignerClient for order operations
            logger.info("[LIGHTER] Initializing SignerClient...")
            self.signer_client = lighter.SignerClient(
                url=self.base_url,
                private_key=self.cfg.private_key,
                account_index=self.cfg.account_index,
                api_key_index=self.cfg.api_key_index,
            )

            # Check client validity
            error = self.signer_client.check_client()
            if error:
                logger.error(f"[LIGHTER] SignerClient error: {error}")
                return False

            # STEP 2: Initialize REST API clients
            logger.info("[LIGHTER] Initializing REST API clients...")
            configuration = lighter.Configuration(host=self.base_url)
            self.api_client = lighter.ApiClient(configuration)
            self.order_api = lighter.OrderApi(self.api_client)
            self.transaction_api = lighter.TransactionApi(self.api_client)
            self.account_api = lighter.AccountApi(self.api_client)

            # STEP 3: Initialize data queues
            self._bbo_queue = asyncio.Queue()

            # STEP 4: Initialize WebSocket for market data and positions
            logger.info("[LIGHTER] Starting WebSocket streams...")
            await self._subscribe_websocket_streams()

            self._connected = True
            logger.info(f"[LIGHTER] ✅ Successfully connected to {self.base_url}")
            return True

        except Exception as e:
            logger.error(f"[LIGHTER] ❌ Connection failed: {e}")
            return False

    def _validate_connection(self):
        """Validate connection state"""
        if not self._connected:
            raise RuntimeError("Not connected to Lighter")

    async def disconnect(self):
        """Clean up connections"""
        logger.info("[LIGHTER] Disconnecting...")

        # Stop WebSocket streams
        self._connected = False

        # Give background tasks time to exit
        await asyncio.sleep(self.DISCONNECT_WAIT_SEC)

        # Cleanup WebSocket client
        if self.ws_client:
            self.ws_client = None

        # Close REST API client
        if self.api_client:
            await self.api_client.close()

        logger.info("[LIGHTER] ✅ Disconnected")

    async def subscribe_bbo(self) -> AsyncIterator[BBO]:
        """Subscribe to best bid/offer stream via WebSocket"""
        self._validate_connection()

        # BBO stream already active from connect() - just yield from queue
        while self._connected:
            try:
                bbo = await asyncio.wait_for(self._bbo_queue.get(), timeout=self.QUEUE_TIMEOUT_SEC)
                yield bbo
            except asyncio.TimeoutError:
                continue

    def _calculate_scaled_quantity(self, qty: float) -> int:
        """Calculate scaled quantity based on trading pair"""
        pair_upper = self.cfg.pair.upper()

        if "SOL" in pair_upper:
            return int(qty * self.QTY_SCALE_SOL)
        elif "ETH" in pair_upper:
            return int(qty * self.QTY_SCALE_ETH)
        elif "BTC" in pair_upper:
            return int(qty * self.QTY_SCALE_BTC)
        else:
            return int(qty * self.QTY_SCALE_DEFAULT)

    def _calculate_execution_price(self, side: Side) -> int:
        """Calculate worst acceptable price for market order"""
        if side == Side.BID:
            # Buying - worst price is high
            return self.MAX_PRICE
        else:
            # Selling - worst price is low
            return self.MIN_PRICE

    async def place_market_order(self, side: Side, qty: float, slippage_bps: float = 100, reduce_only: bool = False) -> str:
        """Place a market order using Lighter's dedicated create_market_order()"""
        self._validate_connection()

        market_id = self._get_market_id(self.cfg.pair)
        base_amount = self._calculate_scaled_quantity(qty)
        client_order_id = int(now_ms() % self.ORDER_ID_MODULO)
        avg_execution_price = self._calculate_execution_price(side)

        try:
            # Use Lighter's dedicated market order function
            tx, tx_hash, error = await self.signer_client.create_market_order(
                market_index=market_id,
                client_order_index=client_order_id,
                base_amount=base_amount,
                avg_execution_price=avg_execution_price,
                is_ask=(side == Side.ASK),
                reduce_only=reduce_only,
            )

            if error is not None:
                logger.error(f"[LIGHTER] Market order REJECTED: {error}")
                raise RuntimeError(f"Market order rejected: {error}")

            reduce_flag = " [REDUCE-ONLY]" if reduce_only else ""
            logger.info(
                f"[LIGHTER] Market order ACCEPTED: {side} {qty}{reduce_flag} | "
                f"coid={client_order_id} tx_hash={tx_hash}"
            )
            return str(client_order_id)

        except Exception as e:
            logger.error(f"[LIGHTER] Market order placement failed: {e}")
            raise

    def _get_ws_url(self) -> str:
        """Get WebSocket URL from base URL"""
        return self.base_url.replace('https', 'wss') + '/stream'

    async def cancel_all_orders(self):
        """Cancel all open orders using WebSocket"""
        self._validate_connection()

        try:
            next_nonce = await self.transaction_api.next_nonce(
                account_index=self.cfg.account_index,
                api_key_index=self.cfg.api_key_index
            )

            tx_info, error = self.signer_client.sign_cancel_all_orders(
                time_in_force=0,  # GOOD_TILL_TIME
                time=0,  # No expiration
                nonce=next_nonce.nonce
            )

            if error is not None:
                logger.error(f"[LIGHTER-WS] Cancel all signing failed: {error}")
                raise RuntimeError(f"Cancel signing failed: {error}")

            ws_url = self._get_ws_url()

            async with websockets.connect(ws_url) as ws:
                await ws.recv()

                cancel_request = {
                    "type": "jsonapi/sendtx",
                    "data": {
                        "id": f"cancel_all_{now_ms()}",
                        "tx_type": self.signer_client.TX_TYPE_CANCEL_ALL_ORDERS,
                        "tx_info": json.loads(tx_info),
                    },
                }

                await ws.send(json.dumps(cancel_request))

                response = await asyncio.wait_for(ws.recv(), timeout=self.CANCEL_TIMEOUT_SEC)
                response_data = json.loads(response)

                logger.info(f"[LIGHTER-WS] Cancel all response: {response_data}")

                if response_data.get("success") or "id" in response_data:
                    logger.info("[LIGHTER-WS] Cancel all successful")
                else:
                    error_msg = response_data.get("error", response_data)
                    logger.warning(f"[LIGHTER-WS] Cancel all unclear: {error_msg}")

        except Exception as e:
            logger.error(f"[LIGHTER-WS] Cancel all failed: {e}")
            raise

    def _on_order_book_update(self, market_id: int, order_book: Dict[str, Any]):
        """Callback for order book updates (BBO)"""
        try:
            bids = order_book.get("bids", [])
            asks = order_book.get("asks", [])

            if bids and asks:
                best_bid = float(bids[0].get("price", 0))
                best_ask = float(asks[0].get("price", 0))

                if best_bid > 0 and best_ask > 0:
                    bbo = BBO(
                        bid=best_bid,
                        ask=best_ask,
                        ts_ms=now_ms()
                    )
                    # Put in queue (non-blocking)
                    try:
                        self._bbo_queue.put_nowait(bbo)
                    except asyncio.QueueFull:
                        pass  # Skip if queue is full
        except Exception as e:
            logger.error(f"[LIGHTER] BBO callback error: {e}")

    def _on_account_update(self, account_id: int, account_data: Dict[str, Any]):
        """Callback for account updates (positions)"""
        try:
            # Update positions
            self._update_position_cache(account_data.get("positions", {}))
            
            # Log trades
            self._log_trades(account_data.get("trades", {}))

        except Exception as e:
            logger.error(f"[LIGHTER] Account callback error: {e}")

    def _update_position_cache(self, positions_dict: Dict[str, Any]):
        """Update position cache from WebSocket data"""
        for market_id_str, pos_data in positions_dict.items():
            market_id = int(market_id_str)
            sign = float(pos_data.get("sign", 0))
            position_amount = float(pos_data.get("position", 0))
            qty = sign * position_amount
            avg_price = float(pos_data.get("avg_entry_price", 0))

            self._position_cache[market_id] = {
                'qty': qty,
                'avg_price': avg_price,
                'market_id': market_id
            }

            logger.debug(
                f"[LIGHTER] Position update: market_id={market_id}, "
                f"qty={qty}, avg_price={avg_price}"
            )

    def _log_trades(self, trades_dict: Dict[str, Any]):
        """Log trade executions from WebSocket data"""
        for market_id_str, trades in trades_dict.items():
            for trade in trades:
                trade_id = trade.get("trade_id")
                size = trade.get("size")
                price = trade.get("price")
                is_maker_ask = trade.get("is_maker_ask", False)
                side = "SELL" if is_maker_ask else "BUY"

                logger.info(
                    f"[LIGHTER] Trade executed: {side} {size}@{price} "
                    f"(trade_id={trade_id}, market={market_id_str})"
                )

    async def _subscribe_websocket_streams(self):
        """Subscribe to account position and order book WebSocket streams"""
        try:
            # Get market ID from config
            market_id = self._get_market_id(self.cfg.pair)

            # Create single WsClient for BOTH order book and account updates
            self.ws_client = lighter.WsClient(
                order_book_ids=[market_id],  # Subscribe to market order book for BBO
                account_ids=[self.cfg.account_index],  # Subscribe to account for positions
                on_order_book_update=self._on_order_book_update,
                on_account_update=self._on_account_update
            )

            # Start WebSocket in background with error handling
            asyncio.create_task(self._run_ws_with_reconnect())

            logger.info(
                f"[LIGHTER] Subscribed to order book (market {market_id}) and "
                f"account position stream (account {self.cfg.account_index})"
            )

        except Exception as e:
            logger.error(f"[LIGHTER] Failed to subscribe to WebSocket streams: {e}")

    async def _run_ws_with_reconnect(self):
        """Run WebSocket with auto-reconnect on ping errors"""
        while self._connected:
            try:
                await self.ws_client.run_async()
            except Exception as e:
                # Ignore ping message errors, reconnect for others
                error_msg = str(e)
                if "Unhandled message" in error_msg and "'type': 'ping'" in error_msg:
                    logger.debug("[LIGHTER] Ignoring ping message, reconnecting...")
                    await asyncio.sleep(self.WS_PING_RETRY_DELAY_SEC)
                    continue
                else:
                    logger.error(f"[LIGHTER] WebSocket error: {e}")
                    await asyncio.sleep(self.WS_RECONNECT_DELAY_SEC)
                    continue

    async def get_position(self, market_id: int) -> Dict[str, Any]:
        """Get current position for market from WebSocket cache"""
        self._validate_connection()

        # Return cached position from WebSocket stream
        if market_id in self._position_cache:
            return self._position_cache[market_id]

        # Not in cache = no position
        return {'qty': 0.0, 'avg_price': 0.0, 'market_id': market_id}
