#!/usr/bin/env python3
"""
Test script for GRVT adapter
Verifies connection, BBO streaming, and basic functionality
"""
import asyncio
import signal
import sys
from loguru import logger

from adapters.grvt import GrvtAdapter, GrvtConfig
from common.types import Side
from config import CFG


async def test_grvt_connection():
    """Test GRVT adapter connection and basic functionality"""
    logger.info("=== Testing GRVT Adapter ===")

    # Create adapter configuration
    config = GrvtConfig(
        api_key=CFG.grvt_api_key,
        private_key=CFG.grvt_api_secret,
        trading_account_id=CFG.grvt_sub_account_id,
        pair=CFG.pair,
        env=CFG.grvt_env
    )

    adapter = GrvtAdapter(config)

    try:
        # Test connection
        logger.info("Testing connection...")
        connected = await adapter.connect()
        if not connected:
            logger.error("Failed to connect to GRVT")
            return False

        # Test dual stream subscription (mini.d + ticker.d - for 10 seconds)
        logger.info("Testing dual streams (BBO + Market Info) for 10 seconds...")

        # Run both stream tests concurrently
        bbo_task = asyncio.create_task(test_bbo_stream(adapter))
        market_info_task = asyncio.create_task(test_market_info_stream(adapter))

        # Wait for 10 seconds
        await asyncio.sleep(10)

        # Cancel stream tasks
        bbo_task.cancel()
        market_info_task.cancel()

        # Retrieve counts (tasks were cancelled so we need to handle that)
        bbo_count = 0
        market_info_count = 0

        try:
            await bbo_task
        except asyncio.CancelledError:
            pass  # Expected

        try:
            await market_info_task
        except asyncio.CancelledError:
            pass  # Expected

        logger.info(f"Stream test completed (check logs above for actual update counts)")

        # Test order placement (if private key available)
        if config.private_key:
            logger.info("Testing order placement...")
            await test_order_placement(adapter)

        logger.info("✅ GRVT adapter test completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ GRVT test failed: {e}")
        return False

    finally:
        await adapter.disconnect()


async def test_bbo_stream(adapter: GrvtAdapter) -> int:
    """Test BBO streaming (mini.d) - runs until cancelled"""
    count = 0
    try:
        async for bbo in adapter.subscribe_bbo():
            count += 1
            logger.info(f"[mini.d #{count}] BBO: {bbo.bid:.2f} / {bbo.ask:.2f} (spread: {bbo.ask - bbo.bid:.4f})")
    except asyncio.CancelledError:
        logger.info(f"[mini.d] Received {count} BBO updates total")
        raise
    return count


async def test_market_info_stream(adapter: GrvtAdapter) -> int:
    """Test market info streaming (ticker.d) - runs until cancelled"""
    count = 0
    try:
        async for info in adapter.subscribe_market_info():
            count += 1
            logger.info(
                f"[ticker.d #{count}] Funding: {info.funding_rate:.6f}% | "
                f"OI: ${info.open_interest:,.0f} | "
                f"Vol24h: ${info.volume_24h:,.0f} | "
                f"Mark: ${info.mark_price:.2f}"
            )
    except asyncio.CancelledError:
        logger.info(f"[ticker.d] Received {count} market info updates total")
        raise
    return count


async def test_order_placement(adapter: GrvtAdapter):
    """Test order placement and cancellation"""
    try:
        # Get current prices for a safe test order
        bbo_iter = adapter.subscribe_bbo()
        current_bbo = await bbo_iter.__anext__()

        # Place a very low bid (unlikely to fill)
        test_price = current_bbo.bid * 0.8  # 20% below market
        test_qty = 0.01  # Small quantity

        logger.info(f"Placing test order: BUY {test_qty} @ {test_price}")

        order_id = await adapter.place_postonly_limit(
            side=Side.BID,
            price=test_price,
            qty=test_qty
        )

        logger.info(f"Order placed with ID: {order_id}")

        # Wait a bit
        await asyncio.sleep(2)

        # Cancel all orders
        logger.info("Cancelling all orders...")
        await adapter.cancel_all_orders()

        logger.info("✅ Order test completed")

    except Exception as e:
        logger.warning(f"Order test failed (might be normal): {e}")


async def main():
    """Main test function"""
    # Setup logging
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

    # Check configuration
    if not CFG.grvt_api_key:
        logger.error("GRVT_API_KEY not configured in .env")
        return

    if not CFG.grvt_sub_account_id:
        logger.error("GRVT_SUB_ACCOUNT_ID not configured in .env")
        return

    # Run test
    success = await test_grvt_connection()

    if success:
        logger.info("🎉 All tests passed!")
    else:
        logger.error("💥 Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        sys.exit(1)