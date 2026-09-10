import json
import os

import pandas as pd
from sqlalchemy import text

from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.config.globalfunc import GlobalFunc


class BrokerInit:
    """券商目录初始化（思路沿用 auto_down_email_clean_to_statement 项目 broker_init.py）。

    项目启动时按数据库视图 v_config_bill_future_account 中的券商列表，
    在资源目录下预建 {resource_root}/{broker} 目录，并记录到环境专属的
    config/datapath_init_{Place}.json，避免运行期因目录缺失而中断。
    """

    def __init__(self, init_date: str, statement_type: str = "Trade"):
        global_func = GlobalFunc(statement_type=statement_type)
        self.current_dir = global_func.get_parent_path()
        self.init_date = init_date
        self.statement_type = statement_type
        self.resource_root = global_func.get_file_path("resource_root")
        self.engine, _ = global_func.connect_database()
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.init_date}.log",
            logger_name="broker_init_logger",
        )
        # 环境专属的券商目录初始化记录文件（测试/生产各自维护，互不覆盖）
        self.datapath_init_path = os.path.join(
            self.current_dir,
            "config",
            f"datapath_init_{self.statement_type}.json",
        )

    def _load_datapath_init(self) -> dict:
        """读取券商目录初始化记录；文件不存在或为空时返回空记录。"""
        if not os.path.exists(self.datapath_init_path):
            self.logger.warning(
                f"检测到不存在券商目录初始化记录文件，开始创建: {self.datapath_init_path}"
            )
            return {"Path": []}
        with open(self.datapath_init_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return {"Path": []} if not content else json.loads(content)

    def broker_init(self):
        """按数据库券商列表预建资源目录，并将新增券商目录写入初始化记录文件。"""
        select_sql = text("SELECT DISTINCT broker FROM v_config_bill_future_account")
        with self.engine.connect() as connection:
            result = connection.execute(select_sql)
            broker_df = pd.DataFrame(
                result.fetchall(), columns=result.keys()
            )
        broker_list = (
            broker_df["broker"].dropna().astype(str).unique().tolist()
        )
        self.logger.info(f"当前券商列表: {broker_list}")

        datapath_init = self._load_datapath_init()
        for broker in broker_list:
            broker_dir = os.path.join(self.resource_root, broker)
            if not os.path.exists(broker_dir):
                os.makedirs(broker_dir, exist_ok=True)
                datapath_init["Path"].append({broker: broker_dir})
                self.logger.info(f"检测到新增券商: {broker}，目录 {broker_dir} 新建完成")
            else:
                self.logger.info(f"券商目录已存在: {broker_dir}")

        with open(self.datapath_init_path, "w", encoding="utf-8") as file:
            json.dump(datapath_init, file, ensure_ascii=False, indent=4)
        self.logger.info(
            f"券商目录初始化完成，记录文件: {self.datapath_init_path}"
        )
        return self.datapath_init_path