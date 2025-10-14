"""
Basic Adapter Usage Example
Demonstrates how to use GRVT and Lighter adapters for basic operations
"""
import asyncio
import os
from typing import Optional
from loguru import logger

from adapters.grvt import GrvtAdapter, GrvtConfig
from adapters.lighter import LighterAdapter, LighterConfig
from common.types import BBO, Side


class AdapterExample:
    """Example class showing basic adapter usage"""
    
    def __init__(self):
        self.grvt: Optional[GrvtAdapter] = None
        self.lighter: Optional[LighterAdapter] = None
        
    async def setup_adapters(self):
        """Initialize and connect to both exchanges"""
        logger.info("🚀 Setting up adapters...")
        
        # GRVT Configuration
        grvt_config = GrvtConfig(
            api_key=os.getenv("GRVT_API_KEY", ""),
            private_key=os.getenv("GRVT_PRIVATE_KEY", ""),
            trading_account_id=os.getenv("GRVT_TRADING_ACCOUNT_ID", ""),
            pair="SOL-USDT-PERP",
            env="testnet"  # Use testnet for safety
        )
        
        # Lighter Configuration  
        lighter_config = LighterConfig(
            private_key=os.getenv("LIGHTER_PRIVATE_KEY", ""),
            account_index=int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0")),
            api_key_index=int(os.getenv("LIGHTER_API_KEY_INDEX", "2")),
            pair="SOL-USDT-PERP",
            env="testnet"  # Use testnet for safety
        )
        
        # Initialize adapters
        self.grvt = GrvtAdapter(grvt_config)
        self.lighter = LighterAdapter(lighter_config)
        
        # Connect to exchanges
        grvt_connected = await self.grvt.connect()
        lighter_connected = await self.lighter.connect()
        
        if not grvt_connected:
            logger.error("Failed to connect to GRVT")
            return False
            
        if not lighter_connected:
            logger.error("Failed to connect to Lighter")
            return False
            
        logger.info("Successfully connected to both exchanges")
        return True
    
    async def monitor_bbo_streams(self, duration_seconds: int = 10):
        """Monitor BBO streams from both exchanges"""
        logger.info(f"Monitoring BBO streams for {duration_seconds} seconds...")
        
        async def monitor_grvt_bbo():
            """Monitor GRVT BBO stream"""
            try:
                async for bbo in self.grvt.subscribe_bbo():
                    logger.info(f"[GRVT] BBO: {bbo.bid:.4f} / {bbo.ask:.4f} (mid: {bbo.mid:.4f})")
            except Exception as e:
                logger.error(f"GRVT BBO monitoring error: {e}")
        
        async def monitor_lighter_bbo():
            """Monitor Lighter BBO stream"""
            try:
                async for bbo in self.lighter.subscribe_bbo():
                    logger.info(f"[LIGHTER] BBO: {bbo.bid:.4f} / {bbo.ask:.4f} (mid: {bbo.mid:.4f})")
            except Exception as e:
                logger.error(f"Lighter BBO monitoring error: {e}")
        
        # Run both monitoring tasks concurrently
        tasks = [
            asyncio.create_task(monitor_grvt_bbo()),
            asyncio.create_task(monitor_lighter_bbo())
        ]
        
        # Wait for specified duration
        await asyncio.sleep(duration_seconds)
        
        # Cancel monitoring tasks
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
                
        logger.info("BBO monitoring completed")
    
    async def demonstrate_order_operations(self):
        """Demonstrate order placement and cancellation"""
        logger.info("📝 Demonstrating order operations...")
        
        try:
            # Example: Place a small post-only order on GRVT
            logger.info("Placing post-only order on GRVT...")
            client_order_id = await self.grvt.place_postonly_limit(
                side=Side.BID,
                price=100.0,  # Example price
                qty=0.01,     # Small quantity for safety
                client_order_id="example_bid_001"
            )
            logger.info(f"GRVT order placed: {client_order_id}")
            
            # Wait a moment
            await asyncio.sleep(2)
            
            # Cancel all orders
            logger.info("Cancelling all orders...")
            await self.grvt.cancel_all_orders()
            await self.lighter.cancel_all_orders()
            logger.info("✅ All orders cancelled")
            
        except Exception as e:
            logger.error(f"Order operation failed: {e}")
    
    async def check_positions(self):
        """Check current positions on both exchanges"""
        logger.info("Checking positions...")
        
        try:
            # Get GRVT position
            grvt_position = await self.grvt.get_position("SOL-USDT-PERP")
            logger.info(f"[GRVT] Position: {grvt_position}")
            
            # Get Lighter position (need market_id)
            market_id = 2  # SOL market ID on Lighter
            lighter_position = await self.lighter.get_position(market_id)
            logger.info(f"[LIGHTER] Position: {lighter_position}")
            
        except Exception as e:
            logger.error(f"Position check failed: {e}")
    
    async def cleanup(self):
        """Clean up connections"""
        logger.info("Cleaning up...")
        
        if self.grvt:
            await self.grvt.disconnect()
        if self.lighter:
            await self.lighter.disconnect()
            
        logger.info("Cleanup completed")


async def main():
    """Main example function"""
    example = AdapterExample()
    
    try:
        # Setup adapters
        if not await example.setup_adapters():
            logger.error("Failed to setup adapters")
            return
        
        # Monitor BBO streams for 10 seconds
        await example.monitor_bbo_streams(duration_seconds=10)
        
        # Check positions
        await example.check_positions()
        
        # Demonstrate order operations (commented out for safety)
        # await example.demonstrate_order_operations()
        
        logger.info("Example completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("Example interrupted by user")
    except Exception as e:
        logger.error(f"Example failed: {e}")
    finally:
        # Always cleanup
        await example.cleanup()


if __name__ == "__main__":
    # Configure logging
    logger.remove()  # Remove default handler
    logger.add(
        "examples/basic_usage.log",
        rotation="10 MB",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )
    logger.add(
        lambda msg: print(msg, end=""),  # Console output
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}"
    )
    
    # Run example
    asyncio.run(main())
