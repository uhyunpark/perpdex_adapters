# Perpdex Adapters

Unified exchange adapter for perpetual future DEXs. Build your own strategy with adapters.

## 📋 Table of Contents

- [Overview](#overview)
- [Supported Exchanges](#supported-exchanges)
- [Installation](#installation)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Development](#development)

## Overview

Perpdex Adapters is a Python-based trading system that provides a unified interface for multiple perpetual futures exchanges. 
Currently supports GRVT and Lighter, and more to come

## Supported Exchanges

| Exchange | REST API | WebSocket |
|----------|----------|-----------|
| **GRVT**  | ✅ | ✅ | 
| **Lighter** | ✅ | ✅ | 
| **Pacifica** | 🚧 | ✅  | 
| **Hyperliquid**  | 🚧 | 🚧 | 

## Installation

### Requirements

- Python 3.10+
- pip or poetry

### Install Dependencies

```bash
# activate venv
source .venv/bin/activate
# Install dependencies
pip install -r requirements.txt
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure your API keys:

```bash
cp .env.example .env
```

### Required Settings

```bash
# General settings
ENV=prod
PAIR=SOL-USDT-PERP
BASE_QTY=0.1

# GRVT configuration
GRVT_API_KEY=your_api_key
GRVT_PRIVATE_KEY=your_private_key
GRVT_TRADING_ACCOUNT_ID=your_account_id
GRVT_ENV=prod

# Lighter configuration
LIGHTER_PRIVATE_KEY=your_private_key
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=2
LIGHTER_ENV=mainnet

# Pacifica configuration
PACIFICA_API_KEY=
PACIFICA_API_PRIVATE_KEY=
PACIFICA_API_ENV=mainnet
```

### Lighter Initial Setup
If you're using Lighter for the first time, you need to create public API key first in [here](https://app.lighter.xyz/apikeys)

Also you need to set up your account to get private key:

```bash
# add your lighter login eth wallet private key to LIGHTER_ETH_PRIVATE_KEY in .env
python -m examples.lighter.system_setup
```

## Project Structure

```
perpdex_adapters/
├── adapters/           # Exchange adapters
│   ├── grvt.py        # GRVT adapter
│   └── lighter.py     # Lighter adapter
│   └── pacifica.py    # Pacifica adapter
├── common/            # Common utilities
│   ├── types.py       # Data type definitions
│   └── utils.py       # Helper functions
├── test/           # Test scripts
├── config.py         # Global configuration
└── requirements.txt  # Dependencies
```


## Testing

### Adapter Tests

```bash
# Test GRVT
python -m test.test_grvt

# Test Lighter
python -m test.test_lighter

# Test Pacifica
python -m test.test_pacifica
```

## Contact

If you encounter any issues, please report them via GitHub Issues.