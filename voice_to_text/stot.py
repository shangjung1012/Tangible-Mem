import os
import torch
import whisper

# === 設定區 ===
AUDIO = r"0918.m4a"          # 也可改成絕對路徑 r"c:\專題\語音轉文字\0918.m4a"
OUT   = r"output.txt"
MODEL = "medium"             # 可改 small / medium / large-v3
# ===============

# 檔案存在檢查
if not os.path.exists(AUDIO):
    raise FileNotFoundError(f"找不到音訊檔案：{os.path.abspath(AUDIO)}")

# 選擇裝置
use_cuda = torch.cuda.is_available()
device = "cuda" if use_cuda else "cpu"
print(f"正在載入模型到 {device} ...")
model = whisper.load_model(MODEL, device=device)

def transcribe_once(dev):
    return model.transcribe(
        AUDIO,
        language="zh",
        fp16=(dev == "cuda"),   # 只有 CUDA 才用 FP16
    )

print("開始轉錄 ...")
try:
    result = transcribe_once(device)
except RuntimeError as e:
    # 若顯示 CUDA 記憶體不足，改用 CPU 重跑
    if "CUDA out of memory" in str(e) and device == "cuda":
        print("⚠️ CUDA 記憶體不足，改用 CPU 重跑 ...")
        device = "cpu"
        model = whisper.load_model(MODEL, device=device)
        result = transcribe_once(device)
    else:
        raise

text = (result.get("text") or "").strip()

with open(OUT, "w", encoding="utf-8") as f:
    f.write(text + "\n")

print("================================")
print(f"語音轉文字完成！結果已存到：{os.path.abspath(OUT)}")
print("================================")


