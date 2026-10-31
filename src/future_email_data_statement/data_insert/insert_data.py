import os
import re
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
        # 券商白名单: 统计“未检测到文件账号”时与账号匹配口径保持一致
        self.broker_whitelist = global_func.get_broker_whitelist()
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

    def _query_expected_accounts(self, tradingday: str) -> dict:
        """查询指定交易日有效账号（经券商白名单 / 指定券商 / 销户过滤）。

        Args:
            tradingday: 报文内的真实交易日（YYYYMMDD）。

        Returns:
            dict: {资金账号: 账号明细文本}；查询失败时返回空字典。
        """
        try:
            accounts = self.api.query_account_list(tradingday)
        except Exception as e:
            self.logger.warning(
                f"查询交易日 {tradingday} 有效账号失败, "
                f"无法统计未检测到文件的账号: {type(e).__name__}: {e}"
            )
            return {}

        expected = {}
        for account in accounts:
            broker_id = account.get("brokerId")
            broker_name = "" if broker_id is None else str(broker_id).strip()
            if self.broker_whitelist and broker_name not in self.broker_whitelist:
                continue
            if self.broker and broker_name != self.broker:
                continue
            if "销户" in str(account.get("remark") or ""):
                continue
            account_id = str(account.get("futureAccountId"))
            expected[account_id] = (
                f"{account_id}(券商={broker_id!r}, "
                f"类型={account.get('accountType')!r}, "
                f"有效期={account.get('startDate')}~{account.get('endDate')}, "
                f"备注={account.get('remark')!r})"
            )
        return expected

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

        # 2. 断点续跑：按报文内真实交易日查询已成功账号（懒加载并缓存），
        #    force 时忽略日志全部重新入库（失败账号不在成功集合中，会自然重试）
        if self.force:
            self.logger.warning(
                "Force_redownload=True，启用强制重新入库模式："
                "忽略已成功日志，相关账号全部重新解析入库"
            )
        success_cache = {}

        def success_accounts(tradingday: str) -> set:
            if self.force:
                return set()
            if tradingday not in success_cache:
                success_cache[tradingday] = (
                    self.api.query_insert_success_account_list(tradingday)
                )
                if success_cache[tradingday]:
                    self.logger.info(
                        f"交易日 {tradingday} 已成功入库账号 "
                        f"{len(success_cache[tradingday])} 个, 重跑时自动跳过"
                    )
            return success_cache[tradingday]

        stats = {
            "brokers": 0,
            "files": 0,
            "inserted": 0,
            "skipped": 0,
            "failed": 0,
        }
        # 本次明细统计（均以报文真实交易日分组）
        seen_by_day = {}
        inserted_by_day = {}
        skipped_reasons = {}
        failed_reasons = {}
        unparsed_files = []

        if not self.api.log_path:
            self.logger.warning(
                "未配置写处理日志接口 log_path, 将不写 对账单文件/对账单数据 "
                "的自定义日志; 开发新增接口后在 config/info.ini 对应环境段填写"
            )
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
                    unparsed_files.append(filename)
                    self.logger.warning(
                        f"文件 {filename} 缺少基本资料, 跳过"
                        f"（未调用入库接口, 不产生处理日志）"
                    )
                    stats["skipped"] += 1
                    continue
                account_id = str(basic.iloc[0]["account_id"])
                trading_day = str(basic.iloc[0]["trading_day"]).strip()
                # 一律以报文内真实交易日为准；无法解析时退回运行日并告警
                if not re.fullmatch(r"\d{8}", trading_day):
                    self.logger.warning(
                        f"文件 {filename} 未解析到有效交易日"
                        f"({trading_day!r}), 退回使用运行日 {self.running_day}"
                    )
                    trading_day = self.running_day
                seen_by_day.setdefault(trading_day, set()).add(account_id)

                if account_id in success_accounts(trading_day):
                    skipped_reasons[(trading_day, account_id)] = (
                        f"该交易日已成功入库, 跳过文件 {filename}"
                    )
                    self.logger.info(
                        f"账号 {account_id} 交易日 {trading_day} "
                        f"已成功入库, 跳过文件 {filename}"
                    )
                    stats["skipped"] += 1
                    continue

                table_frames = build_table_frames(
                    template=template, broker=broker, frames=frames
                )
                if not table_frames:
                    skipped_reasons[(trading_day, account_id)] = (
                        f"无可入库数据, 跳过文件 {filename}"
                    )
                    self.logger.warning(
                        f"文件 {filename} 账号 {account_id} 无可入库数据, "
                        f"跳过（未调用入库接口, 不产生处理日志）"
                    )
                    stats["skipped"] += 1
                    continue

                # 整文件通过 API 全量覆盖入库（服务端单事务先删后插并写处理日志）
                self.logger.info(
                    f"[入库] 文件 {filename} 券商 {broker} 账号 {account_id} "
                    f"交易日 {trading_day} 涉及 {len(table_frames)} 张表, "
                    f"调用入库接口"
                )
                ok, info = self.api.settlement_file_insert(
                    tradingday=trading_day,
                    account_id=account_id,
                    table_frames=table_frames,
                )
                if ok:
                    stats["inserted"] += 1
                    inserted_by_day.setdefault(trading_day, set()).add(account_id)
                    self.logger.info(
                        f"文件 {filename} 券商 {broker} 账号 {account_id} {info}"
                    )
                else:
                    stats["failed"] += 1
                    failed_reasons[(trading_day, account_id)] = info
                    self.logger.error(
                        f"文件 {filename} 券商 {broker} 账号 {account_id} {info}"
                    )

                # 通过通用日志接口写入带自定义 info 的“对账单数据”日志
                # （服务端 settlementFileInsert 已写一条，这里按同键覆盖为更详细的信息）
                if self.api.log_path:
                    self.api.write_processing_log(
                        tradingday=trading_day,
                        account_id=account_id,
                        log_type="对账单数据",
                        log_status="Success" if ok else "Failed",
                        log_info=info,
                    )

        self.logger.info(
            f"数据入库步骤结束: 券商 {stats['brokers']} 家, 文件 {stats['files']} 个, "
            f"成功 {stats['inserted']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}"
        )

        trading_days = sorted(seen_by_day.keys())
        if not trading_days:
            # 无可解析报文时无法得知真实交易日，退回运行日仅用于账号统计
            self.logger.warning(
                f"未解析到任何报文交易日, 账号统计退回使用运行日 {self.running_day}"
            )
            trading_days = [self.running_day]
        self._log_uninserted_accounts(
            trading_days=trading_days,
            seen_by_day=seen_by_day,
            inserted_by_day=inserted_by_day,
            skipped_reasons=skipped_reasons,
            failed_reasons=failed_reasons,
            unparsed_files=unparsed_files,
        )
        return stats

    def _log_uninserted_accounts(
        self,
        trading_days: list,
        seen_by_day: dict,
        inserted_by_day: dict,
        skipped_reasons: dict,
        failed_reasons: dict,
        unparsed_files: list,
    ) -> None:
        """入库结束后按报文真实交易日汇总：未检测到文件、检测到但未入库的账号。"""
        self.logger.info("-" * 60)
        self.logger.info("入库结果账号明细（按报文交易日）")
        for trading_day in trading_days:
            seen = seen_by_day.get(trading_day, set())
            inserted = inserted_by_day.get(trading_day, set())
            expected = self._query_expected_accounts(trading_day)
            self.logger.info(
                f"交易日 {trading_day}: 已成功入库 {len(inserted)} 个 | "
                f"检测到文件 {len(seen)} 个 | 有效账号 {len(expected)} 个"
            )

            # 1) 有账号配置但未检测到对账单文件
            if expected:
                no_file_ids = [
                    account_id
                    for account_id in expected
                    if account_id not in seen
                ]
                if no_file_ids:
                    self.logger.warning(
                        f"  未检测到对账单文件、本次未入库的账号 "
                        f"{len(no_file_ids)} 个:"
                    )
                    for account_id in sorted(no_file_ids):
                        self.logger.warning(f"    - {expected[account_id]}")
                        # 把“文件找不到”写入对账单文件日志（若配置了日志接口）
                        if self.api.log_path:
                            self.api.write_processing_log(
                                tradingday=trading_day,
                                account_id=account_id,
                                log_type="对账单文件",
                                log_status="Failed",
                                log_info="未检测到对账单文件",
                            )
                else:
                    self.logger.info("  所有有效账号均检测到对应对账单文件")
            else:
                self.logger.warning(
                    f"  未能获取交易日 {trading_day} 的有效账号列表, "
                    f"跳过“未检测到文件账号”统计"
                )

            # 2) 检测到文件但本次未入库（跳过 / 失败）
            skipped = {
                account_id: reason
                for (day, account_id), reason in skipped_reasons.items()
                if day == trading_day and account_id not in inserted
            }
            failed = {
                account_id: reason
                for (day, account_id), reason in failed_reasons.items()
                if day == trading_day and account_id not in inserted
            }
            if skipped:
                self.logger.warning(
                    f"  检测到文件但本次跳过入库的账号 {len(skipped)} 个:"
                )
                for account_id in sorted(skipped):
                    self.logger.warning(
                        f"    - {account_id}: {skipped[account_id]}"
                    )
            if failed:
                self.logger.error(f"  入库失败的账号 {len(failed)} 个:")
                for account_id in sorted(failed):
                    self.logger.error(f"    - {account_id}: {failed[account_id]}")

        # 3) 无法解析基本资料的报文文件
        if unparsed_files:
            self.logger.warning(
                f"无法解析基本资料的报文文件 {len(unparsed_files)} 个: "
                f"{sorted(unparsed_files)}"
            )
        self.logger.info("-" * 60)
