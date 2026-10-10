# 对账单程序 数据表与 SQL 清单（API 对接用）

> 用途：交付 DBA，作为将「程序直连数据库入库」改为「通过 API 入库」的接口设计依据。
> 本文为**自包含**文档：列出程序当前访问的**全部数据库对象**与**全部 SQL 语句**、
> 各表**全部字段 DDL**，以及由这些语句推导出的 API 接口需求。无需再提供其他 SQL 文件。

## 一、总体说明

- 数据库：MySQL 8.x（程序使用 `mysql+pymysql` 连接）。
- 程序涉及两类数据库操作：
  1. **读**：查询账号/券商配置视图（账号匹配、目录初始化）；
  2. **写**：对账单业务表「先删后插」+ 入库处理日志表。
- 当前写操作为**直连数据库、以「文件」为一个事务**（任一步失败整体回滚）。
  改造后这些写操作应由 API 承接，程序不再直连业务库。
- 日期格式统一为 `CHAR(8)` / `YYYYMMDD`。

## 二、数据库对象总览

| 对象名 | 类型 | 程序用途 | 操作 |
|--------|------|----------|------|
| `v_config_bill_future_account` | 视图（外部已有） | 账号有效期过滤、券商列表 | 读 |
| `bill_future_settle_basic_info` | 表 | 基本资料 | 删 + 插 |
| `bill_future_settle_capital_info` | 表 | 资金状况（三格式统一宽表） | 删 + 插 |
| `bill_future_settle_cash_out_in_detail` | 表 | 出入金明细 | 删 + 插 |
| `bill_future_settle_trade_detail` | 表 | 期货成交记录 | 删 + 插 |
| `bill_future_settle_closing_detail` | 表 | 期货平仓明细 | 删 + 插 |
| `bill_future_settle_position_detail` | 表 | 期货持仓明细 | 删 + 插 |
| `bill_future_settle_position_summary` | 表 | 期货持仓汇总 | 删 + 插 |
| `bill_future_settle_option_exercise_detail` | 表 | 商品期权行权明细 | 删 + 插 |
| `bill_future_settle_option_trade_detail` | 表 | 期权成交记录（ETF 期权） | 删 + 插 |
| `bill_future_settle_option_position_change` | 表 | 期权持仓变动 | 删 + 插 |
| `bill_future_settle_option_position_summary` | 表 | 期权持仓汇总 | 删 + 插 |
| `bill_future_settle_option_position_detail` | 表 | 期权持仓明细 | 删 + 插 |
| `bill_future_settle_option_combination_position` | 表 | 期权组合持仓 | 删 + 插 |
| `bill_future_settle_processing_log` | 表 | 入库处理日志（断点续跑） | 删 + 查 + 插 |

> 说明：13 张 `bill_future_settle_*` 业务表 + 1 张日志表均由本项目建表脚本创建；
> 视图 `v_config_bill_future_account` 为外部系统已有，程序只读。

## 三、读操作（查询语句）

### 3.1 查询券商列表（启动初始化 `BrokerInit`）

```sql
SELECT DISTINCT broker_id FROM v_config_bill_future_account
```

使用字段：`broker_id`。用于按券商预建资源目录。

### 3.2 查询当日有效期货账号（账号匹配 `CheckAccountFile`）

```sql
SELECT *
FROM v_config_bill_future_account
WHERE start_date <= {running_day}
  AND end_date   >= {previous_trading_day}
```

- 参数：`running_day`=运行日（YYYYMMDD），`previous_trading_day`=上一交易日（YYYYMMDD）。
- 程序使用字段：`future_account_id`（资金账号）、`broker_id`（券商）、
  `start_date` / `end_date`（有效期）、`remark`（含「销户」的账号自动跳过）。
- 该查询在应用层还会再次过滤 `remark` 含「销户」的行，API 可保留原始字段返回。

### 3.3 获取数据库当前时间（连接建立时）

```sql
SELECT CURRENT_TIMESTAMP
```

- 程序每次建立数据库连接后执行，用于获取数据库时间（当前仅记录，未参与业务写入）。
- 若 API 化后不再直连库，此语句可一并移除或由健康检查接口替代。

## 四、写操作（入库 SQL）

### 4.1 业务数据表：整文件「先删后插」

每入库一个对账单文件，程序对涉及到的每张业务表执行：

```sql
-- 按表内实际出现的 (tradingday, account_id) 组合逐组删除
DELETE FROM {table_name}
WHERE tradingday = :tradingday
  AND account_id = :account_id;
```

删除后批量追加插入（pandas `to_sql(..., if_exists="append")` 生成的批量 INSERT）：

```sql
INSERT INTO {table_name} (col1, col2, ..., colN)
VALUES (...), (...), ...;
```

**关键约束**

