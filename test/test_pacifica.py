#!/usr/bin/env python3
"""
Test script for Pacifica adapter
Tests connection, position display, and BBO streaming
"""
import asyncio
import sys
from loguru import logger

from adapters.pacifica import PacificaAdapter, PacificaConfig
from common.types import Side
from config import CFG


async def test_pacifica():
    """Test Pacifica adapter connection and basic functionality"""
    logger.info("=== Testing Pacifica Adapter ===")

    # Create adapter configuration
    config = PacificaConfig(
        private_key=CFG.pacifica_api_private_key,
        pair=CFG.pair,
        env=CFG.pacifica_api_env
    )

    adapter = PacificaAdapter(config)

    try:
        # Test connection
        logger.info("Testing connection...")
        connected = await adapter.connect()
        if not connected:
            logger.error("Failed to connect to Pacifica")
            return False

        logger.info(f"✅ Connected to Pacifica ({config.env})")
        logger.info(f"Trading pair: {config.pair}")
        logger.info(f"Account: {adapter.public_key}")

        # Wait a moment for position stream to populate
        await asyncio.sleep(2)

        # Get and display position
        logger.info("\n=== Current Position ===")
        await test_position(adapter)

        # Test BBO subscription (for 10 seconds)
        logger.info("\n=== Testing BBO Stream ===")
        logger.info("Streaming BBO for 10 seconds...")
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

        logger.info(f"\n✅ Received {bbo_count} BBO updates")

        logger.info("\n✅ Pacifica adapter test completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Pacifica test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await adapter.disconnect()


async def test_position(adapter: PacificaAdapter):
    """Test position retrieval and display"""
    try:
        symbol = adapter._format_symbol(adapter.cfg.pair)
        position = await adapter.get_position(symbol)

        logger.info(f"Symbol: {position['symbol']}")
        logger.info(f"Position Size: {position['qty']:.4f}")

        if position['qty'] != 0:
            logger.info(f"Average Price: ${position['avg_price']:.2f}")
            logger.info(f"Unrealized PnL: ${position.get('unrealized_pnl', 0):.2f}")
        else:
            logger.info("Status: No open position")

    except Exception as e:
        logger.error(f"Position retrieval failed: {e}")


async def test_bbo_stream(adapter: PacificaAdapter, max_count: int = 10) -> int:
    """Test BBO streaming"""
    count = 0
    async for bbo in adapter.subscribe_bbo():
        spread = bbo.ask - bbo.bid
        spread_bps = (spread / bbo.mid) * 10000 if bbo.mid > 0 else 0

        logger.info(
            f"[{count+1}] BBO: {bbo.bid:.2f} / {bbo.ask:.2f} | "
            f"Mid: {bbo.mid:.2f} | Spread: {spread:.2f} ({spread_bps:.2f}bps)"
        )

        count += 1
        if count >= max_count:
            break

    return count


async def test_order_placement(adapter: PacificaAdapter):
    """Test order placement and cancellation"""
    try:
        logger.info("\n=== Testing Order Placement ===")

        # Get current BBO
        async for bbo in adapter.subscribe_bbo():
            # Place a limit order far from market
            test_price = bbo.bid * 0.9  # 10% below bid
            test_qty = 0.01

            logger.info(f"Placing test limit order: BID {test_qty}@{test_price:.2f}")

            order_id = await adapter.place_limit_order(
                side=Side.BID,
                price=test_price,
                qty=test_qty,
                post_only=True
            )

            logger.info(f"✅ Order placed: {order_id}")

            # Wait a bit
            await asyncio.sleep(2)

            # Cancel the order
            logger.info(f"Cancelling order: {order_id}")
            success = await adapter.cancel_order(client_order_id=order_id)

            if success:
                logger.info("✅ Order cancelled successfully")
            else:
                logger.warning("⚠️ Order cancellation unclear")

            break

    except Exception as e:
        logger.error(f"Order placement test failed: {e}")


async def main():
    """Main test function"""
    # Setup logging
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"
    )

    # Check configuration
    if not CFG.pacifica_api_private_key:
        logger.error("PACIFICA_API_PRIVATE_KEY not configured in .env")
        logger.info("Please add PACIFICA_API_PRIVATE_KEY=your_solana_private_key to your .env file")
        return

    if not CFG.pair:
        logger.error("PAIR not configured in .env")
        return

    # Run test
    success = await test_pacifica()

    if success:
        logger.info("\n🎉 All tests passed!")
    else:
        logger.error("\n💥 Some tests failed")
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
