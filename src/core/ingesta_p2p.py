import asyncio
import aiohttp
import os
import json
import logging
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [API P2P] %(levelname)s - %(message)s')

REDIS_URL = os.getenv('REDIS_URL')
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

# Capital Base Parametrizable (Ej. ARS, USD, EUR)
P2P_FIAT = os.getenv('P2P_FIAT', 'ARS').upper()
ASSET = os.getenv('P2P_ASSET', 'USDT').upper()

async def fetch_p2p_page(session, trade_type):
    """
    Consume la API oculta de Binance P2P para rastrear los primeros lugares de la cartelera.
    trade_type: 'BUY' (gente comprando cripto), 'SELL' (gente vendiendo cripto)
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    
    payload = {
        "page": 1,
        "rows": 10,  # Rastreamos los top 10 competidores
        "payTypes": [],
        "asset": ASSET,
        "tradeType": trade_type,
        "fiat": P2P_FIAT,
        "merchantCheck": False  # Mirar a todos, no solo comerciantes verificados
    }
    
    try:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                if data and "data" in data:
                    return data["data"]
            else:
                logging.warning(f"Error {response.status} consultando la API P2P")
            return []
    except Exception as e:
        logging.error(f"Caída de red P2P: {e}")
        return []

async def p2p_ingestion_loop(r_client):
    logging.info("="*50)
    logging.info(f" 📡 INICIO MOTOR INGESTA P2P ({ASSET}/{P2P_FIAT})")
    logging.info("="*50)
    
    async with aiohttp.ClientSession() as session:
        while True:
            # Los anuncios "BUY" son de la gente que con moneda Fiat quiere COMPRAR USDT
            anuncios_compra = await fetch_p2p_page(session, "BUY")
            
            # Los anuncios "SELL" son de la gente que tiene USDT y quiere VENDER por Fiat
            anuncios_venta = await fetch_p2p_page(session, "SELL")
            
            if anuncios_compra and anuncios_venta:
                # El precio comercial base de todo Maker
                # Competencia "Compra": Precio más alto al que la gente está dispuesta a comprar.
                mejor_compra = float(anuncios_compra[0]['adv']['price'])
                
                # Competencia "Venta": Precio más bajo al que la gente está vendiendo.
                mejor_venta = float(anuncios_venta[0]['adv']['price'])
                
                # Para un Maker P2P (como el amigo), él quiere VENDER caro (compitiendo con 'anuncios_venta')
                # Y COMPRAR barato (compitiendo con 'anuncios_compra')
                
                # Serializar el JSON del listado superior completo para el motor analítico
                payload_compra = json.dumps([{"price": float(x['adv']['price']), "minSingleTransAmount": float(x['adv']['minSingleTransAmount'])} for x in anuncios_compra])
                payload_venta = json.dumps([{"price": float(x['adv']['price']), "minSingleTransAmount": float(x['adv']['minSingleTransAmount'])} for x in anuncios_venta])
                
                await r_client.hset(f"P2P:{P2P_FIAT}", mapping={
                    "mejor_compra": mejor_compra,
                    "mejor_venta": mejor_venta,
                    "libro_compradores": payload_compra,
                    "libro_vendedores": payload_venta
                })
                
                logging.info(f"💾 Guardado en Redis | Maker Venta Ideal: ~{mejor_venta} | Maker Compra Ideal: ~{mejor_compra}")
            
            # El mercado P2P se mueve muchísimo más lento que HFT. Refrescamos cada 15 segundos.
            await asyncio.sleep(15)

async def main():
    if REDIS_URL:
        r_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    else:
        r_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    
    try:
        await r_client.ping()
        await p2p_ingestion_loop(r_client)
    except Exception as e:
        logging.error(f"Falla fatal en REDIS conectando el motor P2P: {e}")

if __name__ == '__main__':
    asyncio.run(main())
