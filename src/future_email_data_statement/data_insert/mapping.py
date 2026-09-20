"""对账单清洗结果 -> 数据库表 的映射规则。

按「券商模板 + 对账单类型(statement_type) + 清洗板块」确定目标表与列映射：

- 基本资料 / 资金状况：清洗层已是英文列名，仅需把 trading_day 改为 tradingday；
- 明细表：清洗层为中文表头，需按 docs/数据库表结构设计.md 第 4 节映射为英文列；
- 盯市持仓明细/持仓汇总 源表无日期列，由文件头交易日注入 tradingday；
- 期权与盯市的 成交记录/持仓明细/持仓汇总 列结构不同，必须按 statement_type 路由。

新增券商时，在此登记 TEMPLATE_MAP 与 TABLE_RULES 即可，入库逻辑无需改动。
"""

import pandas as pd

# 账号 broker_id -> 清洗/入库模板名（国君、国泰海通实际为同一家，共用模板）
TEMPLATE_MAP = {
    "国君": "guojun",
    "国泰海通": "guojun",
}

# 清洗层对账单类型 -> 入库存储值（盯市实际即期货数据，统一存为“期货”）
STATEMENT_TYPE_STORE_MAP = {
    "盯市": "期货",
    "标准": "期货",
    "期权": "期权",
    "证券现货": "证券现货",
}

# 期货（盯市）明细表：清洗中文表头 -> 数据库列名
# tradingday 取自表内日期列；持仓类无日期列，由文件头注入（见 inject_tradingday）
GUOJUN_COMMON_RULES = {
    "基本资料": {
        "table": "bill_future_settle_basic_info",
        "rename": {"trading_day": "tradingday"},
        "keep_all_columns": True,
    },
    "资金状况": {
        "table": "bill_future_settle_capital_info",
        "rename": {"trading_day": "tradingday"},
        "keep_all_columns": True,
    },
}

