 MA10TouchStrategy.py
# Estrategia de mean reversion: compra en el toque de la MA10
# SOLO si MA10 > MA20 (filtro de tendencia corta alcista).
# Timeframe: 1h | Solo LARGOS | Pensada para ZEC/USDC:USDC en Hyperliquid.
#
# SALIDA COMBINADA (v2):
#   - ROI escalonado por TIEMPO: objetivo que baja cuanto mas dura la operacion.
#   - TRAILING STOP: persigue al precio en subidas fuertes para dejar correr ganancia.
#   - STOP-LOSS ampliado a -5% (antes -4%, saltaba por ruido en ZEC).
#   NOTA: todos los % son de PRECIO. Con leverage 2x, la ganancia/perdida sobre
#   tu margen es ~el doble (5% precio ≈ 10% margen).
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
      - SALIDA COMBINADA:
          * ROI por tiempo: 5% inmediato, 3% a 2h, 1.5% a 6h, 0% a 12h.
          * Trailing stop: se activa en +2.5%, cierra si retrocede 1.5%.
          * Stop-loss: -5%.
          * Salida de seguridad: si MA10 pierde MA20 (rompe tendencia).
        Gana el mecanismo que se dispare primero.
    """

    INTERFACE_VERSION = 3

    # --- Ajustes generales ---
    timeframe = "1h"
    can_short = False  # solo largos, como acordamos

    # Solo una operación abierta a la vez en este par (gestión de riesgo).
    # Se controla también desde config.json con max_open_trades.

    # --- Gestión de salida combinada ---
    # Todos los % son de PRECIO. Con leverage 2x, el efecto sobre tu margen
    # es aproximadamente el doble.

    # STOP-LOSS: ampliado a -5% (antes -4%). En ZEC el -4% estaba a tiro del
    # ruido normal; -5% da algo mas de aire. A 2x son ~-10% de margen, muy
    # lejos aun de la liquidacion.
    stoploss = -0.05

    # ROI ESCALONADO POR TIEMPO (clave = minutos desde la apertura):
    #   0 min  -> 5%   objetivo inicial (a 2x ≈ 10% de margen).
    #   120min -> 3%   si en 2h no llego, se conforma con 3%.
    #   360min -> 1.5% si se alarga, recoge algo.
    #   720min -> 0%   a las 12h sale en break-even o mejor, libera capital.
    minimal_roi = {
        "0": 0.05,
        "120": 0.03,
        "360": 0.015,
        "720": 0.0,
    }

    # TRAILING STOP: deja correr las subidas fuertes de ZEC.
    #   - No se activa hasta tener +2.5% de ganancia (trailing_only_offset_is_reached).
    #   - A partir de ahi, cierra si el precio retrocede 1.5% desde el maximo.
    trailing_stop = True
    trailing_stop_positive = 0.015          # retroceso del 1.5% cierra
    trailing_stop_positive_offset = 0.025   # se activa al +2.5%
    trailing_only_offset_is_reached = True  # no trailing antes del offset

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
