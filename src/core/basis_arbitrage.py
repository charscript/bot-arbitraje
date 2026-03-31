import asyncio
import os
import logging
import ccxt.async_support as ccxt
from dotenv import load_dotenv

import sys
sys.path.insert(0, 'src')
from core.telegram_alertas import enviar_mensaje

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [BASIS ARBITRAGE] %(levelname)s - %(message)s')

EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'binance').lower()
TARGET_FUNDING_RATE = float(os.getenv('TARGET_FUNDING_RATE', 0.2)) # 0.2% mínimo por 8 horas (Altísimo, solo bull-markets)

async def scan_funding_rates(exchange):
    logging.info("="*50)
    logging.info(f" 🛡️ INICIO DETECTOR DELTA-NEUTRAL ({EXCHANGE_ID.upper()})")
    logging.info(f" Target Mínimo: {TARGET_FUNDING_RATE}% cada 8 horas")
    logging.info("="*50)
    
    ultimo_mensaje = 0
    
    while True:
        try:
            # Traer todas las tasas de financiamiento de Perpetuos en un solo ping masivo
            funding_rates = await exchange.fetch_funding_rates()
            anomalias = []
            
            for symbol, details in funding_rates.items():
                if details and 'fundingRate' in details and details['fundingRate']:
                    tasa_pct = float(details['fundingRate']) * 100
                    
                    # Buscamos anomalías donde la gente está MUY apalancada comprando (longs pagan shorts)
                    if tasa_pct >= TARGET_FUNDING_RATE:
                        anomalias.append((symbol, tasa_pct, details.get('nextFundingTime')))
                        
            anomalias.sort(key=lambda x: x[1], reverse=True)
            
            if anomalias:
                mejor_activo = anomalias[0]
                symbol, tasa, ts = mejor_activo
                
                logging.warning(f"🏆 Anomalía Grave de Funding Rate en {symbol}: {tasa:.4f}% | Pago inminente")
                
                ahora = asyncio.get_event_loop().time()
                # Cooldown de 4 horas para no hacer spam (son tasas lentas, duran 8hs)
                if ahora - ultimo_mensaje > 14400:
                    ganancia_anualificada = tasa * 3 * 365 
                    msg = (
                        f"🛡️ <b>ALERTA DELTA-NEUTRAL (FUNDING FARM)</b> 🛡️\n\n"
                        f"¡Mercado sobrecalentado!\n"
                        f"<b>Mercado Perpetuo:</b> {symbol}\n"
                        f"<b>Tasa Actual:</b> {tasa:.4f}% (Pago en unas horas)\n"
                        f"<b>Rendimiento APR Proyectado:</b> {ganancia_anualificada:.1f}%\n\n"
                        f"📈 <b>Instrucciones de Cobertura ($0 Riesgo Direccional):</b>\n"
                        f"1. Compra <b>Spot</b>: Adquiere el activo físico en el mercado tradicional.\n"
                        f"2. Vende <b>Short</b>: Vende la misma cantidad como cobertura 1X en Futuros.\n"
                        f"<i>Tu portafolio estará blindado de las caídas, y cobrarás interes por aportar liquidez vendedora.</i>"
                    )
                    asyncio.create_task(enviar_mensaje(msg))
                    ultimo_mensaje = ahora
            else:
                logging.info(f"Cazando anomalías... Nivel más alto actual no supera la valla de {TARGET_FUNDING_RATE}%")
                
        except Exception as e:
            # Algunos exchanges o simbolos arrojan error dev si la api de futuros no está activa
            logging.error(f"Error escaneando tasas de cobertura: {e}")
            
        await asyncio.sleep(60 * 15) # Refrescar la curva completa cada 15 minutos

async def main():
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    
    # Binance divide Spot y Futuros en endpoints distintos (usdfutures)
    options = {'defaultType': 'swap'} if EXCHANGE_ID == 'binance' else {}
    
    exchange = exchange_class({
        'enableRateLimit': True,
        'options': options
    })
    
    try:
        await exchange.load_markets()
        await scan_funding_rates(exchange)
    except Exception as e:
        logging.error(f"Caída catastrofica del motor Delta-Neutral: {e}")
    finally:
        await exchange.close()

if __name__ == '__main__':
    asyncio.run(main())
