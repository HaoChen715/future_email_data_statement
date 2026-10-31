import asyncio
import os
import re
import shutil
import warnings

import pandas as pd
from openpyxl import load_workbook

from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.data_insert.api_client import (
    BillFutureApiClient,
)


# 忽略指定的 UserWarning
warnings.simplefilter("ignore", UserWarning)


class CheckAccountFile:
    """
    账号匹配与文件迁移模块（思路沿用 auto_down_email 项目）。

    账号信息来源为 Open API queryAccountList（服务端读取视图
    v_config_bill_future_account 并按有效期过滤；字段：futureAccountId / brokerId /
    startDate / endDate 等，接口返回后映射为库表下划线命名）。
    匹配逻辑：先按文件名拆分出的连续数字组合精确匹配资金账号，再按文件内容
    （前20行）匹配；匹配成功后迁移到 resource/{broker}/{交易日}/ 并备份到历史目录。
    """

    def __init__(self, running_day: str, statement_type: str = "Trade"):
        global_func = GlobalFunc(statement_type=statement_type)
        self.current_dir = global_func.get_parent_path()
        # 文件迁移目录：资源目录（取自 info.ini [FilePath]/[TestFilePath]）
        self.destination_directory = global_func.get_file_path("resource_root")
        # 解压后的最终文件目录（随环境切换）
        self.final_file_dir = global_func.get_file_path("unzip_final_root")
        self.running_day = running_day
        # 只扫描/匹配配置中允许的文件格式，其余格式直接跳过
        self.file_extensions = global_func.get_file_extensions()
        # 券商白名单: 仅白名单内券商视为已注册券商(用于账号过滤) 空集合表示不限制
        self.broker_whitelist = global_func.get_broker_whitelist()
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="checkaccountfile_logger",
        )
        # 账号配置改由 Open API 查询（queryAccountList，服务端按有效期过滤）
        self.api = BillFutureApiClient(
            logger=self.logger, **global_func.get_api_config()
        )

    def select_account_info(self) -> pd.DataFrame:
        """
        通过 Open API 查询当日有效的期货账号配置。

        Returns:
            pd.DataFrame: 含 future_account_id / broker_id / remark 等字段的账号配置
                （字段名由接口 camelCase 统一映射为库表下划线命名）。
        """
        accounts = self.api.query_account_list(self.running_day)
        accounts = self._filter_accounts(accounts)
        field_map = {
            "futureAccountId": "future_account_id",
            "futureName": "future_name",
            "accountType": "account_type",
            "brokerId": "broker_id",
            "startDate": "start_date",
            "endDate": "end_date",
            "remark": "remark",
        }
        account_info = pd.DataFrame(
            [
                {
                    target: account.get(source)
                    for source, target in field_map.items()
                }
                for account in accounts
            ],
            columns=list(field_map.values()),
        ).reset_index(drop=True)
        if account_info.empty:
            self.logger.warning("未查询到当日有效的期货账号配置")
        else:
            self.logger.info(f"查询到 {len(account_info)} 个有效期货账号配置")
        return account_info

    @staticmethod
    def _broker_of(account: dict) -> str:
        """取账号的券商名并去除首尾空白（None 视为空串）。"""
        value = account.get("brokerId")
        return "" if value is None else str(value).strip()

    @staticmethod
    def _account_brief(account: dict) -> str:
        """账号简要信息（账号/券商/类型/有效期/备注），用于过滤日志定位。"""
        return (
            f"{account.get('futureAccountId')}"
            f"(券商={account.get('brokerId')!r}, "
            f"类型={account.get('accountType')!r}, "
            f"有效期={account.get('startDate')}~{account.get('endDate')}, "
            f"备注={account.get('remark')!r})"
        )

    def _filter_accounts(self, accounts: list) -> list:
        """按券商白名单过滤接口返回的账号配置。

        仅当账号的 brokerId（去除首尾空格后）完全等于白名单中的券商名时才保留。
        brokerId 为空/None 或不在白名单内的账号都会被过滤，并在日志中列出。

        Args:
            accounts: 接口 queryAccountList 返回的账号 DTO 列表（camelCase）。

        Returns:
            list: 白名单内券商的账号；白名单为空时返回全部账号。
        """
        self.logger.info(f"券商白名单过滤前, 接口返回账号 {len(accounts)} 个")
        if not self.broker_whitelist:
            self.logger.info("未配置券商白名单, 不进行券商过滤")
            kept = list(accounts)
        else:
            kept, dropped = [], []
            for account in accounts:
                if self._broker_of(account) in self.broker_whitelist:
                    kept.append(account)
                else:
                    dropped.append(account)
            self.logger.info(
                f"券商白名单过滤: 白名单 {sorted(self.broker_whitelist)} | "
                f"保留 {len(kept)} 个账号, 过滤掉 {len(dropped)} 个"
            )
            if dropped:
                dropped_detail = ", ".join(
                    self._account_brief(account) for account in dropped
                )
                self.logger.info(
                    f"被白名单过滤掉的账号 {len(dropped)} 个: {dropped_detail}"
                )
            empty_broker = [
                account for account in accounts if not self._broker_of(account)
            ]
            if empty_broker:
                self.logger.warning(
                    f"其中 {len(empty_broker)} 个账号的 brokerId 为空, 已按未注册券商过滤: "
                    + ", ".join(
                        self._account_brief(account) for account in empty_broker
                    )
                )
        self._log_retained_accounts(kept)
        return kept

    def _log_retained_accounts(self, accounts: list) -> None:
        """输出过滤后留存的账号（账号/券商/类型等），便于核对当次匹配范围。"""
        if not accounts:
            self.logger.warning("券商过滤后无任何账号留存")
            return
        detail = ", ".join(self._account_brief(account) for account in accounts)
        self.logger.info(f"过滤后留存账号 {len(accounts)} 个: {detail}")

    def load_file_names(self, source_dir):
        try:
            all_files = os.listdir(source_dir)
            files = [
                file
                for file in all_files
                if os.path.splitext(file)[1].lower() in self.file_extensions
            ]
            skipped = len(all_files) - len(files)
            if skipped:
                self.logger.info(
                    f"[文件扫描] 跳过 {skipped} 个非目标格式文件 "
                    f"(允许格式: {sorted(self.file_extensions)})"
                )
            if not files:
                self.logger.warning(
                    f"目录下不存在目标格式文件: {source_dir}"
                )
        except Exception as e:
            self.logger.error(f"源文件地址出错: {e}")
            files = []
        return files

    def _guess_trading_day(self, file_path: str, file_name: str) -> str:
        """推断报文真实交易日：文件名日期 -> txt 内容日期 -> 运行日兜底。"""
        match = re.search(r"(20\d{6})", file_name)
        if match:
            return match.group(1)
        if file_name.lower().endswith(".txt"):
            try:
                with open(
                    file_path, "r", encoding="gb18030", errors="ignore"
                ) as file:
                    head = file.read(8192)
                match = re.search(r"日期\s*Date[：:]\s*(\d{8})", head)
                if match:
                    return match.group(1)
            except OSError:
                pass
        self.logger.warning(
            f"文件 {file_name} 未能从文件名/内容解析交易日, "
            f"匹配日志使用运行日 {self.running_day}"
        )
        return self.running_day

    def _log_file_match(
        self, account_id: str, file_name: str, file_path: str, broker_id: str
    ) -> None:
        """匹配到文件时立即写入 log_type=对账单文件 的成功日志。"""
        if not self.api.log_path:
            return
        tradingday = self._guess_trading_day(file_path, file_name)
        self.api.write_processing_log(
            tradingday=tradingday,
            account_id=account_id,
            log_type="对账单文件",
            log_status="Success",
            log_info=f"检测到对账单文件: {file_name} (券商={broker_id})",
        )

    def account_in_file_name(self, file_name: str, account_id: str) -> bool:
        """按正则拆分文件名，连续数字组成一个整体；账号完全等于其中某个数字组即判定匹配。

        例：文件名 20260825_7070_9980029659_交易结算单.txt 拆分为
        [20260825, 7070, 9980029659]，账号 9980029659 完全命中即匹配。

        Args:
            file_name: 文件名。
            account_id: 资金账号。

        Returns:
            bool: 账号是否完全等于文件名中的某个连续数字组。
        """
        digit_groups = re.findall(r"\d+", file_name)
        return str(account_id) in digit_groups

    async def find_accounts_in_file(
        self, file_path: str, file_name: str, account_ids
    ) -> set:
        """读取一次文件内容，批量返回其中命中的全部资金账号。

        与逐个账号重复读取同一文件相比，本方法对每个文件只读取一次，
        再一次性校验所有候选账号，可显著降低文件 I/O 与 Excel 解析开销。

        Args:
            file_path: 文件绝对路径。
            file_name: 文件名（用于判断文件类型）。
            account_ids: 候选资金账号集合（字符串）。

        Returns:
            set: 命中的资金账号集合。
        """
        candidates = [str(account_id) for account_id in account_ids]
        if not candidates:
            return set()

        def match_text(text: str) -> set:
            # 账号必须作为独立的数字串出现，避免被更长的账号"包含"而误命中。
            # 例如期权账号 9980009876 内含期货账号 80009876，纯子串匹配会把
            # 期权报文误判给期货账号，导致期货账号被标记已匹配、实际却没有入库。
            return {
                account_id
                for account_id in candidates
                if re.search(
                    rf"(?<!\d){re.escape(account_id)}(?!\d)", text
                )
            }

        def dataframe_to_text(df: pd.DataFrame) -> str:
            # pandas 3.0 下 DataFrame.astype(str) 会把缺失值保留为 float('nan')，
            # 直接 join 会抛 "expected str instance, float found"，
            # 故逐元素 str() 兜底转换后再拼接
            return "\n".join(str(cell) for cell in df.to_numpy().ravel())

        async def search_in_txt():
            # 资金账号为 ASCII 数字，utf-8/gbk/gb18030/big5 等编码对 ASCII 字节的
            # 表示完全一致；直接按字节匹配，避免因文件编码不统一而解码报错。
            # 同样要求账号前后不是数字，避免长账号包含短账号造成误命中。
            with open(file_path, "rb") as file:
                content = file.read()
            found = set()
            for account_id in candidates:
                pattern = re.compile(
                    rb"(?<!\d)"
                    + re.escape(account_id.encode("ascii", errors="ignore"))
                    + rb"(?!\d)"
                )
                if pattern.search(content):
                    found.add(account_id)
            return found

        async def search_in_xlsx():
            workbook = load_workbook(file_path, read_only=True)

            async def search_in_sheet(sheet):
                # 只读取前 20 行
                df = pd.read_excel(file_path, sheet_name=sheet, nrows=20)
                return match_text(dataframe_to_text(df))

            tasks = [search_in_sheet(sheet) for sheet in workbook.sheetnames]
            results = await asyncio.gather(*tasks)
            found = set()
            for result in results:
                found |= result
            return found

        async def search_in_xls():
            df = pd.read_excel(file_path, header=None, nrows=20)
            return match_text(dataframe_to_text(df))

        if file_name.endswith((".txt", ".TXT")):
            return await search_in_txt()
        if file_name.endswith((".xlsx", ".XLSX")):
            return await search_in_xlsx()
        if file_name.endswith((".xls", ".XLS")):
            return await search_in_xls()
        return set()

    def move_file(self, file_path: str, source, broker_id: str):
        """
        将匹配成功的文件迁移到资源目录。

        Args:
            file_path (str): 源文件路径。
            source: 未使用（保留与 auto_down_email 一致的接口，允许传 None）。
            broker_id (str): 账号对应券商。
        """
        target_directory = os.path.join(
            self.destination_directory,
            broker_id,
            self.running_day,
        )
        os.makedirs(target_directory, exist_ok=True)
        shutil.copy(file_path, target_directory)
        self.logger.info(f"文件{file_path} 迁移完成")

    async def check_file_account(self, account_info: pd.DataFrame):
        # 账号 -> 券商 映射（跳过已销户账号）
        if "remark" in account_info.columns:
            closed_mask = account_info["remark"].astype(str).str.contains("销户")
            closed_accounts = account_info[closed_mask]
            if not closed_accounts.empty:
                detail = ", ".join(
                    f"{row['future_account_id']}"
                    f"(券商={row['broker_id']}, 备注={row['remark']})"
                    for _, row in closed_accounts.iterrows()
                )
                self.logger.info(
                    f"跳过已销户账号 {len(closed_accounts)} 个: {detail}"
                )
            account_info = account_info[~closed_mask].reset_index(drop=True)
        account_broker_dict = dict(
            zip(
                account_info["future_account_id"].astype(str),
                account_info["broker_id"].astype(str),
            )
        )
        account_ids = set(account_broker_dict.keys())

        source_dir = os.path.join(self.final_file_dir, self.running_day)
        filenames_list = self.load_file_names(source_dir=source_dir)
        self.logger.info(
            f"[文件扫描] 开始匹配：待扫描文件 {len(filenames_list)} 个，"
            f"待匹配账号 {len(account_ids)} 个"
        )

        # 以「文件」为外层循环：每个文件只读取一次内容，批量校验所有账号，
        # 避免原来「每个账号都把全部文件重新读取一遍」的重复 I/O。
        # 每个账号仍只取文件列表顺序中首个命中的文件，保持原有匹配语义。
        matched_accounts = set()
        for file_name in filenames_list:
            if "港股" in file_name or "双融" in file_name:
                continue
            file_path = os.path.join(source_dir, file_name)
            # 检查是否为文件
            if not os.path.isfile(file_path):
                continue

            self.logger.info(f"[文件扫描] 当前检测文件：{file_name}")

            # 第一步：文件名按连续数字组精确匹配资金账号（批量比对未匹配账号）
            digit_groups = set(re.findall(r"\d+", file_name))
            for account_id in (account_ids - matched_accounts) & digit_groups:
                matched_accounts.add(account_id)
                broker_id = account_broker_dict[account_id]
                self.logger.info(
                    f"[文件扫描] 文件名命中：{file_name} -> "
                    f"账号 {account_id}（券商 {broker_id}）"
                )
                self.move_file(file_path, None, broker_id)
                self._log_file_match(
                    account_id, file_name, file_path, broker_id
                )

            # 第二步：文件内容搜索资金账号（前20行，每文件仅读取一次）
            remaining_accounts = account_ids - matched_accounts
            if not remaining_accounts:
                continue
            content_matched = await self.find_accounts_in_file(
                file_path, file_name, remaining_accounts
            )
            for account_id in content_matched:
                matched_accounts.add(account_id)
                broker_id = account_broker_dict[account_id]
                self.logger.info(
                    f"[文件扫描] 内容命中：{file_name} -> "
                    f"账号 {account_id}（券商 {broker_id}）"
                )
                self.move_file(file_path, None, broker_id)
                self._log_file_match(
                    account_id, file_name, file_path, broker_id
                )

        # 未被任何文件命中的账号统一告警
        unmatched_accounts = [
            (account_id, broker_id)
            for account_id, broker_id in account_broker_dict.items()
            if account_id not in matched_accounts
        ]
        for account_id, broker_id in unmatched_accounts:
            self.logger.error(
                f"[文件扫描] 未命中：未在当日邮件附件中找到 "
                f"券商 {broker_id} 账号 {account_id} 所属文件"
            )
        if unmatched_accounts:
            self.logger.warning(
                "请检查当日邮件信息,如果确实存在遗漏,请联系对应券商"
            )

        self.logger.info(
            f"[文件扫描] 匹配结束：命中 {len(matched_accounts)}/{len(account_ids)} 个账号，"
            f"未命中 {len(unmatched_accounts)} 个"
        )

    async def main(self):
        account_info = self.select_account_info()
        await self.check_file_account(account_info)
        return account_info
