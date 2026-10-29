# 期货对账单 Open API 对接更新说明（交割明细 + 日志 logInfo）

> 面向对象：接口开发 / DBA
> 更新日期：2026-10-29
> 关联文档：[期货对账单聚合入库接口文档.html](./期货对账单聚合入库接口文档.html)、[API对接-数据表与SQL清单.md](./API对接-数据表与SQL清单.md)
> 适用样本：`test_resource/国君/20261016/*.txt`（国君交易结算单，新增 `交割明细 Delivery` 表）

本次需要开发配合的改动共 3 项：

1. **新增业务表** `bill_future_settle_delivery_detail`（交割明细），并纳入 `settlementFileInsert` 的全量覆盖范围；
2. `settlementFileInsert` 请求体新增 `deliveryDetailList` 数组（业务表由 13 张变为 **14 张**）；
3. **处理日志的 `logInfo` 开放传参**，并新增/提供一个写日志接口，用于写入 `log_type=对账单文件` 及自定义 `log_type=对账单数据` 的 `logInfo`（入库失败原因、文件找不到等）。

---

## 一、新增业务表：交割明细

### 1.1 建表 SQL（MySQL 8.x，utf8mb4）

```sql
CREATE TABLE IF NOT EXISTS bill_future_settle_delivery_detail (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    tradingday              CHAR(8)         NOT NULL                COMMENT '交割日期 Date',
    account_id              VARCHAR(32)     NOT NULL                COMMENT '资金账号 AccountID',
    invest_unit             VARCHAR(32)     DEFAULT NULL            COMMENT '投资单元 InvestUnit',
    exchange                VARCHAR(16)     DEFAULT NULL            COMMENT '交易所 Exchange',
    trading_code            VARCHAR(32)     DEFAULT NULL            COMMENT '交易编码 tradingcode',
    product                 VARCHAR(64)     DEFAULT NULL            COMMENT '品种 Product',
    delivery_month          VARCHAR(16)     DEFAULT NULL            COMMENT '交割期 Del.Mth',
    speculation_or_hedge    VARCHAR(8)      DEFAULT NULL            COMMENT '投/保 S/H',
    buy_or_sell             VARCHAR(8)      DEFAULT NULL            COMMENT '买/卖 B/S',
    delivered_quantity      INT             DEFAULT NULL            COMMENT '实提数量 Delivered Qty',
    residual_quantity       INT             DEFAULT NULL            COMMENT '剩余数量 Residual',
    delivery_price          DECIMAL(20,6)   DEFAULT NULL            COMMENT '交割价格 Delivery Price',
    delivery_amount         DECIMAL(20,2)   DEFAULT NULL            COMMENT '交割金额 Delivery Amount',
    delivery_fee            DECIMAL(20,2)   DEFAULT NULL            COMMENT '交割手续费 Delivery Fee',
    average_open_price      DECIMAL(20,6)   DEFAULT NULL            COMMENT '开仓均价 Avg Opening Price',
    delivery_profit_loss    DECIMAL(20,2)   DEFAULT NULL            COMMENT '交割盈亏 Realized P/L at Delivery',
    insert_time             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (id),
    KEY idx_tradingday_account (tradingday, account_id),
    KEY idx_product (product),
    KEY idx_delivery_month (delivery_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='期货对账单-交割明细表';
```

### 1.2 源报文结构（国君）

```
交割明细  Delivery
|交割日期| 投资单元 | 交易所 | 交易编码 | 品种 |交割期 | 投/保 |买/卖| 实提数量 |剩余数量| 交割价格 | 交割金额 | 交割手续费 | 开仓均价 | 交割盈亏 | 资金账号 |
```

### 1.3 接口实体字段（BillFutureSettleDeliveryDetail）

