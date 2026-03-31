#!/usr/bin/env python3
"""
Main Orchestrator - El Cerebro
Levanta en paralelo:
  - ingesta_websockets.py  -> Conecta CCXT Pro a Bybit via WS y vuelca bid/ask a Redis
  - detector_arbitraje.py  -> Lee Redis y ejecuta Bellman-Ford en tiempo real
"""
import asyncio
import logging
import sys

# Agregar src al path para imports relativos
sys.path.insert(0, 'src')

from core.ingesta_websockets import main as ingesta_main
from core.detector_arbitraje import main as detector_main

import os
from dotenv import load_dotenv
load_dotenv()

EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'binance').upper()
PARES = os.getenv('PARES', 'BTC/USDT,ETH/BTC,ETH/USDT')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ORQUESTADOR] %(levelname)s - %(message)s'
)

# Filtramos la advertencia visual de DeprecationWarning
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

async def run_all():
    logging.info("=" * 60)
    logging.info("  BOT DE ARBITRAJE TRIANGULAR - INICIANDO (VIVO)")
    logging.info(f"  Exchange: {EXCHANGE_ID} | Pares: {PARES}")
    logging.info("=" * 60)
    
    # Correr ambos engines de manera totalmente concurrente
    await asyncio.gather(
        ingesta_main(),
        detector_main(),
    )

if __name__ == '__main__':
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logging.info("Sistema detenido por el usuario.")