- `{table_name}` 为下表之一，非用户输入、由程序模板映射产生。
- 删除维度：`(tradingday, account_id)`（注意：部分明细表中一个账号在同一天有多行，
  删除需覆盖该账号当日**该表全部行**后再整体重插）。
- 插入列：除自增主键 `id`、默认值列 `insert_time` 外，清洗/映射产生的全部业务列。
- **事务范围**：一个对账单文件涉及的多张表为**一个事务**，任一步失败整体回滚，
  避免半入库。
- 幂等语义：同一文件重复提交应等价于「覆盖」，即先按 `(tradingday, account_id)`
  删除旧数据再写入新数据。

**13 张业务表清单（表名与 DDL 章节对应）**

| 序号 | 表名 | 说明 | 删除键 |
|------|------|------|--------|
| 1 | `bill_future_settle_basic_info` | 基本资料 | `(tradingday, account_id)` |
| 2 | `bill_future_settle_capital_info` | 资金状况 | `(tradingday, account_id)` |
| 3 | `bill_future_settle_cash_out_in_detail` | 出入金明细 | `(tradingday, account_id)` |
| 4 | `bill_future_settle_trade_detail` | 期货成交记录 | `(tradingday, account_id)` |
| 5 | `bill_future_settle_closing_detail` | 期货平仓明细 | `(tradingday, account_id)` |
| 6 | `bill_future_settle_position_detail` | 期货持仓明细 | `(tradingday, account_id)` |
| 7 | `bill_future_settle_position_summary` | 期货持仓汇总 | `(tradingday, account_id)` |
| 8 | `bill_future_settle_option_exercise_detail` | 商品期权行权明细 | `(tradingday, account_id)` |
| 9 | `bill_future_settle_option_trade_detail` | 期权成交记录 | `(tradingday, account_id)` |
| 10 | `bill_future_settle_option_position_change` | 期权持仓变动 | `(tradingday, account_id)` |
| 11 | `bill_future_settle_option_position_summary` | 期权持仓汇总 | `(tradingday, account_id)` |
| 12 | `bill_future_settle_option_position_detail` | 期权持仓明细 | `(tradingday, account_id)` |
| 13 | `bill_future_settle_option_combination_position` | 期权组合持仓 | `(tradingday, account_id)` |

字段级定义见本文**第八节 建表 DDL**。
各表共有：自增主键 `id`，以及自动维护的 `insert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
（API 侧写入时无需程序传值）。

### 4.2 入库处理日志表 `bill_future_settle_processing_log`

该表用于**断点续跑**：记录每个交易日每个账号的入库状态。程序执行三类语句：

**（1）清理当日失败日志（失败账号本次重新入库）**

```sql
DELETE FROM bill_future_settle_processing_log
WHERE tradingday    = :tradingday
  AND account_type  = '期货'
  AND log_type      = '对账单数据'
  AND log_status    = 'Failed';
```

**（2）查询当日已成功入库账号（重跑跳过）**

```sql
SELECT DISTINCT account_id
FROM bill_future_settle_processing_log
WHERE tradingday    = :tradingday
  AND account_type  = '期货'
  AND log_type      = '对账单数据'
  AND log_status    = 'Success';
```

**（3）写入/覆盖单个账号状态（先删后插）**

```sql
DELETE FROM bill_future_settle_processing_log
WHERE tradingday = :tradingday
  AND account_id = :account_id
  AND log_type   = '对账单数据';

INSERT INTO bill_future_settle_processing_log
    (tradingday, account_id, account_type, log_type,
     log_time, log_date, log_status, log_info)
VALUES
    (:tradingday, :account_id, '期货', '对账单数据',
     :log_time, :log_date, :log_status, :log_info);
