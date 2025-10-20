#!/usr/bin/env python3
"""
Test GRVT fill stream
Places an order close to market and monitors fill stream
"""
import asyncio
import sys
from loguru import logger

from adapters.grvt import GrvtAdapter, GrvtConfig
from common.types import Side
from config import CFG


async def test_fill_stream():
    """Test GRVT fill stream"""
    logger.info("=== GRVT Fill Stream Test ===")

    # Setup adapter
    config = GrvtConfig(
        api_key=CFG.grvt_api_key,
        private_key=CFG.grvt_api_secret,
        trading_account_id=CFG.grvt_sub_account_id,
        pair=CFG.pair,
        env=CFG.grvt_env,
    )

    if not config.private_key:
        logger.error("Private key required for fill stream")
        return

    grvt = GrvtAdapter(config)

    # Connect
    logger.info("[1/4] Connecting to GRVT...")
    if not await grvt.connect():
        logger.error("Failed to connect")
        return

    try:
        # Get current BBO
        logger.info("[2/4] Getting current BBO...")
        bbo = None
        async for b in grvt.subscribe_bbo():
            bbo = b
            logger.info(f"Current BBO: {bbo.bid:.2f} / {bbo.ask:.2f}")
            break

        if not bbo:
            logger.error("No BBO received")
            return

        # Start fill monitoring task
        logger.info("[3/4] Starting fill stream monitor...")
        fill_count = 0

        async def monitor_fills():
            nonlocal fill_count
            async for fill in grvt.subscribe_fills():
                fill_count += 1
                logger.info(f"🎯 FILL #{fill_count}: {fill.side} {fill.qty}@{fill.px} | coid={fill.client_order_id}")

        fill_task = asyncio.create_task(monitor_fills())

        # Place a marketable order to trigger a fill
        # Buy slightly above best ask to ensure immediate fill
        logger.info("[4/4] Placing marketable order to trigger fill...")

        fill_price = bbo.ask * 0.9999  # 0.05% above ask (should fill immediately)
        fill_qty = 0.1  # Minimum qty

        logger.info(f"Placing BUY {fill_qty} @ {fill_price:.2f} (above ask: {bbo.ask:.2f})")

        order_id = await grvt.place_postonly_limit(
            side=Side.BID,
            price=fill_price,
            qty=fill_qty
        )

        logger.info(f"Order placed: coid={order_id}")
        logger.info("\n⏳ Waiting for fill notification (30 seconds max)...")

        # Wait for fill
        try:
            await asyncio.wait_for(asyncio.sleep(30), timeout=30)
        except asyncio.TimeoutError:
            pass

        # Cancel task
        fill_task.cancel()
        try:
            await fill_task
        except asyncio.CancelledError:
            pass

        # Summary
        logger.info(f"\n=== Test Complete ===")
        logger.info(f"Total fills received: {fill_count}")

        if fill_count > 0:
            logger.info("✅ Fill stream working!")
        else:
            logger.warning("⚠️  No fills received - check if order was filled on GRVT")
            logger.info("Tip: Order might not have filled if market moved away")

        # Cancel all remaining orders
        logger.info("\n🧹 Cancelling all orders...")
        await grvt.cancel_all_orders()

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await grvt.disconnect()


async def main():
    """Main"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="DEBUG"
    )

    # Check config
    if not CFG.grvt_api_key:
        logger.error("GRVT_API_KEY not configured")
        return

    if not CFG.grvt_api_secret:
        logger.error("GRVT_API_SECRET (private key) not configured")
        return

    await test_fill_stream()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
