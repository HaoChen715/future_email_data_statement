import asyncio
import os
import re
import shutil
import warnings

import pandas as pd
from openpyxl import load_workbook
from sqlalchemy import text

from src.future_email_data_statement.common.CheckTradingDay import CheckTradingDay
from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.common.logger_init import LoggerInit


# 忽略指定的 UserWarning
warnings.simplefilter("ignore", UserWarning)


class CheckAccountFile:
    """
    账号匹配与文件迁移模块（思路沿用 auto_down_email 项目）。

    账号信息来源为 future_data 项目的数据库视图 v_config_bill_future_account
    （字段：future_account_id / broker_id / start_date / end_date 等）。
    匹配逻辑：先按文件名拆分出的连续数字组合精确匹配资金账号，再按文件内容
    （前20行）匹配；匹配成功后迁移到 resource/{broker}/{交易日}/ 并备份到历史目录。
    """

    def __init__(self, running_day: str, statement_type: str = "Trade"):
        global_func = GlobalFunc(statement_type=statement_type)
        self.current_dir = global_func.get_parent_path()
        self.engine, self.dtime = global_func.connect_database()
        # 文件迁移目录：资源目录（取自 info.ini [FilePath]/[TestFilePath]）
        self.destination_directory = global_func.get_file_path("resource_root")
        # 解压后的最终文件目录（随环境切换）
        self.final_file_dir = global_func.get_file_path("unzip_final_root")
        self.running_day = running_day
        check_trading_day = CheckTradingDay()
        self.previous_trading_day = check_trading_day.previous_trading_day(
            date=self.running_day
        )
        # 与 auto_down_email 一致的有效期过滤：运行日 <= start_date 且 前一交易日 >= end_date
        self.select_sql = text(
            f"SELECT * FROM v_config_bill_future_account "
            f"WHERE start_date<={self.running_day} AND end_date>={self.previous_trading_day} "
        )
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="checkaccountfile_logger",
        )

    def select_account_info(self) -> pd.DataFrame:
        """
        查询数据库中当日有效的期货账号配置（视图 v_config_bill_future_account）。

        Returns:
            pd.DataFrame: 含 future_account_id / broker_id 等字段的账号配置。
        """
        with self.engine.connect() as conn:
            result = conn.execute(self.select_sql)
            account_info = pd.DataFrame(result.fetchall(), columns=result.keys()).reset_index(drop=True)
        if account_info.empty:
            self.logger.warning("未查询到当日有效的期货账号配置")
        else:
            self.logger.info(f"查询到 {len(account_info)} 个有效期货账号配置")
        return account_info

    def load_file_names(self, source_dir):
        try:
            files = [file for file in os.listdir(source_dir)]
            if not files:
                print("目录下不存在文件")
                files = []
        except Exception as e:
            print("源文件地址出错: %s", e)
            files = []
        return files

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
            # 以换行拼接单元格，避免账号数字跨单元格边界被误判命中
            return {account_id for account_id in candidates if account_id in text}

        def dataframe_to_text(df: pd.DataFrame) -> str:
            # pandas 3.0 下 DataFrame.astype(str) 会把缺失值保留为 float('nan')，
            # 直接 join 会抛 "expected str instance, float found"，
            # 故逐元素 str() 兜底转换后再拼接
            return "\n".join(str(cell) for cell in df.to_numpy().ravel())

        async def search_in_txt():
            # 资金账号为 ASCII 数字，utf-8/gbk/gb18030/big5 等编码对 ASCII 字节的
            # 表示完全一致；直接按字节匹配，避免因文件编码不统一而解码报错
            with open(file_path, "rb") as file:
                content = file.read()
            found = set()
            for account_id in candidates:
                if account_id.encode("ascii", errors="ignore") in content:
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
            account_info = account_info[
                ~account_info["remark"].astype(str).str.contains("销户")
            ].reset_index(drop=True)
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