GUOJUN_DETAIL_RULES = {
    "盯市": {
        "出入金明细": {
            "table": "bill_future_settle_cash_out_in_detail",
            "rename": {
                "发生日期": "tradingday",
                "出入金类型": "transfer_type",
                "入金": "deposit",
                "出金": "withdrawal",
                "汇率": "exchange_rate",
                "说明": "note",
                "资金账号": "account_id",
            },
        },
        "成交记录": {
            "table": "bill_future_settle_trade_detail",
            "rename": {
                "成交日期": "tradingday",
                "投资单元": "invest_unit",
                "交易所": "exchange",
                "交易编码": "trading_code",
                "品种": "product",
                "合约": "instrument",
                "买/卖": "buy_or_sell",
                "投/保": "speculation_or_hedge",
                "成交价": "price",
                "手数": "lots",
                "成交额": "turnover",
                "开平": "open_or_close",
                "手续费": "fee",
                "平仓盈亏": "realized_profit_loss",
                "权利金收支": "premium_received_paid",
                "成交序号": "transaction_number",
                "资金账号": "account_id",
            },
        },
        "平仓明细": {
            "table": "bill_future_settle_closing_detail",
            "rename": {
                "平仓日期": "tradingday",
                "投资单元": "invest_unit",
                "交易所": "exchange",
                "交易编码": "trading_code",
                "品种": "product",
                "合约": "instrument",
                "开仓日期": "open_date",
                "投/保": "speculation_or_hedge",
                "买/卖": "buy_or_sell",
                "手数": "lots",
                "开仓价": "position_open_price",
                "昨结算": "previous_settlement",
                "成交价": "transaction_price",
                "平仓盈亏": "realized_profit_loss",
                "权利金收支": "premium_received_paid",
                "资金账号": "account_id",
            },
        },
        "持仓明细": {
            "table": "bill_future_settle_position_detail",
            "inject_tradingday": True,
            "rename": {
                "投资单元": "invest_unit",
                "交易所": "exchange",
                "交易编码": "trading_code",
                "品种": "product",
                "合约": "instrument",
                "开仓日期": "open_date",
                "投/保": "speculation_or_hedge",
                "买/卖": "buy_or_sell",
                "持仓量": "position_lots",
                "开仓价": "position_open_price",
                "昨结算": "previous_settlement",
                "结算价": "settlement_price",
                "浮动盈亏": "accumulated_profit_loss",
                "盯市盈亏": "mark_to_market_profit_loss",
                "保证金": "margin",
                "期权市值": "option_market_value",
                "资金账号": "account_id",
            },
        },
        "持仓汇总": {
            "table": "bill_future_settle_position_summary",
            "inject_tradingday": True,
            "rename": {
                "投资单元": "invest_unit",
                "交易编码": "trading_code",
                "品种": "product",
                "合约": "instrument",
                "买持": "long_position",
                "买开仓均价": "average_buy_price",
                "卖持": "short_position",
                "卖开仓均价": "average_sell_price",
                "昨结算": "previous_settlement",
                "今结算": "settlement_today",
                "持仓盯市盈亏": "mark_to_market_profit_loss",
                "保证金占用": "margin_occupied",
                "投/保": "speculation_or_hedge",
                "多头期权市值": "long_market_value",
                "空头期权市值": "short_market_value",
                "资金账号": "account_id",
            },
        },
        "行权明细": {
            "table": "bill_future_settle_option_exercise_detail",
            "rename": {
                "成交日期": "tradingday",
                "投资单元": "invest_unit",
                "交易所": "exchange",
                "交易编码": "trading_code",
                "品种": "product",
                "合约": "instrument",
                "投/保": "speculation_or_hedge",
                "买/卖": "buy_or_sell",
                "是否行权": "exercise_flag",
                "行权数量": "exercise_volume",
                "行权价格": "exercise_price",
                "行权金额": "exercise_amount",
                "行权盈亏": "exercise_profit_loss",
                "行权手续费": "exercise_fee",
                "资金账号": "account_id",
            },
        },
    },
    "期权": {
        "成交记录": {
            "table": "bill_future_settle_option_trade_detail",
            "rename": {
                "资金账号": "account_id",
                "交易日期": "tradingday",
                "交易所": "exchange",
                "标的证券": "underlying",
                "合约编码": "instrument_code",
                "合约代码": "instrument_id",
                "成交编号": "trade_id",
                "买/卖": "buy_or_sell",
                "开/平": "open_or_close",
                "备兑": "cover",
                "成交价": "price",
                "手数": "lots",
                "成交额": "turnover",
                "权利金收支": "premium_received_paid",
                "经手费": "handling_fee",
                "结算费": "settlement_fee",
            },
        },
        "持仓明细": {
            "table": "bill_future_settle_option_position_detail",
            "rename": {
                "资金账号": "account_id",
                "交易日期": "tradingday",
                "交易所": "exchange",
                "标的证券": "underlying",
                "合约编码": "instrument_code",
                "合约代码": "instrument_id",
                "备兑": "cover",
                "持仓方向": "position_direction",
                "开仓日期": "open_date",
                "成交编号": "trade_id",
                "开仓价": "open_price",
                "持仓量": "volume",
                "未参与组合数量": "single_volume",
                "参与组合数量": "combination_volume",
                "今结算": "settlement_today",
            },
        },
        "持仓汇总": {
            "table": "bill_future_settle_option_position_summary",
            "rename": {
                "资金账号": "account_id",
                "交易日期": "tradingday",
                "交易所": "exchange",
                "标的证券": "underlying",
                "合约编码": "instrument_code",
                "合约代码": "instrument_id",
                "备兑": "cover",
                "权利仓数量": "long_volume",
                "未组合权利仓数量": "single_long_volume",
                "组合权利仓数量": "combine_long_volume",
                "义务仓数量": "short_volume",
                "未组合义务仓数量": "single_short_volume",
                "组合义务仓数量": "combine_short_volume",
                "保证金占用": "margin_occupied",
                "今结算": "settlement_today",
                "权利仓市值": "long_market_value",
                "义务仓市值": "short_market_value",
            },
        },
        "持仓变动": {
            "table": "bill_future_settle_option_position_change",
            "rename": {
                "资金账号": "account_id",
                "交易日期": "tradingday",
                "交易所": "exchange",
                "标的证券": "underlying",
                "合约编码": "instrument_code",
                "合约代码": "instrument_id",
                "备兑": "cover",
                "持仓方向": "position_direction",
                "变动数量": "change_volume",
                "变动类型": "change_type",
            },
        },
        "组合持仓": {
            "table": "bill_future_settle_option_combination_position",
            "rename": {
                "资金账号": "account_id",
                "交易日期": "tradingday",
                "交易所": "exchange",
                "组合编号": "combination_number",
                "组合策略编码": "combination_strategy_code",
                "持仓量": "volume",
                "保证金占用": "margin_occupied",
                "组合成分数量": "combination_leg_count",
                "合约编码一": "instrument_code1",
                "合约代码一": "instrument_id1",
                "备兑一": "cover1",
                "持仓方向一": "position_direction1",
                "持仓量一": "volume1",
                "合约编码二": "instrument_code2",
                "合约代码二": "instrument_id2",
                "备兑二": "cover2",
                "持仓方向二": "position_direction2",
                "持仓量二": "volume2",
            },
        },
    },
    # 证券现货当前样本仅含 基本资料 + 资金状况，明细表结构待样本补充
    "证券现货": {},
}

TABLE_RULES = {
    "guojun": {
        "common": GUOJUN_COMMON_RULES,
        "detail": GUOJUN_DETAIL_RULES,
    },
}

