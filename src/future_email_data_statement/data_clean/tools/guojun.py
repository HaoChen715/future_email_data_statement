import os
import re
import traceback

import pandas as pd

from src.future_email_data_statement.common.statement_type import (
    detect_statement_type,
)
from .statement import Statement


class GuoJun(Statement):
    """国泰君安期货-交易结算单 txt 数据清洗类。

    源文件为 GBK 编码文本（邮件附件），共同结构：

        表头: 制表时间/客户号/客户名称/日期
        资金状况: "标签 英文：数值" 键值对（盯市/期权/证券现货三种格式）
        明细表: | 分隔表格（出入金明细/成交记录/平仓明细/持仓明细/持仓汇总/持仓变动）

    清洗后分化成多个标准 DataFrame（data_frames_json）:
        基本资料 / 资金状况 / 出入金明细 / 成交记录 / 平仓明细 /
        持仓明细 / 持仓汇总 / 持仓变动
    """

    broker = "国君"

    # 资金状况中文标签 -> 标准英文列名（覆盖盯市/期权/证券现货三种格式）
    CAPITAL_FIELD_MAP = {
        "期初结存": "last_day_balance",
        "期末结存": "balance",
        "客户权益": "customer_equity",
        "出入金": "deposit_withdrawal",
        "手续费": "commission",
        "维持保证金": "maintenance_margin",
        "权利金收入": "premium_received",
        "权利金支出": "premium_paid",
        "可用资金": "available_funds",
        "基础保证金": "initial_margin",
        "追加保证金": "margin_call",
        "权利仓市值": "long_option_market_value",
        "义务仓市值": "short_option_market_value",
        "市值权益": "market_value_equity",
        "风险度": "risk",
        "执行冻结资金": "strike_frozen_sum",
        "执行实收资金": "strike_receivable",
        "执行实付资金": "strike_payable",
        "现金替代实收资金": "received_sum_by_cash",
        "现金替代实付资金": "paid_sum_by_cash",
        "平仓盈亏": "closing_profit_loss",
        "持仓盯市盈亏": "floating_profit_loss",
        "期权执行盈亏": "option_exercise_profit_loss",
        "交割盈亏": "delivery_profit_loss",
        "质押金": "pledge_amount",
        "货币质押保证金占用": "fx_pledge_occupancy",
        "保证金占用": "margin_occupancy",
        "交割保证金": "delivery_margin",
        "多头期权市值": "long_option_market_value",
        "空头期权市值": "short_option_market_value",
        "货币质入": "new_fx_pledge",
        "货币质出": "fx_redemption",
        "质押变化金额": "change_in_pledge_amount",
        "货币质押变化金额": "change_in_fx_pledge",
        "期初总资产": "total_assets_brought_forward",
        "期末总资产": "total_assets_carried_forward",
        "期初资金余额": "fund_balance_brought_forward",
        "期末资金余额": "fund_balance_carried_forward",
        "股票市值": "stock_market_value",
        "开仓准备金": "open_preparation",
        "可提资金": "fund_withdrawal",
        "冻结资金": "fund_frozen",
        "利息": "interest",
        "买券金额": "buy_security_payment",
        "卖券金额": "sell_security_income",
        "实际收付": "actual_payment",
        "红利": "bonus",
    }

    # 资金状况单行表标准列顺序
    CAPITAL_COLUMNS = (
        "last_day_balance",
        "balance",
        "customer_equity",
        "deposit_withdrawal",
        "commission",
        "maintenance_margin",
        "premium_received",
        "premium_paid",
        "available_funds",
        "initial_margin",
        "margin_call",
        "long_option_market_value",
        "short_option_market_value",
        "market_value_equity",
        "risk",
        "strike_frozen_sum",
        "strike_receivable",
        "strike_payable",
        "received_sum_by_cash",
        "paid_sum_by_cash",
        "closing_profit_loss",
        "floating_profit_loss",
        "option_exercise_profit_loss",
        "delivery_profit_loss",
        "pledge_amount",
        "fx_pledge_occupancy",
        "margin_occupancy",
        "delivery_margin",
        "new_fx_pledge",
        "fx_redemption",
        "change_in_pledge_amount",
        "change_in_fx_pledge",
        "total_assets_brought_forward",
        "total_assets_carried_forward",
        "fund_balance_brought_forward",
        "fund_balance_carried_forward",
        "stock_market_value",
        "open_preparation",
        "fund_withdrawal",
        "fund_frozen",
        "interest",
        "buy_security_payment",
        "sell_security_income",
        "actual_payment",
        "bonus",
    )

    # ---------------- 基本资料解析 ---------------- #
    def _parse_basic_info(self, lines: list, file_name: str) -> dict:
        """解析表头与资金账号信息。

        Args:
            lines: 文件行列表。
            file_name: 源文件名。

        Returns:
            dict: 基本资料字段（trading_day/account_id/client_id/client_name/
                broker/statement_type/creation_date/file_name）。
        """
        creation_date = None
        client_id = None
        client_name = None
        trading_day = None
        account_id = None
        statement_type = "标准"
        for line in lines:
            s = line.strip()
            if "资金状况" in s and "资金账号" in s:
                match = re.search(r"资金账号[：:]\s*(\d+)", s)
                if match:
                    account_id = match.group(1)
                break  # 表头信息均在资金状况块之前
            if not s:
                continue
            match = re.search(r"制表(?:时间|日期) Creation Date[：:]\s*(\d{8})", s)
            if match:
                creation_date = match.group(1)
            match = re.search(r"客户号 Client ID[：:]\s*(\d+)", s)
            if match:
                client_id = match.group(1)
            match = re.search(r"客户名称 Client Name[：:]\s*(.+)$", s)
            if match:
                client_name = match.group(1).strip()
            match = re.search(r"日期 Date[：:]\s*(\d{8})", s)
            if match:
                trading_day = match.group(1)
            if ("(盯市)" in s) or ("Settlement Statement(MTM)" in s):
                statement_type = "盯市"
        if not account_id:
            account_id = client_id
        return {
            "trading_day": trading_day,
            "account_id": account_id,
            "client_id": client_id,
            "client_name": client_name,
            "broker": self.broker,
            "statement_type": statement_type,
            "creation_date": creation_date,
            "file_name": file_name,
        }

    def _check_statement_type(
        self,
        lines: list,
        statement_type: str,
        account_id: str = None,
        file_name: str = None,
    ) -> str:
        """根据文件内容与账号前缀细分对账单类型（盯市/期权/证券现货）。

        判断逻辑封装在 common/statement_type.py：内容特征（资金状况字段
        互斥）优先，文件名资金账号前缀（95=证券现货 / 99=期权）兜底，
        内容无法判定时保留标题解析出的原始类型。

        Args:
            lines: 文件行列表。
            statement_type: 标题解析出的原始类型（盯市/标准）。
            account_id: 资金账号（前缀兜底规则）。
            file_name: 文件名（账号提取兜底）。

        Returns:
            str: 盯市 / 期权 / 证券现货（未判定时返回原始类型）。
        """
        detected = detect_statement_type(
            lines=lines, account_id=account_id, file_name=file_name
        )
        category = detected["category"]
        if category:
            return detected["format"]
        return statement_type

    # ---------------- 数据清洗 ---------------- #
    def data_clean(self, lines: list, file_name: str) -> dict:
        """将对账单文件清洗为多个 DataFrame。

        Args:
            lines: 文件行列表（read_txt_lines 读取结果）。
            file_name: 源文件名。

        Returns:
            dict: {表名: DataFrame}，键为 基本资料/资金状况/出入金明细/
                成交记录/平仓明细/持仓明细/持仓汇总/持仓变动。
        """
        data_frames_json = {}
        try:
            # 1. 基本资料（对账单类型细分后生成 DataFrame）
            basic = self._parse_basic_info(lines=lines, file_name=file_name)

            # 2. 资金状况（键值对 -> 标准英文列名单行表）
            capital = self.parse_capital(lines=lines)
            basic["statement_type"] = self._check_statement_type(
                lines=lines,
                statement_type=basic["statement_type"],
                account_id=basic["account_id"],
                file_name=file_name,
            )
            data_frames_json["基本资料"] = pd.DataFrame([basic])
            capital_row = {"statement_type": basic["statement_type"]}
            for cn_label, std_key in self.CAPITAL_FIELD_MAP.items():
                if cn_label in capital:
                    capital_row[std_key] = self.to_number(capital[cn_label])
            capital_df = pd.DataFrame(
                [
                    {
                        col: capital_row.get(col)
                        for col in ["statement_type"] + list(self.CAPITAL_COLUMNS)
                    }
                ]
            )
            capital_df.insert(0, "account_id", basic["account_id"])
            capital_df.insert(0, "trading_day", basic["trading_day"])
            data_frames_json["资金状况"] = capital_df

            # 3. | 分隔明细表（逐表切分清洗）
            for title in self.TABLE_TITLES:
                header, rows = self.parse_pipe_table(
                    lines=lines, title_prefix=title
                )
                if header is None:
                    continue
                df = self.build_table_df(header=header, rows=rows)
                # 表内未含资金账号列时补充，便于多文件合并追溯
                if "资金账号" not in df.columns:
                    df.insert(0, "资金账号", basic["account_id"])
                data_frames_json[title] = df
        except Exception as e:
            self.logger.error(e)
            self.logger.error(
                "数据清洗发生异常,报错信息: %s", traceback.format_exc()
            )
        return data_frames_json

    # ---------------- 目录批量清洗 ---------------- #
    def main(self) -> dict:
        """清洗目录下全部对账单文件。

        Returns:
            dict: {文件名: data_frames_json}。
        """
        self.logger.info("券商: 国君 开始对账单数据清洗")
        files = self.load_file_path(resource_files_path=self.resource_data_path)
        if not files:
            self.logger.warning(
                f"警告: 目录 {self.resource_data_path} 下不存在对账单文件, 跳出国君清洗"
            )
            return {}

        result = {}
        for filename in files:
            file_path = os.path.join(self.resource_data_path, filename)
            try:
                lines = self.read_txt_lines(file_path=file_path)
                if not any("交易结算单" in line for line in lines[:6]):
                    self.logger.warning(f"跳过非交易结算单文件: {filename}")
                    continue
                data_frames_json = self.data_clean(
                    lines=lines, file_name=filename
                )
                result[filename] = data_frames_json
                basic = data_frames_json.get("基本资料")
                account_id = (
                    basic.iloc[0]["account_id"]
                    if basic is not None and not basic.empty
                    else "未知"
                )
                section_info = " ".join(
                    f"{name}:{len(df)}行"
                    for name, df in data_frames_json.items()
                    if not df.empty
                )
                self.logger.info(f"文件: {filename} 账号: {account_id} 清洗完成")
                self.logger.info(f"    -> {section_info}")
            except Exception as e:
                self.logger.error(f"文件: {filename} 清洗失败: {e}")
                self.logger.error(traceback.format_exc())
        self.logger.info(
            f"国君对账单数据清洗完成, 共处理 {len(result)}/{len(files)} 个文件"
        )
        return result
