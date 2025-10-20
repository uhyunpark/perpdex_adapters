import asyncio
import logging
import lighter
from config import CFG

logging.basicConfig(level=logging.DEBUG)

def trim_exception(e: Exception) -> str:
    return str(e).strip().split("\n")[-1]


async def main():
    client = lighter.SignerClient(
        url=CFG.lighter_base_url,
        private_key=CFG.lighter_api_private_key,
        account_index=CFG.lighter_account_index,
        api_key_index=CFG.lighter_api_key_index,
    )

    # tx = await client.create_market_order_limited_slippage(market_index=0, client_order_index=0, base_amount=30000000,
    #                                                        max_slippage=0.001, is_ask=True)
    tx = await client.create_market_order_if_slippage(market_index=0, client_order_index=0, base_amount=30000000,
                                                           max_slippage=0.01, is_ask=True, ideal_price=300000)
    print("Create Order Tx:", tx)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())