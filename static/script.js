let selectedElement = null;

// 非同期で顧客データを読み込む（検索クエリを使用）
async function loadCustomers(query = '') {
    try {
        const response = await fetch(`/customers?name=${query}`);
        if (!response.ok) {
            throw new Error('顧客データの読み込みに失敗しました。');
        }
        const customers = await response.json();
        displayNames(customers);
    } catch (error) {
        console.error('エラー:', error);
    }
}

// 検索機能
function searchNames() {
    const searchValue = document.getElementById('search-box').value.toLowerCase();
    loadCustomers(searchValue);
}

// ...

// 名前リストを表示（色を適用）
function displayNames(customers) {
    const namesList = document.getElementById('names-list');
    namesList.innerHTML = ''; 
    customers.forEach(customer => {
        const nameElement = document.createElement('div');
        nameElement.textContent = customer.name;
        nameElement.setAttribute('data-customer-id', customer.ID); 
        nameElement.onclick = () => {
            loadCustomerDetails(customer.ID); 
            selectName(nameElement);
        };
        // 背景色を適用
        applyColorToNameElement(nameElement, customer.color);
        namesList.appendChild(nameElement);
    });
}

// ...


// 顧客詳細を読み込む
async function loadCustomerDetails(customerId) {
    try {
        const response = await fetch(`/customer/${customerId}`);
        if (!response.ok) {
            throw new Error('顧客詳細の読み込みに失敗しました。');
        }
        const customerDetails = await response.json();
        displayDetails(customerDetails); // ここを変更
    } catch (error) {
        console.error('エラー:', error);
    }
}
// 詳細情報を表示（HTMLで整形）
function displayDetails(details) {
    const previewText = document.getElementById('preview-text');
    previewText.innerHTML = '';

    const detailsList = document.createElement('ul');
    for (const key in details) {
        if (details.hasOwnProperty(key)) {
            const listItem = document.createElement('li');
            listItem.textContent = `${key}: ${details[key]}`;
            detailsList.appendChild(listItem);
        }
    }
    previewText.appendChild(detailsList);
}


// 選択された名前をハイライトする
function selectName(element) {
    if (selectedElement) {
        selectedElement.classList.remove('selected');
    }
    selectedElement = element;
    selectedElement.classList.add('selected');
}




// 色を名前の要素に適用
function applyColorToNameElement(element, color) {
    switch (color) {
        case "赤":
            element.classList.add("red-background");
            break;
        case "黄":
            element.classList.add("yellow-background");
            break;
        case "青":
            element.classList.add("lightblue-background");
            break;
        case "緑":
            element.classList.add("green-background");
            break;
        default:
            element.style.backgroundColor = ""; // 初期状態（白）
    }
}

// 状態ボタンのクリックイベント
document.addEventListener('DOMContentLoaded', function () {
    const statusButtonsContainer = document.getElementById('status-buttons');
    if (!statusButtonsContainer) {
        return;
    }

    const statusButtons = statusButtonsContainer.getElementsByTagName('button');
    for (let button of statusButtons) {
        button.addEventListener('click', function () {
            if (selectedElement) {
                const customerId = selectedElement.getAttribute('data-customer-id');
                updateCustomerStatus(customerId, this.textContent);
            }
        });
    }
});

// 顧客の状態を更新
async function updateCustomerStatus(customerId, statusText) {
    // ステータスのテキストから状態をマッピングする
    const statusMapping = {
        '要対応': '要対応',
        '見積もり済': '見積もり済',
        '作業中': '作業中',
        '完了': '完了'
    };
    const status = statusMapping[statusText];

    try {
        const response = await fetch(`/update_status/${customerId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: status }),
        });
        if (!response.ok) {
            throw new Error('顧客状態の更新に失敗しました。');
        }
        const updatedCustomer = await response.json();
        // 更新された顧客情報で名前リストを更新
        loadCustomers();
    } catch (error) {
        console.error('エラー:', error);
    }
}

// カルテ作成機能
function createRecord() {
    if (selectedElement) {
        const recordText = prompt("カルテの内容を入力してください:");
        if (recordText) {
            // ここでバックエンドにデータを送信するコードを追加
            console.log("カルテ内容:", recordText);
        }
    } else {
        alert("顧客を選択してください。");
    }
}

// メール返信機能
// モーダルウィンドウを表示する関数
function replyEmail() {
    var modal = document.getElementById('emailModal');
    modal.style.display = 'block';
}

// モーダルウィンドウを閉じる関数
window.onload = function() {
    var closeButton = document.getElementsByClassName('close')[0];
    closeButton.onclick = function() {
        var modal = document.getElementById('emailModal');
        modal.style.display = 'none';
    }
}


function sendEmail() {
    const subject = document.getElementById('emailSubject').value;
    const body = document.getElementById('emailBody').value;
    const attachment = document.getElementById('emailAttachment').files[0];
    const receiverEmail = selectedCustomerData ? selectedCustomerData['メールアドレス'] : '';

    console.log('送信データ:', { subject, body, receiverEmail, attachment });

    const formData = new FormData();
    formData.append('subject', subject);
    formData.append('body', body);
    formData.append('receiverEmail', receiverEmail);
    if (attachment) {
        formData.append('attachment', attachment);
    }

    fetch('/send_email', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        console.log('レスポンス:', response);
        return response.json();
    })
    .then(data => {
        console.log('成功:', data);
    })
    .catch((error) => {
        console.error('エラー:', error);
    });
}

// 初期表示時に顧客データを読み込む
loadCustomers();


