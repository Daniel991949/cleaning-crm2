# fetch_cleaning_estimate.py

import os
from dotenv import load_dotenv
import imaplib
import email
from email.header import decode_header

# Load environment variables from .env
load_dotenv()
IMAP_HOST     = os.getenv('IMAP_HOST', 'imap.gmail.com')
IMAP_PORT     = int(os.getenv('IMAP_PORT', '993'))
IMAP_USER     = os.getenv('IMAP_USER')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')
MAILBOX       = os.getenv('IMAP_MAILBOX', 'INBOX')

def fetch_cleaning_estimate(limit=20):
    """
    IMAP にログインして「クリーニング見積もり」という件名のメールを取得し、
    最新 limit 件分だけヘッダーと本文をターミナルに出力します。
    """
    # Connect to IMAP server
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASSWORD)
    imap.select(MAILBOX)

    # まず全UIDを取得
    status, data = imap.uid('SEARCH', None, 'ALL')
    if status != 'OK':
        print("ERROR: UID SEARCH ALL failed")
        imap.logout()
        return

    all_uids = data[0].split()
    # 最新200件に絞る
    recent_uids = all_uids[-200:]
    matching = []

    # 新しい順（UID降順）でチェックし、件名に「クリーニング見積もり」を含むものを集める
    for raw_uid in reversed(recent_uids):
        uid = raw_uid.decode() if isinstance(raw_uid, bytes) else raw_uid
        status, msg_data = imap.uid('FETCH', uid, '(RFC822)')
        if status != 'OK' or not msg_data or not msg_data[0]:
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        # 件名をデコード
        subj, encoding = decode_header(msg.get('Subject') or '')[0]
        if isinstance(subj, bytes):
            subj = subj.decode(encoding or 'utf-8', errors='ignore')

        # 件名にフィルタ文字列が含まれるか
        if 'クリーニング見積もり' not in subj:
            continue

        matching.append((uid, msg))
        if len(matching) >= limit:
            break

    print(f"Found {len(matching)} messages matching 'クリーニング見積もり'")

    # 取得したメールを表示
    for uid, msg in matching:
        # 再デコードして安全に出力
        subj, encoding = decode_header(msg.get('Subject') or '')[0]
        if isinstance(subj, bytes):
            subj = subj.decode(encoding or 'utf-8', errors='ignore')

        print(f"\nUID:     {uid}")
        print(f"Subject: {subj}")
        print(f"From:    {msg.get('From')}")
        print(f"Date:    {msg.get('Date')}")

        # 本文を抽出
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

        print("\n--- Body ---")
        print(body)
        print("--- End Body ---\n")

    imap.logout()

if __name__ == '__main__':
    # 最新20通を取得
    fetch_cleaning_estimate(20)
