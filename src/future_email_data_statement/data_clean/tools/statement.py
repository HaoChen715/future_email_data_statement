import os
import re
import traceback
from datetime import datetime

import pandas as pd

from src.future_email_data_statement.common.get_parent_path import ParentPath
from src.future_email_data_statement.common.logger_init import LoggerInit


class Statement:
    """期货对账单数据清洗基类（思路沿用 auto_down_email 项目的 Statement 基类）。

    提供对账单 txt 文件的多编码读取、资金状况键值对解析、| 分隔表格切分等
    通用能力；各券商清洗类（tools/ 目录下）继承本类并实现 data_clean()，
    将对账单源文件分化成多个标准 DataFrame（data_frames_json）。
    """

    # 对账单 txt 文件常见编码（gb18030 完美兼容 gbk 并覆盖特殊制表符，utf-8 兜底）
    FILE_ENCODINGS = ("gb18030", "gbk", "utf-8")

    # 交易结算单明细表标题（中文前缀，用于切分 | 分隔的表格）
    TABLE_TITLES = (
        "出入金明细",
        "成交记录",
        "平仓明细",
        "持仓明细",
        "持仓汇总",
        "持仓变动",
        "行权明细",
        "组合持仓",
    )

    def __init__(self, statement_day: str, resource_data_path: str):
        """初始化清洗基类。

        Args:
            statement_day: 对账单交易日（YYYYMMDD）。
            resource_data_path: 对账单源文件所在目录。
        """
        self.statement_day = statement_day
        self.resource_data_path = resource_data_path
        parent_path = ParentPath()
        self.current_dir = parent_path.get_current_dir()
        self.running_day = datetime.now().strftime("%Y%m%d")
        self.logger = self.logger_init()

    def logger_init(self):
        """初始化清洗日志（独立 logger 名称，防重复挂载由 LoggerInit 保证）。"""
        logger_init = LoggerInit()
        return logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="future_data_clean",
        )

    # ---------------- 文件加载 ---------------- #
    def load_file_path(self, resource_files_path: str) -> list:
        """加载目录下的对账单文件列表（按文件名排序）。

        Args:
            resource_files_path: 对账单源文件目录。

        Returns:
            list: 文件名列表；目录不存在或为空时返回空列表。
        """
        try:
            if not os.path.isdir(resource_files_path):
                self.logger.warning(f"目标目录不存在: {resource_files_path}")
                return []
            files = [
                file
                for file in os.listdir(resource_files_path)
                if file.lower().endswith(".txt")
            ]
        except OSError as e:
            self.logger.error(e)
            self.logger.error("读取文件源地址出错: %s", traceback.format_exc())
            return []
        return sorted(files)

    def read_txt_lines(self, file_path: str) -> list:
        """多编码兼容读取对账单 txt 文件，返回去除行尾换行的行列表。

        Args:
            file_path: 文件绝对路径。

        Returns:
            list: 文本行列表。
        """
        for enc in self.FILE_ENCODINGS:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return [line.rstrip("\r\n") for line in f]
            except UnicodeDecodeError:
                continue
        # 兜底: 忽略无法解码的字节，保证程序不崩溃
        with open(file_path, "r", encoding="gb18030", errors="ignore") as f:
            return [line.rstrip("\r\n") for line in f]

    # ---------------- 资金状况解析 ---------------- #
    @classmethod
    def _parse_capital_pairs(cls, line: str) -> list:
        """解析资金状况行，格式为 "标签 英文：数值 标签 英文：数值"（每行 1~2 对）。

        标签以中文字符开头，数值为 ASCII 数字串；部分行分隔符为半角 ":"，
        因此按全角 "：" 与半角 ":" 混合切分。

        Args:
            line: 资金状况单行文本。

        Returns:
            list: [(中文标签, 数值字符串), ...]。
        """
        segments = [seg.strip() for seg in re.split(r"[:：]", line.strip())]
        if not segments or not segments[0]:
            return []
        pairs = []
        label = segments[0]
        for seg in segments[1:]:
            match = re.match(
                r"^(?P<value>[-0-9.,%]+)\s+(?P<next_label>[\u4e00-\u9fff].*)$",
                seg,
            )
            if match:
                pairs.append((label, match.group("value")))
                label = match.group("next_label")
            else:
                pairs.append((label, seg if seg else None))
                label = None
        return pairs

    @staticmethod
    def _pure_chinese(label: str) -> str:
        """提取标签中的纯中文（去除空格与英文说明，如 "手 续 费" -> "手续费"）。"""
        return "".join(re.findall(r"[\u4e00-\u9fff]+", label or ""))

    def parse_capital(self, lines: list) -> dict:
        """解析资金状况块，返回 {纯中文标签: 数值字符串}。

        资金状况块以含 "资金状况" 与 "资金账号" 的行为起始，至后续分隔线
        （第二个 ---- 行）或首个不含冒号的行（空行/下一节标题）结束。

        Args:
            lines: 文件行列表。

        Returns:
            dict: 资金状况键值对。
        """
        capital = {}
        in_block = False
        dash_seen = False
        for line in lines:
            s = line.strip()
            if not in_block:
                if "资金状况" in s and "资金账号" in s:
                    in_block = True
                continue
            if s.startswith("----"):
                if dash_seen:
                    break
                dash_seen = True
                continue
            if ("：" not in s) and (":" not in s):
                break
            for label, value in self._parse_capital_pairs(s):
                key = self._pure_chinese(label)
                if key:
                    capital[key] = value
        return capital

    # ---------------- | 分隔表格解析 ---------------- #
    def parse_pipe_table(self, lines: list, title_prefix: str):
        """切分以 title_prefix 开头的 | 分隔表格。

        表格结构: 标题行 -> 分隔线 -> |中文表头| -> |英文表头| -> 分隔线
        -> 数据行 -> 分隔线 -> |共 N 条| 汇总行 -> 分隔线 -> 图例。

        Args:
            lines: 文件行列表。
            title_prefix: 表格标题中文前缀。

        Returns:
            tuple: (中文表头列表, 数据行二维列表)；未找到表格时返回 (None, [])。
        """
        for idx, line in enumerate(lines):
            if not line.strip().startswith(title_prefix):
                continue
            header = None
            rows = []
            skip_english_header = False
            data_started = False
            for sub_line in lines[idx + 1 :]:
                s = sub_line.strip()
                if not s.startswith("|"):
                    if not data_started:
                        continue  # 表头之间的分隔线
                    break  # 数据行结束后遇到图例/空行，表格结束
                cells = [c.strip() for c in s.strip("|").split("|")]
                if header is None:
                    header = cells
                    skip_english_header = True  # 下一 | 行为英文表头，跳过
                    continue
                if skip_english_header:
                    skip_english_header = False
                    continue
                data_started = True
                if cells and ("共" in cells[0]) and ("条" in cells[0]):
                    break  # 汇总行，丢弃
                rows.append(cells)
            return header, rows
        return None, []

    def build_table_df(self, header: list, rows: list) -> pd.DataFrame:
        """由表头与数据行构建清洗后的 DataFrame。

        列名去除空格（受制表样式影响），行按表头列数对齐（补 None 防错位），
        删除全空行。

        Args:
            header: 中文表头列表。
            rows: 数据行二维列表。

        Returns:
            pd.DataFrame: 清洗后的表格数据。
        """
        width = len(header)
        aligned_rows = []
        for row in rows:
            if len(row) < width:
                row = row + [None] * (width - len(row))
            elif len(row) > width:
                row = row[:width]
            aligned_rows.append(row)
        df = pd.DataFrame(aligned_rows, columns=header)
        df.columns = [str(col).replace(" ", "").strip() for col in df.columns]
        df = df.dropna(how="all").reset_index(drop=True)
        return df

    @staticmethod
    def to_number(value):
        """数值字符串转 float，非数值（如风险度百分比）保持原样。"""
        if value is None:
            return None
        value = str(value).strip()
        if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
            return float(value)
        return value
