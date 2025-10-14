import asyncio
import datetime
import lighter
import logging
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from config import CFG

logging.basicConfig(level=logging.INFO)

async def print_api(method, *args, **kwargs):
    logging.info(f"{method.__name__}: {await method(*args, **kwargs)}")

async def only_account_apis(client: lighter.ApiClient):
    logging.info("ONLY ACCOUNT APIS")
    account_instance = lighter.AccountApi(client)
    await print_api(account_instance.account, by="l1_address", value=CFG.lighter_eth_address)


async def account_apis(client: lighter.ApiClient):
    logging.info("ACCOUNT APIS")
    account_instance = lighter.AccountApi(client)
    await print_api(account_instance.account, by="l1_address", value=CFG.lighter_eth_address)
    await print_api(account_instance.account, by="index", value=str(CFG.lighter_account_index))
    await print_api(account_instance.accounts_by_l1_address, l1_address=CFG.lighter_eth_address)
    await print_api(account_instance.apikeys, account_index=CFG.lighter_account_index, api_key_index=CFG.lighter_api_key_index)
    await print_api(account_instance.public_pools, filter="all", limit=1, index=0)


async def block_apis(client: lighter.ApiClient):
    logging.info("BLOCK APIS")
    block_instance = lighter.BlockApi(client)
    await print_api(block_instance.block, by="height", value="1")
    await print_api(block_instance.blocks, index=0, limit=2, sort="asc")
    await print_api(block_instance.current_height)


async def candlestick_apis(client: lighter.ApiClient):
    logging.info("CANDLESTICK APIS")
    candlestick_instance = lighter.CandlestickApi(client)
    await print_api(
        candlestick_instance.candlesticks,
        market_id=0,
        resolution="1h",
        start_timestamp=int(datetime.datetime.now().timestamp() - 60 * 60 * 24),
        end_timestamp=int(datetime.datetime.now().timestamp()),
        count_back=2,
    )
    await print_api(
        candlestick_instance.fundings,
        market_id=0,
        resolution="1h",
        start_timestamp=int(datetime.datetime.now().timestamp() - 60 * 60 * 24),
        end_timestamp=int(datetime.datetime.now().timestamp()),
        count_back=2,
    )


async def order_apis(client: lighter.ApiClient):
    logging.info("ORDER APIS")
    order_instance = lighter.OrderApi(client)
    await print_api(order_instance.exchange_stats)
    await print_api(order_instance.order_book_details, market_id=0)
    await print_api(order_instance.order_books)
    await print_api(order_instance.recent_trades, market_id=0, limit=2)


async def transaction_apis(client: lighter.ApiClient):
    logging.info("TRANSACTION APIS")
    transaction_instance = lighter.TransactionApi(client)
    await print_api(transaction_instance.block_txs, by="block_height", value="1")
    await print_api(
        transaction_instance.next_nonce,
        account_index=int(CFG.lighter_account_index),
        api_key_index=0,
    )
    # use with a valid sequence index
    # await print_api(transaction_instance.tx, by="sequence_index", value="5")
    await print_api(transaction_instance.txs, index=0, limit=2)


async def main():
    client = lighter.ApiClient(configuration=lighter.Configuration(host="https://mainnet.zklighter.elliot.ai"))
    # await only_account_apis(client)
    await order_apis(client)
    await transaction_apis(client)
    await block_apis(client)
    await candlestick_apis(client)
    await account_apis(client)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())