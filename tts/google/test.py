from google.cloud import texttospeech
import os
from pathlib import Path

script_dir = Path(__file__).parent
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(script_dir / "tts_credential.json")
client = texttospeech.TextToSpeechClient()

# text = "hello, I'm fine, thank you. And you?"
text = '''
本文將逐步說明如何使用雙向串流合成音訊。

雙向串流可讓您同時傳送文字輸入內容及接收音訊資料。也就是說，在傳送完整輸入文字前即可開始合成語音，這樣就能縮短延遲時間，並進行即時互動。語音助理和互動式遊戲會使用雙向串流，打造回應迅速的動態應用程式。

如要進一步瞭解 Text-to-Speech 的基本概念，請參閱「Text-to-Speech 基本概念」。
'''

synthesis_input = texttospeech.SynthesisInput(text=text)


# https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types?hl=zh-tw

# voice = texttospeech.VoiceSelectionParams(
#     language_code="en-US",
#     name="en-US-Chirp-HD-O"
# )

voice = texttospeech.VoiceSelectionParams(
    language_code="cmn-TW",
    name="cmn-TW-Wavenet-C"
)

audio_config = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3,
    effects_profile_id=["handset-class-device"],
    # speaking_rate=1.0,
    # pitch=1.0
)

response = client.synthesize_speech(
    input=synthesis_input,
    voice=voice,
    audio_config=audio_config
)

with open(f"{script_dir}/output.mp3", "wb") as out:
    out.write(response.audio_content)
    print('Audio content written to file "output.mp3"')
