"""
Test Lighter position fetching via WebSocket
"""
import json
import asyncio
import logging
from loguru import logger
import lighter
from config import CFG

logging.basicConfig(level=logging.INFO)


def on_account_update(account_id, account_data):
    """Callback for account updates (includes positions)"""
    logger.info("="*80)
    logger.info(f"ACCOUNT UPDATE: {account_id}")
    logger.info("="*80)

    # Debug: print raw account_data to see what we're getting
    logger.debug(f"Raw account_data: {json.dumps(account_data, indent=2)}")

    logger.info(f"\n📊 Account #{account_id}")

    # Positions come as a dict with market_id as keys
    positions_dict = account_data.get("positions", {})

    logger.info(f"Found {len(positions_dict)} position slots")

    # Filter for non-zero positions
    active_positions = []
    for market_id, pos in positions_dict.items():
        position_size = float(pos.get("position", 0))
        if position_size != 0:
            active_positions.append((market_id, pos))

    if active_positions:
        logger.info(f"\n📈 Active Positions ({len(active_positions)}):")
        logger.info("-" * 80)

        for market_id, pos in active_positions:
            symbol = pos.get("symbol", "?")
            position_size = float(pos.get("position", "0"))
            sign = int(pos.get("sign", 1))
            avg_entry = pos.get("avg_entry_price", "0")
            position_value = pos.get("position_value", "0")
            unrealized_pnl = pos.get("unrealized_pnl", "0")
            realized_pnl = pos.get("realized_pnl", "0")

            # Calculate actual quantity (sign * position)
            qty = sign * position_size

            side = "LONG" if sign > 0 else "SHORT"
            side_emoji = "📈" if sign > 0 else "📉"

            logger.info(f"\n{side_emoji} {symbol} (Market {market_id}) - {side}")
            logger.info(f"  Quantity:        {qty:,.4f}")
            logger.info(f"  Avg Entry:       ${float(avg_entry):,.2f}")
            logger.info(f"  Position Value:  ${float(position_value):,.2f}")
            logger.info(f"  Unrealized PnL:  ${float(unrealized_pnl):,.2f}")
            logger.info(f"  Realized PnL:    ${float(realized_pnl):,.2f}")
    else:
        logger.info("\n  ⚠️  No active positions (all flat)")

    # Summary stats
    logger.info(f"\n📊 Account Summary:")
    logger.info(f"  Daily trades:    {account_data.get('daily_trades_count', 0)}")
    logger.info(f"  Daily volume:    ${account_data.get('daily_volume', 0):,.2f}")
    logger.info(f"  Total trades:    {account_data.get('total_trades_count', 0)}")
    logger.info(f"  Total volume:    ${account_data.get('total_volume', 0):,.2f}")

    logger.info("="*80)


def on_order_book_update(market_id, order_book):
    """Callback for order book updates (not used but required)"""
    pass  # We don't care about order book for this test


async def main():
    """Test Lighter position WebSocket subscription"""
    logger.info("=== Testing Lighter Position WebSocket ===")
    logger.info(f"Account Index: {CFG.lighter_account_index}")

    logger.info(f"Connecting to Lighter WebSocket...")
    logger.info(f"Subscribed to account {CFG.lighter_account_index}")
    logger.info("Waiting for account updates... (Press Ctrl+C to stop)")

    while True:
        try:
            # Create WebSocket client
            # Subscribe to account updates for our account
            client = lighter.WsClient(
                host=CFG.lighter_base_url.replace("https://", ""),
                order_book_ids=[],  # We don't need order book
                account_ids=[CFG.lighter_account_index],  # Subscribe to our account
                on_order_book_update=on_order_book_update,
                on_account_update=on_account_update,
            )

            await client.run_async()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            # Ignore "Unhandled message: {'type': 'ping'}" errors - these are keepalive messages
            error_msg = str(e)
            if "Unhandled message" in error_msg and "'type': 'ping'" in error_msg:
                logger.debug(f"Ignoring ping message, reconnecting...")
                await asyncio.sleep(0.1)  # Brief delay before reconnect
                continue  # Reconnect
            else:
                logger.error(f"Error: {e}")
                import traceback
                traceback.print_exc()
                break


if __name__ == "__main__":
    asyncio.run(main())
