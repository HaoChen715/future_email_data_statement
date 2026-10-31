import os
import re
import configparser
from pathlib import Path
from src.future_email_data_statement.common.get_parent_path import ParentPath


# 环境 -> 配置段 映射（文件目录 / 入库 API）
FILE_PATH_CONFIG_MAP = {
    "Trade": "FilePath",
    "Test": "TestFilePath",
}
API_CONFIG_MAP = {
    "Trade": "ApiParams",
    "Test": "TestApiParams",
}
# 文件目录配置键名全集（与 auto_down_email 项目 data_paths.json 键名一致）
FILE_PATH_KEYS = (
    "email_download_root",
    "resource_root",
    "unzip_zip_root",
    "unzip_extract_root",
    "unzip_final_root",
    "unzip_question_root",
)


class GlobalFunc:
    """全局配置类（风格沿用 future_data 项目，测试/生产环境隔离）。

    由 main.py 读取 config/info.ini [RunParams] 的 Place 参数
    （Trade=生产 / Test=测试）传入后统一切换：
        - 入库 API  : info.ini 的 [ApiParams] / [TestApiParams]
        - 文件落盘目录 : info.ini 的 [FilePath] / [TestFilePath]

    对账单数据不再直连数据库，读写均通过 Open API 完成
    （见 data_insert/api_client.py）。
    """

    def __init__(self, statement_type: str = "Trade"):
        self.statement_type = statement_type
        self.current_dir = self.get_parent_path()
        self.config = self.load_config()

    def get_parent_path(self) -> Path:
        """返回项目根目录（含 pyproject.toml 或 config/info.ini）。"""
        parent = ParentPath()
        return parent.get_current_dir()

    def load_config(self) -> configparser.ConfigParser:
        """加载项目根目录下的 config/info.ini 配置文件。"""
        config = configparser.ConfigParser()
        config.read(f"{self.current_dir}/config/info.ini", encoding="utf-8")
        return config

    def _file_config_section(self) -> str:
        """返回当前环境对应的文件目录配置段名。"""
        return FILE_PATH_CONFIG_MAP.get(self.statement_type, "TestFilePath")

    def get_file_path(self, key: str) -> str:
        """
        读取当前环境对应 [FilePath]/[TestFilePath] 段中的文件目录配置。

        Args:
            key (str): 配置键名，如 email_download_root / resource_root / unzip_zip_root。

        Returns:
            str: 目录路径；相对路径（以 ./ 开头）将基于项目根目录展开。
        """
        section = self._file_config_section()
        raw_path = self.config.get(section, key)
        if raw_path.startswith("./"):
            return os.path.join(self.current_dir, raw_path[2:])
        return raw_path

    def get_file_paths(self) -> dict:
        """
        读取当前环境对应的全部文件目录配置。

        Returns:
            dict: {配置键名: 展开后的目录路径}。
        """
        section = self._file_config_section()
        paths = {}
        for key in FILE_PATH_KEYS:
            raw_path = self.config.get(section, key)
            paths[key] = (
                os.path.join(self.current_dir, raw_path[2:])
                if raw_path.startswith("./")
                else raw_path
            )
        return paths

    def get_broker_whitelist(self) -> set:
        """
        读取券商白名单（[BrokerFilter] brokers）。

        仅白名单内的券商视为「已注册券商」，用于生成券商目录与账号匹配过滤。

        Returns:
            set: 券商名称集合；未配置时返回空集合（表示不限制）。
        """
        raw = self.config.get("BrokerFilter", "brokers", fallback="")
        # 支持英文/中文逗号与换行分隔
        return {
            name.strip()
            for name in re.split(r"[,\n，]", raw)
            if name.strip()
        }

    def get_file_extensions(self) -> set:
        """
        读取只参与扫描/匹配的文件扩展名（[RunParams] File_extensions）。

        Returns:
            set: 小写扩展名集合（含前导点）；未配置时默认 .txt/.xlsx/.xls。
        """
        raw = self.config.get(
            "RunParams", "File_extensions", fallback=".txt,.xlsx,.xls"
        )
        extensions = set()
        for part in re.split(r"[,\n，;；]", raw):
            ext = part.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            extensions.add(ext)
        return extensions or {".txt", ".xlsx", ".xls"}

    def get_api_config(self) -> dict:
        """
        读取当前环境对应的入库 API 配置（[ApiParams]/[TestApiParams]）。

        Returns:
            dict: {base_url, timeout, app_key, app_secret, user_agent,
                verify_ssl, log_path}；配置段缺失时返回默认值。
        """
        section = API_CONFIG_MAP.get(self.statement_type, "TestApiParams")
        if not self.config.has_section(section):
            return {
                "base_url": "",
                "timeout": 30,
                "app_key": "",
                "app_secret": "",
                "user_agent": "",
                "verify_ssl": True,
                "log_path": "",
            }
        return {
            "base_url": self.config.get(section, "base_url", fallback="").strip(),
            "timeout": self.config.getint(section, "timeout", fallback=30),
            "app_key": self.config.get(section, "app_key", fallback="").strip(),
            "app_secret": self.config.get(
                section, "app_secret", fallback=""
            ).strip(),
            "user_agent": self.config.get(section, "user_agent", fallback="").strip(),
            "verify_ssl": self.config.getboolean(
                section, "verify_ssl", fallback=True
            ),
            "log_path": self.config.get(section, "log_path", fallback="").strip(),
        }
