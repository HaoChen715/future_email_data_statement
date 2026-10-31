# future_email_data_statement

期货对账单数据 **「邮件下载 → 解压 → 账号匹配迁移」** 程序。

结合 [auto_down_email_clean_to_statement](https://github.com/HaoChen715/auto_down_email_clean_to_statement)
与 [future_data_download_and_clean_to_statement](https://github.com/HaoChen715/future_data_download_and_clean_to_statement)
两个项目的共同特性：

- 数据源文件按 **auto_down_email 的思路**从邮箱自动下载当日对账单附件；
- 账号信息与数据入库均通过开发的 **Open API** 获取/写入（程序不再直连业务库）；
- 采用 **auto_down_email 的账号匹配思路**将文件匹配并迁移到指定目录；
- 数据清洗沿用 **auto_down_email 的 Statement 清洗基类思路**，将对账单解析为多个标准 DataFrame。

## 功能概述

| 阶段 | 模块 | 职责 |
|------|------|------|
| ① 启动初始化 | `BrokerInit`（datainit/broker_init.py） | 启动时通过 Open API `queryBrokerInit` 获取券商列表，预建 `resource/{券商}/` 目录，并生成环境专属的 `config/datapath_init_{Place}.json` |
| ② 下载 | `Auto_DownLoad_Email`（email_download/email_download.py） | 登录 IMAP 邮箱、按日期搜索并下载当日全部附件 |
| ③ 解压 | `UnZip`（unzip/unzip.py） | 压缩包（zip/rar）解压、直接文件拷贝到最终文件目录 |
| ④ 匹配迁移 | `CheckAccountFile`（account_match/check_file.py） | 通过 Open API `queryAccountList` 获取当日有效资金账号并匹配文件，迁移到 `resource/{券商}/{交易日}/` 并备份历史目录 |
| ⑤ 数据清洗 | `CleanDataFile`（data_clean/clean_data.py） | 逐文件读取 `resource/{券商}/{交易日}/` 下的对账单，清洗为多个内置 DataFrame（不动原始文件） |
| ⑥ 清洗入库 | `InsertDataFile`（data_insert/insert_data.py） | 内部完成清洗后，按券商模板映射为 API 请求体，逐文件调用 `settlementFileInsert` 全量覆盖入库；通过 `queryInsertSuccessAccountList` 支持断点续跑 |

- 对账单**读写均通过 Open API 完成，程序不再直连业务库**：券商/账号查询对应 3 个 GET 接口，整文件入库对应 `settlementFileInsert`（服务端按 `(tradingday, accountId)` 单事务先删后插，并同步维护处理日志）。接口清单见 [docs/期货对账单聚合入库接口文档.html](docs/期货对账单聚合入库接口文档.html)；本次新增交割明细与日志 logInfo 的对接说明见 [docs/API对接更新-交割明细与日志logInfo.md](docs/API对接更新-交割明细与日志logInfo.md)。
- 支持**生产 / 测试环境隔离**：由 `config/info.ini` 的 `[RunParams] Place` 参数统一切换 API 地址与全部文件落盘目录。
- 处理日期与执行步骤**通过命令行参数控制**（`main.py yyyymmdd [today|last] [steps...]`，风格沿用 auto_down_email 项目）：`today`=下载当天邮件，`last`=下载上一交易日邮件。
- 按邮箱顺序**串行登录下载**，全部下载解压后再统一做账号匹配（与股票邮件下载程序一致，无多线程登录）。
- 账号配置支持**有效期过滤**（start_date / end_date）与**已销户账号自动跳过**（remark 含"销户"）。

## 运行流程

1. `main.py` 读取命令行参数（yyyymmdd / today|last / steps）与 `config/info.ini [RunParams]`（Place）；
2. 根据运行日计算上一交易日，确定邮件下载日（last 模式取上一交易日）；
3. **启动初始化**：通过 Open API `queryBrokerInit` 获取券商列表，预建 `resource/{券商}/` 目录（记录到 `config/datapath_init_{Place}.json`）；
4. 按步骤执行：
   - **邮件下载**：登录 `config/email.json` 中配置的全部邮箱，搜索当日邮件并下载附件到 `email_download_root/{交易日}/`；
   - **解压**：压缩包解压、直接文件拷贝到 `unzip_final_root/{交易日}/`，异常压缩包移入 `unzip_question_root/`；
   - **账号匹配**：调用 Open API `queryAccountList` 获取当日有效账号；只扫描 `File_extensions` 允许的文件格式；先将文件名按正则拆分为连续数字组合，账号完全等于其中某个数字组即判定为该账号文件，未命中再按文件内容（前 20 行）匹配；命中后迁移到 `resource_root/{broker}/{交易日}/`，并立即写一条 `对账单文件` 成功匹配日志（配置了 `log_path` 时）；
   - **数据清洗**：按券商加载对应清洗类，将 `resource_root/{broker}/{交易日}/` 下的对账单逐文件读取、清洗为多个内置 DataFrame，供后续映射为 API 请求体；
   - **清洗入库**：内部先执行清洗，再按「券商模板 + 对账单类型 + 板块」映射为 14 张业务表的请求数组；逐文件调用 Open API `settlementFileInsert`（顶层 `tradingday + accountId`，服务端单事务先删后插并写处理日志）。按**报文真实交易日**调用 `queryInsertSuccessAccountList` 获取已成功账号，默认跳过；需要**删除重新入库**时用 `--force`（或 `[RunParams] Force_redownload=True`）忽略成功日志全部重跑。`国君` / `国泰海通` / `国海` / `海通` 共用同一清洗模板，`broker` 列写实际券商名。

## 目录结构

```
main.py                               主入口：下载→解压→匹配迁移 编排
compile_so.py                         生产部署工具：将 src 下业务模块编译为 .so
pyinstall.py                          一键打包：.so 编译 + PyInstaller + 发布包组装
config/
  info.ini                            运行/API/文件目录配置（[RunParams] 等）
  email.json                          邮箱账号配置（账号/口令均为 Fernet 密文）
  secret.key                          Fernet 密钥（本地生成，勿入库）
config_template/                      部署配置模板（打包时随发布包分发，真实凭据不打包）
docs/
  内网GitLab推送计划.md                内网 GitLab 克隆推送与部署方案
src/future_email_data_statement/
  common/                             通用工具
    encrpty.py                        加解密（Fernet）
    get_parent_path.py                项目根目录定位（兼容 .py 源码 / .so 生产部署）
    logger_init.py                    日志初始化
    CheckTradingDay.py                交易日判断（SSE 日历）
    statement_type.py                 对账单类型判断（期货/期权/证券现货，文件名前缀+内容特征）
    generate_key.py / generate_password.py  密钥与密文生成工具
  config/
    globalfunc.py                     配置读取（API 地址、文件目录，Place 环境切换）
  email_download/
    email_download.py                 邮件下载（含大邮件强化处理）
  unzip/
    unzip.py                          压缩包解压
  account_match/
    check_file.py                     账号匹配与文件迁移（API 查询有效账号）
  data_clean/
    clean_data.py                     数据清洗步骤入口：按券商逐文件清洗为内置 DataFrame
    datastatement.py                  券商清洗类动态调度（BROKER_IMPORT_MAP）
    tools/
      statement.py                    清洗基类：多编码读取/资金状况解析/|分隔表格切分
      guojun.py                       国君-交易结算单 txt 清洗（盯市/期权/证券现货三种格式）
  data_insert/
    api_client.py                     对账单 Open API 客户端（查询/整文件入库）
    mapping.py                        清洗结果 -> 数据库表/接口字段 的映射规则
    insert_data.py                    清洗入库步骤入口（映射后逐文件调用入库接口）
```

## 配置文件

### config/info.ini（运行参数、API 与目录配置）

- `[RunParams]`：运行时参数
  - `Place`：运行环境，`Trade`=生产 / `Test`=测试（处理日期与执行步骤由命令行参数控制）
  - `Force_redownload`：`True` 时入库忽略已成功账号，全部重新解析入库
  - `File_extensions`：只扫描/匹配的文件扩展名（逗号分隔，不区分大小写，默认 `.txt,.xlsx,.xls`），其余格式直接跳过以节省时间
- `[BrokerFilter]`：券商白名单（仅列表中券商视为「已注册券商」）
  - `brokers`：逗号分隔的券商名，如 `国君,国泰海通`；留空表示不限制（全部券商）
  - 生效范围：券商目录初始化（仅白名单券商建目录）、账号匹配（仅白名单券商账号参与匹配）；
    过滤后留存的账号会输出到日志便于核对
- `[ApiParams]` / `[TestApiParams]`：生产 / 测试环境对账单 Open API 配置（网关签名鉴权，见 [docs/apiDemo.py](docs/apiDemo.py)）
  - `base_url`：Open API 基础地址（含上下文路径），如 `http://192.168.166.4/agent-monitor-boot`
  - `timeout`：请求超时秒数，默认 30
  - `app_key` / `app_secret`：网关分配的密钥
  - `user_agent`：可选，请求 User-Agent（默认与 apiDemo 一致）
  - `verify_ssl`：是否校验 HTTPS 证书，内网自签证书时设为 `False`
  - `log_path`：开发新增的写处理日志接口路径（用于写 `log_type=对账单文件`），留空则不写
  - 签名规则：`signature = md5(app_key + app_secret + timestamp(毫秒))`，程序每次请求即时生成并随 `appKey` / `signature` / `timestamp` 请求头发送
- `[FilePath]` / `[TestFilePath]`：生产 / 测试环境文件目录（键名与 auto_down_email 项目 data_paths.json 一致）：
  - `email_download_root`：邮件附件下载根目录
  - `unzip_zip_root` / `unzip_extract_root` / `unzip_final_root` / `unzip_question_root`：解压各阶段目录
  - `resource_root`：账号匹配后对账单文件存放根目录

> `Place=Trade` 时读取 `[ApiParams]` + `[FilePath]`，`Place=Test` 时读取 `[TestApiParams]` + `[TestFilePath]`，
> 测试环境默认落在本地 `./test_data`、`./test_resource`，不会污染生产目录。

### config/email.json（邮箱配置）

```json
{
    "user1": {
        "email_usr": "",          // 邮箱账号（密文）
        "email_pwd": "",          // 邮箱密码（密文）
        "email_safe_code": "",    // 邮箱安全码（密文）
        "mail_server": "",        // IMAP 服务器地址
        "port": 993,
        "user_code": "True"       // True=使用安全码登录 / False=使用密码登录
    }
}
```

## 环境与安装

- Python 3.11（`requires-python = "==3.11.*"`）
- 使用 PDM 管理：`pdm install`

## 运行

```bash
# 首次部署：生成加密密钥（config/secret.key）
pdm run python -m src.future_email_data_statement.common.generate_key

# 生成密码/邮箱口令密文并填入 info.ini / email.json
pdm run python -m src.future_email_data_statement.common.generate_password <明文>

# 运行（参数风格沿用 auto_down_email 项目）
# yyyymmdd 为运行日期, today|last 为下载模式, 步骤可选
# 默认: download_and_unzip → check_account → insert_data(清洗+入库)
pdm run python main.py 20260826 today                # 下载 → 解压 → 账号匹配 → 清洗入库
pdm run python main.py 20260826 last                 # 同上, 下载上一交易日邮件
pdm run python main.py 20260826 today download_and_unzip   # 仅下载解压
pdm run python main.py 20260826 today check_account        # 仅账号匹配迁移
pdm run python main.py 20260826 today clean_data           # 仅清洗(查看结果, 不入库)
pdm run python main.py 20260826 today insert_data          # 仅清洗入库(默认跳过已成功账号)
pdm run python main.py 20260826 today insert_data 国君 --force  # 强制重新入库(忽略已成功日志)
pdm run python main.py 20260826 today 国君                 # 仅处理指定券商(国君): 跳过邮件下载, 走默认步骤
pdm run python main.py 20260826 today insert_data 国君     # 指定步骤 + 指定券商
```

> 各步骤执行失败会明确打印原因并返回退出码 1（附件目录为空 / 全部邮箱登录失败 /
> 无可解压文件等场景均会报错，不会静默跳过）。

## 生产打包（思路同 future_data 项目）

```bash
# 一键打包: ① 编译 src 全部业务模块为 .so(含 __init__.py 与 generate_key/generate_password 工具)
#          ② 扫描虚拟环境依赖 ③ PyInstaller 打包 main.py(排除 src)
#          ④ 组装发布目录(可执行程序 + 外部 src 纯 .so 模块树 + config 模板)并打 tar.gz
pdm run python pyinstall.py

# 【限制】发布包 src 目录内只允许存在 .so 文件:
#   - .so 编译失败或任一 .py 未编译出同名 .so 时, 打包直接中止
#   - 组装完成后再次校验, 发布目录内检出 .py 同样中止

# 产物:
#   future_email_data_statement_tree.tar.gz               完整部署包
#   future_email_data_statement_config_template.tar.gz    config 模板包
```

> **部署形态**：`可执行程序 + _internal 运行库 + 外部 src/.so 模块树 + config 模板`，
> 真实凭据不打包（部署时填写 config 并运行 generate_key / generate_password 生成密文），
> 运行方式：`./future_email_data_statement yyyymmdd [today|last] [steps...]`。
> 内网 GitLab 推送与部署步骤见 [docs/内网GitLab推送计划.md](docs/内网GitLab推送计划.md)。

## 数据清洗（阶段④）

- 当前支持券商：**国君 / 国泰海通 / 国海 / 海通**（国泰君安期货 交易结算单 txt，GBK 编码邮件附件；四者共用同一清洗模板，入库 `broker` 写实际券商名）。
- 对账单类型判断（common/statement_type.py）：**文件内容特征优先**（盯市标题 MTM /
  资金状况互斥字段），**文件名资金账号前缀兜底**（95=证券现货 / 99=期权 / 其余=期货），
  清洗后 `基本资料.statement_type` 细分为 盯市 / 期权 / 证券现货，**入库时 盯市 归一为 期货**
  （见 `data_insert/mapping.py` 的 `STATEMENT_TYPE_STORE_MAP`）。
- 只读取、不动原始文件：逐文件清洗为内置 DataFrame，以 `{文件名: data_frames_json}` 返回，
  供后续按 `data_insert/mapping.py` 映射为数据库表与 API 请求字段。
- 单个文件清洗后分化成多个 DataFrame（`data_frames_json`）：
  - `基本资料`：交易日 / 资金账号 / 客户号 / 客户名称 / 券商 / 对账单类型（期货/期权/证券现货；盯市入库归一为期货）/ 制表日期 / 文件名；
  - `资金状况`：键值对标准化为单行宽表（英文列名，覆盖期货/期权/证券现货三种格式）；
  - `出入金明细` / `成交记录` / `平仓明细` / `持仓明细` / `持仓汇总` / `持仓变动` / `行权明细` / `组合持仓` / `交割明细`：| 分隔表格按中文表头清洗为 DataFrame（汇总行已剔除，表内缺失资金账号列时自动补充）。
- 新增券商时：在 `data_clean/tools/` 下实现继承 `Statement` 的清洗类，并在 `datastatement.py` 的 `BROKER_IMPORT_MAP` 注册中文券商名即可。

## 数据入库（阶段⑥）

- 入库方式：**通过 Open API `settlementFileInsert` 全量覆盖入库**，程序不再直连业务库。
  - 每个对账单文件映射为一次入库请求：顶层 `tradingday + accountId`，其余 14 个业务数组显式提交（无数据提交空数组）；
  - 服务端在同一事务内按 `(tradingday, accountId)` 删除 14 张业务表旧数据再写入，失败整体回滚，重复提交等价覆盖（幂等）；
  - 处理日志由服务端同步维护，程序不再写日志表；
  - 检测到文件并匹配到账号时（账号匹配阶段），若配置了 `log_path`，立即写一条 `log_type=对账单文件`、`log_status=Success` 的处理日志；无文件账号在入库结束后写 `Failed`（`未检测到对账单文件`）。
- 断点续跑：按**报文内真实交易日**调用 `queryInsertSuccessAccountList` 获取该日已成功账号并跳过；`--force`（或 `[RunParams] Force_redownload=True`）忽略成功日志全部重跑，失败账号不在成功集合中会自然重试。
- 结果明细：入库结束后**按报文交易日**汇总输出「未检测到对账单文件、本次未入库的账号」「检测到文件但本次跳过/失败的账号」「无法解析基本资料的文件」，账号明细含券商、类型、有效期、备注。
- 字段映射见 `data_insert/mapping.py`（数据库列名 -> 接口 camelCase），整型列显式转整数、缺失值转 `null`。
- 接口清单与字段定义见 [docs/期货对账单聚合入库接口文档.html](docs/期货对账单聚合入库接口文档.html) /
  [docs/API对接-数据表与SQL清单.md](docs/API对接-数据表与SQL清单.md)。
- 本次新增 **交割明细** `bill_future_settle_delivery_detail`（`deliveryDetailList`）与 **处理日志 logInfo 传参**，
  详见 [docs/API对接更新-交割明细与日志logInfo.md](docs/API对接更新-交割明细与日志logInfo.md)。

## 日志

- 运行日志：`logs/{日期}.log`（各模块按业务日期写入）
- **全量运行日志**：`logs/runtime_{运行日}.log` —— 程序启动时接管 stdout/stderr，
  把前端 `print`、日志控制台输出、异常 traceback 等全部运行期输出同时写入该文件

## 已知问题修复记录

**邮件大附件下载失败**（沿用自 auto_down_email 项目，本仓库已修复）：

- **问题**：部分券商在一封邮件中塞入几十个附件，附件大于约 50KB 的文件始终无法下载；
- **根因**：大文件被券商按 RFC 2046 切分为多个 `message/partial` 分片发送，每片无独立文件名，原逻辑在文件名检查处被静默跳过；
- **修复**（email_download/email_download.py）：
  - 按 id / number 重组 `message/partial` 分片并递归提取内嵌附件；
  - 解析改用 `email.policy.default`（RFC 2231 文件名、`name=` 参数回退）；
  - 标准 `get_payload(decode=True)` 优先，失败后按 CTE 手工解码兜底；
  - 取件时校验 `RFC822.SIZE`，检测到服务器截断（或整封解析无附件）时改用 `BODYSTRUCTURE` 逐段（`BODY.PEEK[n]`）取件，绕开大邮件整体取件限制。

## 数据表（服务端依赖）

- 账号配置视图：`v_config_bill_future_account`（由 Open API 查询，使用字段：future_account_id / broker_id / start_date / end_date / remark 等）
- 14 张对账单业务表与处理日志表 `bill_future_settle_processing_log` 均由服务端维护；
  建表 SQL 见 [docs/create_tables.sql](docs/create_tables.sql) / [docs/数据库表结构设计.md](docs/数据库表结构设计.md)
