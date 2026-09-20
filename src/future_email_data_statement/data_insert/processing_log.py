from datetime import datetime

from sqlalchemy import text


class ProcessingLog:
    """对账单入库处理日志（bill_future_settle_processing_log）。

    每处理一个账号写一行状态（Success / Failed），并在重跑时查询当日已成功
    账号用于断点续跑。同一 (tradingday, account_id, log_type) 先删后插，
    保证只保留最新状态。
    """

    TABLE = "bill_future_settle_processing_log"
    LOG_TYPE = "对账单数据"
    ACCOUNT_TYPE = "期货"

    def __init__(self, engine):
        self.engine = engine

    def delete_failed(self, tradingday: str) -> int:
        """清理指定交易日的失败日志（用于失败账号重新入库）。

        Args:
            tradingday: 交易日（YYYYMMDD）。

        Returns:
            int: 删除的记录数。
        """
        sql = text(
            f"DELETE FROM {self.TABLE} "
            f"WHERE tradingday=:tradingday "
            f"AND account_type=:account_type "
            f"AND log_type=:log_type "
            f"AND log_status='Failed'"
        )
        params = {
            "tradingday": tradingday,
            "account_type": self.ACCOUNT_TYPE,
            "log_type": self.LOG_TYPE,
        }
        with self.engine.begin() as connection:
            result = connection.execute(sql, params)
        return result.rowcount if result.rowcount and result.rowcount > 0 else 0

    def success_accounts(self, tradingday: str) -> set:
        """查询指定交易日已成功入库的账号集合（断点续跑用）。

        Args:
            tradingday: 交易日（YYYYMMDD）。

        Returns:
            set: 已成功入库的 account_id 集合。
        """
        sql = text(
            f"SELECT DISTINCT account_id FROM {self.TABLE} "
            f"WHERE tradingday=:tradingday "
            f"AND account_type=:account_type "
            f"AND log_type=:log_type "
            f"AND log_status='Success'"
        )
        params = {
            "tradingday": tradingday,
            "account_type": self.ACCOUNT_TYPE,
            "log_type": self.LOG_TYPE,
        }
        with self.engine.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return {str(row[0]) for row in rows}

    def write(
        self, tradingday: str, account_id: str, status: str, info: str
    ) -> None:
        """写入（或覆盖）一个账号的入库状态。

        Args:
            tradingday: 交易日（YYYYMMDD）。
            account_id: 资金账号。
            status: Success / Failed。
            info: 成功信息或失败原因。
        """
        now = datetime.now()
        delete_sql = text(
            f"DELETE FROM {self.TABLE} "
            f"WHERE tradingday=:tradingday AND account_id=:account_id "
            f"AND log_type=:log_type"
        )
        insert_sql = text(
            f"INSERT INTO {self.TABLE} "
            f"(tradingday, account_id, account_type, log_type, "
            f" log_time, log_date, log_status, log_info) "
            f"VALUES (:tradingday, :account_id, :account_type, :log_type, "
            f" :log_time, :log_date, :log_status, :log_info)"
        )
        params = {
            "tradingday": tradingday,
            "account_id": account_id,
            "log_type": self.LOG_TYPE,
        }
        with self.engine.begin() as connection:
            connection.execute(delete_sql, params)
            connection.execute(
                insert_sql,
                {
                    **params,
                    "account_type": self.ACCOUNT_TYPE,
                    "log_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "log_date": now.strftime("%Y%m%d"),
                    "log_status": status,
                    "log_info": info,
                },
            )
