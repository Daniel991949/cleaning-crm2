# -*- coding: utf-8 -*-
"""
メールボックス（IMAP）から「クリーニング見積もり」メールを取得し、
SQLite に保存するユーティリティ。

CLI で実行するとき  ────────────────
$ python email_sync_app.py                 # 直近 20 通だけ取得
$ python email_sync_app.py --limit 50      # 直近 50 通だけ取得
$ python email_sync_app.py --mode month    # 過去 1 か月分をまとめて取得

Heroku Scheduler から呼び出す例 ─────────────
Hourly で：  python email_sync_app.py --limit 20
一度だけ：  python email_sync_app.py --mode month
"""

import os
import re
import sys
import imaplib
import email
import argparse
from email.header import decode_header
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup        # pip install beautifulsoup4
from dotenv import load_dotenv       # pip install python-dotenv
from sqlalchemy import (
    create_engine, Column, BigInteger, String,
    Text, DateTime, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker

# ---------------------------------------------------------------------------
# Windows での日本語標準出力対策
# ---------------------------------------------------------------------------
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# ---------------------------------------------------------------------------
# .env 読み込み
# ---------------------------------------------------------------------------
load_dotenv()
IMAP_HOST     = os.getenv('IMAP_HOST', 'imap.gmail.com')
IMAP_PORT     = int(os.getenv('IMAP_PORT', '993'))
IMAP_USER     = os.getenv('IMAP_USER')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')
MAILBOX       = os.getenv('IMAP_MAILBOX', 'INBOX')
DB_URL        = os.getenv('DATABASE_URL', 'sqlite:///emails.db')

if not IMAP_USER or not IMAP_PASSWORD:
    print('[ERROR] IMAP_USER / IMAP_PASSWORD が .env にありません', file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# DB 定義
# ---------------------------------------------------------------------------
Base = declarative_base()

class EmailModel(Base):
    __tablename__ = 'emails'

    uidvalidity  = Column(BigInteger, primary_key=True)
    uid          = Column(BigInteger, primary_key=True)
    message_id   = Column(String(255), unique=True, nullable=False)

    subject      = Column(Text)
    from_addr    = Column(Text)
    to_addr      = Column(Text)
    date         = Column(DateTime)
    body         = Column(Text)
    raw_content  = Column(Text)

    status       = Column(String(20), default='新規')
    gpt_response = Column(Text)
    fetched_at   = Column(DateTime, default=datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('message_id', name='_message_id_uc'),
    )

engine  = create_engine(DB_URL, echo=False, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# ---------------------------------------------------------------------------
# 文字デコード util
# ---------------------------------------------------------------------------

def dec_mime(val: str | None) -> str:
    """MIME ヘッダをデコードして str にする"""
    if not val:
        return ''
    out = ''
    for part, enc in decode_header(val):
        out += part.decode(enc or 'utf-8', 'ignore') if isinstance(part, bytes) else part
    return out


def extract_body(msg: email.message.Message) -> str:
    """text/plain 優先、無ければ html をテキスト化して返す"""
    # payload 抽出
    if msg.is_multipart():
        plain = next((p for p in msg.walk() if p.get_content_type() == 'text/plain'), None)
        payload = plain or next((p for p in msg.walk() if p.get_content_type() == 'text/html'), None)
    else:
        payload = msg

    if payload is None:
        return ''

    # デコード
    charset = payload.get_content_charset() or 'utf-8'
    raw     = payload.get_payload(decode=True) or b''
    if payload.get_content_type() == 'text/plain':
        text = raw.decode(charset, 'ignore')
    else:
        text = BeautifulSoup(raw, 'html.parser').get_text('\n')

    # 整形
    text = text.replace('■', '●')
    text = re.sub(r'\s+\n', '\n', text)  # 空白→改行詰め
    return text.strip()

# ---------------------------------------------------------------------------
# 共通 IMAP ハンドラ
# ---------------------------------------------------------------------------

def _connect_imap() -> tuple[imaplib.IMAP4_SSL, int] | tuple[None, None]:
    """IMAP 接続して (imap, UIDVALIDITY) を返す。失敗時は (None, None)"""
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(IMAP_USER, IMAP_PASSWORD)
        imap.select(MAILBOX)
        status, d = imap.status(MAILBOX, '(UIDVALIDITY)')
        uidvalidity = int(d[0].decode().split()[2].rstrip(')'))
        return imap, uidvalidity
    except Exception as e:
        print(f'[ERROR] IMAP 接続/ログイン失敗: {e}', file=sys.stderr)
        return None, None

# ---------------------------------------------------------------------------
# 直近 N 件を取得
# ---------------------------------------------------------------------------

def fetch_and_save(limit: int = 20):
    print(f'[INFO] fetch_and_save: 最新 {limit} 件')
    imap, uidvalidity = _connect_imap()
    if not imap:
        return

    # 全 UID を取得 → 後ろから N 件
    status, data = imap.uid('SEARCH', None, 'ALL')
    all_uids = [int(u) for u in data[0].split()]
    target_uids = all_uids[-limit:][::-1]

    _save_uids(imap, uidvalidity, target_uids)
    imap.logout()

# ---------------------------------------------------------------------------
# 過去 1 か月分を取得
# ---------------------------------------------------------------------------

def fetch_past_month_and_save():
    print('[INFO] fetch_past_month_and_save: 過去 1 か月分')
    imap, uidvalidity = _connect_imap()
    if not imap:
        return

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%d-%b-%Y')
    status, data = imap.uid('SEARCH', None, f'(SINCE {since})')
    target_uids = [int(u) for u in data[0].split()]

    _save_uids(imap, uidvalidity, target_uids)
    imap.logout()

# ---------------------------------------------------------------------------
# UID リストを走査して保存
# ---------------------------------------------------------------------------

def _save_uids(imap: imaplib.IMAP4_SSL, uidvalidity: int, uids: list[int]):
    session = Session()
    saved   = 0

    for idx, uid in enumerate(uids, 1):
        try:
            status, msg_data = imap.uid('FETCH', str(uid), '(RFC822)')
            if not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
        except Exception as e:
            print(f'  [WARN] UID={uid} FETCH 失敗: {e}')
            continue

        subj = dec_mime(msg.get('Subject'))
        if 'クリーニング見積もり' not in subj:
            continue

        mid = msg.get('Message-ID')
        if session.query(EmailModel).filter_by(message_id=mid).first():
            continue

        try:
            rec = EmailModel(
                uidvalidity = uidvalidity,
                uid         = uid,
                message_id  = mid,
                subject     = subj,
                from_addr   = dec_mime(msg.get('From')),
                to_addr     = dec_mime(msg.get('To')),
                date        = email.utils.parsedate_to_datetime(msg.get('Date')),
                body        = extract_body(msg),
                raw_content = raw.decode('utf-8', 'ignore')
            )
            session.add(rec)
            session.commit()
            saved += 1
        except Exception as e:
            session.rollback()
            print(f'  [ERROR] DB 保存失敗: {e}', file=sys.stderr)

    session.close()
    print(f'[INFO] 保存完了: {saved} 件')

# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='クリーニング見積もりメール同期ツール')
    parser.add_argument('--mode', choices=['latest', 'month'], default='latest',
                        help="latest: 直近 N 件 / month: 過去 1 か月分")
    parser.add_argument('--limit', type=int, default=20,
                        help='latest モード時に取得する件数 (default: 20)')
    args = parser.parse_args()

    if args.mode == 'month':
        fetch_past_month_and_save()
    else:
        fetch_and_save(limit=args.limit)
