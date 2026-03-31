import asyncio
import os
import logging
import redis.asyncio as aioredis
from dotenv import load_dotenv

# Reutilizamos el potente envíador de Telegram que ya hicimos en HFT
import sys
sys.path.insert(0, 'src')
from core.telegram_alertas import enviar_mensaje

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [P2P DETECTOR] %(levelname)s - %(message)s')

REDIS_URL = os.getenv('REDIS_URL')
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
P2P_FIAT = os.getenv('P2P_FIAT', 'ARS').upper()

# Configuración del Negocio Comercial P2P
MIN_SPREAD_PCT = float(os.getenv('P2P_MIN_SPREAD_PCT', 0.8)) # Ganancia mínima
CAPITAL_INICIAL = float(os.getenv('P2P_CAPITAL', 20000)) # Capital disponible
UMBRAL_BALLENA = float(os.getenv('P2P_WHALE_LIMIT', 50000)) # Ej: Ignorar rivales que no operen al menos con 50.000 ARS por transacción
import json

async def motor_inteligencia_p2p(r_client):
    logging.info("="*50)
    logging.info(f" 🧠 INICIO INTELIGENCIA COMERCIAL P2P ({P2P_FIAT})")
    logging.info("="*50)
    
    ultimo_mensaje = 0
    
    while True:
        try:
            data = await r_client.hgetall(f"P2P:{P2P_FIAT}")
            if data and 'libro_compradores' in data and 'libro_vendedores' in data:
                compradores = json.loads(data['libro_compradores'])
                vendedores = json.loads(data['libro_vendedores'])
                
                # --- GAME THEORY: SMART ROUTING ---
                # Filtrar a los peces pequeños ("Guppies"). Solo competir contra mayoristas de peso.
                ballenas_compra = [c for c in compradores if c['minSingleTransAmount'] >= UMBRAL_BALLENA]
                ballenas_venta = [v for v in vendedores if v['minSingleTransAmount'] >= UMBRAL_BALLENA]
                
                # Si no hay ballenas, caemos de vuelta al tope de la lista general
                if not ballenas_compra: ballenas_compra = compradores
                if not ballenas_venta: ballenas_venta = vendedores
                
                compra_mercado = float(ballenas_compra[0]['price']) 
                venta_mercado = float(ballenas_venta[0]['price'])   
                
                # Para ser #1 institucional, le agregamos/quitamos 1 centavo/peso al mejor competidor REAL.
                mi_precio_ad_compra = compra_mercado + 0.05
                mi_precio_ad_venta = venta_mercado - 0.05
                
                # ¿Cuánto gano si completo el circuito comprando a USD Retailers y vendiendo a USD Institucionales?
                spread_bruto_pct = ((mi_precio_ad_venta - mi_precio_ad_compra) / mi_precio_ad_compra) * 100
                ganancia_estimada_ciclo = CAPITAL_INICIAL * (spread_bruto_pct / 100.0)
                
                log_msg = f"Analizando P2P | Tu Compra Optima: {mi_precio_ad_compra:.2f} | Tu Venta Optima: {mi_precio_ad_venta:.2f} | RENTABILIDAD: {spread_bruto_pct:.3f}%"
                logging.info(log_msg)
                
                # Guardamos los "Smart Prices" en Redis para que el Dashboard Web lo levante idéntico a la consola
                await r_client.hset(
                    f"P2P_TARGETS:{P2P_FIAT}",
                    mapping={
                        "compra_optima": str(mi_precio_ad_compra),
                        "venta_optima": str(mi_precio_ad_venta),
                        "rentabilidad_pct": f"{spread_bruto_pct:.3f}%"
                    }
                )
                
                # Filtrar y emitir Asistencia por Telegram
                if spread_bruto_pct >= MIN_SPREAD_PCT:
                    ahora = asyncio.get_event_loop().time()
                    
                    # Evitar bombardear el Telegram. Enviar mensaje solo cada 30 minutos si el spread sigue bueno
                    if ahora - ultimo_mensaje > 1800:
                        msg = (
                            f"💼 <b>ALERTA NEGOCIO P2P ({P2P_FIAT})</b> 💼\n\n"
                            f"¡Hueco de rentabilidad detectado!\n"
                            f"<b>Margen Bruto:</b> {spread_bruto_pct:.2f}%\n"
                            f"<b>Beneficio 1 Vuelta ({CAPITAL_INICIAL} USD):</b> ${ganancia_estimada_ciclo:.2f} USD\n\n"
                            f"📋 <b>Instrucciones Creador de Mercado:</b>\n"
                            f"1. Publicá anuncio COMPRA a: <b>{mi_precio_ad_compra:.2f}</b>\n"
                            f"2. Publicá anuncio VENTA a:  <b>{mi_precio_ad_venta:.2f}</b>\n\n"
                            f"<i>⚡ <b>Smart-Pricing Action:</b> Se ignoraron usuarios retail ({UMBRAL_BALLENA} min). Estás tradeando contra mayoristas.</i>"
                        )
                        asyncio.create_task(enviar_mensaje(msg))
                        ultimo_mensaje = ahora
                        logging.warning(f"=> TELEGRAM ENVIADO: Brecha ballena de {spread_bruto_pct:.2f}% reportada.")
                        
                # Mandar a Redis un evento de consola para el Dashboard Web
                await r_client.lpush("UI_LOGS", json.dumps({"engine": "P2P", "msg": log_msg, "type": "info"}))
                await r_client.ltrim("UI_LOGS", 0, 50) # Mantener solo últimos 50 logs
            else:
                logging.warning(f"Esperando JSON P2P para {P2P_FIAT}...")
                
        except Exception as e:
            logging.error(f"Error analizando memoria P2P: {e}")
            
        await asyncio.sleep(5)

async def main():
    if REDIS_URL:
        r_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    else:
        r_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        
    try:
        await r_client.ping()
        await motor_inteligencia_p2p(r_client)
    except Exception as e:
        logging.error(f"Caída catastrófica conectando a Redis en el Detector: {e}")

if __name__ == '__main__':
    asyncio.run(main())
