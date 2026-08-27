# future_email_data_statement

期货对账单数据 **「邮件下载 → 解压 → 账号匹配迁移」** 程序。

结合 [auto_down_email_clean_to_statement](https://github.com/HaoChen715/auto_down_email_clean_to_statement)
与 [future_data_download_and_clean_to_statement](https://github.com/HaoChen715/future_data_download_and_clean_to_statement)
两个项目的共同特性：

- 数据源文件按 **auto_down_email 的思路**从邮箱自动下载当日对账单附件；
- 账号信息按 **future_data 的思路**从数据库视图 `v_config_bill_future_account` 获取；
- 采用 **auto_down_email 的账号匹配思路**将文件匹配并迁移到指定目录。

后续的数据清洗与入库功能将在本阶段完成后继续开发。

## 功能概述

| 阶段 | 模块 | 职责 |
|------|------|------|
| ① 下载 | `Auto_DownLoad_Email`（email_download/email_download.py） | 登录 IMAP 邮箱、按日期搜索并下载当日全部附件 |
| ② 解压 | `UnZip`（unzip/unzip.py） | 压缩包（zip/rar）解压、直接文件拷贝到最终文件目录 |
| ③ 匹配迁移 | `CheckAccountFile`（account_match/check_file.py） | 按数据库视图中的资金账号匹配文件，迁移到 `resource/{券商}/{交易日}/` 并备份历史目录 |

- 支持**生产 / 测试环境隔离**：由 `config/info.ini` 的 `[RunParams] Place` 参数统一切换数据库连接与全部文件落盘目录。
- 处理日期与执行步骤**通过命令行参数控制**（`main.py yyyymmdd [today|last] [steps...]`，风格沿用 auto_down_email 项目）：`today`=下载当天邮件，`last`=下载上一交易日邮件。
- 按邮箱顺序**串行登录下载**，全部下载解压后再统一做账号匹配（与股票邮件下载程序一致，无多线程登录）。
- 账号配置支持**有效期过滤**（start_date / end_date）与**已销户账号自动跳过**（remark 含"销户"）。

## 运行流程

1. `main.py` 读取命令行参数（yyyymmdd / today|last / steps）与 `config/info.ini [RunParams]`（Place）；
2. 根据运行日计算上一交易日，确定邮件下载日（last 模式取上一交易日）；
3. 按步骤执行：
   - **邮件下载**：登录 `config/email.json` 中配置的全部邮箱，搜索当日邮件并下载附件到 `attachments_dir/{交易日}/`；
   - **解压**：压缩包解压、直接文件拷贝到 `final_directory/{交易日}/`，异常压缩包移入 `question_directory/`；
   - **账号匹配**：查询视图 `v_config_bill_future_account`（当日有效账号），先按文件名匹配资金账号，未命中再按文件内容（前 20 行）匹配；命中后迁移到 `resource/{broker}/{交易日}/`，同时备份到 `history/{broker}/{yyyyMM}/`。

## 目录结构

```
main.py                               主入口：下载→解压→匹配迁移 编排
compile_so.py                         生产部署工具：将 src 下业务模块编译为 .so
pyinstall.py                          一键打包：.so 编译 + PyInstaller + 发布包组装
config/
  info.ini                            运行/数据库/文件目录配置（[RunParams] 等，密码为 Fernet 密文）
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
    generate_key.py / generate_password.py  密钥与密文生成工具
  config/
    globalfunc.py                     配置读取与数据库连接（Place 环境切换）
  email_download/
    email_download.py                 邮件下载（含大邮件强化处理）
  unzip/
    unzip.py                          压缩包解压
  account_match/
    check_file.py                     账号匹配与文件迁移
```

## 配置文件

### config/info.ini（运行参数与连接、目录配置）

- `[RunParams]`：运行时参数
  - `Place`：运行环境，`Trade`=生产 / `Test`=测试（处理日期与执行步骤由命令行参数控制）
- `[DataBaseParams]` / `[TestDataBaseParams]`：生产库 / 测试库（host / port / user / password / database / data_path）
- `[FilePath]` / `[TestFilePath]`：生产 / 测试环境文件目录（attachments_dir / resource_dir / history_dir 及解压相关目录）

> `Place=Trade` 时读取 `[DataBaseParams]` + `[FilePath]`，`Place=Test` 时读取 `[TestDataBaseParams]` + `[TestFilePath]`，
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
# yyyymmdd 为运行日期, today|last 为下载模式, 步骤可选(默认全部执行)
pdm run python main.py 20260826 today                 # 下载当天邮件 → 解压 → 账号匹配
pdm run python main.py 20260826 last                  # 下载上一交易日邮件 → 解压 → 账号匹配
pdm run python main.py 20260826 today download_and_unzip   # 仅下载解压
pdm run python main.py 20260826 today check_account        # 仅账号匹配迁移
```

## 生产打包（思路同 future_data 项目）

```bash
# 一键打包: ① 编译 src 业务模块为 .so(含 generate_key/generate_password 工具)
#          ② 扫描虚拟环境依赖 ③ PyInstaller 打包 main.py(排除 src)
#          ④ 组装发布目录(可执行程序 + 外部 src .so + config 模板)并打 tar.gz
pdm run python pyinstall.py
# 开发机无 gcc 时调试打包可用: pdm run python pyinstall.py --skip-compile(发布包将携带 .py 源码)

# 产物:
#   future_email_data_statement_tree.tar.gz               完整部署包
#   future_email_data_statement_config_template.tar.gz    config 模板包
```

> **部署形态**：`可执行程序 + _internal 运行库 + 外部 src/.so 模块树 + config 模板`，
> 真实凭据不打包（部署时填写 config 并运行 generate_key / generate_password 生成密文），
> 运行方式：`./future_email_data_statement yyyymmdd [today|last] [steps...]`。
> 内网 GitLab 推送与部署步骤见 [docs/内网GitLab推送计划.md](docs/内网GitLab推送计划.md)。

## 日志

- 运行日志：`logs/{日期}.log`

## 已知问题修复记录

**邮件大附件下载失败**（沿用自 auto_down_email 项目，本仓库已修复）：

- **问题**：部分券商在一封邮件中塞入几十个附件，附件大于约 50KB 的文件始终无法下载；
- **根因**：大文件被券商按 RFC 2046 切分为多个 `message/partial` 分片发送，每片无独立文件名，原逻辑在文件名检查处被静默跳过；
- **修复**（email_download/email_download.py）：
  - 按 id / number 重组 `message/partial` 分片并递归提取内嵌附件；
  - 解析改用 `email.policy.default`（RFC 2231 文件名、`name=` 参数回退）；
  - 标准 `get_payload(decode=True)` 优先，失败后按 CTE 手工解码兜底；
  - 取件时校验 `RFC822.SIZE`，检测到服务器截断（或整封解析无附件）时改用 `BODYSTRUCTURE` 逐段（`BODY.PEEK[n]`）取件，绕开大邮件整体取件限制。

## 数据库表（依赖）

- 账号配置视图：`v_config_bill_future_account`（使用字段：future_account_id / broker / start_date / end_date / remark 等）

## 待完成

- 数据清洗（对账单各 sheet 解析）
- 数据入库（bill_* 数据表）与 `bill_processing_log` 断点续跑机制
