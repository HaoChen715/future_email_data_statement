import asyncio
import json
import os
import sys
import time
import warnings

# ============================================================
# 1. 运行路径重定向
#    区分"源码运行"与"PyInstaller 打包运行"两种模式：
#    - 打包后：以可执行程序所在目录为准（外置 src / config 目录）
#    - 源码  ：以 main.py 所在目录为准
# ============================================================
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 将 BASE_DIR 加入模块搜索路径，保证打包后仍能找到外部的 src 模块/.so 文件
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.future_email_data_statement.account_match.check_file import CheckAccountFile
from src.future_email_data_statement.common.CheckTradingDay import CheckTradingDay
from src.future_email_data_statement.email_download.email_download import Auto_DownLoad_Email
from src.future_email_data_statement.unzip.unzip import UnZip

# 忽略 pandas 等库抛出的 UserWarning / FutureWarning，避免日志刷屏
warnings.simplefilter("ignore", UserWarning)
warnings.simplefilter("ignore", FutureWarning)


# ============================================================
# 2. 运行时配置加载
# ============================================================
def load_runtime_config() -> dict:
    """
    读取 config/account_list.json 中的运行时参数。

    参数说明（与 future_data 项目一致）：
        - Place             : 运行环境，Trade=生产 / Test=测试，切换数据库与落盘目录
        - data_list         : 下载日期范围 ['yyyy-mm-dd','yyyy-mm-dd']；空则取最近交易日
        - Direction         : 黑白名单方向：black / white（预留）
        - Account_list      : 黑白名单账号列表（预留）

    Returns:
        dict: 配置字典；文件缺失或 JSON 解析失败时返回空 dict（各参数走默认值）。
    """
    config_path = os.path.join(BASE_DIR, "config", "account_list.json")
    try:
        with open(config_path, mode="r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[main] 读取配置文件失败: {e}，相关参数使用默认值")
        return {}


def _fmt_elapsed(seconds: float) -> str:
    """将运行秒数格式化为 'Xh Ym Zs' 字符串。"""
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours)}h {int(minutes)}m {secs:.2f}s"


# ============================================================
# 3. 单日流水线：邮件下载 → 解压 → 账号匹配迁移
# ============================================================
def run_single_day(trading_day: str, place: str) -> None:
    """
    对单个交易日执行完整文件准备流程。

    1. 邮件下载：按 auto_down_email 思路从邮箱下载当日附件到 attachments/{日}；
    2. 解压：压缩包解压、直接文件拷贝到 unzip/final_file/{日}；
    3. 账号匹配：按数据库视图 v_config_bill_future_account 中的资金账号匹配文件，
       迁移到 resource/{券商}/{日}/ 并备份历史目录。

    Args:
        trading_day (str): 交易日，"yyyy-mm-dd" 格式。
        place (str): 运行环境，Trade / Test。
    """
    download_day = trading_day.replace("-", "")
    print(f"\n{'=' * 50}")
    print(f"[main] 开始处理交易日: {trading_day}")
    print(f"{'=' * 50}\n")

    # ① 邮件下载
    email_download = Auto_DownLoad_Email(
        email_download_day=download_day, statement_type=place
    )
    email_download.main()

    # ② 解压
    unzip = UnZip(unzip_file_day=download_day, statement_type=place)
    unzip.unzip()

    # ③ 账号匹配与文件迁移
    check_file = CheckAccountFile(running_day=download_day, statement_type=place)
    asyncio.run(check_file.main())


# ============================================================
# 4. 程序入口
# ============================================================
def main() -> None:
    """
    程序入口：
        1. 加载配置文件，读取 Place / data_list；
        2. 计算需要处理的交易日列表（空则取最近交易日）；
        3. 逐日执行：邮件下载 → 解压 → 账号匹配迁移。
    """
    start_time = time.time()
    config = load_runtime_config()

    place = config.get("Place", "Trade")
    date_list = config.get("data_list") or [time.strftime("%Y-%m-%d")]
    print(
        f"[main] 配置加载完成: Place={place}, data_list={date_list}"
    )

    # 校验日期范围，得到交易日列表
    check_trading_day = CheckTradingDay()
    trading_days_list = check_trading_day.judge_trading_day(date_list=date_list)
    print(f"[main] 待处理交易日: {trading_days_list}")

    for trading_day in trading_days_list:
        try:
            run_single_day(trading_day=trading_day, place=place)
        except Exception as e:
            import traceback

            print(f"[main] 交易日 {trading_day} 处理异常: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"[main] 程序总运行时间: {_fmt_elapsed(time.time() - start_time)}")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
    print("程序已退出。")
