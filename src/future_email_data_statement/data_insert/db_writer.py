import traceback

from sqlalchemy import text


class StatementDbWriter:
    """对账单数据入库器：以「文件」为一个事务，逐表先删后插。

    删除键取每张表数据自身的 (tradingday, account_id)，与清洗层输出的
    实际日期保持一致；任一步失败整体回滚，避免半入库。
    """

    def __init__(self, engine, logger):
        self.engine = engine
        self.logger = logger

    def write_file(self, table_frames: dict):
        """将单个文件的 {数据库表名: DataFrame} 写入数据库。

        Args:
            table_frames: {表名: 待入库 DataFrame}；空表会被跳过。

        Returns:
            tuple: (是否成功, 结果信息)。
        """
        inserted = 0
        used_tables = 0
        try:
            # begin() 自动管理事务：任一步异常则整体回滚
            with self.engine.begin() as connection:
                for table_name, df in table_frames.items():
                    if df is None or df.empty:
                        continue
                    used_tables += 1
                    keys = df[["tradingday", "account_id"]].drop_duplicates()
                    for _, row in keys.iterrows():
                        connection.execute(
                            text(
                                f"DELETE FROM {table_name} "
                                f"WHERE tradingday=:tradingday "
                                f"AND account_id=:account_id"
                            ),
                            {
                                "tradingday": row["tradingday"],
                                "account_id": row["account_id"],
                            },
                        )
                    # 表名来自受控映射，非用户输入；默认 executemany 批量写入
                    df.to_sql(
                        table_name,
                        con=connection,
                        if_exists="append",
                        index=False,
                    )
                    inserted += len(df)
                    self.logger.info(f"[{table_name}] 入库 {len(df)} 行")
            return True, f"入库成功: {used_tables} 张表 {inserted} 行"
        except Exception as e:
            self.logger.error(f"入库失败: {e}")
            self.logger.error(traceback.format_exc())
            return False, f"入库失败: {type(e).__name__}: {e}"
