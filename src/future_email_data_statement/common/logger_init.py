import logging
import os


class LoggerInit:
    """日志初始化工具类。"""

    # 日志内容格式
    LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
    # 日志时间格式
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S %a"
    # 日志级别
    LOG_LEVEL = logging.INFO

    def logger_init(self, log_path: str, logger_name: str) -> logging.Logger:
        """
        初始化并返回指定名称的 logger。

        :param log_path: 日志文件路径
        :param logger_name: logger 名称，同一名称对应同一个 logger 实例
        :return: 已配置好的 logger
        """
        # 按名称获取 logger（同名 logger 为单例，多次调用返回同一实例）
        logger = logging.getLogger(logger_name)
        logger.setLevel(self.LOG_LEVEL)

        # 确保日志文件所在目录存在，否则 FileHandler 会抛 FileNotFoundError
        log_dir = os.path.dirname(os.path.abspath(log_path))
        os.makedirs(log_dir, exist_ok=True)

        formatter = logging.Formatter(self.LOG_FORMAT, self.DATE_FORMAT)

        # 若已存在指向同一日志文件的文件处理器，则不再重复添加，避免重复输出
        if not any(
            isinstance(handler, logging.FileHandler)
            and handler.baseFilename == os.path.abspath(log_path)
            for handler in logger.handlers
        ):
            # 创建文件处理器，写入指定日志文件
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        # 若已有控制台处理器，则不再重复添加，避免重复输出
        if not any(
            isinstance(handler, logging.StreamHandler)
            for handler in logger.handlers
        ):
            # 创建控制台处理器，输出到标准输出
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

        # 设置 propagate 为 False，避免日志向 root logger 重复传播
        logger.propagate = False

        return logger