| JSON 字段 | 类型 | 数据库列 | 说明 |
|-----------|------|----------|------|
| `tradingday` | String | `tradingday` | 交割日期（必须与顶层 `tradingday` 一致） |
| `accountId` | String | `account_id` | 资金账号（必须与顶层 `accountId` 一致） |
| `investUnit` | String | `invest_unit` | 投资单元 |
| `exchange` | String | `exchange` | 交易所 |
| `tradingCode` | String | `trading_code` | 交易编码 |
| `product` | String | `product` | 品种 |
| `deliveryMonth` | String | `delivery_month` | 交割期（如 IC2610） |
| `speculationOrHedge` | String | `speculation_or_hedge` | 投/保 |
| `buyOrSell` | String | `buy_or_sell` | 买/卖 |
| `deliveredQuantity` | Integer | `delivered_quantity` | 实提数量 |
| `residualQuantity` | Integer | `residual_quantity` | 剩余数量 |
| `deliveryPrice` | BigDecimal | `delivery_price` | 交割价格 |
| `deliveryAmount` | BigDecimal | `delivery_amount` | 交割金额 |
| `deliveryFee` | BigDecimal | `delivery_fee` | 交割手续费 |
| `averageOpenPrice` | BigDecimal | `average_open_price` | 开仓均价 |
| `deliveryProfitLoss` | BigDecimal | `delivery_profit_loss` | 交割盈亏 |
| `id` / `insertTime` | — | — | 客户端不传；服务端清空并由数据库生成 |

---

## 二、`settlementFileInsert` 变更

### 2.1 请求体新增数组 `deliveryDetailList`

- 新增第 14 个业务数组：`deliveryDetailList: Array<BillFutureSettleDeliveryDetail>`
- **全量快照语义不变**：服务端需按顶层 `(tradingday, accountId)` 删除 **14 张**业务表旧数据，再分别写入各数组；数组为 `null` / 缺失 / 空数组时，该表旧数据同样被清空。
- 调用方（本程序）每次都会显式提交全部 14 个数组；缺失的类别以空数组提交。

### 2.2 请求体示例（节选）

```json
{
  "tradingday": "20261016",
  "accountId": "80029349",
  "basicInfoList": [ ... ],
  "capitalInfoList": [ ... ],
  "cashOutInDetailList": [],
  "tradeDetailList": [ ... ],
  "closingDetailList": [ ... ],
  "positionDetailList": [ ... ],
  "positionSummaryList": [ ... ],
  "optionExerciseDetailList": [],
  "optionTradeDetailList": [],
  "optionPositionChangeList": [],
  "optionPositionSummaryList": [],
  "optionPositionDetailList": [],
  "optionCombinationPositionList": [],
  "deliveryDetailList": [
    {
      "tradingday": "20261016",
      "accountId": "80029349",
      "investUnit": "80029349",
      "exchange": "中金所",
      "tradingCode": "00092667",
      "product": "中证500指数",
      "deliveryMonth": "IC2610",
      "speculationOrHedge": "交易",
      "buyOrSell": "卖",
      "deliveredQuantity": 6,
      "residualQuantity": 0,
      "deliveryPrice": 6805.740,
      "deliveryAmount": 8166888.00,
      "deliveryFee": 408.34,
      "averageOpenPrice": 6757.167,
      "deliveryProfitLoss": -65928.00
    }
  ]
}
```

### 2.3 响应 `tableRecordCounts`

`result.tableRecordCounts` 需增加：

```json
"bill_future_settle_delivery_detail": 8
```

`totalRecordCount` 同步纳入该表行数。

---

## 三、处理日志 `logInfo` 开放传参

### 3.1 需求

处理日志表 `bill_future_settle_processing_log` 的 `log_info` 需要由调用方传入，用于保存：

- `log_type=对账单文件`：文件检测结果（成功 / **未找到文件**等）；
- `log_type=对账单数据`：入库成功信息 / **入库失败原因**（含服务端异常、接口校验失败等）。

目前 `settlementFileInsert` 仅固定写 `log_type=对账单数据`，且无法自定义 `log_info`。请按下述两种方式补齐。

### 3.2 新增通用写日志接口（必需）

建议路径：`POST /openApi/billFutureApi/insertProcessingLog`（路径会由本程序配置项 `log_path` 指定，可按实际调整）

