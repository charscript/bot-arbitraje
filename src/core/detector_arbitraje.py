import asyncio
import redis.asyncio as aioredis
import redis as redis_sync
import logging
import os
from dotenv import load_dotenv

# Importar módulos del proyecto
import sys
sys.path.insert(0, 'src')
from core.arbitraje_triangular import ArbitrajeTriangular
from core.risk_engine import RiskEngine
from core.telegram_alertas import enviar_mensaje, formatear_oportunidad, formatear_circuit_breaker

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [DETECTOR] %(levelname)s - %(message)s')

REDIS_HOST  = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT  = int(os.getenv('REDIS_PORT', 6379))
EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'bybit')
FEE         = 0.001

TRIANGULO = {
    'BTC/USDT': ('BTC', 'USDT'),
    'ETH/BTC':  ('ETH', 'BTC'),
    'ETH/USDT': ('ETH', 'USDT'),
}

# Risk Engine compartido con configuración del .env
risk = RiskEngine(
    capital_max_usdt=float(os.getenv('CAPITAL_MAX_USDT', 500)),
    min_spread_pct=float(os.getenv('MIN_SPREAD_PCT', 0.05)),
    max_errores_consecutivos=int(os.getenv('MAX_ERRORES_CONSECUTIVOS', 5)),
)


async def leer_precios_redis(r_client):
    precios = {}
    for simbolo in TRIANGULO:
        data = await r_client.hgetall(f"{EXCHANGE_ID}:{simbolo}")
        if data and 'bid' in data and 'ask' in data:
            precios[simbolo] = {
                'bid': float(data['bid']),
                'ask': float(data['ask']),
            }
    return precios


async def ciclo_deteccion(r_client):
    logging.info("Motor de detección iniciado. Escaneando cada 50ms...")
    oportunidades_n = 0

    while True:
        # Si el circuit breaker está activo, no ejecutar — esperar reset manual
        if risk.circuito_abierto:
            await asyncio.sleep(5)
            continue

        try:
            precios = await leer_precios_redis(r_client)

            if len(precios) < len(TRIANGULO):
                logging.warning(f"Esperando datos de Redis... ({len(precios)}/{len(TRIANGULO)} pares)")
                await asyncio.sleep(0.5)
                continue

            arb = ArbitrajeTriangular(fee=FEE)
            for simbolo, (base, quote) in TRIANGULO.items():
                p = precios[simbolo]
                arb.agregar_mercado(base, quote, p['bid'], p['ask'])

            for origen in arb.monedas:
                ciclos = arb.bellman_ford(origen)
                if ciclos:
                    for ciclo in ciclos:
                        # Validar con el Risk Engine antes de alertar
                        resultado = risk.validar_oportunidad(
                            spread_bruto=0.003,         # TODO: calcular spread real desde el ciclo
                            fee_total=FEE * len(ciclo),
                            profundidad_bid=500,        # TODO: leer profundidad real desde Redis
                            profundidad_ask=500,
                        )
                        if resultado['aprobado']:
                            oportunidades_n += 1
                            ruta = " -> ".join(ciclo)
                            logging.warning(f"*** OPORTUNIDAD #{oportunidades_n} APROBADA *** {ruta}")
                            msg = formatear_oportunidad(ciclo, resultado)
                            asyncio.create_task(enviar_mensaje(msg))
                        else:
                            logging.info(f"Ciclo detectado pero rechazado: {resultado['motivo']}")
                    break

            await asyncio.sleep(0.05)

        except Exception as e:
            logging.error(f"Error en ciclo de detección: {e}")
            risk.registrar_error(str(e))

            # Notificar si el circuit breaker se activó
            if risk.circuito_abierto:
                msg = formatear_circuit_breaker(
                    errores=int(os.getenv('MAX_ERRORES_CONSECUTIVOS', 5)),
                    ventana=60.0
                )
                asyncio.create_task(enviar_mensaje(msg))

            await asyncio.sleep(1)


async def main():
    r_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        await r_client.ping()
        logging.info("Conectado a Redis correctamente.")
        await ciclo_deteccion(r_client)
    except redis_sync.exceptions.ConnectionError:
        logging.error("ERROR: No se puede conectar a Redis. Levanta el servidor primero.")
    finally:
        await r_client.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Motor de detección detenido.")
