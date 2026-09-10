import asyncio
import configparser
import os
import sys
import time
import traceback
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
from src.future_email_data_statement.data_clean.clean_data import CleanDataFile
from src.future_email_data_statement.datainit.broker_init import BrokerInit
from src.future_email_data_statement.email_download.email_download import Auto_DownLoad_Email
from src.future_email_data_statement.unzip.unzip import UnZip

# 忽略 pandas 等库抛出的 UserWarning / FutureWarning，避免日志刷屏
warnings.simplefilter("ignore", UserWarning)
warnings.simplefilter("ignore", FutureWarning)


# ============================================================
# 2. 运行时配置加载
# ============================================================
def load_place() -> str:
    """
    读取 config/info.ini [RunParams] 中的 Place 运行环境。

    处理日期与执行步骤均通过命令行参数控制（见 main），本程序无需其他运行时参数。

    Returns:
        str: 运行环境，Trade=生产 / Test=测试；读取失败时默认 Trade。
    """
    config = configparser.ConfigParser()
    try:
        config.read(os.path.join(BASE_DIR, "config", "info.ini"), encoding="utf-8")
        return config.get("RunParams", "Place", fallback="Trade")
    except Exception as e:
        print(f"[main] 读取配置文件失败: {e}，使用默认 Place=Trade")
        return "Trade"


def _fmt_elapsed(seconds: float) -> str:
    """将运行秒数格式化为 'Xh Ym Zs' 字符串。"""
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours)}h {int(minutes)}m {secs:.2f}s"


