"""
Test fetching positions from both exchanges
"""
import asyncio
from loguru import logger
from config import CFG
from adapters.grvt import GrvtAdapter, GrvtConfig
from adapters.lighter import LighterAdapter, LighterConfig
from strategy.config import StrategyConfig


async def test_grvt_position():
    """Test GRVT position fetching"""
    logger.info("=== Testing GRVT Position ===")

    grvt_config = GrvtConfig(
        api_key=CFG.grvt_api_key,
        private_key=CFG.grvt_api_secret,
        trading_account_id=CFG.grvt_sub_account_id,
        pair=CFG.pair,
        env=CFG.grvt_env,
    )

    grvt = GrvtAdapter(grvt_config)
    await grvt.connect()

    try:
        # Get position for the trading pair
        position = await grvt.get_position(CFG.pair)
        logger.info(f"GRVT Position response: {position}")
        logger.info(f"Type: {type(position)}")

        if position:
            logger.info(f"Position size: {position.get('size', 0)}")
            logger.info(f"Position value: {position.get('value', 0)}")
            logger.info(f"Entry price: {position.get('entry_price', 0)}")
            logger.info(f"Unrealized PnL: {position.get('unrealized_pnl', 0)}")
            logger.info(f"Full position data: {position}")
        else:
            logger.info("No position or empty response")

    except Exception as e:
        logger.error(f"Error fetching GRVT position: {e}")
        import traceback
        traceback.print_exc()

    await grvt.disconnect()


async def test_lighter_position():
    """Test Lighter position fetching"""
    logger.info("\n=== Testing Lighter Position ===")

    lighter_config = LighterConfig(
        private_key=CFG.lighter_api_private_key,
        account_index=CFG.lighter_account_index,
        api_key_index=CFG.lighter_api_key_index,
        pair=CFG.pair,
        env=CFG.lighter_env,
    )

    lighter = LighterAdapter(lighter_config)
    await lighter.connect()

    try:
        # Get market ID
        market_id = lighter._get_market_id(CFG.pair)
        logger.info(f"Market ID: {market_id}")

        # Get position
        position = await lighter.get_position(market_id)
        logger.info(f"Lighter Position response: {position}")
        logger.info(f"Type: {type(position)}")

        if position:
            logger.info(f"Position size: {position.get('size', 0)}")
            logger.info(f"Position value: {position.get('value', 0)}")
            logger.info(f"Entry price: {position.get('entry_price', 0)}")
            logger.info(f"Full position data: {position}")
        else:
            logger.info("No position or empty response")

    except Exception as e:
        logger.error(f"Error fetching Lighter position: {e}")
        import traceback
        traceback.print_exc()

    await lighter.disconnect()


async def test_both_positions():
    """Test both exchange positions"""
    await test_grvt_position()
    await test_lighter_position()


if __name__ == "__main__":
    asyncio.run(test_both_positions())
