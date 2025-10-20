"""
Test GRVT position fetching via WebSocket
"""
import asyncio
import os
from loguru import logger
from pysdk.grvt_ccxt_env import GrvtEnv, GrvtWSEndpointType
from pysdk.grvt_ccxt_logging_selector import logger as grvt_logger
from pysdk.grvt_ccxt_ws import GrvtCcxtWS
from config import CFG


async def position_callback(message: dict):
    """Callback for position updates"""
    logger.info("="*80)
    logger.info("POSITION UPDATE RECEIVED")
    logger.info("="*80)

    stream = message.get("stream", "")
    selector = message.get("selector", "")
    feed = message.get("feed", {})

    logger.info(f"Stream: {stream}")
    logger.info(f"Selector: {selector}")
    logger.info(f"Raw Feed: {feed}")

    if feed:
        logger.info(f"\n📊 Position Details:")
        logger.info(f"  Instrument:         {feed.get('instrument', 'N/A')}")
        logger.info(f"  Size:               {feed.get('size', '0')}")
        logger.info(f"  Entry Price:        {feed.get('entry_price', '0')}")
        logger.info(f"  Mark Price:         {feed.get('mark_price', '0')}")
        logger.info(f"  Unrealized PnL:     {feed.get('unrealized_pnl', '0')}")
        logger.info(f"  Realized PnL:       {feed.get('realized_pnl', '0')}")
        logger.info(f"  Total PnL:          {feed.get('total_pnl', '0')}")
        logger.info(f"  Leverage:           {feed.get('leverage', '0')}")
        logger.info(f"  Liquidation Price:  {feed.get('est_liquidation_price', '0')}")

    logger.info("="*80)


async def test_grvt_position_websocket():
    """Test GRVT position WebSocket subscription"""
    logger.info("=== Testing GRVT Position WebSocket ===")

    # Setup WebSocket client
    params = {
        "api_key": CFG.grvt_api_key,
        "trading_account_id": CFG.grvt_sub_account_id,
        "api_ws_version": CFG.grvt_ws_stream_version,
    }
    if CFG.grvt_api_secret:
        params["private_key"] = CFG.grvt_api_secret

    env = GrvtEnv(CFG.grvt_env)
    loop = asyncio.get_event_loop()

    ws_client = GrvtCcxtWS(env, loop, grvt_logger, parameters=params)
    await ws_client.initialize()

    # Subscribe to position stream
    logger.info(f"Subscribing to position stream for pair: {CFG.pair}")

    # Convert pair format: SOL-USDT-PERP -> SOL_USDT_Perp
    instrument = CFG.pair.replace("-", "_").replace("PERP", "Perp")

    await ws_client.subscribe(
        stream="position",
        callback=position_callback,
        ws_end_point_type=GrvtWSEndpointType.TRADE_DATA_RPC_FULL,
        params={"instrument": instrument}  # Optional: filter by instrument
    )

    logger.info(f"Subscribed to position updates for {instrument}")
    logger.info("Waiting for position updates... (Press Ctrl+C to stop)")

    # Keep running to receive updates
    try:
        await asyncio.sleep(300)  # Wait 5 minutes
    except KeyboardInterrupt:
        logger.info("Interrupted by user")

    logger.info("Test completed")


if __name__ == "__main__":
    asyncio.run(test_grvt_position_websocket())
