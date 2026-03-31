import math

class ArbitrajeTriangular:
    def __init__(self, fee=0.001): # Asumimos 0.1% de fee estándar (ej. Bybit/OKX Taker)
        self.fee = fee
        self.grafo = []
        self.monedas = []

    def agregar_mercado(self, base, quote, precio_bid, precio_ask):
        """
        Agrega las aristas dirigidas al grafo.
        Vender Base -> Comprar Quote (usamos el precio Bid)
        Comprar Base <- Vender Quote (usamos el precio Ask)
        """
        if base not in self.monedas: self.monedas.append(base)
        if quote not in self.monedas: self.monedas.append(quote)

        # Arista: Vender Base para obtener Quote (Peso = -log(bid * (1 - fee)))
        if precio_bid > 0:
            peso_venta = -math.log(precio_bid * (1 - self.fee))
            self.grafo.append((base, quote, peso_venta))

        # Arista: Comprar Base usando Quote (Peso = -log((1 / ask) * (1 - fee)))
        if precio_ask > 0:
            peso_compra = -math.log((1.0 / precio_ask) * (1 - self.fee))
            self.grafo.append((quote, base, peso_compra))

    def bellman_ford(self, nodo_origen):
        """
        Ejecuta Bellman-Ford para encontrar ciclos negativos.
        Complejidad temporal: O(V * E)
        Un ciclo negativo en este grafo logaritmico equivale a una
        oportunidad de arbitraje triangular rentable.
        """
        distancias = {nodo: float('inf') for nodo in self.monedas}
        predecesores = {nodo: None for nodo in self.monedas}
        distancias[nodo_origen] = 0

        # Relajacion de aristas (V - 1 veces)
        for _ in range(len(self.monedas) - 1):
            for u, v, w in self.grafo:
                if distancias[u] != float('inf') and distancias[u] + w < distancias[v]:
                    distancias[v] = distancias[u] + w
                    predecesores[v] = u

        # Deteccion de ciclos negativos (La oportunidad de arbitraje)
        ciclos = []
        nodos_ya_procesados = set()

        for u, v, w in self.grafo:
            # Tolerancia 1e-9 para evitar falsos positivos por errores de punto flotante
            if distancias[u] != float('inf') and distancias[u] + w < distancias[v] - 1e-9:
                if v in nodos_ya_procesados:
                    continue

                # Paso 1: Avanzar V veces para garantizar que el nodo este DENTRO del ciclo
                nodo_en_ciclo = v
                for _ in range(len(self.monedas)):
                    siguiente = predecesores.get(nodo_en_ciclo)
                    if siguiente is None:
                        break
                    nodo_en_ciclo = siguiente

                # Paso 2: Reconstruir el ciclo usando un conjunto de visitados
                ciclo = []
                visitados = set()
                nodo_actual = nodo_en_ciclo

                while nodo_actual not in visitados:
                    visitados.add(nodo_actual)
                    ciclo.append(nodo_actual)
                    siguiente = predecesores.get(nodo_actual)
                    if siguiente is None:
                        break
                    nodo_actual = siguiente

                # Paso 3: Cerrar y ordenar el ciclo en el sentido de ejecucion
                if len(ciclo) >= 2:
                    ciclo.append(ciclo[0])
                    ciclo.reverse()
                    if ciclo not in ciclos:
                        ciclos.append(ciclo)
                        nodos_ya_procesados.update(visitados)

        return ciclos


if __name__ == '__main__':
    # --- EJEMPLO DE USO (Simulando datos que vendrian de Redis) ---
    print("=" * 52)
    print("  Detector de Arbitraje Triangular - Test")
    print("=" * 52)

    # Test 1: Mercado con ineficiencia artificial
    # Ruta rentable: USDT -> ETH -> BTC -> USDT
    # 1 USDT -> 1/3000 ETH -> (1/3000) * 0.053 BTC -> (1/3000)*0.053*62000 USDT
    # = 1.0953 USDT => ganancia antes de fees > 3x fee = 0.3%
    arb = ArbitrajeTriangular(fee=0.001)
    arb.agregar_mercado('BTC', 'USDT', 62000, 62010)   # BTC sobrevaluado en USDT
    arb.agregar_mercado('ETH', 'BTC',  0.053,  0.0531) # ETH sobrevaluado en BTC
    arb.agregar_mercado('ETH', 'USDT', 3000,   3001)   # ETH subvaluado en USDT

    print("\n[Test 1] Mercado con ineficiencia artificial:")
    for origen in arb.monedas:
        oportunidades = arb.bellman_ford(origen)
        if oportunidades:
            print("  *** OPORTUNIDAD DETECTADA ***")
            for ciclo in oportunidades:
                print(f"  Ruta desde '{origen}': {' -> '.join(ciclo)}")
            break
    else:
        print("  Mercado eficiente. Sin oportunidad tras fees.")

    # Test 2: Mercado perfectamente eficiente
    arb2 = ArbitrajeTriangular(fee=0.001)
    arb2.agregar_mercado('BTC', 'USDT', 60000, 60010)
    arb2.agregar_mercado('ETH', 'BTC',  0.05,   0.0501)
    arb2.agregar_mercado('ETH', 'USDT', 3000,   3005)

    print("\n[Test 2] Mercado eficiente (precios alineados):")
    found = False
    for origen in arb2.monedas:
        oportunidades2 = arb2.bellman_ford(origen)
        if oportunidades2:
            found = True
            print("  *** OPORTUNIDAD DETECTADA (inesperada) ***")
            for ciclo in oportunidades2:
                print(f"  Ruta: {' -> '.join(ciclo)}")
            break
    if not found:
        print("  Mercado eficiente. Sin oportunidad. [CORRECTO]")

    print("\n" + "=" * 52)

