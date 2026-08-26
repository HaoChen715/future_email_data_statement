import base64
import email
import json
import os
import quopri
import re
import shutil
import traceback
import uuid
from datetime import datetime, timedelta
from email.header import decode_header
from email import policy

from dateutil.parser import parse
from imapclient import IMAPClient
from pytz import timezone

from ..common.encrpty import EncryptionTool
from ..common.get_parent_path import ParentPath
from ..common.logger_init import LoggerInit
from ..config.globalfunc import GlobalFunc


class Auto_DownLoad_Email:
    """
    邮件附件下载模块（思路沿用 auto_down_email 项目）。

    针对部分券商"一封邮件塞几十个附件"的场景做了强化：
        - 使用 email.policy.default 解析（RFC 2231 文件名、name= 参数回退）；
        - 按 RFC 2046 重组 message/partial 分片（大附件被切割为多片、单片无文件名，
          旧逻辑会直接跳过导致大附件永远下载不到）；
        - 标准 get_payload(decode=True) 优先，失败后按 CTE 手工解码兜底；
        - 取件时校验 RFC822.SIZE，若整封邮件被服务器截断则改用
          BODYSTRUCTURE 逐段(BODY.PEEK[n])取件，避免大邮件整体取件失败。

    params:
    self.running_day: 程序运行日期
    self.email_download_day: 指定的邮件下载日期（yyyymmdd）
    """

    def __init__(self, email_download_day: str, statement_type: str = "Trade"):
        self.running_day = datetime.now().strftime("%Y%m%d")
        self.email_download_day = email_download_day
        parent_path = ParentPath()
        self.current_dir = parent_path.get_current_dir()
        # 通过 info.ini（Place 切换生产/测试）读取落盘目录与密钥
        global_func = GlobalFunc(statement_type=statement_type)
        self.attachments_dir = global_func.get_file_path("attachments_dir")
        self.encrpty = EncryptionTool(f"{self.current_dir}/config/secret.key")
        logger_init = LoggerInit()
        self.logger = logger_init.logger_init(
            log_path=f"{self.current_dir}/logs/{self.running_day}.log",
            logger_name="email_download_logger",
        )
        self.logger.info("邮件下载程序初始化完成")
        self.logger.info("邮件下载程序开始运行")

    def decode_mime_words(self, mime_words):
        """
        解码 MIME 编码字（RFC 2047）。
        """
        if isinstance(mime_words, bytes):
            mime_words = mime_words.decode("utf-8", errors="ignore")
        decoded_parts = []
        for word, encoding in decode_header(mime_words):
            if isinstance(word, bytes):
                try:
                    word = word.decode(encoding if encoding else "utf-8")
                except (LookupError, UnicodeDecodeError):
                    word = word.decode("utf-8", errors="ignore")
            decoded_parts.append(word)
        return "".join(decoded_parts)

    def load_config(self):
        with open(f"{self.current_dir}/config/email.json", mode="r", encoding="utf-8") as js:
            email_dict = json.load(js)
        return email_dict

    def login(self, email_params):
        """
        登录模块
        """
        try:
            mail = IMAPClient(
                host=email_params["mail_server"],
                port=int(email_params["port"]),
                ssl=True,
                timeout=300,
            )
            if email_params["user_code"] == "True":
                mail.login(
                    self.encrpty.decrypt_message(email_params["email_usr"]),
                    self.encrpty.decrypt_message(email_params["email_safe_code"]),
                )
                self.logger.info("登录成功")
                return mail
            mail.login(
                self.encrpty.decrypt_message(email_params["email_usr"]),
                self.encrpty.decrypt_message(email_params["email_pwd"]),
            )
            self.logger.info("登录成功")
            return mail
        except Exception as e:
            self.logger.error(f"登录失败: {e}")
            self.logger.error("详细异常: %s", traceback.format_exc())
            return None

    def get_server_timezone(self, mail):
        """获取服务器实际时区"""
        try:
            _, caps = mail.capability()
            if b"TIMEZONE" in caps:
                _, tz_data = mail.fetch("1", "(INTERNALDATE)")
                date_str = tz_data[0].decode().split('"')[1]
                return parse(date_str).tzinfo
            return timezone("Asia/Shanghai")  # 默认值
        except Exception:
            return timezone("UTC")

    def generate_unique_filename(self, filename):
        """
        生成随机uuid
        """
        unique_id = uuid.uuid4().hex[:8]
        base, ext = os.path.splitext(filename)
        return f"{base}_{unique_id}{ext}"

    # ============================================================
    # 附件内容解码
    # ============================================================
    @staticmethod
    def _manual_base64_decode(raw) -> bytes:
        """手工 base64 解码（清理非法字符后解码），用于 CTE 不规范的内容兜底。"""
        if isinstance(raw, bytes):
            s = raw.decode("ascii", errors="ignore")
        else:
            s = str(raw)
        s = re.sub(r"[^a-zA-Z0-9+/=]", "", s)
        s += "=" * (-len(s) % 4)
        try:
            return base64.b64decode(s)
        except Exception:
            return None

    @staticmethod
    def _manual_qp_decode(raw) -> bytes:
        """手工 quoted-printable 解码兜底。"""
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        try:
            return quopri.decodestring(data)
        except Exception:
            return None

    def _get_part_payload(self, part) -> bytes:
        """
        获取 MIME 部分的原始字节内容。

        优先使用标准 get_payload(decode=True)；失败后按 Content-Transfer-Encoding
        手工解码兜底；message/rfc822 附件取内嵌邮件原始字节；多部分附件
        （整体携带文件名）合并其非文本子部分。
        """
        if part.get_content_type() == "message/rfc822":
            try:
                inner = part.get_payload(0)
                return inner.as_bytes()
            except Exception:
                pass

        if part.is_multipart():
            # 多部分附件：合并其中的非文本子部分
            chunks = []
            for sub in part.get_payload():
                if sub.get_content_maintype() == "text":
                    continue
                chunk = self._get_part_payload(sub)
                if chunk:
                    chunks.append(chunk)
            return b"".join(chunks) if chunks else None

        try:
            payload = part.get_payload(decode=True)
        except Exception as e:
            self.logger.warning(f"get_payload 解码失败: {e}")
            payload = None
        if payload is not None:
            return payload

        # 兜底：按 CTE 手工解码
        cte = (part.get("Content-Transfer-Encoding") or "").lower()
        raw = part.get_payload()
        if cte == "base64":
            return self._manual_base64_decode(raw)
        if cte == "quoted-printable":
            return self._manual_qp_decode(raw)
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return None

    # ============================================================
    # 附件提取与落盘
    # ============================================================
    def _write_attachment(self, payload: bytes, filename: str, download_dir: str) -> bool:
        """将附件内容写入下载目录，返回是否成功。"""
        # 防止邮件中的文件名携带路径穿越字符
        filename = os.path.basename(str(filename))
        if not filename:
            filename = "unknown_attachment.bin"
        unique_name = self.generate_unique_filename(filename)
        filepath = os.path.join(download_dir, unique_name)
        try:
            with open(filepath, "wb") as f:
                f.write(payload)
        except OSError as e:
            self.logger.error(f"附件写入失败: {filename}, 错误: {e}")
            return False
        written_size = os.path.getsize(filepath)
        if written_size == 0:
            os.remove(filepath)
            self.logger.warning(f"附件内容为空: {filename}")
            return False
        self.logger.info(f"附件下载成功: {filename}, 大小: {written_size} 字节")
        return True

    def _reassemble_partials(self, msg) -> list:
        """
        按 RFC 2046 重组 message/partial 分片。

        部分券商会把大附件切分成多片 message/partial 发送，每一片都没有独立
        文件名（旧逻辑在 filename 检查处直接跳过，导致大附件永远无法下载）。
        此处按 id 分组、number 排序拼接，重组出完整内嵌邮件后交给
        extract_attachments 递归提取其中的附件。

        Args:
            msg: 已解析的邮件对象。

        Returns:
            list: 重组成功的邮件对象列表。
        """
        groups = {}
        for part in msg.walk():
            if part.get_content_type() != "message/partial":
                continue
            params = dict(part.get_params(header="Content-Type", failobj=[]))
            pid = params.get("id")
            if not pid:
                continue
            try:
                number = int(params.get("number", "0"))
            except (TypeError, ValueError):
                continue
            # message/* 部分在 default policy 下会被解析为嵌套消息,
            # get_content() 才能取到分片的原始内容(仍带 CTE 编码)
            raw_content = part.get_content()
            if not raw_content:
                continue
            cte = (part.get("Content-Transfer-Encoding") or "").lower()
            if cte == "base64":
                decoded = self._manual_base64_decode(raw_content)
            elif cte == "quoted-printable":
                decoded = self._manual_qp_decode(raw_content)
            else:
                decoded = raw_content
            if decoded:
                groups.setdefault(pid, {})[number] = (decoded, raw_content, cte)

        rebuilt_list = []
        for pid, pieces in groups.items():
            if not pieces:
                continue
            expected = max(pieces)
            missing = [n for n in range(1, expected + 1) if n not in pieces]
            if missing:
                self.logger.warning(
                    f"message/partial 分片缺失(id={pid}, 已有 {len(pieces)} 片, "
                    f"缺第 {missing} 片), 跳过重组"
                )
                continue
            sorted_pieces = [pieces[n] for n in sorted(pieces)]
            # 方式一(RFC 2046 标准): 每片独立解码后拼接
            data = b"".join(p[0] for p in sorted_pieces)
            rebuilt = self._parse_rebuilt(data)
            if rebuilt is None or not self._has_attachment(rebuilt):
                # 方式二(非标准): 部分系统先对整封邮件做 CTE 编码再切片, 需先拼接再整体解码
                if all(p[2] == "base64" for p in sorted_pieces):
                    joined = b"".join(p[1] for p in sorted_pieces)
                    data2 = self._manual_base64_decode(joined)
                    if data2:
                        rebuilt2 = self._parse_rebuilt(data2)
                        if rebuilt2 is not None:
                            self.logger.warning(
                                f"message/partial(id={pid}) 按整体解码方式重组成功"
                            )
                            rebuilt = rebuilt2
            if rebuilt is None:
                self.logger.error(f"message/partial 重组失败(id={pid}): 无法解析重组内容")
                continue
            rebuilt_list.append(rebuilt)
            self.logger.info(
                f"message/partial 重组成功(id={pid}, {len(pieces)} 片, {len(data)} 字节)"
            )
        return rebuilt_list

    @staticmethod
    def _parse_rebuilt(data: bytes):
        try:
            return email.message_from_bytes(data, policy=policy.default)
        except Exception:
            return None

    @staticmethod
    def _has_attachment(msg) -> bool:
        for part in msg.walk():
            if part.get_content_type() == "message/partial":
                continue
            if part.get_filename():
                return True
        return False

    def extract_attachments(self, msg, download_dir: str) -> int:
        """
        解析整封邮件并下载全部附件。

        Args:
            msg: 已解析的邮件对象。
            download_dir (str): 附件落盘目录。

        Returns:
            int: 成功保存的附件数量。
        """
        total = 0
        for part in msg.walk():
            # message/partial 分片统一由 _reassemble_partials 处理
            if part.get_content_type() == "message/partial":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = self.decode_mime_words(filename)
            payload = self._get_part_payload(part)
            if payload is None:
                self.logger.error(f"附件内容解码失败: {filename}")
                continue
            if self._write_attachment(payload, filename, download_dir):
                total += 1

        # message/partial 分片重组后递归提取内层附件
        for rebuilt in self._reassemble_partials(msg):
            total += self.extract_attachments(rebuilt, download_dir)
        return total

    # ============================================================
    # BODYSTRUCTURE 逐段取件（大邮件/截断兜底）
    # ============================================================
    @staticmethod
    def _bs_lower(value) -> bytes:
        if value is None:
            return b""
        return value.lower() if isinstance(value, bytes) else str(value).lower().encode()

    @staticmethod
    def _bs_param_get(pairs, key: bytes):
        """从 BODYSTRUCTURE 参数元组中取值（键大小写不敏感）。

        兼容两种结构：
            - imapclient 解析器产生的扁平元组 (k, v, k, v, ...)
            - 嵌套对元组 ((k, v), (k, v), ...)
        """
        if not pairs:
            return None
        for i, item in enumerate(pairs):
            if isinstance(item, (tuple, list)):
                # 嵌套对形式
                if len(item) >= 2:
                    k = item[0].lower() if isinstance(item[0], bytes) else str(item[0]).lower().encode()
                    if k == key:
                        return item[1]
            else:
                # 扁平形式
                if i + 1 < len(pairs):
                    k = item.lower() if isinstance(item, bytes) else str(item).lower().encode()
                    if k == key:
                        return pairs[i + 1]
        return None

    @staticmethod
    def _bs_attachment_count(bs_data) -> int:
        """统计 BODYSTRUCTURE 中带文件名的叶子部分数量。"""
        if bs_data is None:
            return 0
        count = 0

        def walk(bd):
            nonlocal count
            if bd.is_multipart:
                for sub in bd[0]:
                    walk(sub)
                return
            params = bd[2] if len(bd) > 2 else None
            dparams = bd[9] if len(bd) > 9 else None
            if (
                Auto_DownLoad_Email._bs_param_get(dparams, b"filename")
                or Auto_DownLoad_Email._bs_param_get(params, b"name")
            ):
                count += 1

        walk(bs_data)
        return count

    def _fetch_part_body(self, mail, email_id, part_number: str, cte: bytes):
        """按段号取回 MIME 部分原始内容并解码。"""
        try:
            response = mail.fetch(email_id, [f"BODY.PEEK[{part_number}]"])
            body = response.get(email_id, {}).get(f"BODY[{part_number}]".encode())
        except Exception as e:
            self.logger.error(f"取段 BODY[{part_number}] 失败: {e}")
            return None
        if body is None:
            return None
        if cte == b"base64":
            return self._manual_base64_decode(body)
        if cte == b"quoted-printable":
            return self._manual_qp_decode(body)
        return body

    def _download_via_bodystructure(self, mail, email_id, bs_data, download_dir: str) -> int:
        """
        逐段取件下载：遍历 BODYSTRUCTURE 找到全部附件叶子，
        逐个用 BODY.PEEK[n] 取回内容并落盘；message/partial 分片同样逐段取回后重组。

        用于整封邮件 BODY[] 取回被服务器截断/解析异常的兜底场景，
        每一段的取回数据量小，避开服务器对大邮件整体取件的限制。

        Returns:
            int: 成功保存的附件数量。
        """
        if bs_data is None:
            self.logger.error("服务器未返回 BODYSTRUCTURE，无法逐段取件")
            return 0

        attachments = []       # (段号, 文件名字节, CTE)
        partial_groups = {}    # id -> {片号: (段号, CTE)}

        def walk(bd, prefix):
            if bd.is_multipart:
                for i, sub in enumerate(bd[0], 1):
                    walk(sub, f"{prefix}.{i}" if prefix else str(i))
                return
            mime = f"{self._bs_lower(bd[0]).decode()}/{self._bs_lower(bd[1]).decode()}"
            cte = self._bs_lower(bd[5]) if len(bd) > 5 else b""
            params = bd[2] if len(bd) > 2 else None
            dparams = bd[9] if len(bd) > 9 else None
            if mime == "message/partial":
                pid = self._bs_param_get(params, b"id")
                try:
                    num = int(self._bs_param_get(params, b"number") or b"0")
                except (TypeError, ValueError):
                    return
                if pid is not None:
                    partial_groups.setdefault(pid, {})[num] = (prefix, cte)
                return
            filename = self._bs_param_get(dparams, b"filename") or self._bs_param_get(params, b"name")
            if filename:
                attachments.append((prefix, filename, cte))

        walk(bs_data, "")

        total = 0
        for part_number, filename, cte in attachments:
            payload = self._fetch_part_body(mail, email_id, part_number, cte)
            if payload is None:
                self.logger.error(f"逐段取件失败: 段 {part_number} (文件名 {filename!r})")
                continue
            decoded_name = self.decode_mime_words(filename)
            if self._write_attachment(payload, decoded_name, download_dir):
                total += 1

        # message/partial 分片逐段取回后重组
        for pid, pieces in partial_groups.items():
            if not pieces:
                continue
            expected = max(pieces)
            if any(n not in pieces for n in range(1, expected + 1)):
                self.logger.warning(f"逐段取件: message/partial 分片缺失(id={pid}), 跳过重组")
                continue
            data = b""
            ok = True
            for n in sorted(pieces):
                part_number, cte = pieces[n]
                chunk = self._fetch_part_body(mail, email_id, part_number, cte)
                if chunk is None:
                    ok = False
                    break
                data += chunk
            if not ok:
                continue
            try:
                rebuilt = email.message_from_bytes(data, policy=policy.default)
                total += self.extract_attachments(rebuilt, download_dir)
                self.logger.info(f"逐段取件: message/partial 重组成功(id={pid})")
            except Exception as e:
                self.logger.error(f"逐段取件: message/partial 重组失败(id={pid}): {e}")
        return total

    # ============================================================
    # 单封邮件下载入口
    # ============================================================
    def download_attachments(self, mail, email_id, download_dir: str) -> int:
        """下载单封邮件的全部附件（含截断检测与逐段取件兜底）。"""
        try:
            # 一次性取回 BODYSTRUCTURE / RFC822.SIZE / BODY[]（单次往返）
            response = mail.fetch(email_id, ["BODYSTRUCTURE", "RFC822.SIZE", "BODY[]"])
            msg_data = response.get(email_id, {})
            raw_email = msg_data.get(b"BODY[]")
            if raw_email is None:
                self.logger.error("BODY[] 数据为空，无法处理该邮件")
                return 0
            declared_size = msg_data.get(b"RFC822.SIZE")
            bs_data = msg_data.get(b"BODYSTRUCTURE")

            # 截断检测：服务器返回的字节数明显少于 RFC822.SIZE
            if declared_size is not None and len(raw_email) < declared_size:
                self.logger.error(
                    f"整封邮件取回被截断（实际 {len(raw_email)} 字节 / 应有 {declared_size} 字节），"
                    "改用 BODYSTRUCTURE 逐段取件"
                )
                return self._download_via_bodystructure(mail, email_id, bs_data, download_dir)

            msg = email.message_from_bytes(raw_email, policy=policy.default)

            # 邮件头信息解析（仅用于日志）
            try:
                rq = parse(msg["Date"].split("(")[0].strip())
                strrq = datetime.strftime(rq, "%Y-%m-%d")
                subject = str(msg["Subject"] or "")
            except Exception:
                strrq = "未知日期"
                subject = "未知主题"
                self.logger.error("解析邮件头信息失败")
            self.logger.info(f"日期: {strrq}, 主题: {subject}, 开始解析附件")

            total = self.extract_attachments(msg, download_dir)

            # 兜底：整封解析无附件，但 BODYSTRUCTURE 显示存在附件
            if total == 0 and self._bs_attachment_count(bs_data) > 0:
                self.logger.warning("整封解析未得到附件，改用 BODYSTRUCTURE 逐段取件兜底")
                total = self._download_via_bodystructure(mail, email_id, bs_data, download_dir)

            self.logger.info(f"邮件处理完成，共下载 {total} 个附件")
            return total

        except Exception as e:
            self.logger.error(f"处理邮件附件失败: {str(e)}")
            self.logger.error(traceback.format_exc())
            return 0

    def main(self):
        try:
            download_dir = os.path.join(self.attachments_dir, self.email_download_day)
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
            else:
                shutil.rmtree(download_dir)
                # 重新创建文件夹
                os.makedirs(download_dir)
                self.logger.info("历史邮件文件清理完成")
            email_dict = self.load_config()
            for user, user_info in email_dict.items():
                self.logger.info(f"当前下载邮件用户：{user}")
                mail = self.login(user_info)
                if not mail:
                    continue

                server_tz = self.get_server_timezone(mail)

                # 精确日期范围计算
                target_date = datetime.strptime(
                    self.email_download_day, "%Y%m%d"
                ).date()
                start_dt = server_tz.localize(
                    datetime(target_date.year, target_date.month, target_date.day)
                )
                end_dt = start_dt + timedelta(days=1)

                # 构建精确搜索条件
                search_criteria = ["SINCE", start_dt, "BEFORE", end_dt]
                self.logger.info(f"最终搜索条件: {search_criteria}")

                try:
                    if user == "yr":
                        mail.id_({"name": "IMAPClient", "version": "2.1.0"})
                    mail.select_folder("INBOX", readonly=True)
                    self.logger.info(f"执行搜索: {search_criteria}")

                    email_ids = mail.search(search_criteria)

                    # 解析响应
                    if not email_ids:
                        self.logger.error(f"搜索失败: 未找到当日邮件")
                        continue

                    self.logger.info(f"找到 {len(email_ids)} 封符合条件的邮件")

                    # 分批次处理
                    BATCH_SIZE = 20
                    for idx in range(0, len(email_ids), BATCH_SIZE):
                        batch = email_ids[idx: idx + BATCH_SIZE]
                        self.logger.info(
                            f"处理批次 {idx // BATCH_SIZE + 1}/{(len(email_ids) - 1) // BATCH_SIZE + 1}"
                        )

                        for email_id in batch:
                            self.download_attachments(mail, email_id, download_dir)

                finally:
                    mail.logout()
        except Exception as e:
            self.logger.error(f"主流程异常: {e}")
            self.logger.error("详细异常: %s", traceback.format_exc())
