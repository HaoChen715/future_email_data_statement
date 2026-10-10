import json
import os

from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.data_insert.api_client import (
    BillFutureApiClient,
)


class BrokerInit:
    """券商目录初始化（思路沿用 auto_down_email_clean_to_statement 项目 broker_init.py）。

    项目启动时通过 Open API queryBrokerInit 获取券商列表，在资源目录下预建
    {resource_root}/{broker} 目录，并记录到环境专属的
    config/datapath_init_{Place}.json，避免运行期因目录缺失而中断。
    """

    def __init__(self, init_date: str, statement_type: str = "Trade"):
        global_func = GlobalFunc(statement_type=statement_type)
        self.current_dir = global_func.get_parent_path()
        self.init_date = init_date
        self.statement_type = statement_type
        self.resource_root = global_func.get_file_path("resource_root")
        # 券商白名单: 仅白名单内券商视为已注册券商(用于建目录) 空集合表示不限制
        self.broker_whitelist = global_func.get_broker_whitelist()
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.init_date}.log",
            logger_name="broker_init_logger",
        )
        self.api = BillFutureApiClient(
            logger=self.logger, **global_func.get_api_config()
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

    def _filter_brokers(self, all_brokers: list) -> list:
        """按券商白名单过滤接口返回的券商列表。

        Args:
            all_brokers: 接口 queryBrokerInit 返回的全部券商。

        Returns:
            list: 白名单内的券商；白名单为空时返回全部券商。
        """
        if not self.broker_whitelist:
            self.logger.info("未配置券商白名单, 全部券商视为已注册券商")
            return list(all_brokers)
        kept = [broker for broker in all_brokers if broker in self.broker_whitelist]
        dropped = [
            broker for broker in all_brokers if broker not in self.broker_whitelist
        ]
        missing = [
            broker for broker in self.broker_whitelist if broker not in all_brokers
        ]
        self.logger.info(
            f"券商白名单过滤: 白名单 {sorted(self.broker_whitelist)} | "
            f"保留 {len(kept)} 个 {kept} | 过滤掉 {len(dropped)} 个 {dropped}"
        )
        if missing:
            self.logger.warning(f"白名单中未在接口返回的券商: {missing}")
        return kept

    def broker_init(self):
        """按 API 券商列表（白名单过滤后）预建资源目录，并写入初始化记录文件。"""
        all_brokers = self.api.query_broker_init()
        self.logger.info(f"接口返回券商列表: {all_brokers}")
        broker_list = self._filter_brokers(all_brokers)

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