# 数值列（DECIMAL / INT）：统一 to_numeric，避免空串/'-' 入库报错
NUMERIC_COLUMNS = {
    # 资金状况
    "last_day_balance", "balance", "customer_equity", "deposit_withdrawal",
    "commission", "maintenance_margin", "premium_received", "premium_paid",
    "available_funds", "initial_margin", "margin_call",
    "long_option_market_value", "short_option_market_value",
    "market_value_equity", "strike_frozen_sum", "strike_receivable",
    "strike_payable", "received_sum_by_cash", "paid_sum_by_cash",
    "closing_profit_loss", "floating_profit_loss",
    "option_exercise_profit_loss", "delivery_profit_loss", "pledge_amount",
    "fx_pledge_occupancy", "margin_occupancy", "delivery_margin",
    "new_fx_pledge", "fx_redemption", "change_in_pledge_amount",
    "change_in_fx_pledge", "total_assets_brought_forward",
    "total_assets_carried_forward", "fund_balance_brought_forward",
    "fund_balance_carried_forward", "stock_market_value", "open_preparation",
    "fund_withdrawal", "fund_frozen", "interest", "buy_security_payment",
    "sell_security_income", "actual_payment", "bonus",
    # 出入金
    "deposit", "withdrawal", "exchange_rate",
    # 成交 / 平仓 / 持仓
    "price", "lots", "turnover", "fee", "realized_profit_loss",
    "premium_received_paid", "position_open_price", "previous_settlement",
    "transaction_price", "position_lots", "settlement_price",
    "accumulated_profit_loss", "mark_to_market_profit_loss", "margin",
    "option_market_value", "long_position", "average_buy_price",
    "short_position", "average_sell_price", "settlement_today",
    "margin_occupied", "long_market_value", "short_market_value",
    # 行权
    "exercise_volume", "exercise_price", "exercise_amount",
    "exercise_profit_loss", "exercise_fee",
    # 期权
    "handling_fee", "settlement_fee", "change_volume",
    "long_volume", "single_long_volume", "combine_long_volume",
    "short_volume", "single_short_volume", "combine_short_volume",
    "open_price", "volume", "single_volume", "combination_volume",
    "combination_leg_count", "volume1", "volume2",
}


def build_table_frames(template: str, broker: str, frames: dict) -> dict:
    """将单个文件的清洗结果映射为 {数据库表名: DataFrame}。

    Args:
        template: 券商模板名（如 guojun）。
        broker: 账号实际券商（资源目录名），写入基本资料 broker 列。
        frames: {清洗板块: DataFrame}。

    Returns:
        dict: {数据库表名: 待入库 DataFrame}；无法识别的板块会被忽略。
    """
    rules = TABLE_RULES.get(template)
    if rules is None:
        return {}

    basic = frames.get("基本资料")
    if basic is None or basic.empty:
        return {}
    statement_type = str(basic.iloc[0]["statement_type"])
    trading_day = str(basic.iloc[0]["trading_day"])

    section_rules = dict(rules["common"])
    section_rules.update(rules["detail"].get(statement_type, {}))

    table_frames = {}
    for section, rule in section_rules.items():
        df = frames.get(section)
        if df is None or df.empty:
            continue
        mapped = df.rename(columns=rule["rename"])
        # 用 assign 生成新对象，避免对 DataFrame 就地赋值：pandas 3.0 的链式
        # 赋值检测在 Cython 编译后的函数里会因取不到局部变量而误报
        extras = {}
        if section == "基本资料":
            extras["broker"] = broker
        # 无日期列的板块（如盯市持仓明细/汇总）由文件头交易日注入 tradingday
        if rule.get("inject_tradingday"):
            extras["tradingday"] = trading_day
        if extras:
            mapped = mapped.assign(**extras)
        # 明细表仅保留映射后的目标列，避免清洗层的多余中文列导致入库失败
        if not rule.get("keep_all_columns"):
            allowed = list(rule["rename"].values())
            if rule.get("inject_tradingday"):
                allowed.append("tradingday")
            mapped = mapped[
                [column for column in allowed if column in mapped.columns]
            ]
        # 逐列生成结果（数值转换 / 字符串去空格），最后整体构造新 DataFrame
        result_columns = {}
        for column in mapped.columns:
            if column in NUMERIC_COLUMNS:
                result_columns[column] = pd.to_numeric(
                    mapped[column], errors="coerce"
                )
            else:
                result_columns[column] = mapped[column].map(
                    lambda value: str(value).strip() if pd.notna(value) else None
                )
        # 存入数据库时把 盯市/标准 归一为 期货
        if "statement_type" in result_columns:
            result_columns["statement_type"] = result_columns[
                "statement_type"
            ].map(
                lambda value: STATEMENT_TYPE_STORE_MAP.get(
                    str(value), str(value)
                )
            )
        table_frames[rule["table"]] = pd.DataFrame(result_columns).reset_index(
            drop=True
        )
    return table_frames
