# MA10TouchStrategy.py
# Estrategia de mean reversion: compra en el toque de la MA10
# SOLO si MA10 > MA20 (filtro de tendencia corta alcista).
# Timeframe base: 1h | Solo LARGOS | ZEC/USDC:USDC en Hyperliquid.
#
# FILTRO MULTI-MARCO (v3) — la mejora clave:
#   El bot ya no mira solo 1h. Antes de entrar confirma:
#     - 4h  : sesgo mayor alcista (MA10_4h > MA20_4h). No comprar contra el marco grande.
#     - 15m : el corto NO debe estar girado abajo (evita comprar cuchillos cayendo).
#   Esto habria evitado la operacion perdedora #2 (entro en 458 mientras 15m
#   ya caia desde 474.95 con las medias giradas a la baja).
#
# SALIDA COMBINADA (v2):
#   - ROI escalonado por TIEMPO + TRAILING STOP + STOP-LOSS -5%.
#   NOTA: todos los % son de PRECIO. Con leverage 2x, el efecto sobre tu margen
#   es ~el doble (5% precio ≈ 10% margen).
#
# Coloca este archivo en: user_data/strategies/MA10TouchStrategy.py
#
# IMPORTANTE: arranca SIEMPRE en dry-run. No pases a live hasta validar.

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter, merge_informative_pair


class MA10TouchStrategy(IStrategy):
    """
    Lógica:
      - Marco BASE 1h: calcula MA5, MA10, MA20 (SMA) como las de tu app.
      - CONFIRMACION MULTI-MARCO antes de entrar:
          * 4h: MA10 > MA20 (sesgo mayor alcista).
          * 15m: MA10 > MA20 (el corto no esta girado abajo) Y precio sobre MA10_15m.
      - ENTRADA (long): toque de MA10 en 1h con MA10>MA20 y precio sobre MA20,
        RSI>35, Y ADEMAS las confirmaciones de 4h y 15m anteriores.
      - SALIDA COMBINADA: ROI por tiempo + trailing stop + stop -5% +
        salida de seguridad si MA10 pierde MA20 en 1h.
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

    # Necesitamos suficientes velas para que las MA20 sean válidas en TODOS
    # los marcos. La MA20 de 4h es la mas exigente: 20 velas de 4h = 80h = 80
    # velas de 1h. Ponemos margen de sobra.
    startup_candle_count: int = 100

    # --- Parámetros ajustables (para optimizar luego con hyperopt) ---
    # "Tocar" la MA10 = el mínimo de la vela se acerca a la MA10 dentro
    # de este margen (en %). 0.3% por defecto.
    touch_margin = IntParameter(1, 10, default=3, space="buy")  # se divide /1000

    # --- Marcos temporales de confirmacion (multi-marco) ---
    # El marco base es 1h (timeframe). Estos son los marcos extra que el bot
    # carga para confirmar la direccion antes de entrar.
    informative_timeframe_15m = "15m"
    informative_timeframe_4h = "4h"

    def informative_pairs(self):
        # Le decimos a Freqtrade que ademas del 1h cargue 15m y 4h del mismo par.
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative_timeframe_15m) for pair in pairs]
        informative_pairs += [(pair, self.informative_timeframe_4h) for pair in pairs]
        return informative_pairs

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ----- Marco base (1h) -----
        # Medias simples idénticas a las de tu app (MA5, MA10, MA20).
        dataframe["ma5"] = ta.SMA(dataframe, timeperiod=5)
        dataframe["ma10"] = ta.SMA(dataframe, timeperiod=10)
        dataframe["ma20"] = ta.SMA(dataframe, timeperiod=20)
        # RSI como filtro anti "cuchillo cayendo".
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # ----- Marco 4h (sesgo mayor) -----
        inf_4h = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe_4h
        )
        inf_4h["ma10"] = ta.SMA(inf_4h, timeperiod=10)
        inf_4h["ma20"] = ta.SMA(inf_4h, timeperiod=20)
        # Fusiona el 4h en el dataframe de 1h (columnas con sufijo _4h).
        dataframe = merge_informative_pair(
            dataframe, inf_4h, self.timeframe, self.informative_timeframe_4h, ffill=True
        )

        # ----- Marco 15m (confirmacion de corto plazo) -----
        inf_15m = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe_15m
        )
        inf_15m["ma10"] = ta.SMA(inf_15m, timeperiod=10)
        inf_15m["ma20"] = ta.SMA(inf_15m, timeperiod=20)
        # Fusiona el 15m en el dataframe de 1h (columnas con sufijo _15m).
        dataframe = merge_informative_pair(
            dataframe, inf_15m, self.timeframe, self.informative_timeframe_15m, ffill=True
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        margin = self.touch_margin.value / 1000.0  # p.ej. 3 -> 0.003 = 0.3%

        dataframe.loc[
            (
                # ===== Señal base en 1h =====
                # 1) Tendencia corta 1h: MA10 por encima de MA20.
                (dataframe["ma10"] > dataframe["ma20"])
                # 2) Estructura 1h: precio por encima de la MA20.
                & (dataframe["close"] > dataframe["ma20"])
                # 3) "Toque" de la MA10 en 1h (retroceso a la media).
                & (dataframe["low"] <= dataframe["ma10"] * (1 + margin))
                & (dataframe["close"] > dataframe["ma10"] * (1 - margin))
                # 4) Anti caída libre: RSI no en sobreventa extrema.
                & (dataframe["rsi"] > 35)

                # ===== Confirmacion 4h (sesgo mayor alcista) =====
                # No comprar contra el marco grande.
                & (dataframe["ma10_4h"] > dataframe["ma20_4h"])

                # ===== Confirmacion 15m (el corto NO esta girado abajo) =====
                # Esto es lo que habria evitado la operacion perdedora #2:
                # exige que en 15m las medias sigan alcistas y el precio sobre MA10.
                & (dataframe["ma10_15m"] > dataframe["ma20_15m"])
                & (dataframe["close_15m"] > dataframe["ma10_15m"])

                # 5) Volumen presente.
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "toque_ma10_multimarco")

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
