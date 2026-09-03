import importlib
from typing import Optional

from src.future_email_data_statement.data_clean.tools.statement import Statement


class DataStatement(Statement):
    """对账单数据清洗统一调度类（风格沿用 auto_down_email 项目的 DataStatement）。

    根据券商中文名（broker）动态加载对应的券商清洗类，
    并调用其 main() 方法将目录下对账单文件清洗为多个 DataFrame。
    """

    # 券商中文名 -> (模块文件名, 类名) 映射
    BROKER_IMPORT_MAP = {
        "国君": ("guojun", "GuoJun"),
    }

    def __init__(
        self,
        broker: str,
        statement_day: str,
        resource_data_path: str,
    ):
        """初始化清洗调度器。

        Args:
            broker: 券商中文名，用于选择对应的券商清洗类。
            statement_day: 对账单交易日（YYYYMMDD）。
            resource_data_path: 券商对账单文件目录。
        """
        super().__init__(
            statement_day=statement_day,
            resource_data_path=resource_data_path,
        )
        self.broker = broker
        self.statement_object: Optional["Statement"] = None

    def _load_broker_class(self, broker: str):
        """根据券商中文名动态导入对应的券商清洗类。

        Returns:
            券商清洗类；券商不支持或导入失败时返回 None。
        """
        if broker not in self.BROKER_IMPORT_MAP:
            return None

        module_name, class_name = self.BROKER_IMPORT_MAP[broker]
        full_module = f"src.future_email_data_statement.data_clean.tools.{module_name}"

        try:
            module = importlib.import_module(full_module)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            self.logger.error(f"导入券商清洗类失败: {broker}, {e}")
            return None

    def statement(self):
        """加载对应券商清洗类实例。

        Returns:
            券商清洗类实例；券商不支持或导入失败时返回 None。
        """
        broker_class = self._load_broker_class(self.broker)
        if not broker_class:
            self.logger.warning(f"程序暂未支持券商: {self.broker}")
            return None

        statement_object = broker_class(
            self.statement_day,
            self.resource_data_path,
        )
        self.logger.info(f"当前清洗券商: {self.broker}")
        return statement_object
