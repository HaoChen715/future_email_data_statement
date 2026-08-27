import logging
import sys
import traceback
import pandas as pd
import pandas_market_calendars as mcal


class CheckTradingDay:
    def __init__(self):
        """
        params:
        self.market: 交易日历市场,此处选择中国沪市交易日历
        """
        self.market = mcal.get_calendar("SSE")
        self.logger = self.init_log()

    def init_log(self) -> logging.Logger:
        return logging.getLogger("CheckTradingDay")

    def previous_trading_day(self, date: str) -> str:
        """
        获取指定日期（含非交易日）的前一个交易日（逻辑沿用 auto_down_email 项目）。

        Args:
            date (str): 目标日期，"yyyymmdd" 格式。

        Returns:
            str: 前一个交易日，"yyyymmdd" 格式。
        """
        try:
            valid_days = self.market.valid_days(
                start_date=pd.Timestamp(date) - pd.Timedelta(days=10),
                end_date=pd.Timestamp(date) - pd.Timedelta(days=1),
            )
            previous_trading_day = (
                valid_days[-1].date() if len(valid_days) > 0 else None
            )
            if previous_trading_day is None:
                self.logger.error(
                    f"无法获取 {date} 的前一个交易日（日历数据不足）"
                )
                sys.exit(1)
            return previous_trading_day.strftime("%Y%m%d")
        except Exception as e:
            self.logger.error(e)
            self.logger.error("发生异常: %s", traceback.format_exc())
            sys.exit(1)
