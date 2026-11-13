# zip_router
Python-ZIP-File-Decrypt-Routing
ZIP 解密與解壓工具（Linux / Python 3.6/pyzipper==0.3.6）

1. 用途
從 source/ 讀取加密 ZIP，由 conf/ZIPSource.properties 取得密碼。
成功解壓的檔案放到 output/，原始 ZIP 搬到 archive/ 保留，不自動刪除。
解密、解壓或輸出驗證失敗的 ZIP 搬到 error/。
每次呼叫執行單次批次後結束，沒有常駐監控或內建排程。
需要 Linux、Python 3.6；啟動腳本使用 Bash，python3.6 必須能由 PATH 找到。
可讀取 AES 與傳統 ZipCrypto 加密 ZIP；其他格式需以實檔確認。

2. 目錄結構
zip_router/
├── bin/
│   ├── zip_router.py             Python 批次程式
│   └── run_zip_router.sh         Bash 啟動腳本
├── conf/
│   └── ZIPSource.properties      密碼設定檔（自行建立）
├── source/                      待處理 ZIP
├── process/                     處理中的 ZIP
├── output/                      解壓結果
├── error/                       失敗或上次批次遺留的 ZIP
├── archive/                     成功處理的原始 ZIP 備份
├── log/                         每日執行日誌
└── requirements.txt             固定版本套件清單

程式會自動建立 conf、source、process、output、error、archive、log。
不會自動產生密碼設定檔。所有資料夾會保留；成功時移出 process 的是 ZIP。
archive、error 與 log 中的檔案都不會自動清除。

3. 安裝與設定
以下指令在 Linux / Bash 執行，以 ~/zip_router 為例。
~ 代表目前登入使用者的家目錄；先將工具檔案放到對應位置。

確認 Python 版本並安裝依賴工具：

  python3.6 --version
  
下載並安裝必要的 Python 套件（支援 AES 加密 ZIP）：

  pip3.6 install -r ~/zip_router/requirements.txt
  
或單獨安裝：

  pip3.6 install pyzipper==0.3.6

建立工作目錄：

  mkdir -p ~/zip_router/conf ~/zip_router/source


建立 conf/ZIPSource.properties，格式如下：

  ZIP_PASSWORD=你的ZIP密碼

必須有且只有一筆非空的 ZIP_PASSWORD。支援 UTF-8 與 UTF-8 BOM，
忽略空白行及以 # 或 ! 開頭的註解。等號後的空白及其他等號會保留。
不要在密碼外加引號，引號也會被當作密碼內容。

也可互動輸入並寫入設定檔（會覆蓋原設定檔）：

  read -r -s -p "Enter ZIP password: " ZIP_PASSWORD
  printf '\n'
  printf 'ZIP_PASSWORD=%s\n' "$ZIP_PASSWORD" > ~/zip_router/conf/ZIPSource.properties
  unset ZIP_PASSWORD
  chmod 600 ~/zip_router/conf/ZIPSource.properties

執行帳號需要能讀取設定檔並讀寫工作目錄。
以 bash 或 python3.6 呼叫時，程式檔不需要設定 777。
若需直接執行啟動腳本，可設定：

  chmod u+x ~/zip_router/bin/run_zip_router.sh

Shell 腳本以 LF 換行儲存，避免 Windows CRLF 造成 Linux 執行問題。

4. 代碼置換配置（重要）
本工具使用通用佔位符代碼 ROUTE_A、ROUTE_B 等作為範例。
在實際部署時，需要進行代碼置換：

(1) 編輯 config.example.json，將通用代碼替換為實際業務代碼
    例如：ROUTE_A → YOUR_ACTUAL_CODE_A
    或複製 config.example.json 為 config.json 後修改

(2) 修改 ZIP 檔名前綴，使用對應的業務代碼
    例如：ROUTE_A.20261013.zip → YOUR_ACTUAL_CODE_A.20261013.zip

(3) 批次流程中掃描的 ZIP 名稱不限制特定前綴
    任何 .zip 檔案都會被處理，但建議保持前綴命名規範便於管理

