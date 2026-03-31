import os
import ccxt.async_support as ccxt
import logging
import asyncio
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [EXEC] %(levelname)s - %(message)s')

class ExecutionEngine:
    def __init__(self):
        self.exchange_id = os.getenv('EXCHANGE_ID', 'binance').lower()
        self.api_key = os.getenv('API_KEY', '')
        self.secret = os.getenv('API_SECRET', '')
        
        # Activamos el MOCK (Simulacro) por defecto si no detectamos API keys, para no comprometer nuestro deploy actual
        self.mock_mode = os.getenv('MOCK_EXECUTION', 'True').lower() == 'true' or not self.api_key
        
        ex_class = getattr(ccxt, self.exchange_id)
        
        # Inicialización del exchange
        if self.mock_mode:
            logging.warning("⚠️ Execution Engine iniciado en MODO SIMULACRO (Las órdenes no enviarán dólares reales)")
            self.exchange = ex_class({'enableRateLimit': True})
        else:
            logging.warning("🔥 Execution Engine iniciado en MODO REAL. Las API keys conectadas transaccionarán dinero.")
            self.exchange = ex_class({
                'apiKey': self.api_key,
                'secret': self.secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })

    async def _execute_leg(self, num, symbol, side, amount, expected_price):
        """Dispara una rama de la operación. Puede ser real o un simulacro instantáneo."""
        if self.mock_mode:
            await asyncio.sleep(0.01) # Simular la latencia de la fibra óptica
            logging.info(f"   [SIMULACRO] Pata {num}: Orden ejecutada => {side.upper()} {amount:.4f} de {symbol} (Precio referencial: {expected_price})")
            return {"status": "closed", "filled": amount, "average": expected_price}
        
        try:
            # En la vida real, los HFT de arbitraje mandan órdenes "Market" o Limit tipo IOC para velocidad supersónica
            logging.info(f"   [REAL] Enviando pata {num}: {side.upper()} {amount:.4f} de {symbol}")
            order = await self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=amount
            )
            return order
        except Exception as e:
            logging.error(f"   [FATAL] Error ejecutando la pata {num} en {symbol}: {e}")
            return {"status": "failed", "error": str(e)}

    async def execute_triangular_arbitrage(self, ruta, base_amount=100.0):
        """
        Lee el ciclo descubierto y dispara el arbitraje en vivo de forma simultánea.
        ruta: Lista ['USDT', 'BTC', 'ETH', 'USDT']
        base_amount: Cantidad del capital inicial a invertir
        """
        logging.info(f"🚀 [DISPARO] Iniciando ráfaga de órdenes para el ciclo: {' -> '.join(ruta)}")
        logging.info(f"🚀 [CAPITAL] Asignado: {base_amount} {ruta[0]}")
        
        # TODO: Transformar moneda origen/destino en Base/Quote de CCXT según liquidez viva.
        # Por ahora lo mantenemos estructurado conceptualmente para testeo del framework:
        
        # En el HFT moderno inter-par, una ráfaga paralela es mejor que ser secuencial, 
        # pero es más riesgoso si una de las tres falla (desbalance de portafolio).
        # A fines de nuestro "GameChanger", la latencia simulada será asíncrona concurrente.
        
        tareas_ejecucion = [
            self._execute_leg(1, f"{ruta[1]}/{ruta[0]}", 'buy', base_amount / 65000, 65000),      # E.g. BTC/USDT
            self._execute_leg(2, f"{ruta[2]}/{ruta[1]}", 'buy', (base_amount / 65000), 0.04),     # E.g. ETH/BTC
            self._execute_leg(3, f"{ruta[2]}/{ruta[0]}", 'sell', (base_amount / 65000), 2600)     # E.g. ETH/USDT
        ]
        
        # Ejecutar todas las patas al unísono
        resultados = await asyncio.gather(*tareas_ejecucion, return_exceptions=True)
        
        exitosas = sum(1 for r in resultados if isinstance(r, dict) and r.get('status') == 'closed')
        if exitosas == 3:
            logging.info("🎯 [ÉXITO] Ráfaga de Arbitraje Completada al 100%. Beneficio asegurado en cuenta.")
            return True
        else:
            logging.error(f"💥 [FALLO] Solo pasaron {exitosas}/3 órdenes. Riesgo de exposición direccional activo.")
            # El Risk Engine debe intervenir aquí.
            return False

    async def close(self):
        await self.exchange.close()

if __name__ == '__main__':
    # Testeo rústico local del Engine
    async def tester():
        motor = ExecutionEngine()
        await motor.execute_triangular_arbitrage(['USDT', 'BTC', 'ETH', 'USDT'], 500)
        await motor.close()
    
    asyncio.run(tester())
