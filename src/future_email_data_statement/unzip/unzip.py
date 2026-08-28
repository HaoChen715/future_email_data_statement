import os
import shutil
import traceback
import uuid
from datetime import datetime

import patoolib
import rarfile

from src.future_email_data_statement.common.get_parent_path import ParentPath
from src.future_email_data_statement.config.globalfunc import GlobalFunc
from src.future_email_data_statement.common.logger_init import LoggerInit


class UnZip:
    """
    邮件附件解压模块（思路沿用 auto_down_email 项目）。

    部分券商提供 zip/rar 压缩包附件，部分直接提供 xlsx/xls/txt 文件：
    - 直接文件：拷贝到最终文件目录；
    - 压缩包：解压后将其中的 xlsx/xls 拷贝到最终文件目录（解压失败移入异常目录）。
    """

    def __init__(self, unzip_file_day: str, statement_type: str = "Trade"):
        self.running_day = datetime.now().strftime("%Y%m%d")
        self.unzip_file_day = unzip_file_day
        parent_path = ParentPath()
        self.current_dir = parent_path.get_current_dir()
        global_func = GlobalFunc(statement_type=statement_type)
        # 全部目录均随 Place 切换生产/测试环境（info.ini [FilePath]/[TestFilePath]）
        self.paths = global_func.get_file_paths()
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="unzip_logger",
        )
        self.logger.info("压缩文件解压程序开始运行")
        self.logger.info("压缩文件解压程序配置文件加载完毕")

    def decode_filename(self, encoded_name):
        """
        尝试将文件名从cp437 编码解码为 utf-8 编码
        """
        try:
            return encoded_name.encode("cp437", errors="ignore").decode(
                "gbk", errors="ignore"
            )
        except Exception as e:
            self.logger.error(f"文件名解码失败：{encoded_name}, 错误: {e}")
            return encoded_name

    def generate_unique_filename(self, filename):
        unique_id = str(uuid.uuid4())
        base, ext = os.path.splitext(filename)
        return f"{base}_{unique_id}{ext}"

    def rename_and_move(self, extract_dir, final_dir):
        # 查找解压后的 XLSX 和 XLS 文件
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if file.endswith((".xlsx", ".xls")):
                    # 拷贝到最终目录
                    original_path = os.path.join(root, file)
                    unique_file = self.generate_unique_filename(filename=file)
                    new_path = os.path.join(extract_dir, unique_file)
                    try:
                        os.rename(original_path, new_path)
                    except OSError as o:
                        self.logger.error("文件重命名失败：%s", o)
                        new_path = os.path.join(extract_dir, file)
                    shutil.move(new_path, final_dir)

    def unzip(self):
        # 定义目录路径
        source_dir = os.path.join(
            self.paths["email_download_root"], self.unzip_file_day
        )  # 源目录
        zip_file_dir = os.path.join(
            self.paths["unzip_zip_root"], self.unzip_file_day
        )  # 拷贝目录
        extract_dir = os.path.join(
            self.paths["unzip_extract_root"], self.unzip_file_day
        )  # 解压目录
        final_dir = os.path.join(
            self.paths["unzip_final_root"], self.unzip_file_day
        )  # 最终文件存放目录
        question_dir = os.path.join(
            self.paths["unzip_question_root"], self.unzip_file_day
        )  # 异常压缩文件存放目录

        # 确保目录存在
        path_list = [zip_file_dir, extract_dir, final_dir, question_dir]
        for path in path_list:
            if not os.path.exists(path):
                os.makedirs(path)
            else:
                shutil.rmtree(path)
                # 重新创建文件夹
                os.makedirs(path)
                self.logger.info("历史解压文件清理完成")

        # 遍历目录, 先将文件附件全部拷贝到zip目录
        processed_count = 0
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith(
                    (".zip", ".ZIP", ".rar", ".RAR")
                ):  # 检查压缩文件
                    # 拷贝到拷贝目录
                    file_path = os.path.join(root, file)
                    shutil.copy(file_path, zip_file_dir)
                    processed_count += 1
                elif file.endswith(
                    (".xls", ".xlsx", ".txt", ".TXT", ".XLS", ".XLSX")
                ):
                    file_path = os.path.join(root, file)
                    shutil.copy(file_path, final_dir)
                    processed_count += 1

        # 附件目录中没有任何可处理文件时直接报错, 避免"静默成功"
        if processed_count == 0:
            raise RuntimeError(
                f"附件目录 {source_dir} 中没有可处理的压缩包或对账单文件, "
                "请检查邮件下载步骤是否成功"
            )

        # 解压拷贝的压缩文件
        for file in os.listdir(zip_file_dir):
            file_path = os.path.join(zip_file_dir, file)
            # 解压文件
            if file.endswith((".zip", ".ZIP", ".rar", ".RAR")):
                try:
                    patoolib.extract_archive(file_path, outdir=extract_dir)
                    self.logger.info(f"文件 {file} 解压完成")
                    # 解压后对文件名进行二次处理
                    for extracted_file in os.listdir(extract_dir):
                        original_path = os.path.join(
                            extract_dir, extracted_file
                        )
                        decode_name = self.decode_filename(extracted_file)
                        new_path = os.path.join(extract_dir, decode_name)
                        if original_path != new_path:
                            try:
                                os.rename(original_path, new_path)
                            except OSError as o:
                                self.logger.error("文件重命名失败：%s", o)
                except Exception as e:
                    # 额外增加针对rar文件的再次解压尝试
                    if file.endswith((".RAR", ".rar")):
                        try:
                            with rarfile.RarFile(file_path) as rf:
                                rf.extractall(extract_dir)
                                for extracted_file in os.listdir(
                                    extract_dir
                                ):
                                    original_path = os.path.join(
                                        extract_dir, extracted_file
                                    )
                                    decode_name = self.decode_filename(
                                        extracted_file
                                    )
                                    new_path = os.path.join(
                                        extract_dir, decode_name
                                    )
                                    if original_path != new_path:
                                        try:
                                            os.rename(
                                                original_path, new_path
                                            )
                                        except OSError as o:
                                            self.logger.error(
                                                "文件重命名失败：%s", o
                                            )
                        except rarfile.Error:
                            self.logger.error(
                                f"解压文件时存在问题，请单独处理，文件名：{file} 已移动到异常文件目录{question_dir}"
                            )
                            shutil.move(file_path, question_dir)
                    else:
                        self.logger.error(
                            f"解压文件时存在问题，请单独处理，文件名：{file} 已移动到异常文件目录{question_dir}"
                        )
                        shutil.move(file_path, question_dir)
                # 查找解压后的 XLSX 和 XLS 文件
                self.rename_and_move(
                    extract_dir=extract_dir, final_dir=final_dir
                )
        self.logger.info("文件解压任务处理完成")