请求体：

```json
{
  "tradingday": "20261016",
  "accountId": "80029349",
  "accountType": "期货",
  "logType": "对账单文件",
  "logStatus": "Success",
  "logInfo": "检测到对账单文件: 80029349.txt"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tradingday` | String | 是 | 报文真实交易日 `yyyyMMdd` |
| `accountId` | String | 是 | 资金账号 |
| `accountType` | String | 否 | 默认 `期货` |
| `logType` | String | 是 | `对账单文件` / `对账单数据` |
| `logStatus` | String | 是 | `Success` / `Failed` |
| `logInfo` | String | 否 | 成功信息或失败原因（原样入库，可为空） |

服务端处理要求：

1. 先按 `(tradingday, account_id, log_type)` 删除旧记录，再插入新记录（与现有处理日志一致）；
2. `log_time`、`log_date` 由服务端生成；
3. 返回统一 `Result`（`success=true` 表示写入成功）。

### 3.3 `settlementFileInsert` 增加可选 `logInfo`（建议）

为便于直接保存入库成功/失败信息，请为 `settlementFileInsert` 顶层增加可选字段：

```json
{
  "tradingday": "20261016",
  "accountId": "80029349",
  "logInfo": "文件 80029349.txt 入库成功，共 8 张表 266 行",
  "...": "... 其余 14 个业务数组 ..."
}
```

- 成功时：服务端写 `log_type=对账单数据 / Success / logInfo=请求值`；
- 失败时：若请求已传入 `logInfo`，优先使用；否则沿用异常消息；
- 若未传 `logInfo`，保持现有默认行为。

> 与 3.2 的关系：本程序在入库调用后会通过通用写日志接口，以 `log_type=对账单数据` **覆盖**写入更精确的结果信息（成功汇总或失败原因）。因此：
> - 若实现 3.2，则 3.3 可选（不实现也能满足自定义 `log_info`）；
> - 若实现 3.3，可减少一次“覆盖写”，但不是必须。

### 3.4 本程序的调用方式

| 场景 | log_type | log_status | log_info 示例 |
|------|----------|------------|---------------|
| 检测到对账单文件 | `对账单文件` | `Success` | `检测到对账单文件: 80029349.txt` |
| 账号配置存在但无文件 | `对账单文件` | `Failed` | `未检测到对账单文件` |
| 数据入库成功 | `对账单数据` | `Success` | `期货对账单入库成功(266 行)` |
| 数据入库失败 | `对账单数据` | `Failed` | `API入库失败: HTTP 500 ...` |

> 同一 `(tradingday, account_id, log_type)` 只保留最新一条。

---

## 四、联调 / 验收清单（开发侧）

- [ ] 创建 `bill_future_settle_delivery_detail` 表；
- [ ] `settlementFileInsert` 请求实体新增 `deliveryDetailList`，并纳入 14 张表的“先删后插”事务；
- [ ] 响应 `tableRecordCounts` 增加 `bill_future_settle_delivery_detail`，`totalRecordCount` 同步；
- [ ] 提供 `insertProcessingLog`（或等价）写日志接口，支持 `logType` 与 `logInfo` 传参；
- [ ] （建议）`settlementFileInsert` 支持顶层可选 `logInfo`；
- [ ] 确认 `deliveryDetailList` 中每行的 `tradingday` / `accountId` 必须与顶层一致，否则整单回滚；
- [ ] 确认 `deliveredQuantity` / `residualQuantity` 按 Integer 接收，金额/价格按 BigDecimal 接收。

## 五、兼容性说明

- 本次改动对程序侧是**增量**的：即使新表/新接口尚未上线，程序仍可入库原有 13 张表；`deliveryDetailList` 会以空数组提交（若服务端尚未实现该字段，需要服务端先发布接口，否则可能因未知字段报错，建议服务端先兼容未知字段或与程序同步上线）。
- 本程序通过 `config/info.ini` 的 `[ApiParams] log_path` 控制是否调用通用写日志接口；未配置时不影响入库主流程。