代碼映射無硬碼於程式中，僅供 ZIP 檔名管理與日誌追蹤使用。

5. 執行
將有效加密 ZIP 複製到 source/，例如：
  YOUR_ACTUAL_CODE_A.20261013.zip
  YOUR_ACTUAL_CODE_B.20261013.zip

使用啟動腳本：

  bash ~/zip_router/bin/run_zip_router.sh

或直接執行 Python：

  python3.6 ~/zip_router/bin/zip_router.py

預設根目錄是 zip_router.py 所在 bin/ 的上一層，不依賴目前工作目錄。
亦可指定資料根目錄：

  python3.6 ~/zip_router/bin/zip_router.py --root /data/zip_router

指定 --root 後，設定檔及工作資料夾全部改從該根目錄讀寫。
目前啟動腳本不轉交命令列參數；需要 --root 時請直接呼叫 Python。

6. 批次流程
(1) 取得批次鎖，同一根目錄僅允許一個批次執行。
(2) 掃描 source 與 process 第一層的一般 ZIP，忽略符號連結。
    .zip 副檔名不分大小寫，不限制代碼前綴（通用佔位符為 ROUTE_A、ROUTE_B 等）。
    不遞迴掃描子目錄；掃描後新增的 ZIP 留待下次處理。
(3) process 中上次遺留的 ZIP 直接移到 error，不自動重新解壓。
    搬移失敗時停止批次並回傳 2。
(4) 將本次 source ZIP 搬到 process，完成搬移後讀取密碼並逐一解壓。
(5) 密碼設定讀取失敗時，ZIP 留在 process，回傳 2。
    修正設定後，確認沒有批次執行，再將要重試的 ZIP 搬回 source。
    若直接再次執行，process 的遺留 ZIP 會被移到 error。
(6) 成功後將原始 ZIP 從 process 搬到 archive，保留內容。
    解壓失敗移到 error，其他 ZIP 繼續處理。
    移到 archive 或 error 失敗時，ZIP 留在 process 並記錄錯誤。

搬到 process、archive 或 error 時，若目的檔名已存在，會加上 UUID，
不覆蓋原有檔案。上游建議先上傳 .part，完成後再改成 .zip。

7. 輸出與保護機制
ZIP 內檔案及子目錄直接放到 output，不另外建立 ZIP 名稱的子目錄。
例如 YOUR_ACTUAL_CODE_A.20261013.zip 內含 YOUR_ACTUAL_CODE_A.20261013，結果為：
  output/YOUR_ACTUAL_CODE_A.20261013

先在 output 內暫存區完整解壓，再驗證並發布：
  - 既有同名檔案內容完全相同：保留既有檔案，記錄 identical。
  - 既有同名檔案內容不同：該 ZIP 失敗，不覆蓋，移到 error。
  - 拒絕危險路徑、重複項目、符號連結及特殊檔案。
  - 每個 ZIP 解壓總大小上限 10 GiB，目前無命令列調整選項。
  - 使用硬連結發布，output 所在檔案系統需要支援硬連結。

一般發布失敗會清除本次已發布的新檔案，並嘗試清除本次新增的空目錄；若目錄無法刪除，會保留並記錄清理失敗訊息。

目前程式設定 umask 為 000，新建工作目錄、日誌及鎖定檔通常為 777，
新解壓的一般檔案明確設定為 777，不還原 ZIP 原始權限或檔案時間。
既有工作目錄及密碼設定檔的權限不會因此自動改成 777。

8. 日誌與結束碼
日誌依 Linux 主機當地日期寫入：
  log/zip_router_YYYYMMDD.log
例如 2026-10-14 執行時為 zip_router_20261014.log。
同日追加至同一檔案；日期在啟動時決定，不自動刪除舊日誌。
處理紀錄也同步顯示在終端機。

查看當日日誌：

  tail -n 50 ~/zip_router/log/zip_router_$(date +%Y%m%d).log

