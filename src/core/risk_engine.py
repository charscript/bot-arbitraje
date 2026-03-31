"""
Risk Engine - Gestor de Riesgos del sistema de arbitraje.

Responsabilidades:
  - Circuit breaker: Detiene el motor si se acumulan errores.
  - Filtro de liquidez: Valida que el order book tenga profundidad suficiente.
  - Stop loss dinamico: Limita el capital en riesgo por operacion.
"""
import time
import logging

logger = logging.getLogger('RiskEngine')

class RiskEngine:
    def __init__(
        self,
        capital_max_usdt: float = 500.0,     # Capital maximo por operacion
        min_spread_pct:  float = 0.05,        # Spread minimo neto rentable (%)
        max_errores_consecutivos: int = 5,    # Circuit breaker
        ventana_segundos: float = 60.0,       # Ventana de tiempo para errores
    ):
        self.capital_max_usdt = capital_max_usdt
        self.min_spread_pct   = min_spread_pct / 100.0
        self.max_errores      = max_errores_consecutivos
        self.ventana          = ventana_segundos

        self._errores: list[float] = []       # timestamps de errores recientes
        self._circuit_abierto = False

    # -------------------------------------------------------------------
    # CIRCUIT BREAKER
    # -------------------------------------------------------------------
    def registrar_error(self, motivo: str = ""):
        ahora = time.time()
        self._errores.append(ahora)
        # Limpiar errores fuera de la ventana
        self._errores = [t for t in self._errores if ahora - t <= self.ventana]
        logger.warning(f"Error registrado: {motivo}. Total en ventana: {len(self._errores)}")

        if len(self._errores) >= self.max_errores:
            self._circuit_abierto = True
            logger.error(f"*** CIRCUIT BREAKER ACTIVADO *** ({len(self._errores)} errores en {self.ventana}s)")

    def resetear_circuito(self):
        self._errores = []
        self._circuit_abierto = False
        logger.info("Circuit breaker reseteado manualmente.")

    @property
    def circuito_abierto(self) -> bool:
        return self._circuit_abierto

    # -------------------------------------------------------------------
    # VALIDACIÓN DE OPORTUNIDAD
    # -------------------------------------------------------------------
    def validar_oportunidad(
        self,
        spread_bruto: float,
        fee_total: float,
        profundidad_bid: float,
        profundidad_ask: float,
        saldo_disponible_usdt: float = None
    ) -> dict:
        """
        Decide si una oportunidad es ejecutable.

        Args:
            spread_bruto:     Ganancia bruta en % (antes de fees).
            fee_total:        Suma de todos los fees de la ruta.
            profundidad_bid:  Suma del top-5 bid en USDT.
            profundidad_ask:  Suma del top-5 ask en USDT.
            saldo_disponible_usdt: El balance real disponible en el Exchange. Si es None, usa el estático.

        Returns:
            Dict con 'aprobado' (bool) y 'motivo' (str).
        """
        if self._circuit_abierto:
            return {'aprobado': False, 'motivo': 'Circuit breaker activo'}

        spread_neto = spread_bruto - fee_total
        if spread_neto < self.min_spread_pct:
            return {
                'aprobado': False,
                'motivo': f'Spread neto {spread_neto*100:.4f}% < minimo {self.min_spread_pct*100:.4f}%'
            }

        # El capital a arriesgar no puede superar la profundidad disponible
        
        # --- GAMECHANGER: DYNAMIC ALLOCATION (Proxy de Kelly) ---
        # Si le pasamos el saldo real del Exchange, jamás apostamos más del 10% del portafolio por trade.
        if saldo_disponible_usdt is not None:
            max_capital_permitido = saldo_disponible_usdt * 0.10
        else:
            max_capital_permitido = self.capital_max_usdt
            
        capital_efectivo = min(max_capital_permitido, profundidad_bid, profundidad_ask)
        
        if capital_efectivo < 10:
            return {'aprobado': False, 'motivo': f'Profundidad insuficiente: {capital_efectivo:.2f} USDT'}

        ganancia_estimada = capital_efectivo * spread_neto
        return {
            'aprobado': True,
            'motivo': 'OK',
            'capital_usdt': round(capital_efectivo, 2),
            'spread_neto_pct': round(spread_neto * 100, 4),
            'ganancia_estimada_usdt': round(ganancia_estimada, 4),
        }


# -------------------------------------------------------------------
# TEST RAPIDO
# -------------------------------------------------------------------
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    re = RiskEngine(capital_max_usdt=500, min_spread_pct=0.05)

    print("--- Test 1: Oportunidad APROBADA ---")
    res = re.validar_oportunidad(
        spread_bruto=0.003,   # 0.3% bruto
        fee_total=0.001,      # 0.1% fees
        profundidad_bid=1000,
        profundidad_ask=800,
    )
    print(res)

    print("\n--- Test 2: Spread insuficiente ---")
    res = re.validar_oportunidad(
        spread_bruto=0.0005,
        fee_total=0.001,
        profundidad_bid=1000,
        profundidad_ask=800,
    )
    print(res)

    print("\n--- Test 3: Circuit Breaker ---")
    for i in range(5):
        re.registrar_error(f"timeout #{i+1}")
    res = re.validar_oportunidad(
        spread_bruto=0.01,
        fee_total=0.001,
        profundidad_bid=5000,
        profundidad_ask=5000,
    )
    print(res)
