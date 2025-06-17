# fetch_and_save_cleaning.py

import os
from dotenv import load_dotenv
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    BigInteger,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ── Load environment variables from .env ─────────────────────────
load_dotenv()
IMAP_HOST     = os.getenv('IMAP_HOST', 'imap.gmail.com')
IMAP_PORT     = int(os.getenv('IMAP_PORT', '993'))
IMAP_USER     = os.getenv('IMAP_USER')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')
MAILBOX       = os.getenv('IMAP_MAILBOX', 'INBOX')
DB_URL        = os.getenv('DATABASE_URL', 'sqlite:///emails.db')

# ── Database setup ────────────────────────────────────────────────
Base = declarative_base()

class EmailModel(Base):
    __tablename__ = 'emails'
    uidvalidity = Column(BigInteger, primary_key=True)
    uid         = Column(BigInteger, primary_key=True)
    message_id  = Column(String(255), unique=True, nullable=False)
    subject     = Column(Text)
    from_addr   = Column(Text)
    to_addr     = Column(Text)
    date        = Column(DateTime)
    body        = Column(Text)
    raw_content = Column(Text)                 # 全メール本文をまるっと保存
    fetched_at  = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('message_id', name='_message_id_uc'),)

engine  = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

# 1) テーブルが存在しなければ作成
Base.metadata.create_all(engine)

# 2) 既存DBに raw_content カラムがなければ追加
with engine.begin() as conn:
    result = conn.execute(text("PRAGMA table_info(emails)"))
    columns = [row[1] for row in result]
    if 'raw_content' not in columns:
        conn.execute(text("ALTER TABLE emails ADD COLUMN raw_content TEXT"))


def fetch_and_save_cleaning(limit=20):
    """
    IMAP にログインして「クリーニング見積もり」という件名のメールを取得し、
    最新 limit 件分をローカルDBにまるごと保存します。
    """
    # 1) Connect to IMAP
    print(f"[DEBUG] Connecting to IMAP {IMAP_HOST}:{IMAP_PORT} as {IMAP_USER}")
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASSWORD)
    print("[DEBUG] IMAP login successful")
    imap.select(MAILBOX)
    print(f"[DEBUG] Selected mailbox: {MAILBOX}")

    # 2) Retrieve UIDVALIDITY for safety
    status, uid_data = imap.status(MAILBOX, '(UIDVALIDITY)')
    if status != 'OK':
        print("[ERROR] Failed to get UIDVALIDITY")
        imap.logout()
        return
    uidvalidity_str = uid_data[0].decode()  # b'INBOX (UIDVALIDITY 12345)' → str
    uidvalidity = int(uidvalidity_str.split()[2].strip(')'))
    print(f"[DEBUG] UIDVALIDITY: {uidvalidity}")

    # 3) Fetch all UIDs, then limit to recent 200
    status, data = imap.uid('SEARCH', None, 'ALL')
    if status != 'OK':
        print("[ERROR] UID SEARCH ALL failed")
        imap.logout()
        return

    all_uids = data[0].split()  # list of bytes
    print(f"[DEBUG] Total messages in mailbox: {len(all_uids)}")
    recent_uids = all_uids[-200:]
    print(f"[DEBUG] Filtering over {len(recent_uids)} most recent UIDs")

    # 4) Open DB session
    db = SessionLocal()

    # 5) Iterate over recent_uids in reverse (newest first)
    saved_count = 0
    for raw_uid in reversed(recent_uids):
        uid = int(raw_uid.decode())  # bytes → int

        # 5.1) Fetch full RFC822
        status, msg_data = imap.uid('FETCH', str(uid), '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        # 5.2) Decode Subject
        subj, enc = decode_header(msg.get('Subject') or '')[0]
        if isinstance(subj, bytes):
            subj = subj.decode(enc or 'utf-8', errors='ignore')

        # 5.3) Filter by subject containing "クリーニング見積もり"
        if 'クリーニング見積もり' not in subj:
            continue

        message_id = msg.get('Message-ID')
        # 5.4) Check duplicate by message_id
        exists = db.query(EmailModel).filter_by(message_id=message_id).first()
        if exists:
            print(f"[DEBUG] Duplicate skipped: {message_id}")
            continue

        # 5.5) Decode From, To, Date
        from_addr = msg.get('From')
        to_addr   = msg.get('To')
        date_obj  = email.utils.parsedate_to_datetime(msg.get('Date'))

        # 5.6) Extract plain-text body
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    charset = part.get_content_charset() or 'utf-8'
                    body = part.get_payload(decode=True).decode(charset, errors='ignore')
                    break
        else:
            charset = msg.get_content_charset() or 'utf-8'
            body = msg.get_payload(decode=True).decode(charset, errors='ignore')

        # 5.7) Save entire raw email as UTF-8 string
        try:
            raw_str = raw_email.decode('utf-8', errors='ignore')
        except:
            raw_str = raw_email.decode('iso-8859-1', errors='ignore')

        # 6) Create EmailModel record
        record = EmailModel(
            uidvalidity = uidvalidity,
            uid         = uid,
            message_id  = message_id,
            subject     = subj,
            from_addr   = from_addr,
            to_addr     = to_addr,
            date        = date_obj,
            body        = body,
            raw_content = raw_str
        )
        db.add(record)
        db.commit()
        saved_count += 1
        print(f"[DEBUG] Saved UID={uid}, message_id={message_id}")

        if saved_count >= limit:
            break

    # 7) Cleanup
    db.close()
    imap.logout()
    print(f"[INFO] Finished. Total saved: {saved_count}")

if __name__ == '__main__':
    # 最新20件をDBに保存
    fetch_and_save_cleaning(20)