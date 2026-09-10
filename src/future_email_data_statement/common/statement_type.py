"""国君邮件对账单文件类型判断模块。

TestData / 邮件附件中的国君对账单 txt 共有三种类型，可同时从
「文件名资金账号前缀」与「文件内容特征」两个维度判断：

    1. 期货（盯市）: 资金账号 80/81/83/86 等开头（非 95/99）；
       标题含 "交易结算单(盯市)" / "Settlement Statement(MTM)"；
       资金状况含 期初结存 / 基础保证金 / 持仓盯市盈亏 等字段。
    2. 期权        : 资金账号 99 开头（自有账号）；
       资金状况含 权利仓市值 / 义务仓市值 / 维持保证金 等字段，
       明细表含 标的证券 / 备兑 等列。
    3. 证券现货    : 资金账号 95 开头；
       资金状况含 期初总资产 / 股票市值 / 买券金额 / 红利 等字段。

判断优先级：文件内容特征 > 文件名资金账号前缀 > 未知。
内容特征唯一性高（三种格式的资金状况字段互斥），文件名前缀仅作
内容缺失（如空文件）时的兜底；两者冲突时以内容为准并保留来源标记。
"""

import re
from typing import Optional

# 对账单类型（大类）
STATEMENT_FUTURES = "期货"
STATEMENT_OPTIONS = "期权"
STATEMENT_SECURITIES = "证券现货"

# 类型 -> 国君对账单内 statement_type 细分值
CATEGORY_TO_TYPE = {
    STATEMENT_FUTURES: "盯市",
    STATEMENT_OPTIONS: "期权",
    STATEMENT_SECURITIES: "证券现货",
}

# 账号前缀规则（按顺序匹配，命中即返回）
ACCOUNT_PREFIX_RULES = (
    (STATEMENT_SECURITIES, "95"),
    (STATEMENT_OPTIONS, "99"),
)

# 标题特征：唯一标识期货盯市结算单
FUTURE_TITLE_MARKERS = ("(盯市)", "Settlement Statement(MTM)")

# 资金状况 / 明细表字段特征（三类互斥，用于内容判断）
OPTION_FIELD_MARKERS = (
    "权利仓市值",
    "义务仓市值",
    "维持保证金",
    "备兑",
    "标的证券",
)
SECURITY_FIELD_MARKERS = (
    "期初总资产",
    "期末总资产",
    "股票市值",
    "买券金额",
    "卖券金额",
    "红利",
)
FUTURE_FIELD_MARKERS = (
    "期初结存",
    "基础保证金",
    "持仓盯市盈亏",
    "交割保证金",
    "多头期权市值",
    "空头期权市值",
)


def extract_account_id(file_name: Optional[str]) -> Optional[str]:
    """从文件名中提取资金账号。

    覆盖 "20260825_7070_9580029685_交易结算单.txt" 与 "80009387.txt"
    两类命名。规则：取所有长度 >=6 的数字串，先排除 20YYMMDD 形态的
    日期串（仅当存在其他候选时），再优先返回 95/99 开头的账号，
    最后取最长的数字串。

    Args:
        file_name: 文件名。

    Returns:
        str: 资金账号；未匹配到长数字串时返回 None。
    """
    if not file_name:
        return None
    runs = re.findall(r"\d{6,}", file_name)
    if not runs:
        return None

    def is_date_like(run: str) -> bool:
        return len(run) == 8 and run.startswith(("201", "202", "203"))

    candidates = [run for run in runs if not is_date_like(run)]
    if not candidates:
        candidates = runs
    for run in candidates:
        if run.startswith(("95", "99")):
            return run
    return max(candidates, key=len)


def detect_by_account_id(account_id: Optional[str]) -> Optional[str]:
    """按资金账号前缀判断对账单类型。

    Args:
        account_id: 资金账号（客户号/资金账号均可）。

    Returns:
        str: 期货 / 期权 / 证券现货；账号为空或前缀未知时返回 None。
    """
    if not account_id:
        return None
    account_id = str(account_id).strip()
    for category, prefix in ACCOUNT_PREFIX_RULES:
        if account_id.startswith(prefix):
            return category
    return STATEMENT_FUTURES


def detect_by_file_name(file_name: Optional[str]) -> Optional[str]:
    """按文件名判断对账单类型（提取资金账号后按前缀规则）。

    Args:
        file_name: 文件名。

    Returns:
        str: 期货 / 期权 / 证券现货；无法提取账号时返回 None。
    """
    return detect_by_account_id(extract_account_id(file_name))


def detect_by_content(lines) -> Optional[str]:
    """按文件内容特征判断对账单类型。

    规则：标题含 MTM 特征直接判定期货；否则按资金状况/明细表中的
    三类互斥字段特征计数，命中数量多者胜出；无任何特征返回 None。

    Args:
        lines: 文件行列表（read_txt_lines 读取结果）。

    Returns:
        str: 期货 / 期权 / 证券现货；无法判定时返回 None。
    """
    if not lines:
        return None
    scores = {
        STATEMENT_FUTURES: 0,
        STATEMENT_OPTIONS: 0,
        STATEMENT_SECURITIES: 0,
    }
    for line in lines:
        # 标题特征唯一指向期货盯市，直接返回
        if any(marker in line for marker in FUTURE_TITLE_MARKERS):
            return STATEMENT_FUTURES
        for marker in OPTION_FIELD_MARKERS:
            if marker in line:
                scores[STATEMENT_OPTIONS] += 1
        for marker in SECURITY_FIELD_MARKERS:
            if marker in line:
                scores[STATEMENT_SECURITIES] += 1
        for marker in FUTURE_FIELD_MARKERS:
            if marker in line:
                scores[STATEMENT_FUTURES] += 1
    category, max_score = None, 0
    for key, score in scores.items():
        if score > max_score:
            category, max_score = key, score
    return category if max_score > 0 else None


def detect_statement_type(
    lines=None,
    account_id: Optional[str] = None,
    file_name: Optional[str] = None,
) -> dict:
    """综合判断对账单类型（内容优先，文件名前缀兜底）。

    Args:
        lines: 文件行列表（优先，内容特征唯一性高）。
        account_id: 资金账号（次选，账号前缀规则）。
        file_name: 文件名（再次，用于提取账号）。

    Returns:
        dict: {
            category: 期货 / 期权 / 证券现货（None=未判定）,
            source: content / account_prefix / file_name_prefix / None,
            account_id: 用于判断的资金账号（可能为 None）,
            format: 盯市 / 期权 / 证券现货（对应 guojun 的 statement_type）,
        }
    """
    content_category = detect_by_content(lines)
    if content_category:
        source = "content"
        category = content_category
        used_account = account_id
    else:
        category = detect_by_account_id(account_id)
        if category:
            source = "account_prefix"
            used_account = account_id
        else:
            category = detect_by_file_name(file_name)
            source = "file_name_prefix" if category else None
            used_account = extract_account_id(file_name)
    return {
        "category": category,
        "source": source,
        "account_id": used_account,
        "format": CATEGORY_TO_TYPE.get(category),
    }
