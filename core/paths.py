# 集中管理跨模組共用的檔案路徑。
# 目前只有「全域共用字典」這一個路徑，之後如有其他跨遊戲共用檔案可加在這裡。
import os


def global_dict_path() -> str:
    """
    回傳全域共用字典檔的路徑：使用者家目錄下的 ~/.game_translator/global_dict.json。

    這本字典跨所有遊戲累積翻譯（UI、常見用語、重複術語等），與各遊戲專屬的
    translator_dict.json 分開存放，讓 A 遊戲翻過的句子能在 B 遊戲直接命中。

    呼叫時順便確保父目錄（~/.game_translator/）存在，避免呼叫端還要自己
    處理目錄不存在的情況（DictCache.save() 內部也有相同的 makedirs 保險，
    這裡先建好目錄純粹是讓路徑一取得就是可直接使用的狀態）。
    """
    path = os.path.join(os.path.expanduser("~"), ".game_translator", "global_dict.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def log_path() -> str:
    """回傳診斷 log 檔路徑：~/.game_translator/translator.log。

    供 GUI 把「啟動失敗／掃描結果」等關鍵事件寫成一行一行，方便事後回報排查
    （Discord 上直接叫人貼這個檔，不用靠截圖猜）。同樣順手確保父目錄存在。
    """
    path = os.path.join(os.path.expanduser("~"), ".game_translator", "translator.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path
