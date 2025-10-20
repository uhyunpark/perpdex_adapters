import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class AppConfig(BaseModel):
    env: str = os.getenv("ENV", "dev")
    pair: str = os.getenv("PAIR", "BTC-USDT-PERP")
    base_qty: float = float(os.getenv("BASE_QTY", "0.01"))

    # GRVT
    grvt_api_key: str = os.getenv("GRVT_API_KEY", "")
    grvt_api_secret: str = os.getenv("GRVT_API_SECRET", "")
    grvt_sub_account_id: str = os.getenv("GRVT_SUB_ACCOUNT_ID", "")
    grvt_env: str = os.getenv("GRVT_ENV", "prod")
    grvt_ws_stream_version: str = os.getenv("GRVT_WS_STREAM_VERSION", "v1")

    # Lighter
    lighter_api_private_key: str = os.getenv("LIGHTER_API_PRIVATE_KEY", "")
    lighter_api_key: str = os.getenv("LIGHTER_API_KEY", "")
    lighter_env: str = os.getenv("LIGHTER_ENV", "mainnet")
    lighter_ws_stream_version: str = os.getenv("LIGHTER_WS_STREAM_VERSION", "v1")
    lighter_account_index: int = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
    lighter_api_key_index: int = int(os.getenv("LIGHTER_API_KEY_INDEX", "2"))
    lighter_eth_address: str = os.getenv("LIGHTER_ETH_ADDRESS", "")
    lighter_eth_private_key: str = os.getenv("LIGHTER_ETH_PRIVATE_KEY", "")
    lighter_base_url: str = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")

    # Pacifica
    pacifica_api_key: str = os.getenv("PACIFICA_API_KEY", "")
    pacifica_api_private_key: str = os.getenv("PACIFICA_API_PRIVATE_KEY", "")
    pacifica_api_env: str = os.getenv("PACIFICA_API_ENV", "mainnet")


CFG = AppConfig()
