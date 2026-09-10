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
    （字段：future_account_id / broker / start_date / end_date 等）。
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
            pd.DataFrame: 含 future_account_id / broker 等字段的账号配置。
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

    async def search_string_in_files(
        self, file_path: str, file_name: str, bill_accountid: str
    ):
        async def search_in_txt(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    content = file.read()
                    return bill_accountid in content
            except UnicodeDecodeError:
                self.logger.warning("检查到非utf-8编码,切换gbk编码")
                with open(file_path, "r", encoding="gbk") as file:
                    content = file.read()
                    return bill_accountid in content

        async def search_in_xlsx(file_path):
            workbook = load_workbook(file_path, read_only=True)

            async def search_in_sheet(sheet):
                # 只读取前 20 行
                df = pd.read_excel(file_path, sheet_name=sheet, nrows=20)
                return df.apply(
                    lambda row: row.astype(str)
                    .str.contains(bill_accountid, na=False)
                    .any(),
                    axis=1,
                ).any()

            tasks = [search_in_sheet(sheet) for sheet in workbook.sheetnames]
            results = await asyncio.gather(*tasks)
            return any(results)

        async def search_in_xls(file_path):
            df = pd.read_excel(file_path, header=None, nrows=20)
            return df.apply(
                lambda row: row.astype(str)
                .str.contains(bill_accountid, na=False)
                .any(),
                axis=1,
            ).any()

        # 遍历目录中的文件
        if file_name.endswith((".txt", ".TXT")):
            if await search_in_txt(file_path):
                return True
        elif file_name.endswith((".xlsx", ".XLSX")):
            if await search_in_xlsx(file_path):
                return True
        elif file_name.endswith((".xls", ".XLS")):
            if await search_in_xls(file_path):
                return True
        return False

    def move_file(self, file_path: str, source: str, broker_id: str):
        """
        将匹配成功的文件迁移到资源目录。

        Args:
            file_path (str): 源文件路径。
            source (str): 未使用（保留与 auto_down_email 一致的接口）。
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
            zip(account_info["future_account_id"], account_info["broker"])
        )

        source_dir = os.path.join(self.final_file_dir, self.running_day)
        filenames_list = self.load_file_names(source_dir=source_dir)

        for account_id, broker_id in account_broker_dict.items():
            self.logger.info(f"正在检测账号：{account_id}（券商：{broker_id}）")
            matched = False
            for file_name in filenames_list:
                if "港股" in file_name or "双融" in file_name:
                    continue
                file_path = os.path.join(source_dir, file_name)
                # 检查是否为文件
                if not os.path.isfile(file_path):
                    continue

                # 第一步：文件名按连续数字组精确匹配资金账号
                if self.account_in_file_name(file_name, str(account_id)):
                    matched = True
                    self.logger.info(
                        f"成功匹配到资金账号：{account_id} 所属文件（文件名匹配）"
                    )
                    self.move_file(file_path, None, broker_id)
                    break

                # 第二步：文件内容搜索资金账号（前20行）
                if await self.search_string_in_files(
                    file_path, file_name, bill_accountid=str(account_id)
                ):
                    matched = True
                    self.logger.info(
                        f"成功匹配到资金账号：{account_id} 所属文件（内容匹配）"
                    )
                    self.move_file(file_path, None, broker_id)
                    break

            if not matched:
                self.logger.error(
                    f"未在当日邮件附件中根据唯一资金账号找到 券商： {broker_id}, 账号：{account_id} 所属文件"
                )
                self.logger.warning(
                    "请检查当日邮件信息,如果确实存在遗漏,请联系对应券商"
                )

        self.logger.info("文件校验程序执行完成")

    async def main(self):
        account_info = self.select_account_info()
        await self.check_file_account(account_info)
        return account_info
