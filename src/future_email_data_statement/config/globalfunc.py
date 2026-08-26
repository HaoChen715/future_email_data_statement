import os
import configparser
from pathlib import Path
from typing import Tuple
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy import URL
from sqlalchemy.engine import Engine
from ..common.encrpty import EncryptionTool
from ..common.get_parent_path import ParentPath


# 环境 -> 配置段 映射（数据库 / 文件目录）
DB_CONFIG_MAP = {
    "Trade": "DataBaseParams",
    "Test": "TestDataBaseParams",
}
FILE_PATH_CONFIG_MAP = {
    "Trade": "FilePath",
    "Test": "TestFilePath",
}
# 文件目录配置键名全集
FILE_PATH_KEYS = (
    "attachments_dir",
    "resource_dir",
    "history_dir",
    "zip_file_dir",
    "extract_directory",
    "final_directory",
    "question_directory",
)


class GlobalFunc:
    """全局配置与数据库连接类（风格沿用 future_data 项目，测试/生产环境隔离）。

    通过 config/account_list.json 的 Place 参数（Trade=生产 / Test=测试）统一切换：
        - 数据库连接   : info.ini 的 [DataBaseParams] / [TestDataBaseParams]
        - 文件落盘目录 : info.ini 的 [FilePath] / [TestFilePath]
    数据库密码为 Fernet 密文，运行时解密。
    """

    def __init__(
        self,
        statement_type: str = "Trade",
        database: str = None,
    ):
        self.statement_type = statement_type
        self.current_dir = self.get_parent_path()
        self.config = self.load_config()
        # 根据运行环境(Place)选择数据库配置段
        db_config = DB_CONFIG_MAP.get(statement_type, "TestDataBaseParams")
        self.db_user = self.config.get(db_config, "user")
        key_file_path = os.path.join(self.current_dir, "config/secret.key")
        decrpty = EncryptionTool(key_file_path)
        self.db_password = decrpty.decrypt_message(
            self.config.get(db_config, "password")
        )
        self.db_host = self.config.get(db_config, "host")
        self.db_port = self.config.get(db_config, "port")
        self.db_database = database or self.config.get(db_config, "database")
        # 对账单文件落盘根目录（当前阶段预留，后续清洗/入库阶段使用）
        self.data_path = self.config.get(db_config, "data_path")

    def get_parent_path(self) -> Path:
        """返回项目根目录（含 pyproject.toml）。"""
        parent = ParentPath()
        return parent.get_current_dir()

    def load_config(self) -> configparser.ConfigParser:
        """加载项目根目录下的 config/info.ini 配置文件。"""
        config = configparser.ConfigParser()
        config.read(f"{self.current_dir}/config/info.ini", encoding="utf-8")
        return config

    def connect_database(self) -> Tuple[Engine, str]:
        """
        连接数据库并获取数据库当前时间。

        Returns:
            Tuple[Engine, str]: (SQLAlchemy Engine, 数据库当前时间 "yyyy-mm-dd HH:MM:SS")。
        """
        url_object = URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,  # plain (unescaped) text
            host=self.db_host,
            database=self.db_database,
            port=int(self.db_port),
        )
        engine = create_engine(url_object)
        query = text("SELECT CURRENT_TIMESTAMP")
        with engine.connect() as connection:
            result = connection.execute(query)
            db_time = result.fetchone()[0]
            db_time = db_time.strftime("%Y-%m-%d %H:%M:%S")
        return engine, db_time

    def _file_config_section(self) -> str:
        """返回当前环境对应的文件目录配置段名。"""
        return FILE_PATH_CONFIG_MAP.get(self.statement_type, "TestFilePath")

    def get_file_path(self, key: str) -> str:
        """
        读取当前环境对应 [FilePath]/[TestFilePath] 段中的文件目录配置。

        Args:
            key (str): 配置键名，如 attachments_dir / resource_dir / history_dir。

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