主要訊息：
  START                   本次來源與遺留 ZIP 數量
  MOVE                    source 搬入 process
  OK                      解壓成功，原 ZIP 已移到 archive
  EXTRACT_FAIL            解密、解壓或輸出驗證失敗
  ERROR_MOVE              失敗 ZIP 已移到 error
  LEFTOVER_ERROR_MOVE     上次遺留 ZIP 已移到 error
  CONFIG_FAIL             密碼設定讀取失敗，ZIP 留在 process
  ARCHIVE_MOVE_FAIL       ZIP 歸檔失敗，留在 process
  END                     成功與失敗數

結束碼：
  0：沒有失敗，或沒有需要處理的 ZIP。
  1：部分搬移、解壓或歸檔失敗；上次遺留 ZIP 也會計入失敗。
  2：初始化、套件載入、密碼設定、批次鎖或遺留 ZIP 搬移失敗。
啟動腳本會顯示「程式結束碼」，並回傳 Python 程式的結束碼。

日誌只能查看，不要貼到 Bash 命令列執行；其中 -> 的 > 會被當成
輸出重導向，可能建立空檔或清空既有 ZIP。

9. 鎖定檔與快取
log/.zip_router.lock：避免同一根目錄的批次同時執行。
output/.unzip_router.lock：協調 output 的解壓發布。
鎖定檔正常保留；檔案存在不代表程式仍在執行，結束時系統會釋放鎖。
不要在執行中刪除鎖定檔。
bin/__pycache__/zip_router.cpython-36.pyc 是匯入模組時產生的 Python 快取，
不是解壓結果，可保留；刪除後仍可能再次產生。

10. 搬移工具
停止執行後，將整個 zip_router 資料夾一起搬移，保留內部結構。
啟動腳本依自己的位置找到 Python 程式，Python 再依自身位置決定根目錄。
例如搬到 /data/zip_router 後：

  bash /data/zip_router/bin/run_zip_router.sh

工具內不用修改路徑，但需確認新位置的讀寫權限與硬連結支援。
排程、上傳程式及外部呼叫路徑需更新；若使用 --root，也需確認指定位置。
搬到另一台主機時，需重新確認 Python 3.6 與套件已安裝。

11. 測試確認
使用已知密碼的有效測試 ZIP，確認大小大於 0，再放到 source 執行。
成功後確認：
  - output 有預期檔案，內容正確。
  - archive 有原 ZIP，大小及內容與原始檔一致。
  - 該 ZIP 已從 source 與 process 移出。
  - 日誌包含 OK 與 END success=N failures=0。
已有相同輸出時，new=0、identical=1 是正常結果。
若失敗，先查看日誌，再決定是否將 error 的 ZIP 搬回 source 重試。

12. 快速設定清單（適用其他地方）
以下為完整的初始化指令集，可在新環境直接執行。
複製整段指令至 Linux / Bash 終端機即可：

--- 步驟開始 ---
# 檢查 Python 版本
python3.6 --version

# 安裝依賴工具（必須，支援 AES 加密 ZIP）
pip3.6 install pyzipper==0.3.6

# 或使用 requirements.txt（推薦）
pip3.6 install -r /path/to/zip_router/requirements.txt

# 建立工作目錄
mkdir -p ~/zip_router/{conf,source,process,output,error,archive,log}

# 建立密碼設定檔
read -r -s -p "Enter ZIP password: " ZIP_PASSWORD
printf '\n'
printf 'ZIP_PASSWORD=%s\n' "$ZIP_PASSWORD" > ~/zip_router/conf/ZIPSource.properties
unset ZIP_PASSWORD
chmod 600 ~/zip_router/conf/ZIPSource.properties

# 設定啟動腳本執行權限
chmod u+x ~/zip_router/bin/run_zip_router.sh

# 執行程式
bash ~/zip_router/bin/run_zip_router.sh
--- 步驟結束 ---

關鍵依賴套件說明：
  pyzipper 0.3.6：支援 AES-256 加密 ZIP 讀取，標準 ZipCrypto 也支援
  
如果 pip3.6 找不到，嘗試：
  python3.6 -m pip install pyzipper==0.3.6

其他常用安裝方式：
  apt-get install python3.6-pip          # Debian/Ubuntu
  yum install python36-pip               # RHEL/CentOS
  brew install python@3.6                # macOS（若有 Homebrew）
