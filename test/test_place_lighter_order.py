#!/usr/bin/env python3
"""
Test placing a single order on Lighter
"""
import asyncio
from loguru import logger

from adapters.lighter import LighterAdapter, LighterConfig
from common.types import Side
from config import CFG


async def main():
    logger.info("=== Lighter Order Placement Test ===")

    # Setup adapter
    config = LighterConfig(
        private_key=CFG.lighter_api_private_key,
        account_index=CFG.lighter_account_index,
        api_key_index=CFG.lighter_api_key_index,
        pair=CFG.pair,
        env=CFG.lighter_env,
    )

    lighter = LighterAdapter(config)

    # Connect
    logger.info("[1/3] Connecting to Lighter...")
    if not await lighter.connect():
        logger.error("Failed to connect")
        return

    # Get current BBO
    logger.info("[2/3] Getting current BBO...")
    bbo = None
    async for b in lighter.subscribe_bbo():
        bbo = b
        logger.info(f"Current BBO: bid={bbo.bid:.4f} / ask={bbo.ask:.4f} / mid={bbo.mid:.4f}")
        break

    if not bbo:
        logger.error("No BBO received")
        await lighter.disconnect()
        return

    # Place a limit order using WebSocket
    test_qty = 1 # 100으로 나눠야 실제 체결되는 값임
    test_price = bbo.ask * 1.01  # 1% above ask (won't fill)

    logger.info(f"\n[3/3] Placing test LIMIT order via WebSocket:")
    logger.info(f"  Market: bid={bbo.bid:.2f} / ask={bbo.ask:.2f}")
    logger.info(f"  Order: SELL {test_qty} @ {test_price:.2f}")

    try:
        # Place limit order via WebSocket
        logger.info("\n[WebSocket] Placing LIMIT SELL order...")
        order_id = await lighter.place_limit_order_ws(
            side=Side.ASK,
            price=test_price,
            qty=test_qty,
            post_only=True
        )
        logger.info(f"✅ [WebSocket] SELL order placed: order_id={order_id}")

        # Wait to let order show up
        logger.info("\n⏳ Waiting 5 seconds... Check Lighter website for order!")
        await asyncio.sleep(3)

        # Cancel all
        logger.info("\n🧹 Cancelling all orders...")
        await lighter.cancel_all_orders()
        logger.info("✅ All orders cancelled")

    except Exception as e:
        logger.error(f"❌ Order placement failed: {e}")
        import traceback
        traceback.print_exc()

    # Disconnect
    await lighter.disconnect()
    logger.info("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
