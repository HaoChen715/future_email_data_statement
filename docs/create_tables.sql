-- =====================================================================
-- 国君邮件对账单数据表 DDL（MySQL）
-- 对应清洗 DataFrame：基本资料 / 资金状况 / 出入金明细 / 成交记录 /
--                    平仓明细 / 持仓明细 / 持仓汇总 / 持仓变动 /
--                    行权明细 / 组合持仓
-- 命名以 bill_future_settle_* 为前缀，区别于 future_data_download_and_
-- clean_to_statement 项目的 bill_future_account_* 表；
-- 逐表按 (tradingday, account_id) 先删后插。
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. 基本资料（全部对账单类型）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bill_future_settle_basic_info (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday      CHAR(8)         NOT NULL                COMMENT '交易日 Date',
    account_id      VARCHAR(32)     NOT NULL                COMMENT '资金账号（资金状况块资金账号）',
    client_id       VARCHAR(32)     DEFAULT NULL            COMMENT '客户号 Client ID',
    client_name     VARCHAR(128)    DEFAULT NULL            COMMENT '客户名称 Client Name',
    broker          VARCHAR(32)     NOT NULL                COMMENT '券商（国君）',
    statement_type  VARCHAR(16)     NOT NULL                COMMENT '对账单类型：盯市/期权/证券现货',
    creation_date   CHAR(8)         DEFAULT NULL            COMMENT '制表日期 Creation Date',
    file_name       VARCHAR(255)    DEFAULT NULL            COMMENT '源文件名',
    insert_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_tradingday_account (tradingday, account_id),
    KEY idx_account_id (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-基本资料表（国君）';

-- ---------------------------------------------------------------------
-- 2. 资金状况（盯市/期权/证券现货 三格式统一宽表）
--    仅 statement_type 对应格式的字段有值，其余为 NULL
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bill_future_settle_capital_info (
    id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday                      CHAR(8)         NOT NULL                COMMENT '交易日 Date',
    account_id                      VARCHAR(32)     NOT NULL                COMMENT '资金账号',
    statement_type                  VARCHAR(16)     NOT NULL                COMMENT '对账单类型：盯市/期权/证券现货',
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
  COMMENT='期货对账单-资金状况表（国君，盯市/期权/证券现货统一宽表）';

-- ---------------------------------------------------------------------
-- 3. 出入金明细（期货；证券现货有该块时结构待样本确认）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-出入金明细表（国君）';

-- ---------------------------------------------------------------------
-- 4. 成交记录（期货，含商品期权交易行）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-成交记录表（国君）';

-- ---------------------------------------------------------------------
-- 5. 平仓明细（期货，含商品期权平仓行）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-平仓明细表（国君）';

-- ---------------------------------------------------------------------
-- 6. 持仓明细（期货，含商品期权持仓行；tradingday 取文件头 Date）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-持仓明细表（国君）';

-- ---------------------------------------------------------------------
-- 7. 持仓汇总（期货，含商品期权汇总行；tradingday 取文件头 Date）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-持仓汇总表（国君）';

-- ---------------------------------------------------------------------
-- 8. 行权明细（期货账号商品期权行权/放弃）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-行权明细表（国君）';

-- ---------------------------------------------------------------------
-- 9. 成交记录（期权账号，上交所/深交所 ETF 期权）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-期权成交记录表（国君）';

-- ---------------------------------------------------------------------
-- 10. 持仓变动（期权账号）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-期权持仓变动表（国君）';

-- ---------------------------------------------------------------------
-- 11. 持仓汇总（期权账号）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-期权持仓汇总表（国君）';

-- ---------------------------------------------------------------------
-- 12. 持仓明细（期权账号）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-期权持仓明细表（国君）';

-- ---------------------------------------------------------------------
-- 13. 组合持仓（期权账号，组合策略成分）
-- ---------------------------------------------------------------------
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
  COMMENT='期货对账单-期权组合持仓表（国君）';

-- ---------------------------------------------------------------------
-- 14. 入库日志（bill_future_settle_processing_log，断点续跑）
--     字段沿用 future_data 项目 bill_processing_log 的设计
-- ---------------------------------------------------------------------
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