import asyncio
import ccxt.pro as ccxt
import redis.asyncio as aioredis
import redis as redis_sync
import logging

import os
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuracion
REDIS_URL = os.getenv('REDIS_URL')
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'binance')
PARES = os.getenv('PARES', 'BTC/USDT,ETH/BTC,ETH/USDT').split(',')

async def stream_orderbook(exchange, r_client, symbol):
    """Obtiene el orderbook en tiempo real y lo guarda en Redis ultra rapido."""
    while True:
        try:
            # CCXT Pro usa WebSocket por debajo y se mantiene conectado
            orderbook = await exchange.watch_order_book(symbol)
            
            # Extraer el mejor precio de compra (Bid) y venta (Ask)
            best_bid = orderbook['bids'][0][0] if len(orderbook['bids']) > 0 else 0
            best_ask = orderbook['asks'][0][0] if len(orderbook['asks']) > 0 else float('inf')
            
            # Estructurar los datos
            data = {
                'bid': best_bid,
                'ask': best_ask,
                'timestamp': exchange.milliseconds()
            }
            
            # Usar Redis Hash para almacenar la data estandarizada en O(1) tiempo
            await r_client.hset(f"{EXCHANGE_ID}:{symbol}", mapping=data)
            
            logging.info(f"[{symbol}] BID: {best_bid} | ASK: {best_ask}")
            
        except Exception as e:
            logging.error(f"Error de red procesando {symbol}: {e}")
            await asyncio.sleep(1) # Backoff para evitar ban por spam

async def main():
    if REDIS_URL:
        r_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    else:
        r_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    
    # Inicializar el modulo asincrono de CCXT
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    exchange = exchange_class({
        'enableRateLimit': True,
        'newUpdates': True, # Exigir al socket que solo traiga deltas o nuevos updates
    })
    
    logging.info(f"Iniciando motor de ingesta WS para {EXCHANGE_ID.upper()}...")
    
    try:
        await r_client.ping()
        logging.info("=> Redis detectado. Conectado.")
        
        # Iniciar una corrutina concurrente para cada par de divisas en la triangulacion
        tareas = [stream_orderbook(exchange, r_client, par) for par in PARES]
        await asyncio.gather(*tareas)
        
    except redis_sync.exceptions.ConnectionError:
        logging.error("=> ERROR CRITICO: Servidor de Redis inalcanzable. Revisa el contenedor de Docker.")
    finally:
        await exchange.close()
        await r_client.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Ingesta de WebSockets detenida por el usuario.")