```

- 固定取值：`account_type='期货'`，`log_type='对账单数据'`。
- `log_time` 格式 `YYYY-MM-DD HH:MM:SS`；`log_date` 格式 `YYYYMMDD`；
  `log_status` 为 `Success` / `Failed`；`log_info` 为成功信息或失败原因（TEXT）。
- 同一 `(tradingday, account_id, log_type)` 仅保留最新一条状态。

## 五、字段清单（API 参数设计参考）

以下为程序写入时实际提供的列（自增 `id`、`insert_time` 由数据库维护，无需传）。
API 请求体可据此设计，列名与数据库列名一致。

- **basic_info**：`tradingday, account_id, client_id, client_name, broker,
  statement_type, creation_date, file_name`
- **capital_info**：`tradingday, account_id, statement_type` + 资金字段宽表，
  完整字段见第八节第 2 张表 DDL（按对账单类型仅部分字段有值，其余为 `NULL`）
- **cash_out_in_detail**：`tradingday, account_id, transfer_type, deposit,
  withdrawal, exchange_rate, note`
- **trade_detail**：`tradingday, account_id, invest_unit, exchange, trading_code,
  product, instrument, buy_or_sell, speculation_or_hedge, price, lots, turnover,
  open_or_close, fee, realized_profit_loss, premium_received_paid, transaction_number`
- **closing_detail**：`tradingday, account_id, invest_unit, exchange, trading_code,
  product, instrument, open_date, speculation_or_hedge, buy_or_sell, lots,
  position_open_price, previous_settlement, transaction_price,
  realized_profit_loss, premium_received_paid`
- **position_detail**：`tradingday, account_id, invest_unit, exchange, trading_code,
  product, instrument, open_date, speculation_or_hedge, buy_or_sell, position_lots,
  position_open_price, previous_settlement, settlement_price,
  accumulated_profit_loss, mark_to_market_profit_loss, margin, option_market_value`
- **position_summary**：`tradingday, account_id, invest_unit, trading_code,
  product, instrument, long_position, average_buy_price, short_position,
  average_sell_price, previous_settlement, settlement_today,
  mark_to_market_profit_loss, margin_occupied, speculation_or_hedge,
  long_market_value, short_market_value`
- **option_exercise_detail**：`tradingday, account_id, invest_unit, exchange,
  trading_code, product, instrument, speculation_or_hedge, buy_or_sell,
  exercise_flag, exercise_volume, exercise_price, exercise_amount,
  exercise_profit_loss, exercise_fee`
- **option_trade_detail**：`tradingday, account_id, exchange, underlying,
  instrument_code, instrument_id, trade_id, buy_or_sell, open_or_close, cover,
  price, lots, turnover, premium_received_paid, handling_fee, settlement_fee`
- **option_position_change**：`tradingday, account_id, exchange, underlying,
  instrument_code, instrument_id, cover, position_direction, change_volume,
  change_type`
- **option_position_summary**：`tradingday, account_id, exchange, underlying,
  instrument_code, instrument_id, cover, long_volume, single_long_volume,
  combine_long_volume, short_volume, single_short_volume, combine_short_volume,
  margin_occupied, settlement_today, long_market_value, short_market_value`
- **option_position_detail**：`tradingday, account_id, exchange, underlying,
  instrument_code, instrument_id, cover, position_direction, open_date, trade_id,
  open_price, volume, single_volume, combination_volume, settlement_today`
- **option_combination_position**：`tradingday, account_id, exchange,
  combination_number, combination_strategy_code, volume, margin_occupied,
  combination_leg_count, instrument_code1, instrument_id1, cover1,
  position_direction1, volume1, instrument_code2, instrument_id2, cover2,
  position_direction2, volume2`

> 数值列由程序统一转为数值类型（DECIMAL/INT），空串/`-` 转为 `NULL`；
> 字符列去除首尾空格，缺失值转为 `NULL`。

## 六、由 SQL 推导的 API 接口需求（建议）

> 以下为按当前程序行为推导的最小接口集合，最终以 DBA 设计为准。

| 接口 | 方法 | 对应 SQL | 说明 |
|------|------|----------|------|
| 查询券商列表 | GET | 3.1 | 返回 `broker_id` 列表 |
| 查询有效账号 | GET | 3.2 | 入参 `running_day`、`previous_trading_day`，返回账号配置 |
| 整文件入库 | POST | 4.1 | 请求体含 `tradingday`、`account_id`、`{表名: [行对象]}`；服务端在**单事务**内先删后插 |
| 查询已成功账号 | GET | 4.2(2) | 入参 `tradingday`，返回 `account_id` 列表 |
| 清理失败日志 | DELETE | 4.2(1) | 入参 `tradingday`，服务端按固定 `account_type/log_type` 清理 Failed |
| 写处理日志 | POST | 4.2(3) | 入参账号状态；服务端按 `(tradingday, account_id, log_type)` 先删后插 |

**接口设计要点**

1. **事务性**：`整文件入库` 必须在服务端单事务内完成多表删除与插入，且失败回滚；
   程序侧当前也正是「一文件一事务」。
2. **幂等性**：重复提交同一文件应覆盖当日该账号该表数据，不得产生重复行。
3. **先删后插的维度**：删除依据 `(tradingday, account_id)`；`tradingday` 必须取自
   请求体（部分明细表的交易日列名与表头不同，程序已在入库前统一为 `tradingday`）。
4. **提交单位**：以一个对账单文件为单位（一次请求可含多张表），而非单表或单行。
5. **返回结构**：需返回明确的成功/失败标志与可读信息，程序据此写 `log_status`
   （`Success`/`Failed`）与 `log_info`。
6. **字符集**：`utf8mb4`，中文券商名（如「国君」「国泰海通」）需正确传输。

## 七、程序侧使用位置（便于对照排查）

| 语句/操作 | 源文件 |
|-----------|--------|
| 券商列表查询 | `src/future_email_data_statement/datainit/broker_init.py:51` |
| 有效账号查询 | `src/future_email_data_statement/account_match/check_file.py:44` |
| `SELECT CURRENT_TIMESTAMP` | `src/future_email_data_statement/config/globalfunc.py:92` |
| 业务表先删后插 | `src/future_email_data_statement/data_insert/db_writer.py:30` |
| 日志表删除/查询/写入 | `src/future_email_data_statement/data_insert/processing_log.py:30,55,83` |
| 表名/列名映射 | `src/future_email_data_statement/data_insert/mapping.py` |

## 八、建表 DDL（含全部字段）

> MySQL 8.x，字符集 `utf8mb4` / `utf8mb4_general_ci`。
> `id` 为自增主键、`insert_time` 由数据库默认值维护，API 写入时均无需程序传值。

### 1. 基本资料

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_basic_info (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday      CHAR(8)         NOT NULL                COMMENT '交易日 Date',
    account_id      VARCHAR(32)     NOT NULL                COMMENT '资金账号（资金状况块资金账号）',
    client_id       VARCHAR(32)     DEFAULT NULL            COMMENT '客户号 Client ID',
    client_name     VARCHAR(128)    DEFAULT NULL            COMMENT '客户名称 Client Name',
    broker          VARCHAR(32)     NOT NULL                COMMENT '券商',
    statement_type  VARCHAR(16)     NOT NULL                COMMENT '对账单类型：期货/期权/证券现货（盯市入库归一为期货）',
    creation_date   CHAR(8)         DEFAULT NULL            COMMENT '制表日期 Creation Date',
    file_name       VARCHAR(255)    DEFAULT NULL            COMMENT '源文件名',
    insert_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_tradingday_account (tradingday, account_id),
    KEY idx_account_id (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-基本资料表';
```

