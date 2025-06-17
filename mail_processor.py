from email.header import Header
import imaplib
import email
import re
import json
import os
import time
from datetime import datetime, timedelta
from email.header import decode_header 

# メールサーバーに接続するための情報
IMAP_SERVER = "imap.gmail.com"
USERNAME = "orientalmoonkimura@gmail.com"
PASSWORD = "tripkjkafhpipwvt"  # 安全な方法でパスワードを設定してください

# データディレクトリを相対パスで設定
DATA_DIR = os.path.join(os.path.dirname(__file__), "顧客データ")
START_ID = 10003

# ディレクトリが存在しない場合は作成
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"ディレクトリ {DATA_DIR} を作成しました。")

def extract_information(body):
    # 正規表現パターン
    patterns = {
        "購入商品": r"１\.\s*当店で購入した商品ですか？　※必須 : (.+)",
        "サイズ": r"２\.\s*サイズ（房（フリンジ）を含めた長さ）　※必須 :\s*(.+)",
        "種類": r"３、\s*種類　※必須 : (.+)",
        "産地": r"４、\s*産地（その他を選択の場合） : (.*)",
        "購入年": r"５、\s*購入年（大体で結構です）※必須 : (.+)",
        "クリーニング回数": r"６\.\s*クリーニング（水洗い）の回数　※必須 :\s*(.+)",
        "使用年数": r"７\.\s*購入もしくはクリーニングからの使用年数（大体で結構です）※必須\s*:\s*(.+)",
        "気になる部分": r"８\.\s*気になる部分、連絡や質問等があればお書きください\s*:\s*(.+)",
        "お名前": r"９\.\s*お名前 : (.+)",
        "メールアドレス": r"１０\.\s*メールアドレス : (.+)",
        "電話番号": r"１１\.\s*電話番号　※必須 : (.+)",
        "梱包用紙": r"１２\.\s*梱包用紙（400円）が必要な場合は選択 : \s*(.+)",
        "見積りコース": r"１３\.\s*お見積りを希望するコース　※必須\s*:\s*([^\r\n]+)",
        "オプション希望": r"１４\.\s*オプションの希望 :\s*(.+)",
        "支払希望方法": r"１５\.\s*ご依頼となった場合のお支払希望　※必須\s*:\s*(.+)",
        "電話相談希望": r"１６\.\s*電話で相談（コース選択や気になる部分について）\s*:\s*(.+)",
        "都合が良い時間帯": r"都合が良い時間帯（電話相談を希望の方のみ）\s*:\s*(.+)",
    }

    # デフォルト値
    default_values = {
        "購入商品": "情報なし",
        "サイズ": "情報なし",
        "種類": "情報なし",
        "産地": "情報なし",
        "購入年": "情報なし",
        "クリーニング回数": "情報なし",
        "使用年数": "情報なし",
        "気になる部分": "情報なし",
        "お名前": "情報なし",
        "メールアドレス": "情報なし",
        "電話番号": "情報なし",
        "梱包用紙": "情報なし",
        "見積りコース": "情報なし",
        "オプション希望": "情報なし",
        "支払希望方法": "情報なし",
        "電話相談希望": "情報なし",
        "都合が良い時間帯": "情報なし",
    }
    
    extracted_info = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, body)
        extracted_info[key] = match.group(1).strip() if match else default_values[key]

    return extracted_info

def save_email_content(subject, body, id):
    extracted_info = extract_information(body)
    extracted_info["ID"] = id
    extracted_info["subject"] = subject

    file_path = os.path.join(DATA_DIR, f"{id}.json")
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(extracted_info, file, ensure_ascii=False, indent=4)
        print(f"Saved email in JSON format: {file_path}")

def get_processed_ids():
    if not os.path.exists("processed_ids.txt"):
        return set()
    with open("processed_ids.txt", "r") as file:
        return set(file.read().splitlines())

def save_processed_ids(processed_ids):
    with open("processed_ids.txt", "w") as file:
        for id in processed_ids:
            file.write(id + "\n")

def process_mail(processed_ids):
    global START_ID
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    try:
        mail.login(USERNAME, PASSWORD)
        print("ログイン成功")
        mail.select('inbox')
        print("受信トレイを選択")
    except Exception as e:
        print(f"Login error: {e}")
        return

    date_30_days_ago = (datetime.today() - timedelta(days=30)).strftime("%d-%b-%Y")
    print(f"検索日付: {date_30_days_ago}")
    
    status, messages = mail.search(None, '(SINCE "{}")'.format(date_30_days_ago))
    if status != 'OK':
        print("Failed to search emails.")
        return

    for num in messages[0].split():
        print(f"Processing message: {num}")
        status, data = mail.fetch(num, '(RFC822)')
        if status != 'OK':
            print(f"Failed to fetch email: {num}")
            continue

        msg = email.message_from_bytes(data[0][1])
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or 'utf-8')
                    print(f"Subject: {subject}")

                    if "クリーニング見積依頼" in subject:
                        body = part.get_payload(decode=True).decode('utf-8')
                        print(f"メール内容: {body[:100]}...")  # 長いメールの場合、最初の100文字だけ表示
                        save_email_content(subject, body, START_ID)
                        START_ID += 1

                        processed_ids.add(msg['Message-ID'])

    mail.logout()
    print("メール処理完了")

# メインループ
if __name__ == "__main__":
    processed_ids = get_processed_ids()  # 処理済みメールIDの読み込み
    print("処理済みメールID:", processed_ids)

    while True:
        print("メールの処理を開始します")
        process_mail(processed_ids)  # 処理済みメールIDを関数に渡す
        save_processed_ids(processed_ids)  # 処理済みメールIDの保存
        print("次の処理まで待機します...")
        time.sleep(60 * 5)  # 5分ごとに実行