# ============================================================
# 3. 主流程：邮件下载 → 解压 → 账号匹配迁移
# ============================================================
def main() -> None:
    """
    程序主入口：邮件下载 -> 压缩包解压 -> 账号校验迁移（参数控制风格沿用 auto_down_email 项目）。

    用法：
        pdm run python main.py yyyymmdd [today|last] [steps...]

    参数说明：
        yyyymmdd     运行日期（邮件下载日）。
        today|last   下载模式：today=下载当天邮件，last=下载上一交易日邮件。
        steps        可选步骤（可多个，默认全部执行）：
                     download_and_unzip / check_account / clean_data
    """
    if len(sys.argv) < 3:
        print("缺少参数！用法：pdm run python main.py yyyymmdd [today|last] [steps...]")
        sys.exit(1)

    start_time = time.time()
    running_day = sys.argv[1]
    is_tradingday = sys.argv[2]
    # 剩余参数为步骤列表；未指定时默认执行完整流水线
    steps = sys.argv[3:] or ["download_and_unzip", "check_account", "clean_data"]

    place = load_place()
    print(
        f"[main] 当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}，运行日: {running_day}，"
        f"下载模式: {is_tradingday}，运行环境: {place}，执行步骤: {steps}"
    )

    # 根据运行日计算上一交易日
    check_trading = CheckTradingDay()
    last_trading_day = check_trading.previous_trading_day(date=running_day)

    # 下载模式为 last 时，下载的是上一交易日的邮件；否则下载当天的邮件
    if is_tradingday == "last":
        email_download_day = last_trading_day
        print(f"[main] 模式 [last]：下载上一交易日 {email_download_day} 的邮件")
    else:
        email_download_day = running_day
        print(f"[main] 模式 [today]：下载当天 {email_download_day} 的邮件")

    # ================= 0. 启动初始化：券商目录结构 =================
    # 按数据库券商列表预建 resource/{broker} 目录，并生成环境专属的
    # config/datapath_init_{Place}.json（思路沿用 auto_down_email 项目）
    try:
        broker_init = BrokerInit(
            init_date=email_download_day, statement_type=place
        )
        broker_init.broker_init()
    except Exception as e:
        print(f"[main] 券商目录初始化失败: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ================= 1. 下载与解压环节 =================
    if "download_and_unzip" in steps:
        try:
            email_download = Auto_DownLoad_Email(
                email_download_day=email_download_day, statement_type=place
            )
            email_download.main()

            # 校验下载结果: 附件目录必须非空, 否则视为失败并明确报错
            download_dir = os.path.join(
                email_download.attachments_dir, email_download_day
            )
            downloaded_files = (
                [f for f in os.listdir(download_dir)]
                if os.path.isdir(download_dir)
                else []
            )
            if not downloaded_files:
                raise RuntimeError(
                    f"附件下载目录为空: {download_dir}，请检查邮箱配置与当日邮件"
                )
            print(
                f"[main] 邮件下载完成: 共 {len(downloaded_files)} 个附件文件"
            )

            unzip = UnZip(unzip_file_day=email_download_day, statement_type=place)
            unzip.unzip()
            print(f"[main] 邮件获取日 {email_download_day} 附件数据下载解压处理完毕")
        except Exception as e:
            print(f"[main] download_and_unzip 步骤执行失败: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.exit(1)

    # ================= 2. 账号校验迁移环节 =================
    if "check_account" in steps:
        try:
            check_file = CheckAccountFile(
                running_day=email_download_day, statement_type=place
            )
            asyncio.run(check_file.main())
            print(f"[main] 邮件获取日 {email_download_day} 附件数据核对分类处理完毕")
        except Exception as e:
            print(f"[main] check_account 步骤执行失败: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.exit(1)

    # ================= 3. 数据清洗环节 =================
    if "clean_data" in steps:
        try:
            clean_data = CleanDataFile(
                running_day=email_download_day, statement_type=place
            )
            clean_results = clean_data.clean()
            cleaned_files = sum(
                len(files) for files in clean_results.values()
            )
            if cleaned_files == 0:
                print(
                    f"[main] 交易日 {email_download_day} 无可清洗的对账单数据，"
                    f"请确认账号匹配迁移已完成"
                )
            else:
                print(
                    f"[main] 邮件获取日 {email_download_day} 对账单数据清洗处理完毕，"
                    f"共清洗 {len(clean_results)} 家券商 {cleaned_files} 个文件"
                )
        except Exception as e:
            print(f"[main] clean_data 步骤执行失败: {type(e).__name__}: {e}")
            traceback.print_exc()
            sys.exit(1)

    print(f"\n{'=' * 50}")
    print(f"[main] 程序总运行时间: {_fmt_elapsed(time.time() - start_time)}")
    print(f"{'=' * 50}\n")


def _setup_builtin_cert():
    """【证书补丁】让 Python 优先使用程序内置的 cacert.pem，避免 SSL 证书校验失败。

    思路沿用 auto_down_email 项目：打包后 PyInstaller 冻结环境的 ssl 默认 CA
    路径是打包机编译 Python 时的系统路径，目标服务器上往往不存在，导致 IMAP
    登录时报"没有 ssl 安全证书"。此处优先使用 pyinstall.py --add-data 复制到
    程序根目录的 certifi cacert.pem，回退 certifi 内置证书。
    """
    builtin_cacert = os.path.join(os.path.dirname(sys.executable), "cacert.pem")

    # PyInstaller onefile 模式：sys.executable 位于临时解压目录，
    # 实际证书随程序解压到 sys._MEIPASS 目录
    if not os.path.exists(builtin_cacert):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            builtin_cacert = os.path.join(meipass, "cacert.pem")
        else:
            # 非 PyInstaller（源码开发），从当前工作目录查找
            builtin_cacert = os.path.join(os.getcwd(), "cacert.pem")

    if os.path.exists(builtin_cacert):
        # 通过标准环境变量通知 Python 与 requests 使用指定 CA 证书
        os.environ["SSL_CERT_FILE"] = builtin_cacert
        os.environ["REQUESTS_CA_BUNDLE"] = builtin_cacert
        print(f"✅ 已启用内置证书: {builtin_cacert}")
    else:
        print("⚠️ 未找到内置证书，将使用系统默认证书路径")
        # 回退到 certifi 提供的默认证书
        try:
            import certifi

            os.environ["SSL_CERT_FILE"] = certifi.where()
            print(f"✅ 退回到 certifi 默认证书: {certifi.where()}")
        except ImportError:
            print("❌ 未找到 certifi，无法加载任何证书（如遇 SSL 错误请安装 certifi）")


# 启动前自动注入证书配置
_setup_builtin_cert()


if __name__ == "__main__":
    main()
    print("程序已退出。")
