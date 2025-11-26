from yating_tts_sdk import YatingClient as ttsClient
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv()

URL = "https://tts.api.yating.tw/v2/speeches/short"
KEY = os.getenv("YATING_API_KEY")

TEXT = "歡迎收聽雅婷文字轉語音"
TEXT_TYPE = ttsClient.TYPE_TEXT
MODEL = ttsClient.MODEL_ZHEN_FEMALE_1
SPEED = 1.0
PITCH = 1.0
ENERGY = 1.0
ENCODING = ttsClient.ENCODING_MP3
SAMPLE_RATE = ttsClient.SAMPLE_RATE_16K

script_dir = Path(__file__).parent
output_dir = script_dir
FILE_NAME = Path(output_dir) / "yating_output.mp3"

try:
    client = ttsClient(URL, KEY)
    client.synthesize(TEXT, TEXT_TYPE, MODEL, SPEED, PITCH, ENERGY, ENCODING, SAMPLE_RATE, FILE_NAME)
except Exception as err :
    print("An exception occurred:", err)