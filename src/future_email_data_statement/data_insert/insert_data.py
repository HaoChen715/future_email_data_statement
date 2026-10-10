import os
import traceback

from src.future_email_data_statement.common.get_parent_path import ParentPath
from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.data_clean.clean_data import CleanDataFile
from src.future_email_data_statement.data_insert.api_client import (
    BillFutureApiClient,
)
from src.future_email_data_statement.data_insert.mapping import (
    TEMPLATE_MAP,
    build_table_frames,
)


class InsertDataFile:
    """对账单数据清洗入库步骤（insert_data）。

    复用 CleanDataFile 完成清洗后，按券商模板将各板块映射为数据库表，再以
    「文件」为单位调用 Open API 整文件全量覆盖入库（服务端单事务先删后插）；
    处理日志由服务端同步维护，重跑时通过接口查询当日已成功账号跳过。
    """

    def __init__(
        self,
        running_day: str,
        statement_type: str = "Trade",
        broker: str = None,
        force: bool = None,
    ):
        """初始化入库入口。

        Args:
            running_day: 对账单交易日（YYYYMMDD）。
            statement_type: 运行环境，Trade=生产 / Test=测试。
            broker: 可选，指定仅入库该券商目录；None 表示全部。
            force: 是否强制重新入库。None 时读取 config/info.ini
                [RunParams] Force_redownload；True 时忽略已成功日志全部重跑。
        """
        global_func = GlobalFunc(statement_type=statement_type)
        self.resource_root = global_func.get_file_path("resource_root")
        parent_path = ParentPath()
        self.current_dir = parent_path.get_current_dir()
        self.running_day = running_day
        self.statement_type = statement_type
        self.broker = broker
        # Force_redownload=True 时忽略成功日志，实现"删除重新入库"
        if force is None:
            force = global_func.config.getboolean(
                "RunParams", "Force_redownload", fallback=False
            )
        self.force = bool(force)
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="future_data_insert",
        )
        self.api = BillFutureApiClient(
            logger=self.logger, **global_func.get_api_config()
        )

    def run(self) -> dict:
        """执行清洗 + 入库主流程。

        Returns:
            dict: 统计信息 {brokers/files/inserted/skipped/failed}。
        """
        self.logger.info(
            f"数据入库步骤开始, 交易日: {self.running_day}, "
            f"指定券商: {self.broker or '全部'}"
        )

        # 1. 清洗（复用 clean_data，得到 {券商: {文件名: {板块: DataFrame}}}）
        try:
            clean_results = CleanDataFile(
                running_day=self.running_day,
                statement_type=self.statement_type,
            ).clean()
        except Exception as e:
            self.logger.error(f"清洗失败: {e}")
            self.logger.error(traceback.format_exc())
            raise

        # 指定券商时仅保留该券商目录结果（与 clean_data 过滤口径一致）
        if self.broker:
            clean_results = {
                name: files
                for name, files in clean_results.items()
                if name == self.broker
            }
            if not clean_results:
                # 列出当日实际有数据的券商目录，便于核对券商名是否写错
                available = []
                if os.path.isdir(self.resource_root):
                    available = sorted(
                        name
                        for name in os.listdir(self.resource_root)
                        if os.path.isdir(
                            os.path.join(
                                self.resource_root, name, self.running_day
                            )
                        )
                    )
                self.logger.warning(
                    f"指定券商 {self.broker} 当日无可入库的已匹配文件; "
                    f"当日存在数据的券商目录: {available or '无'}"
                )

        # 2. 断点续跑：通过接口查询当日已成功账号，重跑时跳过；
        #    force 时忽略日志全部重新入库（失败的账号不在成功集合中，会自然重试）
        if self.force:
            self.logger.warning(
                "Force_redownload=True，启用强制重新入库模式："
                "忽略已成功日志，相关账号全部重新解析入库"
            )
            done_accounts = set()
        else:
            done_accounts = self.api.query_insert_success_account_list(
                self.running_day
            )
            if done_accounts:
                self.logger.info(
                    f"当日已成功入库账号 {len(done_accounts)} 个, 重跑时自动跳过"
                )

        stats = {
            "brokers": 0,
            "files": 0,
            "inserted": 0,
            "skipped": 0,
            "failed": 0,
        }
        for broker, files in clean_results.items():
            template = TEMPLATE_MAP.get(broker)
            if template is None:
                self.logger.warning(f"暂不支持券商入库: {broker}, 跳过")
                continue
            stats["brokers"] += 1
            for filename, frames in files.items():
                stats["files"] += 1
                basic = frames.get("基本资料")
                if basic is None or basic.empty:
                    self.logger.warning(f"文件 {filename} 缺少基本资料, 跳过")
                    stats["skipped"] += 1
                    continue
                account_id = str(basic.iloc[0]["account_id"])
                trading_day = str(basic.iloc[0]["trading_day"])

                if account_id in done_accounts:
                    self.logger.info(
                        f"账号 {account_id} 当日已成功入库, 跳过文件 {filename}"
                    )
                    stats["skipped"] += 1
                    continue

                table_frames = build_table_frames(
                    template=template, broker=broker, frames=frames
                )
                if not table_frames:
                    self.logger.warning(
                        f"文件 {filename} 无可入库数据, 跳过"
                    )
                    stats["skipped"] += 1
                    continue

                # 整文件通过 API 全量覆盖入库（服务端单事务先删后插并写处理日志）
                ok, info = self.api.settlement_file_insert(
                    tradingday=trading_day,
                    account_id=account_id,
                    table_frames=table_frames,
                )
                if ok:
                    stats["inserted"] += 1
                    self.logger.info(
                        f"文件 {filename} 券商 {broker} 账号 {account_id} {info}"
                    )
                else:
                    stats["failed"] += 1
                    self.logger.error(
                        f"文件 {filename} 券商 {broker} 账号 {account_id} {info}"
                    )

        self.logger.info(
            f"数据入库步骤结束: 券商 {stats['brokers']} 家, 文件 {stats['files']} 个, "
            f"成功 {stats['inserted']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}"
        )
        return stats
