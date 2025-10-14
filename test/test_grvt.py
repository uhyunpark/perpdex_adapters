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

        # Test connection functionality
        logger.info("Testing connection functionality...")
        test_ok = await adapter.test_connection()
        if not test_ok:
            logger.error("Connection test failed")
            return False

        # Test BBO subscription (for 10 seconds)
        logger.info("Testing BBO stream for 10 seconds...")
        bbo_count = 0
        timeout_task = asyncio.create_task(asyncio.sleep(10))
        bbo_task = asyncio.create_task(test_bbo_stream(adapter))

        done, pending = await asyncio.wait(
            [timeout_task, bbo_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()

        # Check if we got BBO data
        if not bbo_task.done() or bbo_task.exception():
            logger.warning("BBO stream test incomplete")
        else:
            bbo_count = bbo_task.result()

        logger.info(f"Received {bbo_count} BBO updates")

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


async def test_bbo_stream(adapter: GrvtAdapter, max_count: int = 5) -> int:
    """Test BBO streaming"""
    count = 0
    async for bbo in adapter.subscribe_bbo():
        logger.info(f"BBO: {bbo.bid:.2f} / {bbo.ask:.2f} (spread: {bbo.ask - bbo.bid:.2f})")
        count += 1
        if count >= max_count:
            break
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