#!/usr/bin/env python3
"""
Test script for Lighter WebSocket streaming
Tests real-time order book and account updates using native lighter.WsClient
"""
import asyncio
import sys
import json
from loguru import logger

import lighter
from config import CFG


async def test_lighter_websocket():
    """Test Lighter WebSocket streaming with real data"""
    logger.info("=== Testing Lighter WebSocket Streaming ===")

    # Determine market IDs based on pair
    pair_clean = CFG.pair.replace("-", "_").replace("_PERP", "").replace("-PERP", "")
    market_mapping = {
        "ETH_USDT": 0,
        "BTC_USDT": 1,
        "SOL_USDT": 2,
    }
    market_id = market_mapping.get(pair_clean, 0)
    logger.info(f"Subscribing to market {market_id} ({pair_clean})")

    # Stats tracking
    stats = {
        "orderbook_updates": 0,
        "account_updates": 0,
        "last_bid": None,
        "last_ask": None,
    }

    def on_order_book_update(market_id: int, order_book: dict):
        """Handle order book updates"""
        stats["orderbook_updates"] += 1

        # Extract BBO
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        if bids and asks:
            # Extract best bid/ask - already in decimal format (not scaled)
            bid_data = bids[0]
            ask_data = asks[0]

            best_bid = float(bid_data.get("price", 0))
            best_ask = float(ask_data.get("price", 0))

            if best_bid > 0 and best_ask > 0:
                spread = best_ask - best_bid
                stats["last_bid"] = best_bid
                stats["last_ask"] = best_ask

                logger.info(
                    f"[{stats['orderbook_updates']}] Market {market_id} | "
                    f"BID: {best_bid:.2f} / ASK: {best_ask:.2f} | "
                    f"Spread: {spread:.2f} ({spread/best_bid*10000:.2f}bps)"
                )
            else:
                logger.warning(f"Zero prices - bid_data: {bid_data}, ask_data: {ask_data}")
        else:
            logger.warning(f"Empty order book for market {market_id}")

    def on_account_update(account_id: int, account: dict):
        """Handle account updates"""
        stats["account_updates"] += 1
        logger.info(f"[{stats['account_updates']}] Account {account_id} update")
        logger.debug(f"Account data: {json.dumps(account, indent=2)}")

    try:
        # Create WebSocket client with native lighter.WsClient
        logger.info(f"Connecting to Lighter WebSocket...")

        client = lighter.WsClient(
            order_book_ids=[market_id],
            account_ids=[CFG.lighter_account_index],
            on_order_book_update=on_order_book_update,
            on_account_update=on_account_update,
        )

        # Run for 5 seconds to collect real data
        logger.info("Streaming data for 5 seconds...")

        try:
            await asyncio.wait_for(client.run_async(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.info("Stream timeout (expected)")

        # Print summary
        logger.info("\n=== Stream Summary ===")
        logger.info(f"Order book updates: {stats['orderbook_updates']}")
        logger.info(f"Account updates: {stats['account_updates']}")

        if stats["last_bid"] and stats["last_ask"]:
            logger.info(f"Final BBO: {stats['last_bid']:.2f} / {stats['last_ask']:.2f}")

        if stats["orderbook_updates"] > 0:
            logger.info("✅ WebSocket streaming successful")
            return True
        else:
            logger.error("❌ No order book updates received")
            return False

    except Exception as e:
        logger.error(f"❌ WebSocket test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function"""
    # Setup logging
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

    # Check configuration
    if not CFG.pair:
        logger.error("PAIR not configured in .env")
        return

    # Run test
    success = await test_lighter_websocket()

    if success:
        logger.info("🎉 WebSocket streaming test passed!")
    else:
        logger.error("💥 WebSocket streaming test failed")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)