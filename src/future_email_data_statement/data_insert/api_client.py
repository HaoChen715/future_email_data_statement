"""期货对账单 Open API 客户端。

替代原「直连数据库」方式，全部读写改由开发的 Open API 承接：

- GET  /openApi/billFutureApi/queryBrokerInit              券商列表
- GET  /openApi/billFutureApi/queryAccountList             指定日期有效账号
- GET  /openApi/billFutureApi/queryInsertSuccessAccountList 指定日期入库成功账号
- POST /openApi/billFutureApi/settlementFileInsert         整文件全量覆盖入库

入库接口为全量快照语义：服务端先按顶层 (tradingday, accountId) 删除 13 张业务表
旧数据，再写入各数组；因此调用方必须显式提交全部 13 个数组（缺失按空数组处理），
否则未提交类别的旧数据会被清空。处理日志由服务端在同一接口内维护。
"""

import hashlib
import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

# 网关鉴权（见 docs/apiDemo.py）：signature = md5(appKey + appSecret + timestamp)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
)


def _md5_encrypt(text: str) -> str:
    """MD5 十六进制摘要（与网关签名算法一致）。"""
    md5 = hashlib.md5()
    md5.update(text.encode("utf-8"))
    return md5.hexdigest()

# 数据库表名 -> 入库接口请求体数组字段名
TABLE_TO_REQUEST_FIELD = {
    "bill_future_settle_basic_info": "basicInfoList",
    "bill_future_settle_capital_info": "capitalInfoList",
    "bill_future_settle_cash_out_in_detail": "cashOutInDetailList",
    "bill_future_settle_trade_detail": "tradeDetailList",
    "bill_future_settle_closing_detail": "closingDetailList",
    "bill_future_settle_position_detail": "positionDetailList",
    "bill_future_settle_position_summary": "positionSummaryList",
    "bill_future_settle_option_exercise_detail": "optionExerciseDetailList",
    "bill_future_settle_option_trade_detail": "optionTradeDetailList",
    "bill_future_settle_option_position_change": "optionPositionChangeList",
    "bill_future_settle_option_position_summary": "optionPositionSummaryList",
    "bill_future_settle_option_position_detail": "optionPositionDetailList",
    "bill_future_settle_option_combination_position": "optionCombinationPositionList",
}

# 全部数组字段：入库为全量快照，缺失数组会被服务端清空，故每次显式提交全部 13 个
ALL_REQUEST_FIELDS = tuple(TABLE_TO_REQUEST_FIELD.values())

# 整型列（服务端对应 Integer）：JSON 必须为整数，避免 DataFrame 因缺失值转成 1.0
INTEGER_COLUMNS = {
    "lots", "position_lots", "long_position", "short_position",
    "exercise_volume", "change_volume",
    "long_volume", "single_long_volume", "combine_long_volume",
    "short_volume", "single_short_volume", "combine_short_volume",
    "volume", "single_volume", "combination_volume",
    "combination_leg_count", "volume1", "volume2",
}


def _to_camel(name: str) -> str:
    """snake_case 列名 -> 接口 camelCase 字段名（tradingday 保持原样）。"""
    parts = str(name).split("_")
    return parts[0] + "".join(
        part[:1].upper() + part[1:] for part in parts[1:]
    )


