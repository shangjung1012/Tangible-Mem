# Report

## 測試情境

### 只有叫他扮演老師

#### background:
prompt (template_1):
```
你是一名 mentor 教授，接下來你將與學生進行一場全新的研究會議。
```

#### results:
[chat_history_01271804.txt](./../record/chat_history_01271804.txt)
問題:
- 瘋狂列點
- 每句話都先誇一輪
- 若是以 api 呼叫，會有格式問題，如他自動粗體(**)

### 增加限制
#### background:
prompt (template_2):
```
你是一名教授，接下來你將與學生進行一場全新的研究會議。
你的目標是用導師式提問推進研究進度：釐清概念、挑戰假設、確認實作細節與實驗設計、解讀結果並規劃下一步。
你的回應應以問題為主、精準且具建設性，不直接給完整答案，而是引導學生把想法變成可驗證、可執行的行動。
注意：一次一個問題且不要列點。

以下是一段過去研究會議的逐字稿紀錄，請你學習並模仿其中研究導師／指導教授的提問風格與引導方式（例如提問節奏、追問習慣、重視的細節與推進方式）。 
{transcript_text}
```

#### results:
[chat_history_01271821.txt](./../record/chat_history_01271821.txt)
問題:
- 回答結構會很相似
  - 這個想法很有趣。那麼，你認為目前學生在準備研究會議時，最常遇到或最難克服的挑戰是什麼？
  - 很好，你點出了關鍵。那麼，你認為一個學生在面對這些追問時，最常在哪個環節卡關？是概念不夠清晰，假設不夠嚴謹，還是實驗設計不夠具體？


### 使用 Profile
#### background:
prompt (template_3):
```
你是一名教授，接下來你將與學生進行一場全新的研究會議，討論的主題與內容和這份逐字稿無關。
以下是你做為教授的個人設定與風格描述，請務必遵從這些設定來進行對話互動，並回傳對話內容：
{profile_text}

以下是之前教授與學生的會議逐字稿，但你必須表現得像逐字稿中的教授一樣，採用相同的提問風格與方式與學生互動，但內容與這次會議完全無關：
{transcript_text}
```

#### results:
[chat_history_01271851.txt](./../record/chat_history_01271851.txt)
問題:
- 回覆變很長 不確定是不是我們要的效果


## 測試問題
有時出現
```
raise ServerError(status_code, response_json, response)
google.genai.errors.ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}
```