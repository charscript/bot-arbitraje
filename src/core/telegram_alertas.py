"""
Módulo de alertas Telegram.
Envía notificaciones al operador sobre:
  - Oportunidades de arbitraje detectadas
  - Estado del circuit breaker
  - Resumen de P&L (under development)

Configuración necesaria:
  - BOT_TOKEN: Token del bot de Telegram (obtenerlo con @BotFather)
  - CHAT_ID:   ID del chat donde enviar las alertas (obtenerlo con @userinfobot)
"""
import asyncio
import aiohttp
import logging
import os

logger = logging.getLogger('TelegramAlertas')

# ─────────────────────────────────────────────
# CONFIGURACIÓN (cargar desde variables de entorno o .env)
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'TU_TOKEN_AQUI')
CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID',   'TU_CHAT_ID_AQUI')

BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


async def enviar_mensaje(texto: str, parse_mode: str = "Markdown") -> bool:
    """Envía un mensaje al chat de Telegram configurado."""
    if BOT_TOKEN == 'TU_TOKEN_AQUI':
        logger.warning("Token de Telegram no configurado. Mensaje NO enviado.")
        logger.info(f"[ALERTA SIMULADA] {texto}")
        return False

    payload = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": parse_mode
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(BASE_URL, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return True
                else:
                    logger.error(f"Error Telegram API: {resp.status} - {await resp.text()}")
                    return False
    except Exception as e:
        logger.error(f"Excepción enviando mensaje Telegram: {e}")
        return False


def formatear_oportunidad(ciclo: list, resultado_risk: dict) -> str:
    """Formatea un mensaje de alerta de oportunidad de arbitraje."""
    ruta = " ➜ ".join(ciclo)
    return (
        f"🔥 *ARBITRAJE DETECTADO*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 *Ruta:* `{ruta}`\n"
        f"💰 *Capital:* `{resultado_risk.get('capital_usdt', 0)} USDT`\n"
        f"📈 *Spread neto:* `{resultado_risk.get('spread_neto_pct', 0)}%`\n"
        f"💵 *Ganancia estimada:* `{resultado_risk.get('ganancia_estimada_usdt', 0)} USDT`\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


def formatear_circuit_breaker(errores: int, ventana: float) -> str:
    """Formatea un mensaje de alerta de circuit breaker."""
    return (
        f"⚠️ *CIRCUIT BREAKER ACTIVADO*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ `{errores}` errores en `{ventana}s`\n"
        f"🛑 *Motor de ejecución detenido*\n"
        f"Usa /reset para reactivar manualmente\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


# ─────────────────────────────────────────────
# TEST RÁPIDO
# ─────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    async def test():
        ciclo = ['USDT', 'ETH', 'BTC', 'USDT']
        risk_data = {
            'capital_usdt': 450.0,
            'spread_neto_pct': 0.21,
            'ganancia_estimada_usdt': 0.9450,
        }
        msg = formatear_oportunidad(ciclo, risk_data)
        print("Mensaje formateado:")
        print(msg)
        print("\nIntentando envío (fallará si el token no está configurado)...")
        await enviar_mensaje(msg)

    asyncio.run(test())