def _normalize_value(value, is_int: bool):
    """将 pandas/numpy 标量转为可 JSON 序列化的 Python 原生值，缺失转 None。"""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if is_int:
        return int(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _frame_records(df: pd.DataFrame) -> list:
    """DataFrame -> 接口请求体行对象列表（列名转 camelCase，缺失值转 None）。"""
    records = []
    for _, row in df.iterrows():
        record = {}
        for column in df.columns:
            record[_to_camel(column)] = _normalize_value(
                row[column], column in INTEGER_COLUMNS
            )
        records.append(record)
    return records


class BillFutureApiClient:
    """期货对账单 Open API 轻量客户端（基于标准库 urllib，无额外依赖）。

    网关鉴权头与 docs/apiDemo.py 一致：
        signature = md5(appKey + appSecret + timestamp)，单位为毫秒，
        每次请求即时生成，随 appKey / timestamp 一起放入请求头。
    """

    BROKER_INIT_PATH = "/openApi/billFutureApi/queryBrokerInit"
    ACCOUNT_LIST_PATH = "/openApi/billFutureApi/queryAccountList"
    SUCCESS_ACCOUNT_PATH = "/openApi/billFutureApi/queryInsertSuccessAccountList"
    FILE_INSERT_PATH = "/openApi/billFutureApi/settlementFileInsert"

    def __init__(
        self,
        logger,
        base_url: str = "",
        timeout: int = 30,
        app_key: str = "",
        app_secret: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        verify_ssl: bool = True,
    ):
        """初始化 API 客户端。

        Args:
            logger: 日志记录器。
            base_url: Open API 基础地址（含上下文路径，可含结尾斜杠）。
            timeout: 请求超时秒数。
            app_key: 网关 appKey。
            app_secret: 网关 appSecret。
            user_agent: 请求 User-Agent。
            verify_ssl: 是否校验 HTTPS 证书（内网自签证书时设为 False）。
        """
        self.logger = logger
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = int(timeout) if timeout else 30
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        # 内网自签证书场景（对应 apiDemo 的 verify=False）跳过证书校验
        self.ssl_context = None
        if not verify_ssl:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
        if not self.base_url:
            raise ValueError(
                "未配置入库 API 地址，请在 config/info.ini 对应环境段填写 base_url"
            )
        if not self.app_key or not self.app_secret:
            raise ValueError(
                "未配置 API 鉴权，请在 config/info.ini 对应环境段填写 app_key / app_secret"
            )

    def _sign(self) -> dict:
        """生成网关鉴权头（每次请求即时计算，避免时间戳过期）。"""
        timestamp = int(time.time() * 1000)
        signature = _md5_encrypt(f"{self.app_key}{self.app_secret}{timestamp}")
        return {
            "appKey": self.app_key,
            "signature": signature,
            "timestamp": str(timestamp),
        }

    def _request(self, method: str, path: str, params: dict = None,
                 body: dict = None) -> dict:
        """发起 HTTP 请求并解析统一 Result 响应。

        Args:
            method: HTTP 方法（GET / POST）。
            path: 接口路径（以 / 开头）。
            params: 查询字符串参数。
            body: JSON 请求体。

        Returns:
            dict: 服务端返回的 Result 结构。

        Raises:
            RuntimeError: 网络错误或响应无法解析时抛出。
        """
        url = self.base_url + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Content-Type": "application/json;charset=utf-8",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        headers.update(self._sign())
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self.ssl_context
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore") if e.fp else ""
            raise RuntimeError(f"HTTP {e.code} {e.reason} {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络请求失败: {e.reason}") from e
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"响应非合法 JSON: {raw[:200]}") from e

    @staticmethod
    def _result(payload: dict):
        """校验 Result 成功标志并取出 result；失败时抛出 RuntimeError。"""
        if payload.get("success") is False:
            raise RuntimeError(
                payload.get("message") or f"接口返回失败(code={payload.get('code')})"
            )
        return payload.get("result")

    def query_broker_init(self) -> list:
        """查询券商列表（对应 SQL 3.1）。

        Returns:
            list: 去重后的 broker_id 字符串列表。
        """
        payload = self._request("GET", self.BROKER_INIT_PATH)
        result = self._result(payload) or []
        return [str(broker) for broker in result]

    def query_account_list(self, tradingday: str) -> list:
        """查询指定日期有效账号配置（对应 SQL 3.2）。

        Args:
            tradingday: 交易日（YYYYMMDD）。

        Returns:
            list: ConfigBillFutureAccountDTO 字典列表（camelCase）。
        """
        payload = self._request(
            "GET", self.ACCOUNT_LIST_PATH, params={"tradingday": tradingday}
        )
        return self._result(payload) or []

    def query_insert_success_account_list(
        self,
        tradingday: str,
        account_type: str = "期货",
        log_type: str = "对账单数据",
        log_status: str = "Success",
    ) -> set:
        """查询指定日期已成功入库账号（对应 SQL 4.2(2)，断点续跑用）。

        Args:
            tradingday: 交易日（YYYYMMDD）。
            account_type: 账户类型，默认「期货」。
            log_type: 日志类型，默认「对账单数据」。
            log_status: 日志状态，默认 Success。

        Returns:
            set: 已成功入库的 account_id 字符串集合。
        """
        payload = self._request(
            "GET",
            self.SUCCESS_ACCOUNT_PATH,
            params={
                "tradingday": tradingday,
                "accountType": account_type,
                "logType": log_type,
                "logStatus": log_status,
            },
        )
        return {str(account) for account in (self._result(payload) or [])}

    def settlement_file_insert(
        self, tradingday: str, account_id: str, table_frames: dict
    ) -> tuple:
        """整文件全量覆盖入库（对应 SQL 4.1 + 4.2(3)，服务端单事务先删后插）。

        Args:
            tradingday: 顶层交易日（YYYYMMDD）。
            account_id: 顶层资金账号。
            table_frames: {数据库表名: 待入库 DataFrame}。

        Returns:
            tuple: (是否成功, 结果信息)。服务端会同步写入处理日志。
        """
        body = {"tradingday": str(tradingday), "accountId": str(account_id)}
        # 全量快照：先填满全部数组为空，再用实际数据覆盖，避免误清空未提交类别
        for field in ALL_REQUEST_FIELDS:
            body[field] = []
        for table_name, df in table_frames.items():
            field = TABLE_TO_REQUEST_FIELD.get(table_name)
            if field is None or df is None or df.empty:
                continue
            body[field] = _frame_records(df)
        try:
            payload = self._request("POST", self.FILE_INSERT_PATH, body=body)
        except Exception as e:
            self.logger.error(f"入库接口调用失败: {type(e).__name__}: {e}")
            return False, f"API入库失败: {type(e).__name__}: {e}"
        if payload.get("success") is False:
            message = payload.get("message") or f"code={payload.get('code')}"
            self.logger.error(f"入库接口返回失败: {message}")
            return False, f"API入库失败: {message}"
        result = payload.get("result") or {}
        total = result.get("totalRecordCount")
        message = result.get("message") or payload.get("message") or "期货对账单入库成功"
        return True, f"{message}({total if total is not None else 0} 行)"
