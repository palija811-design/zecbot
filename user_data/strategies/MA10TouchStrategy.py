# MA10TouchStrategy.py
# Estrategia de mean reversion: compra en el toque de la MA10
# SOLO si MA10 > MA20 (filtro de tendencia corta alcista).
# Timeframe: 1h | R:R 1:2 | Pensada para ZEC/USDC:USDC en Hyperliquid.
#
# Coloca este archivo en: user_data/strategies/MA10TouchStrategy.py
#
# IMPORTANTE: arranca SIEMPRE en dry-run. No pases a live hasta validar.

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


class MA10TouchStrategy(IStrategy):
    """
    Lógica:
      - Calcula MA5, MA10, MA20 (SMA) igual que las que ves en tu pantalla.
      - ENTRADA (long): el precio retrocede y "toca" la MA10 desde arriba,
        PERO solo se permite si MA10 > MA20 (tendencia corta alcista).
        Esto evita comprar rebotes en caída libre.
      - Filtro extra de tendencia de fondo: precio por encima de la MA20
        en la vela de señal (no compramos por debajo de la estructura).
      - SALIDA: gestionada por ROI (take-profit) y stoploss con R:R 1:2.
        El stop se calcula para dar ~2x de recorrido al objetivo.
    """

    INTERFACE_VERSION = 3

    # --- Ajustes generales ---
    timeframe = "1h"
    can_short = False  # solo largos, como acordamos

    # Solo una operación abierta a la vez en este par (gestión de riesgo).
    # Se controla también desde config.json con max_open_trades.

    # --- Gestión de salida (R:R 1:2) ---
    # stoploss fijo del 4% por debajo de la entrada.
    # ROI a 8% => objetivo el doble que el riesgo (1:2).
    # Nota: en ZEC, con volatilidad alta post-crash, 4% es un stop ajustado;
    # se puede ampliar tras ver el backtest. Lo dejamos parametrizable abajo.
    stoploss = -0.04

    minimal_roi = {
        "0": 0.08,   # objetivo principal: +8% (el doble del stop => R:R 1:2)
    }

    # Trailing desactivado de inicio: con R:R fijo es más limpio para backtest.
    trailing_stop = False

    # Stop en el exchange (Hyperliquid lo soporta vía stop-loss-limit).
    # Esto protege aunque el bot se caiga.
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
    }

    # Hyperliquid no soporta market orders nativas; usamos limit.
    # Damos un pequeño margen para que el limit de entrada se llene.
    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC",
    }

    # Necesitamos suficientes velas para que la MA20 sea válida.
    startup_candle_count: int = 30

    # --- Parámetros ajustables (para optimizar luego con hyperopt) ---
    # "Tocar" la MA10 = el mínimo de la vela se acerca a la MA10 dentro
    # de este margen (en %). 0.3% por defecto.
    touch_margin = IntParameter(1, 10, default=3, space="buy")  # se divide /1000

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Medias simples idénticas a las de tu app (MA5, MA10, MA20).
        dataframe["ma5"] = ta.SMA(dataframe, timeperiod=5)
        dataframe["ma10"] = ta.SMA(dataframe, timeperiod=10)
        dataframe["ma20"] = ta.SMA(dataframe, timeperiod=20)

        # RSI como filtro opcional anti "cuchillo cayendo".
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        margin = self.touch_margin.value / 1000.0  # p.ej. 3 -> 0.003 = 0.3%

        dataframe.loc[
            (
                # 1) Filtro de tendencia corta: MA10 por encima de MA20.
                (dataframe["ma10"] > dataframe["ma20"])
                # 2) Filtro de estructura: precio por encima de la MA20.
                & (dataframe["close"] > dataframe["ma20"])
                # 3) "Toque" de la MA10: el mínimo de la vela se acerca a la
                #    MA10 por arriba (retroceso a la media).
                & (dataframe["low"] <= dataframe["ma10"] * (1 + margin))
                & (dataframe["close"] > dataframe["ma10"] * (1 - margin))
                # 4) Anti caída libre: RSI no en sobreventa extrema.
                &  (dataframe["rsi"] > 35)
                # 5) Volumen presente.
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "toque_ma10_filtro_ma20")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Salidas gestionadas por ROI y stoploss.
        # Salida adicional de seguridad: si MA10 pierde la MA20 (se rompe la
        # tendencia corta), salimos aunque no se haya alcanzado el objetivo.
        dataframe.loc[
            (
                (dataframe["ma10"] < dataframe["ma20"])
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "ruptura_tendencia")

        return dataframe

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        # Apalancamiento conservador 2x tras dry-run (acordado).
        # En dry-run da igual; en live limita el riesgo.
        return 2.0