### 2. 资金状况

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_capital_info (
    id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday                      CHAR(8)         NOT NULL                COMMENT '交易日 Date',
    account_id                      VARCHAR(32)     NOT NULL                COMMENT '资金账号',
    statement_type                  VARCHAR(16)     NOT NULL                COMMENT '对账单类型：期货/期权/证券现货（盯市入库归一为期货）',
    -- 期权 / 期货 公共字段
    last_day_balance                DECIMAL(20,2)   DEFAULT NULL COMMENT '期初结存 Balance B/F',
    balance                         DECIMAL(20,2)   DEFAULT NULL COMMENT '期末结存 Balance C/F',
    customer_equity                 DECIMAL(20,2)   DEFAULT NULL COMMENT '客户权益 Client Equity',
    deposit_withdrawal              DECIMAL(20,2)   DEFAULT NULL COMMENT '出入金 Deposit/Withdrawal',
    commission                      DECIMAL(20,2)   DEFAULT NULL COMMENT '手续费 Commission',
    maintenance_margin              DECIMAL(20,2)   DEFAULT NULL COMMENT '维持保证金 SMargin',
    premium_received                DECIMAL(20,2)   DEFAULT NULL COMMENT '权利金收入 Premium received',
    premium_paid                    DECIMAL(20,2)   DEFAULT NULL COMMENT '权利金支出 Premium paid',
    available_funds                 DECIMAL(20,2)   DEFAULT NULL COMMENT '可用资金 Fund Avail.',
    initial_margin                  DECIMAL(20,2)   DEFAULT NULL COMMENT '基础保证金 Initial Margin',
    margin_call                     DECIMAL(20,2)   DEFAULT NULL COMMENT '追加保证金 Margin Call',
    -- 期权 专用字段
    long_option_market_value        DECIMAL(20,2)   DEFAULT NULL COMMENT '权利仓市值（期货格式为多头期权市值）',
    short_option_market_value       DECIMAL(20,2)   DEFAULT NULL COMMENT '义务仓市值（期货格式为空头期权市值）',
    market_value_equity             DECIMAL(20,2)   DEFAULT NULL COMMENT '市值权益 Market value(equity)',
    risk                            VARCHAR(20)     DEFAULT NULL COMMENT '风险度 Risk Degree（含%，如 7.83%）',
    strike_frozen_sum               DECIMAL(20,2)   DEFAULT NULL COMMENT '执行冻结资金 StrikeFrozenSum',
    strike_receivable               DECIMAL(20,2)   DEFAULT NULL COMMENT '执行实收资金 StrikeRecAble',
    strike_payable                  DECIMAL(20,2)   DEFAULT NULL COMMENT '执行实付资金 StrikePayAble',
    received_sum_by_cash            DECIMAL(20,2)   DEFAULT NULL COMMENT '现金替代实收资金 RecSumByCash',
    paid_sum_by_cash                DECIMAL(20,2)   DEFAULT NULL COMMENT '现金替代实付资金 PaySumByCash',
    -- 期货（盯市）专用字段
    closing_profit_loss             DECIMAL(20,2)   DEFAULT NULL COMMENT '平仓盈亏 Realized P/L',
    floating_profit_loss            DECIMAL(20,2)   DEFAULT NULL COMMENT '持仓盯市盈亏 MTM P/L',
    option_exercise_profit_loss     DECIMAL(20,2)   DEFAULT NULL COMMENT '期权执行盈亏 Exercise P/L',
    delivery_profit_loss            DECIMAL(20,2)   DEFAULT NULL COMMENT '交割盈亏 Delivery P/L',
    pledge_amount                   DECIMAL(20,2)   DEFAULT NULL COMMENT '质押金 Pledge Amount',
    fx_pledge_occupancy             DECIMAL(20,2)   DEFAULT NULL COMMENT '货币质押保证金占用 FX Pledge Occ.',
    margin_occupancy                DECIMAL(20,2)   DEFAULT NULL COMMENT '保证金占用 Margin Occupied',
    delivery_margin                 DECIMAL(20,2)   DEFAULT NULL COMMENT '交割保证金 Delivery Margin',
    new_fx_pledge                   DECIMAL(20,2)   DEFAULT NULL COMMENT '货币质入 New FX Pledge',
    fx_redemption                   DECIMAL(20,2)   DEFAULT NULL COMMENT '货币质出 FX Redemption',
    change_in_pledge_amount         DECIMAL(20,2)   DEFAULT NULL COMMENT '质押变化金额 Chg in Pledge Amt',
    change_in_fx_pledge             DECIMAL(20,2)   DEFAULT NULL COMMENT '货币质押变化金额 Chg in FX Pledge',
    -- 证券现货 专用字段
    total_assets_brought_forward    DECIMAL(20,2)   DEFAULT NULL COMMENT '期初总资产 Deposit b/f',
    total_assets_carried_forward    DECIMAL(20,2)   DEFAULT NULL COMMENT '期末总资产 Deposit c/f',
    fund_balance_brought_forward    DECIMAL(20,2)   DEFAULT NULL COMMENT '期初资金余额 Balance b/f',
    fund_balance_carried_forward    DECIMAL(20,2)   DEFAULT NULL COMMENT '期末资金余额 Balance c/f',
    stock_market_value              DECIMAL(20,2)   DEFAULT NULL COMMENT '股票市值 Market Value',
    open_preparation                DECIMAL(20,2)   DEFAULT NULL COMMENT '开仓准备金 Open Prepa',
    fund_withdrawal                 DECIMAL(20,2)   DEFAULT NULL COMMENT '可提资金 Fund Withdrawal',
    fund_frozen                     DECIMAL(20,2)   DEFAULT NULL COMMENT '冻结资金 Fund Frozen',
    interest                        DECIMAL(20,2)   DEFAULT NULL COMMENT '利息 Interest',
    buy_security_payment            DECIMAL(20,2)   DEFAULT NULL COMMENT '买券金额 BSecPayment',
    sell_security_income            DECIMAL(20,2)   DEFAULT NULL COMMENT '卖券金额 SSecIncome',
    actual_payment                  DECIMAL(20,2)   DEFAULT NULL COMMENT '实际收付 ActualPayment',
    bonus                           DECIMAL(20,2)   DEFAULT NULL COMMENT '红利 Bonus',
    insert_time                     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_tradingday_account (tradingday, account_id),
    KEY idx_account_id (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-资金状况表（期货/期权/证券现货统一宽表）';
```

### 3. 出入金明细

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_cash_out_in_detail (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday      CHAR(8)         NOT NULL                COMMENT '发生日期 Date',
    account_id      VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    transfer_type   VARCHAR(32)     DEFAULT NULL            COMMENT '出入金类型 Type（银期转账等）',
    deposit         DECIMAL(20,2)   DEFAULT NULL            COMMENT '入金 Deposit',
    withdrawal      DECIMAL(20,2)   DEFAULT NULL            COMMENT '出金 Withdrawal',
    exchange_rate   DECIMAL(20,6)   DEFAULT NULL            COMMENT '汇率 ExchangeRate',
    note            VARCHAR(512)    DEFAULT NULL            COMMENT '说明 Note',
    insert_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-出入金明细表';
```

### 4. 成交记录（期货）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_trade_detail (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '成交日期 Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit             VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    trading_code            VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                 VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product',
    instrument              VARCHAR(32)     DEFAULT NULL            COMMENT '合约 Instrument',
    buy_or_sell             VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    speculation_or_hedge    VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    price                   DECIMAL(20,6)   DEFAULT NULL            COMMENT '成交价 Price',
    lots                    INT             DEFAULT NULL            COMMENT '手数 Lots',
    turnover                DECIMAL(20,2)   DEFAULT NULL            COMMENT '成交额 Turnover',
    open_or_close           VARCHAR(8)      DEFAULT NULL            COMMENT '开平 O/C',
    fee                     DECIMAL(20,2)   DEFAULT NULL            COMMENT '手续费 Fee',
    realized_profit_loss    DECIMAL(20,2)   DEFAULT NULL            COMMENT '平仓盈亏 Realized P/L',
    premium_received_paid   DECIMAL(20,2)   DEFAULT NULL            COMMENT '权利金收支 Premium Received/Paid',
    transaction_number      VARCHAR(32)     DEFAULT NULL            COMMENT '成交序号 Trans.No.',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument (instrument),
    KEY idx_transaction_number (transaction_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-成交记录表';
```

### 5. 平仓明细（期货）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_closing_detail (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '平仓日期 Close Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit             VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    trading_code            VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                 VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product',
    instrument              VARCHAR(32)     DEFAULT NULL            COMMENT '合约 Instrument',
    open_date               CHAR(8)         DEFAULT NULL            COMMENT '开仓日期 Open Date',
    speculation_or_hedge    VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    buy_or_sell             VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    lots                    INT             DEFAULT NULL            COMMENT '手数 Lots',
    position_open_price     DECIMAL(20,6)   DEFAULT NULL            COMMENT '开仓价 Pos. Open Price',
    previous_settlement     DECIMAL(20,6)   DEFAULT NULL            COMMENT '昨结算 Prev. Sttl',
    transaction_price       DECIMAL(20,6)   DEFAULT NULL            COMMENT '成交价 Trans. Price',
    realized_profit_loss    DECIMAL(20,2)   DEFAULT NULL            COMMENT '平仓盈亏 Realized P/L',
    premium_received_paid   DECIMAL(20,2)   DEFAULT NULL            COMMENT '权利金收支 Premium Received/Paid',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument (instrument)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-平仓明细表';
```

### 6. 持仓明细（期货）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_position_detail (
    id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday                  CHAR(8)         NOT NULL                COMMENT '交易日（文件头 Date）',
    account_id                  VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit                 VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    exchange                    VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    trading_code                VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                     VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product',
    instrument                  VARCHAR(32)     DEFAULT NULL            COMMENT '合约 Instrument',
    open_date                   CHAR(8)         DEFAULT NULL            COMMENT '开仓日期 Open Date',
    speculation_or_hedge        VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    buy_or_sell                 VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    position_lots               INT             DEFAULT NULL            COMMENT '持仓量 Positon',
    position_open_price         DECIMAL(20,6)   DEFAULT NULL            COMMENT '开仓价 Pos. Open Price',
    previous_settlement         DECIMAL(20,6)   DEFAULT NULL            COMMENT '昨结算 Prev. Sttl',
    settlement_price            DECIMAL(20,6)   DEFAULT NULL            COMMENT '结算价 Settlement Price',
    accumulated_profit_loss     DECIMAL(20,2)   DEFAULT NULL            COMMENT '浮动盈亏 Accum. P/L',
    mark_to_market_profit_loss  DECIMAL(20,2)   DEFAULT NULL            COMMENT '盯市盈亏 MTM P/L',
    margin                      DECIMAL(20,2)   DEFAULT NULL            COMMENT '保证金 Margin',
    option_market_value         DECIMAL(20,2)   DEFAULT NULL            COMMENT '期权市值 Market Value(Options)',
    insert_time                 TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument (instrument)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-持仓明细表';
```

### 7. 持仓汇总（期货）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_position_summary (
    id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday                  CHAR(8)         NOT NULL                COMMENT '交易日（文件头 Date）',
    account_id                  VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit                 VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    trading_code                VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                     VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product',
    instrument                  VARCHAR(32)     DEFAULT NULL            COMMENT '合约 Instrument',
    long_position               INT             DEFAULT NULL            COMMENT '买持 Long Pos.',
    average_buy_price           DECIMAL(20,6)   DEFAULT NULL            COMMENT '买开仓均价 Avg Buy Price',
    short_position              INT             DEFAULT NULL            COMMENT '卖持 Short Pos.',
    average_sell_price          DECIMAL(20,6)   DEFAULT NULL            COMMENT '卖开仓均价 Avg Sell Price',
    previous_settlement         DECIMAL(20,6)   DEFAULT NULL            COMMENT '昨结算 Prev. Sttl',
    settlement_today            DECIMAL(20,6)   DEFAULT NULL            COMMENT '今结算 Sttl Today',
    mark_to_market_profit_loss  DECIMAL(20,2)   DEFAULT NULL            COMMENT '持仓盯市盈亏 MTM P/L',
    margin_occupied             DECIMAL(20,2)   DEFAULT NULL            COMMENT '保证金占用 Margin Occupied',
    speculation_or_hedge        VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    long_market_value           DECIMAL(20,2)   DEFAULT NULL            COMMENT '多头期权市值 Market Value(Long)',
    short_market_value          DECIMAL(20,2)   DEFAULT NULL            COMMENT '空头期权市值 Market Value(Short)',
    insert_time                 TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument (instrument)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-持仓汇总表';
```

### 8. 行权明细（期货账号商品期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_exercise_detail (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '成交日期 Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit             VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    trading_code            VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                 VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product（白银期权等）',
    instrument              VARCHAR(32)     DEFAULT NULL            COMMENT '合约 Instrument',
    speculation_or_hedge    VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    buy_or_sell             VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    exercise_flag           VARCHAR(16)     DEFAULT NULL            COMMENT '是否行权（期权执行/期权放弃）',
    exercise_volume         INT             DEFAULT NULL            COMMENT '行权数量',
    exercise_price          DECIMAL(20,6)   DEFAULT NULL            COMMENT '行权价格',
    exercise_amount         DECIMAL(20,2)   DEFAULT NULL            COMMENT '行权金额',
    exercise_profit_loss    DECIMAL(20,2)   DEFAULT NULL            COMMENT '行权盈亏',
    exercise_fee            DECIMAL(20,2)   DEFAULT NULL            COMMENT '行权手续费',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument (instrument)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-行权明细表';
```

### 9. 成交记录（期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_trade_detail (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '交易日期 Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号（文件头资金账号）',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange（SSE/SZSE）',
    underlying              VARCHAR(32)     DEFAULT NULL            COMMENT '标的证券 Underlying（510500/588000 等）',
    instrument_code         VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码 InstrumentCode',
    instrument_id           VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码 Instrument ID',
    trade_id                VARCHAR(32)     DEFAULT NULL            COMMENT '成交编号 TradeID',
    buy_or_sell             VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    open_or_close           VARCHAR(8)      DEFAULT NULL            COMMENT '开/平 O/C',
    cover                   VARCHAR(8)      DEFAULT NULL            COMMENT '备兑 Cover',
    price                   DECIMAL(20,6)   DEFAULT NULL            COMMENT '成交价 Price',
    lots                    INT             DEFAULT NULL            COMMENT '手数 Lots',
    turnover                DECIMAL(20,2)   DEFAULT NULL            COMMENT '成交额 Turnover',
    premium_received_paid   DECIMAL(20,2)   DEFAULT NULL            COMMENT '权利金收支 Premium Rec/Pay',
    handling_fee            DECIMAL(20,2)   DEFAULT NULL            COMMENT '经手费 Fee',
    settlement_fee          DECIMAL(20,2)   DEFAULT NULL            COMMENT '结算费 Settle.Fee',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument_id (instrument_id),
    KEY idx_trade_id (trade_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-期权成交记录表';
```

### 10. 持仓变动（期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_position_change (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday          CHAR(8)         NOT NULL                COMMENT '交易日期 Date',
    account_id          VARCHAR(32)     NOT NULL                COMMENT '资金账号（文件头资金账号）',
    exchange            VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    underlying          VARCHAR(32)     DEFAULT NULL            COMMENT '标的证券 Underlying',
    instrument_code     VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码 InstrumentCode',
    instrument_id       VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码 Instrument ID',
    cover               VARCHAR(8)      DEFAULT NULL            COMMENT '备兑 Cover',
    position_direction  VARCHAR(16)     DEFAULT NULL            COMMENT '持仓方向（权利仓/义务仓）',
    change_volume       INT             DEFAULT NULL            COMMENT '变动数量 ChangeVolume',
    change_type         VARCHAR(16)     DEFAULT NULL            COMMENT '变动类型（期权开仓/平仓/仓位对冲等）',
    insert_time         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument_id (instrument_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-期权持仓变动表';
```

### 11. 持仓汇总（期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_position_summary (
    id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday                  CHAR(8)         NOT NULL                COMMENT '交易日期 Date',
    account_id                  VARCHAR(32)     NOT NULL                COMMENT '资金账号（文件头资金账号）',
    exchange                    VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    underlying                  VARCHAR(32)     DEFAULT NULL            COMMENT '标的证券 Underlying',
    instrument_code             VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码 InstrumentCode',
    instrument_id               VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码 Instrument ID',
    cover                       VARCHAR(8)      DEFAULT NULL            COMMENT '备兑 Cover',
    long_volume                 INT             DEFAULT NULL            COMMENT '权利仓数量 Long Vol.',
    single_long_volume          INT             DEFAULT NULL            COMMENT '未组合权利仓数量 Single Long Vol.',
    combine_long_volume         INT             DEFAULT NULL            COMMENT '组合权利仓数量 Combine Long Vol.',
    short_volume                INT             DEFAULT NULL            COMMENT '义务仓数量 Short Vol.',
    single_short_volume         INT             DEFAULT NULL            COMMENT '未组合义务仓数量 Single Short vol.',
    combine_short_volume        INT             DEFAULT NULL            COMMENT '组合义务仓数量 Combine Short vol.',
    margin_occupied             DECIMAL(20,2)   DEFAULT NULL            COMMENT '保证金占用 Margin Occupied',
    settlement_today            DECIMAL(20,6)   DEFAULT NULL            COMMENT '今结算 Sttl Today',
    long_market_value           DECIMAL(20,2)   DEFAULT NULL            COMMENT '权利仓市值 Long Market Value',
    short_market_value          DECIMAL(20,2)   DEFAULT NULL            COMMENT '义务仓市值 Short Market Value',
    insert_time                 TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument_id (instrument_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-期权持仓汇总表';
```

### 12. 持仓明细（期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_position_detail (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday          CHAR(8)         NOT NULL                COMMENT '交易日期 Date',
    account_id          VARCHAR(32)     NOT NULL                COMMENT '资金账号（文件头资金账号）',
    exchange            VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    underlying          VARCHAR(32)     DEFAULT NULL            COMMENT '标的证券 Underlying',
    instrument_code     VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码 InstrumentCode',
    instrument_id       VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码 Instrument ID',
    cover               VARCHAR(8)      DEFAULT NULL            COMMENT '备兑 Cover',
    position_direction  VARCHAR(16)     DEFAULT NULL            COMMENT '持仓方向（权利仓/义务仓）',
    open_date           CHAR(8)         DEFAULT NULL            COMMENT '开仓日期 OpenDate',
    trade_id            VARCHAR(32)     DEFAULT NULL            COMMENT '成交编号 TradeID',
    open_price          DECIMAL(20,6)   DEFAULT NULL            COMMENT '开仓价 Open Price',
    volume              INT             DEFAULT NULL            COMMENT '持仓量 Volume',
    single_volume       INT             DEFAULT NULL            COMMENT '未参与组合数量 Single Volume',
    combination_volume  INT             DEFAULT NULL            COMMENT '参与组合数量 Com Volume',
    settlement_today    DECIMAL(20,6)   DEFAULT NULL            COMMENT '今结算 Sttl Today',
    insert_time         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_instrument_id (instrument_id),
    KEY idx_trade_id (trade_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-期权持仓明细表';
```

### 13. 组合持仓（期权）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_option_combination_position (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '交易日期 Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号（文件头资金账号）',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    combination_number      VARCHAR(64)     DEFAULT NULL            COMMENT '组合编号',
    combination_strategy_code VARCHAR(32)    DEFAULT NULL            COMMENT '组合策略编码',
    volume                  INT             DEFAULT NULL            COMMENT '持仓量',
    margin_occupied         DECIMAL(20,2)   DEFAULT NULL            COMMENT '保证金占用',
    combination_leg_count   INT             DEFAULT NULL            COMMENT '组合成分数量',
    instrument_code1        VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码一',
    instrument_id1          VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码一',
    cover1                  VARCHAR(8)      DEFAULT NULL            COMMENT '备兑一',
    position_direction1     VARCHAR(16)     DEFAULT NULL            COMMENT '持仓方向一',
    volume1                 INT             DEFAULT NULL            COMMENT '持仓量一',
    instrument_code2        VARCHAR(32)     DEFAULT NULL            COMMENT '合约编码二',
    instrument_id2          VARCHAR(32)     DEFAULT NULL            COMMENT '合约代码二',
    cover2                  VARCHAR(8)      DEFAULT NULL            COMMENT '备兑二',
    position_direction2     VARCHAR(16)     DEFAULT NULL            COMMENT '持仓方向二',
    volume2                 INT             DEFAULT NULL            COMMENT '持仓量二',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_combination_number (combination_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-期权组合持仓表';
```

### 14. 入库处理日志

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_processing_log (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday   CHAR(8)         NOT NULL                COMMENT '交易日期',
    account_id   VARCHAR(32)     NOT NULL                COMMENT '资金账号',
    account_type VARCHAR(16)     DEFAULT NULL            COMMENT '账号类型（期货等）',
    log_type     VARCHAR(64)     DEFAULT NULL            COMMENT '日志类型（对账单数据等）',
    log_time     DATETIME        DEFAULT NULL            COMMENT '日志输出时间',
    log_date     CHAR(8)         DEFAULT NULL            COMMENT '日志输出日期',
    log_status   VARCHAR(16)     NOT NULL                COMMENT '状态：Success / Failed',
    log_info     TEXT            DEFAULT NULL            COMMENT '成功信息或失败原因',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_tradingday_status (tradingday, account_type, log_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-入库处理日志表';
```
