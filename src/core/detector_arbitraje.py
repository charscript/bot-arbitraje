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
from core.execution_engine import ExecutionEngine
import math
import json

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [DETECTOR] %(levelname)s - %(message)s')

REDIS_URL   = os.getenv('REDIS_URL')
REDIS_HOST  = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT  = int(os.getenv('REDIS_PORT', 6379))
EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'bybit')
FEE         = 0.001

# El viejo diccionario estático TRIANGULO murió. Ahora somos N-Dimensionales.
# Buscaremos todos los colímites cíclicos de la categoría del Exchange.

# Risk Engine compartido con configuración del .env
risk = RiskEngine(
    capital_max_usdt=float(os.getenv('CAPITAL_MAX_USDT', 500)),
    min_spread_pct=float(os.getenv('MIN_SPREAD_PCT', 0.05)),
    max_errores_consecutivos=int(os.getenv('MAX_ERRORES_CONSECUTIVOS', 5)),
)

# El motor de ejecución (Market Maker / Sniper)
execution = ExecutionEngine()


async def leer_precios_redis(r_client):
    precios = {}
    # N-Dimensional Graph Fetching: Traemos TODOS los nodos vivos (Ej: 100+) en O(1) vía Redis Pipeline
    llaves = await r_client.keys(f"{EXCHANGE_ID}:*")
    
    # Opcional: Para evitar rate limits en keys(), usaremos lrange si queremos optimizar, pero en Upstash keys('*') es rápido con ~100.
    for llave in llaves:
        simbolo = llave.split(f"{EXCHANGE_ID}:")[1]
        data = await r_client.hgetall(llave)
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

            if len(precios) < 10:
                logging.warning(f"Construyendo Grafo N-Dimensional... (Actual: {len(precios)} nodos)")
                await asyncio.sleep(0.5)
                continue

            arb = ArbitrajeTriangular(fee=FEE)
            # Transformar toda la topología de la Categoría cripto en el algoritmo
            for simbolo, p in precios.items():
                try:
                    if '/' in simbolo:
                        base, quote = simbolo.split('/')
                        arb.agregar_mercado(base, quote, p['bid'], p['ask'])
                except Exception:
                    continue

            # Publicar estadísticas del Grafo Topológico a Redis para el Dashboard
            n_nodos = len(arb.monedas)
            n_aristas = len(arb.grafo)
            await r_client.hset("HFT_STATS", mapping={
                "nodos": str(n_nodos),
                "aristas": str(n_aristas),
                "oportunidades": str(oportunidades_n),
                "status": f"Escaneando {n_nodos} monedas, {n_aristas} rutas"
            })

            # Buscar los Colímites comenzando desde liquidez pura
            for origen in ['USDT', 'USDC']:
                if origen not in arb.monedas: continue
                ciclos = arb.bellman_ford(origen)
                if ciclos:
                    for ciclo in ciclos:
                        # === CALCULAR SPREAD REAL DEL CICLO ===
                        # Recorremos la cadena multiplicando tasas reales para obtener la ganancia neta
                        multiplicador = 1.0
                        ruta_valida = True
                        for i in range(len(ciclo) - 1):
                            nodo_a = ciclo[i]
                            nodo_b = ciclo[i+1]
                            # Buscar la tasa de cambio real entre estos dos nodos
                            par_directo = f"{nodo_a}/{nodo_b}"   # Ej: BTC/USDT -> vender BTC por USDT (usar bid)
                            par_inverso = f"{nodo_b}/{nodo_a}"   # Ej: USDT/BTC -> comprar BTC con USDT (usar 1/ask)
                            
                            if par_directo in precios:
                                multiplicador *= precios[par_directo]['bid'] * (1 - FEE)
                            elif par_inverso in precios:
                                multiplicador *= (1.0 / precios[par_inverso]['ask']) * (1 - FEE)
                            else:
                                ruta_valida = False
                                break
                        
                        if not ruta_valida:
                            continue
                            
                        spread_real = multiplicador - 1.0  # Ej: 1.003 -> 0.3% de ganancia neta
                        
                        # Validar con el Risk Engine con el spread REAL calculado
                        resultado = risk.validar_oportunidad(
                            spread_bruto=abs(spread_real),
                            fee_total=0,  # Ya está incluido en el multiplicador
                            profundidad_bid=500,
                            profundidad_ask=500,
                        )
                        if resultado['aprobado'] and spread_real > 0:
                            oportunidades_n += 1
                            ruta = " -> ".join(ciclo)
                            logging.warning(f"*** OPORTUNIDAD #{oportunidades_n} DETECTADA *** {ruta} | Spread Neto: {spread_real*100:.4f}%")
                            
                            # Publicar evento al Live Log del Dashboard
                            await r_client.lpush("UI_LOGS", json.dumps({
                                "engine": "HFT",
                                "msg": f"\u26a1 OPORTUNIDAD #{oportunidades_n}: {ruta} | Profit: {spread_real*100:.4f}%",
                                "type": "alert"
                            }))
                            await r_client.ltrim("UI_LOGS", 0, 50)
                            
                            # Disparar ejecución automática
                            exito = await execution.execute_triangular_arbitrage(
                                ruta=ciclo, 
                                base_amount=float(os.getenv('CAPITAL_MAX_USDT', 500))
                            )
                            
                            msg = formatear_oportunidad(ciclo, resultado)
                            msg += f"\n\n\ud83d\udcca <b>Spread Neto Real:</b> {spread_real*100:.4f}%"
                            if exito:
                                msg += "\n\n\ud83e\udd16 <b>ACCI\u00d3N:</b> \u00d3RDENES FOK EJECUTADAS."
                            else:
                                msg += "\n\n\u26a0\ufe0f <b>ACCI\u00d3N:</b> Falla en ejecuci\u00f3n. Riesgo abortado."
                                
                            asyncio.create_task(enviar_mensaje(msg))
                        else:
                            logging.debug(f"Ciclo {' -> '.join(ciclo)} rechazado: spread={spread_real*100:.4f}% | {resultado.get('motivo', 'spread negativo')}")
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
    if REDIS_URL:
        r_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    else:
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
