document.addEventListener('DOMContentLoaded', () => {
    // Referencias al DOM
    const ui = {
        globalStatus: document.getElementById('global-status'),
        hftExchange: document.getElementById('hft-exchange'),
        hftPairs: document.getElementById('hft-pairs'),
        hftStatus: document.getElementById('hft-status'),
        p2pFiat: document.getElementById('p2p-fiat'),
        p2pBuy: document.getElementById('p2p-buy'),
        p2pSell: document.getElementById('p2p-sell'),
        p2pSpread: document.getElementById('p2p-spread'),
        basisTarget: document.getElementById('basis-target'),
        basisStatus: document.getElementById('basis-status'),
        liveLogs: document.getElementById('live-logs')
    };

    /**
     * Función principal asíncrona que extrae el cerebro de JSON desde Python
     */
    async function syncDashboardData() {
        try {
            const response = await fetch('/api/status');
            
            if (!response.ok) throw new Error('Servidor fuera de línea');
            
            const data = await response.json();
            renderDashboard(data);
            
        } catch (error) {
            console.error("Pérdida de señal con el Motor Orquestador:", error);
            ui.globalStatus.innerHTML = "<span style='color: var(--accent-red)'>❌ Conexión Interrumpida.</span>";
        }
    }

    function renderDashboard(data) {
        if (data.status === "online") {
            ui.globalStatus.textContent = "Sincronizado vía Redis WebSocket";
        }

        // Cargar Motor HFT
        if (data.hft) {
            animateValue(ui.hftExchange, data.hft.exchange);
            animateValue(ui.hftPairs, data.hft.pairs_mode);
            ui.hftStatus.innerHTML = `<i class="fa-solid fa-satellite-dish"></i> ${data.hft.status}`;
        }

        // Cargar Motor P2P
        if (data.p2p) {
            ui.p2pFiat.textContent = data.p2p.fiat;
            animateValue(ui.p2pBuy, data.p2p.maker_buy);
            animateValue(ui.p2pSell, data.p2p.maker_sell);
            animateValue(ui.p2pSpread, data.p2p.spread_neto);
            
            // Si el spread es muy bueno (> 1%), prende las alarmas visuales
            const currentSpread = parseFloat(data.p2p.spread_neto);
            if (currentSpread >= 1.0) {
                ui.p2pSpread.style.textShadow = "0 0 30px rgba(63, 185, 80, 0.9)";
                ui.p2pSpread.style.color = "var(--accent-green)";
            } else {
                ui.p2pSpread.style.textShadow = "0 0 20px rgba(188, 140, 255, 0.8)";
                ui.p2pSpread.style.color = "#fff";
            }
        }

        // Cargar Motor Basis
        if (data.basis) {
            animateValue(ui.basisTarget, data.basis.target);
            ui.basisStatus.innerHTML = `<i class="fa-solid fa-radar"></i> ${data.basis.status}`;
        }
        
        // Renderizar Consola en Vivo
        if (data.logs && Array.isArray(data.logs)) {
            ui.liveLogs.innerHTML = ''; // Limpiar
            let hasLogs = false;
            
            data.logs.forEach(log => {
                if(log && log.msg) {
                    hasLogs = true;
                    const logEl = document.createElement('div');
                    logEl.className = 'log-entry';
                    logEl.innerHTML = `<span style="color:var(--accent-blue)">[${log.engine || 'SYS'}]</span> ${log.msg}`;
                    ui.liveLogs.appendChild(logEl);
                }
            });
            
            if (!hasLogs) {
                ui.liveLogs.innerHTML = '<div class="log-entry" style="color:var(--text-muted)">Esperando señales de la terminal...</div>';
            }
        }
    }
    
    // Función visual de micro-animación para dar vida a los números cambiantes
    function animateValue(domElement, newValue) {
        if (domElement.textContent !== newValue) {
            domElement.style.transition = 'opacity 0.2s';
            domElement.style.opacity = '0';
            
            setTimeout(() => {
                domElement.textContent = newValue;
                domElement.style.opacity = '1';
            }, 200);
        }
    }

    // Iniciar latidos cada 2.5 segundos (Refresco veloz y liviano)
    syncDashboardData();
    setInterval(syncDashboardData, 2500);
});
