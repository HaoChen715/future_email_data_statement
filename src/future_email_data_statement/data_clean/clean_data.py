import os
import traceback
from datetime import datetime

from src.future_email_data_statement.common.get_parent_path import ParentPath
from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.data_clean.datastatement import DataStatement


class CleanDataFile:
    """对账单数据清洗步骤入口（clean_data 步骤）。

    遍历 resource_root 下各券商目录的当日对账单文件，按券商调度对应清洗类，
    将每个文件独立读取、清洗为多个内置 DataFrame（不动原始文件），
    以 {文件名: data_frames_json} 结构返回，供后续按数据库字段做列名转换。
    """

    def __init__(self, running_day: str, statement_type: str = "Trade"):
        self.running_day = running_day
        parent_path = ParentPath()
        self.current_dir = parent_path.get_current_dir()
        global_func = GlobalFunc(statement_type=statement_type)
        self.resource_root = global_func.get_file_path("resource_root")
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=(
                f"{self.current_dir}/logs/"
                f"{datetime.now().strftime('%Y%m%d')}.log"
            ),
            logger_name="future_data_clean",
        )

    def clean(self) -> dict:
        """执行数据清洗主流程：按券商扫描当日目录，逐文件清洗。

        Returns:
            dict: {券商中文名: {文件名: data_frames_json}}。
        """
        self.logger.info(f"数据清洗步骤开始, 交易日: {self.running_day}")
        if not os.path.isdir(self.resource_root):
            raise RuntimeError(f"资源目录不存在: {self.resource_root}")

        all_results = {}
        for broker in sorted(os.listdir(self.resource_root)):
            day_dir = os.path.join(self.resource_root, broker, self.running_day)
            if not os.path.isdir(day_dir):
                continue
            files = [
                f for f in os.listdir(day_dir) if f.lower().endswith(".txt")
            ]
            if not files:
                self.logger.warning(
                    f"券商: {broker} 交易日 {self.running_day} 目录无对账单文件"
                )
                continue

            try:
                data_statement = DataStatement(
                    broker=broker,
                    statement_day=self.running_day,
                    resource_data_path=day_dir,
                )
                statement_object = data_statement.statement()
                if statement_object is None:
                    continue
                results = statement_object.main()
                if results:
                    all_results[broker] = results
            except Exception as e:
                self.logger.error(f"券商: {broker} 数据清洗失败: {e}")
                self.logger.error(traceback.format_exc())

        broker_count = len(all_results)
        file_count = sum(len(files) for files in all_results.values())
        if broker_count == 0:
            self.logger.warning(
                f"交易日 {self.running_day} 未清洗任何券商对账单数据"
            )
        self.logger.info(
            f"数据清洗步骤结束, 共清洗 {broker_count} 家券商 {file_count} 个文件"
        )
        return all_results
