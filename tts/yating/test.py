from yating_tts_sdk import YatingClient as ttsClient
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv()

URL = "https://tts.api.yating.tw/v2/speeches/short"
KEY = os.getenv("YATING_API_KEY")

TEXT = '''
本文將逐步說明如何使用雙向串流合成音訊。

雙向串流可讓您同時傳送文字輸入內容及接收音訊資料。也就是說，在傳送完整輸入文字前即可開始合成語音，這樣就能縮短延遲時間，並進行即時互動。語音助理和互動式遊戲會使用雙向串流，打造回應迅速的動態應用程式。

如要進一步瞭解 Text-to-Speech 的基本概念，請參閱「Text-to-Speech 基本概念」。
'''
TEXT_TYPE = ttsClient.TYPE_TEXT
MODEL = ttsClient.MODEL_ZHEN_FEMALE_1
SPEED = 1.0
PITCH = 1.0
ENERGY = 1.0
ENCODING = ttsClient.ENCODING_MP3
SAMPLE_RATE = ttsClient.SAMPLE_RATE_16K

script_dir = Path(__file__).parent
output_dir = script_dir
FILE_NAME = Path(output_dir) / "yating_output"

try:
    client = ttsClient(URL, KEY)
    client.synthesize(TEXT, TEXT_TYPE, MODEL, SPEED, PITCH, ENERGY, ENCODING, SAMPLE_RATE, FILE_NAME)
except Exception as err :
    print("An exception occurred:", err)