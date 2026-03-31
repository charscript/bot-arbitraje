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
from core.ingesta_p2p import main as p2p_ingesta_main
from core.detector_p2p import main as p2p_detector_main
from core.basis_arbitrage import main as basis_main
import redis.asyncio as aioredis
from aiohttp import web
import json
import os
from dotenv import load_dotenv
load_dotenv()

EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'binance').upper()
PARES = os.getenv('PARES', 'AUTO')
REDIS_URL = os.getenv('REDIS_URL')
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ORQUESTADOR] %(levelname)s - %(message)s'
)

# Filtramos la advertencia visual de DeprecationWarning
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

async def init_redis(app):
    if REDIS_URL:
        app['redis'] = aioredis.from_url(REDIS_URL, decode_responses=True)
    else:
        app['redis'] = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        
async def close_redis(app):
    await app['redis'].close()

async def api_status(request):
    """Endpoint vital para el Dashboard web que devuelve JSON puro directo de Redis"""
    r_client = request.app['redis']
    p2p_fiat = os.getenv('P2P_FIAT', 'ARS').upper()
    
    # Intentar traer datos P2P procesados por el motor de inteligencia (Smart Prices)
    try:
        p2p_data = await r_client.hgetall(f"P2P_TARGETS:{p2p_fiat}")
        mejor_c = float(p2p_data.get('compra_optima', 0))
        mejor_v = float(p2p_data.get('venta_optima', 0))
        p2p_spread = p2p_data.get('rentabilidad_pct', '0.00%')
    except Exception:
        mejor_c = 0
        mejor_v = 0
        p2p_spread = "0.00%"
        
    # Obtener historial de consola para mostrar en la interfaz en tiempo real
    raw_logs = await r_client.lrange("UI_LOGS", 0, 15)
    parsed_logs = []
    for log_str in raw_logs:
        try:
            parsed_logs.append(json.loads(log_str))
        except:
            pass

    payload = {
        "status": "online",
        "hft": {
            "exchange": EXCHANGE_ID,
            "pairs_mode": "Automático (Top 100)" if PARES == "AUTO" else PARES,
            "status": "Escaneando Milisegundos..."
        },
        "p2p": {
            "fiat": p2p_fiat,
            "maker_buy": f"${mejor_c:,.2f}",
            "maker_sell": f"${mejor_v:,.2f}",
            "spread_neto": p2p_spread
        },
        "basis": {
            "status": "Vigilando Curva de Futuros",
            "target": f"{os.getenv('TARGET_FUNDING_RATE', 0.2)}% APR"
        },
        "logs": parsed_logs
    }
    return web.json_response(payload)

async def start_web_server():
    """Inicia el Servidor de Aplicación Web Completo para el Dashboard Frontend"""
    app = web.Application()
    app.on_startup.append(init_redis)
    app.on_cleanup.append(close_redis)
    
    # Rutas API
    app.router.add_get('/api/status', api_status)
    
    # Rutas Frontend Estático (HTML/CSS/JS del Dashboard)
    web_dir = os.path.join(os.path.dirname(__file__), 'src', 'web')
    os.makedirs(web_dir, exist_ok=True)
    
    async def index(request):
        # Si el HTML aún no está construido (porque estamos programando), da fallback a OK
        idx = os.path.join(web_dir, 'index.html')
        if os.path.exists(idx):
            return web.FileResponse(idx)
        return web.Response(text="Dashboard en construcción... 🛠️")
        
    app.router.add_get('/', index)
    app.router.add_static('/', web_dir)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 DASHBOARD WEB y Servidor API levantados en el puerto {port}.")

async def run_all():
    logging.info("=" * 60)
    logging.info("  BOT DE ARBITRAJE TRIANGULAR - INICIANDO (VIVO)")
    logging.info(f"  Exchange: {EXCHANGE_ID} | Pares: {PARES}")
    logging.info("=" * 60)
    
    # 1. Iniciar Servidor Web / Dashboard API
    await start_web_server()
    
    # 2. Banderas de control de los motores (Todo encendido por defecto en La Herramienta Máxima)
    run_hft = os.getenv('ENABLE_HFT_CRYPTO', 'True') == 'True'
    run_p2p = os.getenv('ENABLE_P2P_FIAT', 'True') == 'True'
    run_basis = os.getenv('ENABLE_DELTA_NEUTRAL', 'True') == 'True'
    
    motores_activos = []
    
    if run_hft:
        logging.info("[ORQUESTADOR] => Arrancando Sub-Motor HFT (Cripto a Cripto)...")
        motores_activos.extend([ingesta_main(), detector_main()])
        
    if run_p2p:
        logging.info("[ORQUESTADOR] => Arrancando Sub-Motor P2P (Scanner Fiat/Comercial)...")
        motores_activos.extend([p2p_ingesta_main(), p2p_detector_main()])
        
    if run_basis:
        logging.info("[ORQUESTADOR] => Arrancando Sub-Motor Basis (Delta-Neutral Funding Farm)...")
        motores_activos.append(basis_main())
    
    if not motores_activos:
        logging.error("Todos los motores están apagados en el .env. El bot no hará nada.")
        return
        
    # 3. Correr todos los motores autorizados de manera concurrente
    await asyncio.gather(*motores_activos)

if __name__ == '__main__':
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logging.info("Sistema detenido por el usuario.")
