import base64
import email
import imaplib
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

from src.future_email_data_statement.common.encrpty import EncryptionTool
from src.future_email_data_statement.common.get_parent_path import ParentPath
from src.future_email_data_statement.common.logger_init import LoggerInit
from src.future_email_data_statement.config.globalfunc import GlobalFunc


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
        self.attachments_dir = global_func.get_file_path("email_download_root")
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
            try:
                # 提高 imaplib 单行长度上限, 防止超长 BODYSTRUCTURE 等响应行导致取件异常
                imaplib._MAXLINE = 20_000_000
            except Exception:
                pass
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
        """获取服务器实际时区，失败时回退 Asia/Shanghai。"""
        try:
            _, caps = mail.capability()
            if b"TIMEZONE" not in caps:
                return timezone("Asia/Shanghai")
            # TIMEZONE 扩展可用: 用 INTERNALDATE 推断服务器时区
            # (禁用时间归一化, 保留原始时区偏移)
            mail.normalise_times = False
            try:
                response = mail.fetch(1, ["INTERNALDATE"])
                internal_date = response.get(1, {}).get(b"INTERNALDATE")
                if internal_date is not None and internal_date.tzinfo is not None:
                    return internal_date.tzinfo
            finally:
                mail.normalise_times = True
        except Exception:
            pass
        # 默认值: 券商邮箱均为国内服务器, 任何异常都不应回退到 UTC
        # (UTC 会让搜索窗口偏移 8 小时, 漏掉凌晨时段收到的邮件)
        return timezone("Asia/Shanghai")

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

    def _embedded_is_encoded(self, part) -> bool:
        """
        判断 message/rfc822 部分是否被 CTE 编码且解析器未能解码。

        解析器未解码时内层是携带编码文本的 text/plain 壳，walk() 无法看到
        真实内嵌邮件，需要手动解码后递归提取。
        """
        cte = (part.get("Content-Transfer-Encoding") or "").lower()
        if cte not in ("base64", "quoted-printable"):
            return False
        payload = part.get_payload()
        if not isinstance(payload, list) or len(payload) != 1:
            return False
        inner = payload[0]
        if inner.get_content_type() != "text/plain" or inner.get_filename():
            return False
        return bool(inner.get_payload())

    def _get_embedded_message(self, part):
        """
        返回 message/rfc822 部分的真实内嵌邮件对象。

        Python email 解析器不会对 message/rfc822 部分应用 CTE 解码：当该部分
        被 base64/quoted-printable 编码时，解析出来的"内嵌邮件"其实是一个
        text/plain 壳(内容为编码文本)。此处识别该情况，先按 CTE 解码再重新
        解析，得到真实的内嵌邮件（券商邮件常见的 .bin 包装 rar 即此类）。
        """
        payload = part.get_payload()
        if not isinstance(payload, list) or len(payload) != 1:
            return None
        inner = payload[0]
        cte = (part.get("Content-Transfer-Encoding") or "").lower()
        if cte not in ("base64", "quoted-printable"):
            return inner
        # 判断内层是否为携带编码文本的 text/plain 壳
        if inner.get_content_type() != "text/plain" or inner.get_filename():
            return inner
        text = inner.get_payload()
        if not text:
            return inner
        if cte == "base64":
            decoded = self._manual_base64_decode(text)
        else:
            decoded = self._manual_qp_decode(text)
        if not decoded:
            return inner
        rebuilt = self._parse_rebuilt(decoded)
        return rebuilt if rebuilt is not None else inner

    def _get_part_payload(self, part) -> bytes:
        """
        获取 MIME 部分的原始字节内容。

        优先使用标准 get_payload(decode=True)；失败后按 Content-Transfer-Encoding
        手工解码兜底；message/rfc822 附件取内嵌邮件原始字节；多部分附件
        （整体携带文件名）合并其非文本子部分。
        """
        if part.get_content_type() == "message/rfc822":
            try:
                inner = self._get_embedded_message(part)
                if inner is not None:
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
    @staticmethod
    def _sniff_archive_extension(payload: bytes, filename: str) -> str:
        """
        按文件魔数修正扩展名。

        部分券商邮件用 .bin/.dat 等扩展名携带压缩包内容（客户端也显示 .bin），
        但实际是 rar/zip。此处根据魔数把扩展名修正为真实格式，保证后续
        解压流程能识别该附件。
        """
        base = os.path.splitext(str(filename))[0]
        ext = (os.path.splitext(str(filename))[1] or "").lower()
        if ext in {
            ".rar", ".zip", ".7z", ".gz", ".tar",
            ".xls", ".xlsx", ".txt", ".csv", ".pdf",
            ".doc", ".docx", ".png", ".jpg", ".jpeg",
        }:
            return filename
        magic = payload[:8] if isinstance(payload, (bytes, bytearray)) else b""
        if magic.startswith(b"Rar!"):
            return f"{base}.rar"
        if magic.startswith(b"PK\x03\x04"):
            return f"{base}.zip"
        if magic.startswith(b"7z\xbc\xaf\x27\x1c"):
            return f"{base}.7z"
        if magic.startswith(b"\x1f\x8b"):
            return f"{base}.gz"
        return filename

    def _write_attachment(self, payload: bytes, filename: str, download_dir: str) -> bool:
        """将附件内容写入下载目录，返回是否成功。"""
        # 防止邮件中的文件名携带路径穿越字符
        filename = os.path.basename(str(filename))
        if not filename:
            filename = "unknown_attachment.bin"
        # .bin/.dat 等扩展名但实为压缩包的附件, 按魔数修正扩展名
        filename = self._sniff_archive_extension(payload, filename)
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

    @staticmethod
    def _is_nameless_attachment(part) -> bool:
        """判断一个没有文件名的 MIME 部分是否仍应作为附件保存。"""
        maintype = part.get_content_maintype()
        if maintype in ("text", "multipart", "image", "audio", "video", "message"):
            return False
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment":
            return True
        if not disp and maintype == "application":
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
        nameless_idx = 0
        for part in msg.walk():
            # message/partial 分片统一由 _reassemble_partials 处理
            if part.get_content_type() == "message/partial":
                continue
            # message/rfc822 内嵌邮件: 带文件名时原样保存(客户端显示的 .bin 即此类),
            # CTE 编码未解码时需手动解码后递归提取其中的附件
            if part.get_content_type() == "message/rfc822":
                filename = part.get_filename()
                if filename:
                    filename = self.decode_mime_words(filename)
                    payload = self._get_part_payload(part)
                    if payload is not None:
                        if self._write_attachment(payload, filename, download_dir):
                            total += 1
                # walk() 能下钻正常解析的内嵌邮件; 仅当 CTE 编码未被解析器解码时
                # 才需手动解码后递归提取(避免重复提取)
                if self._embedded_is_encoded(part):
                    try:
                        inner = self._get_embedded_message(part)
                        if inner is not None and hasattr(inner, "walk"):
                            total += self.extract_attachments(inner, download_dir)
                    except Exception:
                        pass
                continue
            filename = part.get_filename()
            if not filename:
                # 无文件名的 application 附件(如整封邮件仅携带一个二进制文件)也要保存,
                # 落盘后按魔数修正扩展名
                if not self._is_nameless_attachment(part):
                    continue
                nameless_idx += 1
                filename = f"attachment_{nameless_idx}.bin"
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
        rfc822_parts = []      # (段号, CTE) 内嵌邮件, 取回后再递归提取其中的附件
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
            if mime == "message/rfc822":
                filename = self._bs_param_get(dparams, b"filename") or self._bs_param_get(params, b"name")
                if filename:
                    attachments.append((prefix, filename, cte))
                rfc822_parts.append((prefix, cte))
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

        # message/rfc822 内嵌邮件: 取回原始内容后递归提取其中的附件
        for part_number, cte in rfc822_parts:
            raw = self._fetch_part_body(mail, email_id, part_number, cte)
            if not raw:
                self.logger.warning(f"逐段取件: 内嵌邮件段 {part_number} 取回失败")
                continue
            try:
                inner_msg = email.message_from_bytes(raw, policy=policy.default)
                total += self.extract_attachments(inner_msg, download_dir)
                self.logger.info(f"逐段取件: 内嵌邮件段 {part_number} 附件提取完成")
            except Exception as e:
                self.logger.error(f"逐段取件: 内嵌邮件段 {part_number} 解析失败: {e}")

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
    def _log_message_meta(self, mail, email_id) -> None:
        """
        取回并记录邮件的日期/主题。

        独立于正文取回（ENVELOPE 失败则回退 HEADER.FIELDS），保证每封邮件在
        日志中都能按主题定位，即使后续正文取回失败也不会漏掉该邮件的信息。
        """
        subject = "未知主题"
        strrq = "未知日期"
        try:
            response = mail.fetch(email_id, ["ENVELOPE"])
            env = response.get(email_id, {}).get(b"ENVELOPE")
            if env is not None:
                if getattr(env, "date", None) is not None:
                    strrq = env.date.strftime("%Y-%m-%d")
                if env.subject:
                    subject = self.decode_mime_words(env.subject)
        except Exception as e:
            self.logger.debug(f"ENVELOPE 获取失败: {e}")
        if subject == "未知主题" or strrq == "未知日期":
            try:
                response = mail.fetch(email_id, ["BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)]"])
                header = response.get(email_id, {}).get(
                    b"BODY[HEADER.FIELDS (SUBJECT DATE)]"
                )
                if header:
                    hmsg = email.message_from_bytes(header, policy=policy.default)
                    if subject == "未知主题" and hmsg["Subject"]:
                        subject = self.decode_mime_words(str(hmsg["Subject"]))
                    if strrq == "未知日期" and hmsg["Date"]:
                        try:
                            rq = parse(hmsg["Date"].split("(")[0].strip())
                            strrq = datetime.strftime(rq, "%Y-%m-%d")
                        except Exception:
                            pass
            except Exception as e:
                self.logger.debug(f"HEADER.FIELDS 获取失败: {e}")
        self.logger.info(f"邮件 ID: {email_id}, 日期: {strrq}, 主题: {subject}, 开始解析附件")

    def _fetch_message_info(self, mail, email_id):
        """
        取回 BODYSTRUCTURE / RFC822.SIZE，失败不阻塞后续取件。

        Returns:
            tuple: (bs_data, declared_size)，失败时对应位置为 None。
        """
        try:
            response = mail.fetch(email_id, ["BODYSTRUCTURE", "RFC822.SIZE"])
            msg_data = response.get(email_id, {})
            return msg_data.get(b"BODYSTRUCTURE"), msg_data.get(b"RFC822.SIZE")
        except Exception as e:
            self.logger.warning(f"BODYSTRUCTURE/RFC822.SIZE 获取失败: {e}，继续整封取件")
            return None, None

    def _fetch_body_once(self, mail, email_id):
        """一次性取回整封邮件 BODY[]，失败返回 None。"""
        try:
            response = mail.fetch(email_id, ["BODY[]"])
            return response.get(email_id, {}).get(b"BODY[]")
        except Exception as e:
            self.logger.warning(f"整封邮件一次性取回失败: {e}")
            return None

    def _fetch_body_chunked(self, mail, email_id, declared_size=None):
        """
        按 RFC 3501 partial 分块取回整封邮件 BODY.PEEK[]<offset.size>。

        用于一次性 BODY[] 取回失败/超时的大邮件兜底，也兼容对单次响应
        大小有限制的服务器。
        """
        chunk_size = 10 * 1024 * 1024
        blob = bytearray()
        offset = 0
        while True:
            try:
                response = mail.fetch(email_id, [f"BODY.PEEK[]<{offset}.{chunk_size}>"])
                chunk = response.get(email_id, {}).get(f"BODY[]<{offset}>".encode())
            except Exception as e:
                self.logger.warning(f"分块取回 BODY[]<{offset}> 失败: {e}")
                break
            if not chunk:
                break
            blob.extend(chunk)
            offset += len(chunk)
            if declared_size and offset >= declared_size:
                break
            if not declared_size and len(chunk) < chunk_size:
                # 服务器未声明大小, 返回不足一块说明已到末尾
                break
        if not blob:
            return None
        if declared_size and len(blob) < declared_size:
            self.logger.warning(f"分块取回仍不完整（{len(blob)}/{declared_size} 字节）")
        return bytes(blob)

    def download_attachments(self, mail, email_id, download_dir: str) -> int:
        """下载单封邮件的全部附件（含截断检测与逐段取件兜底）。"""
        # 先记录邮件日期/主题, 保证每封邮件在日志中均可定位
        self._log_message_meta(mail, email_id)

        try:
            # 取回 BODYSTRUCTURE / RFC822.SIZE（失败不阻塞）
            bs_data, declared_size = self._fetch_message_info(mail, email_id)

            # 整封邮件取回：一次性 BODY[]，失败回退分块取回
            raw_email = self._fetch_body_once(mail, email_id)
            if not raw_email:
                self.logger.warning("整封一次性取回失败，改用分块取回")
                raw_email = self._fetch_body_chunked(mail, email_id, declared_size)

            # 整封取回彻底失败：改用 BODYSTRUCTURE 逐段取件
            if not raw_email:
                self.logger.error("整封邮件取回失败，改用 BODYSTRUCTURE 逐段取件")
                return self._download_via_bodystructure(
                    mail, email_id, bs_data, download_dir
                )

            # 截断检测：服务器返回的字节数明显少于 RFC822.SIZE
            if declared_size is not None and len(raw_email) < declared_size:
                self.logger.error(
                    f"整封邮件取回被截断（实际 {len(raw_email)} 字节 / 应有 {declared_size} 字节），"
                    "改用 BODYSTRUCTURE 逐段取件"
                )
                return self._download_via_bodystructure(
                    mail, email_id, bs_data, download_dir
                )

            msg = email.message_from_bytes(raw_email, policy=policy.default)

            total = self.extract_attachments(msg, download_dir)

            # 兜底：整封解析无附件，但 BODYSTRUCTURE 显示存在附件
            if total == 0 and self._bs_attachment_count(bs_data) > 0:
                self.logger.warning("整封解析未得到附件，改用 BODYSTRUCTURE 逐段取件兜底")
                total = self._download_via_bodystructure(
                    mail, email_id, bs_data, download_dir
                )

            self.logger.info(f"邮件处理完成，共下载 {total} 个附件")
            return total

        except Exception as e:
            self.logger.error(f"处理邮件附件失败: {str(e)}")
            self.logger.error(traceback.format_exc())
            return 0

    def main(self):
        download_dir = os.path.join(self.attachments_dir, self.email_download_day)
        try:
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
            else:
                shutil.rmtree(download_dir)
                # 重新创建文件夹
                os.makedirs(download_dir)
                self.logger.info("历史邮件文件清理完成")
        except Exception as e:
            self.logger.error(f"附件下载目录创建失败: {download_dir}, 错误: {e}")
            self.logger.error("详细异常: %s", traceback.format_exc())
            raise

        try:
            email_dict = self.load_config()
        except FileNotFoundError:
            raise RuntimeError(
                f"邮箱配置文件不存在: {self.current_dir}/config/email.json"
            )
        if not email_dict:
            raise RuntimeError("config/email.json 中无邮箱账号配置")

        login_success = 0
        total_attachments = 0
        for user, user_info in email_dict.items():
            self.logger.info(f"当前下载邮件用户：{user}")
            mail = self.login(user_info)
            if not mail:
                continue
            login_success += 1

            try:
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

                if user == "yr":
                    mail.id_({"name": "IMAPClient", "version": "2.1.0"})
                mail.select_folder("INBOX", readonly=True)
                self.logger.info(f"执行搜索: {search_criteria}")

                email_ids = mail.search(search_criteria)

                # 解析响应
                if not email_ids:
                    self.logger.warning(f"邮箱 {user} 未找到当日邮件")
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
                        total_attachments += self.download_attachments(
                            mail, email_id, download_dir
                        )
            except Exception as e:
                # 单个邮箱处理失败不影响其他邮箱, 记日志后继续
                self.logger.error(f"邮箱 {user} 处理异常: {e}")
                self.logger.error("详细异常: %s", traceback.format_exc())
            finally:
                try:
                    mail.logout()
                except Exception:
                    pass

        if login_success == 0:
            raise RuntimeError(
                "所有邮箱账号均登录失败, 请检查 config/email.json 账号与口令配置"
            )
        self.logger.info(
            f"邮件下载完成: 共 {login_success} 个邮箱登录成功, "
            f"下载 {total_attachments} 个附件"
        )
