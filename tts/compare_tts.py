from dotenv import load_dotenv
from pathlib import Path

from . import google_tts as google_synthesize
from . import yating_tts as yating_synthesize

DEFAULT_TEXT = """
本文將逐步說明如何使用雙向串流合成音訊。

雙向串流可讓您同時傳送文字輸入內容及接收音訊資料。也就是說，在傳送完整輸入文字前即可開始合成語音，這樣就能縮短延遲時間，並進行即時互動。語音助理和互動式遊戲會使用雙向串流，打造回應迅速的動態應用程式。

如要進一步瞭解 Text-to-Speech 的基本概念，請參閱「Text-to-Speech 基本概念」。
"""


def compare(text: str = DEFAULT_TEXT, output_dir: str | Path | None = None):
    load_dotenv()
    base_dir = Path(output_dir) if output_dir else Path(__file__).parent
    google_output = google_synthesize(text, base_dir / "google_compare.mp3")
    yating_output = yating_synthesize(text, base_dir / "yating_compare")
    return google_output, yating_output


if __name__ == "__main__":
    g_path, y_path = compare()
    print(f"Google output: {g_path}")
    print(f"Yating output: {y_path}")
