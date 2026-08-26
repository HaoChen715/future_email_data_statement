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

    def judge_trading_day(self, date_list: list) -> list:
        """
        验证时间区间内的交易日；单日运行时返回 <= 目标日期的最近一个交易日。
        风格沿用 future_data 项目。

        Args:
            date_list (list): 日期列表，单日 ['yyyy-mm-dd'] 或区间 ['起','止']。

        Returns:
            list: 交易日列表（"yyyy-mm-dd" 格式）。
        """
        try:
            if len(date_list) == 1:
                target_date = pd.Timestamp(date_list[0])
                valid_days = self.market.valid_days(
                    start_date=target_date - pd.Timedelta(days=10),
                    end_date=target_date
                )
                last_trading_day = valid_days[-1].date()  # 最后一个是 <= target_date 的最大交易日
                return [last_trading_day.strftime("%Y-%m-%d")]
            else:
                # 将字符串转换为日期对象
                start_date = pd.to_datetime(date_list[0])
                end_date = pd.to_datetime(date_list[1])
                # 获取市场日历（返回 DataFrame，index 为 DatetimeIndex 交易日）
                schedule: pd.DataFrame = self.market.schedule(
                    start_date=start_date, end_date=end_date
                )

                # 提取交易日列表：遍历 index 得到 Timestamp，直接格式化
                trading_days_list = [
                    day.strftime("%Y-%m-%d")
                    for day in pd.DatetimeIndex(schedule.index)
                ]
                return trading_days_list
        except Exception as e:
            self.logger.error(e)
            self.logger.error("发生异常: %s", traceback.format_exc())
            sys.exit(1)

    def previous_trading_day(self, date: str) -> str:
        """
        获取指定日期的前一个交易日（风格沿用 auto_down_email 项目）。
        用于账号配置视图的有效期过滤（start_date <= 运行日 AND end_date >= 前一个交易日）。

        Args:
            date (str): 目标日期，"yyyymmdd" 格式。

        Returns:
            str: 前一个交易日，"yyyymmdd" 格式。
        """
        try:
            schedule = self.market.schedule(
                start_date=pd.Timestamp(date) - pd.Timedelta(days=10),
                end_date=pd.Timestamp(date),
            )
            # 获取前一个交易日
            previous_trading_day = (
                schedule.index[-2].date() if len(schedule) > 1 else None
            )
            if previous_trading_day is None:
                self.logger.error(
                    f"无法获取 {date} 的前一个交易日（日历数据不足）"
                )
                sys.exit(1)
            last_trading_day = previous_trading_day.strftime("%Y%m%d")
            return last_trading_day
        except Exception as e:
            self.logger.error(e)
            self.logger.error("发生异常: %s", traceback.format_exc())
            sys.exit(1)
