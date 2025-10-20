#!/usr/bin/env python3
"""
Test placing a single order on GRVT
"""
import asyncio
from loguru import logger

from adapters.grvt import GrvtAdapter, GrvtConfig
from common.types import Side
from config import CFG


async def main():
    logger.info("=== GRVT Order Placement Test ===")

    # Setup adapter
    config = GrvtConfig(
        api_key=CFG.grvt_api_key,
        private_key=CFG.grvt_api_secret,
        trading_account_id=CFG.grvt_sub_account_id,
        pair=CFG.pair,
        env=CFG.grvt_env,
    )

    grvt = GrvtAdapter(config)

    # Connect
    logger.info("[1/3] Connecting to GRVT...")
    if not await grvt.connect():
        logger.error("Failed to connect")
        return

    # Get current BBO
    logger.info("[2/3] Getting current BBO...")
    bbo = None
    async for b in grvt.subscribe_bbo():
        bbo = b
        logger.info(f"Current BBO: {bbo.bid:.2f} / {bbo.ask:.2f}")
        break

    if not bbo:
        logger.error("No BBO received")
        await grvt.disconnect()
        return

    # Place a test order close to the book (GRVT requires >= 0.01 qty)
    # BID: 1% below current bid
    # ASK: 1% above current ask
    test_bid_price = bbo.bid * 0.99
    test_ask_price = bbo.ask * 1.01
    test_qty = 0.01  # Minimum for GRVT

    logger.info(f"\n[3/3] Placing test orders (won't fill):")
    logger.info(f"  BUY: {test_qty} @ {test_bid_price:.2f} (1% below market)")
    logger.info(f"  SELL: {test_qty} @ {test_ask_price:.2f} (1% above market)")

    try:
        # Place BUY using REST
        logger.info("\n[REST] Placing BUY order...")
        bid_id = await grvt.place_postonly_limit(
            side=Side.BID,
            price=test_bid_price,
            qty=test_qty
        )
        logger.info(f"✅ [REST] BUY order placed: coid={bid_id}")

        # Wait a bit
        await asyncio.sleep(1)

        # Place SELL using WebSocket
        logger.info("\n[WebSocket] Placing SELL order...")
        ask_id = await grvt.place_postonly_limit_ws(
            side=Side.ASK,
            price=test_ask_price,
            qty=test_qty
        )
        logger.info(f"✅ [WebSocket] SELL order sent: coid={ask_id}")

        # Wait to let orders show up
        logger.info("\n⏳ Waiting 5 seconds... Check GRVT website for orders!")
        await asyncio.sleep(5)

        # Cancel all
        logger.info("\n🧹 Cancelling all orders...")
        await grvt.cancel_all_orders()
        logger.info("✅ All orders cancelled")

    except Exception as e:
        logger.error(f"❌ Order placement failed: {e}")
        import traceback
        traceback.print_exc()

    # Disconnect
    await grvt.disconnect()
    logger.info("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
