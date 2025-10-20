#!/usr/bin/env python3
"""
Combined test script for both GRVT and Lighter adapters
Run this to verify both connections are working properly
"""
import asyncio
import sys
from loguru import logger

from test.test_grvt import test_grvt_connection
from test.test_lighter import test_lighter_websocket
from config import CFG


async def main():
    """Test both adapters"""
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

    logger.info("🚀 Testing both GRVT and Lighter adapters...")

    # Check basic configuration
    missing_config = []
    if not CFG.grvt_api_key:
        missing_config.append("GRVT_API_KEY")
    if not CFG.grvt_sub_account_id:
        missing_config.append("GRVT_SUB_ACCOUNT_ID")
    if not CFG.pair:
        missing_config.append("PAIR")

    if missing_config:
        logger.error(f"Missing configuration: {', '.join(missing_config)}")
        logger.error("Please check your .env file")
        return

    # Test GRVT
    logger.info("\n" + "="*50)
    grvt_success = await test_grvt_connection()

    # Test Lighter
    logger.info("\n" + "="*50)
    lighter_success = await test_lighter_websocket()

    # Summary
    logger.info("\n" + "="*50)
    logger.info("=== TEST SUMMARY ===")

    if grvt_success and lighter_success:
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("✅ GRVT adapter: Working")
        logger.info("✅ Lighter adapter: Working")
        logger.info("\nYou can now run the strategy with SIM_MODE=false")
    else:
        logger.error("💥 SOME TESTS FAILED")
        logger.error(f"❌ GRVT adapter: {'OK' if grvt_success else 'FAILED'}")
        logger.error(f"❌ Lighter adapter: {'OK' if lighter_success else 'FAILED'}")
        logger.error("\nPlease fix the issues before running the strategy")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
    except Exception as e:
        logger.error(f"Tests failed with exception: {e}")
        sys.exit(1)