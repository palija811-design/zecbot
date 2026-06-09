    # MA10TouchStrategy.py - VERSION FINAL con fix del 15m
# Marco base 1h + confirmacion multimarco 15m y 4h. Solo largos.
# El 15m se fusiona manualmente (no con merge_informative_pair) porque es
# mas rapido que el marco base y merge_informative_pair lo rechaza.

from datetime import datetime
from typing import Optional
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter, merge_informative_pair


class MA10TouchStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    stoploss = -0.05
    minimal_roi = {"0": 0.05, "120": 0.03, "360": 0.015, "720": 0.0}
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    startup_candle_count: int = 100
    touch_margin = IntParameter(1, 10, default=3, space="buy")
    informative_timeframe_15m = "15m"
    informative_timeframe_4h = "4h"

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        inf = [(p, self.informative_timeframe_15m) for p in pairs]
        inf += [(p, self.informative_timeframe_4h) for p in pairs]
        return inf

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ma5"] = ta.SMA(dataframe, timeperiod=5)
        dataframe["ma10"] = ta.SMA(dataframe, timeperiod=10)
        dataframe["ma20"] = ta.SMA(dataframe, timeperiod=20)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # 4h (mas lento que 1h): merge_informative_pair OK.
        inf_4h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.informative_timeframe_4h)
        inf_4h["ma10"] = ta.SMA(inf_4h, timeperiod=10)
        inf_4h["ma20"] = ta.SMA(inf_4h, timeperiod=20)
        dataframe = merge_informative_pair(dataframe, inf_4h, self.timeframe, self.informative_timeframe_4h, ffill=True)

        # 15m (mas rapido que 1h): merge MANUAL para evitar el error.
        inf_15m = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=self.informative_timeframe_15m)
        inf_15m["ma10_15m"] = ta.SMA(inf_15m, timeperiod=10)
        inf_15m["ma20_15m"] = ta.SMA(inf_15m, timeperiod=20)
        inf_15m["close_15m"] = inf_15m["close"]
        inf_15m_small = inf_15m[["date", "ma10_15m", "ma20_15m", "close_15m"]].copy()
        dataframe = dataframe.merge(inf_15m_small, on="date", how="left")
        dataframe[["ma10_15m", "ma20_15m", "close_15m"]] = dataframe[["ma10_15m", "ma20_15m", "close_15m"]].ffill()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        margin = self.touch_margin.value / 1000.0
        dataframe.loc[
            (
                (dataframe["ma10"] > dataframe["ma20"])
                & (dataframe["close"] > dataframe["ma20"])
                & (dataframe["low"] <= dataframe["ma10"] * (1 + margin))
                & (dataframe["close"] > dataframe["ma10"] * (1 - margin))
                & (dataframe["rsi"] > 35)
                & (dataframe["ma10_4h"] > dataframe["ma20_4h"])
                & (dataframe["ma10_15m"] > dataframe["ma20_15m"])
                & (dataframe["close_15m"] > dataframe["ma10_15m"])
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "toque_ma10_multimarco")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            ((dataframe["ma10"] < dataframe["ma20"]) & (dataframe["volume"] > 0)),
            ["exit_long", "exit_tag"],
        ] = (1, "ruptura_tendencia")
        return dataframe

    def leverage(self, pair, current_time, current_rate, proposed_leverage, max_leverage, entry_tag, side, **kwargs) -> float:
        return 2.0
