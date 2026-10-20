"""當日摘要寄 Email:唯一會送到使用者眼前的管道(使用者 2026-10-06 定案不再開 GitHub Issue——
用自己帳號開的 Issue GitHub 不通知,2026-10-04 實測通知數 0,他也不會上去看)。

密碼是 Gmail 的「應用程式密碼」,存在 Mac 鑰匙圈(service = smtp_keychain_service、
account = mail_from),不進 repo、不進設定檔;用 /usr/bin/security 讀——鑰匙圈項目由它建立,
它讀不會跳授權視窗,launchd 底下也讀得到(LaunchAgent 已實測可讀鑰匙圈)。
"""
from __future__ import annotations

import smtplib
import subprocess
from email.message import EmailMessage

from .config import Config
from .osplat import secret


class MailError(Exception):
    pass


def smtp_password(cfg: Config) -> str:
    # Mac 鑰匙圈、Windows 認證管理員(osplat.secret)
    pw = secret(cfg.smtp_keychain_service, cfg.mail_from)
    if not pw:
        raise MailError(f"鑰匙圈(Windows 是認證管理員)裡找不到寄信密碼"
                        f"(service={cfg.smtp_keychain_service}, account={cfg.mail_from})")
    return pw.replace(" ", "")


def send(cfg: Config, subject: str, body: str) -> None:
    if not cfg.mail_to or not cfg.mail_from:
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"wiki-feeder <{cfg.mail_from}>"
    msg["To"] = cfg.mail_to
    msg.set_content(body)
    # 先取密碼再連線:沒密碼就不必連 Gmail(測試也因此不碰網路;2026-10-14 斷網時這裡先報 No route to host)
    password = smtp_password(cfg)
    try:
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=60) as s:
            s.login(cfg.mail_from, password)
            s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise MailError(f"寄信失敗:{e}") from e
