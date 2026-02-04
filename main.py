import feedparser
import google.generativeai as genai
import requests
import json
import time
import os
from datetime import datetime
from groq import Groq

# ==========================================
# 🔧 設定エリア（環境変数）
# ==========================================
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
DATABASE_ID = os.environ["DATABASE_ID"]

RSS_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"
GEMINI_MODEL = 'gemini-2.5-flash'
GROQ_MODEL = 'llama3-70b-8192'

# ==========================================
# 1. AI分析関数群
# ==========================================

# A. Gemini (強気・機会探索 + タグ生成を担当)
def analyze_with_gemini(text):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    # ★改良点：分析とタグ生成を1回のリクエストにまとめました
    prompt = f"""
    あなたは「成長株投資家」です。以下のニュースから「投資機会」を見出し、ポジティブな視点で分析してください。
    また、関連するタグ（企業名や技術名）も抽出してください。
    
    【ニュース】{text}
    
    【出力】JSON形式のみ（マークダウン不要）
    {{
        "summary": "要約",
        "opportunity": "どのような収益機会があるか（一言）",
        "bull_score": 1〜10の点数（10が超強気）,
        "tags": ["タグA", "タグB"] 
    }}
    """
    try:
        response = model.generate_content(prompt)
        # JSONクリーニング
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"⚠️ Gemini Error: {e}")
        # エラー時はデフォルト値を返す
        return {"summary": "分析失敗", "opportunity": "-", "bull_score": 5, "tags": ["Error"]}

# B. Groq/Llama3 (弱気・リスク管理担当)
def analyze_with_groq(text):
    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
    You are a "Risk Manager". Analyze the following news critically. Find potential risks.
    Output JSON ONLY.
    
    News: {text}
    
    JSON Format:
    {{
        "risk_point": "What is the biggest risk? (Answer in Japanese)",
        "bear_score": 1-10 score (10 is extremely risky)
    }}
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            response_format={"type": "json_object"}
        )
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ Groq Error: {e}")
        return {"risk_point": "分析失敗", "bear_score": 5}

# ==========================================
# 2. Notion送信機能
# ==========================================
def post_to_notion(title, url, gemini_data, groq_data):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # 総合スコア計算
    sentiment_label = "中立"
    # スコアがない場合の安全策
    bull = gemini_data.get('bull_score', 5)
    bear = groq_data.get('bear_score', 5)
    
    score_diff = bull - bear
    if score_diff >= 3: sentiment_label = "強気"
    elif score_diff <= -3: sentiment_label = "弱気"

    # タグの安全な取得
    tags = gemini_data.get('tags', ["Tech"])
    # Notionのタグ制限（マルチセレクトは新しいタグをAPIで作れない場合があるためエラー回避）
    # 今回はそのまま送りますが、エラーが出る場合はここを調整します

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "Sentiment": {"select": {"name": sentiment_label}},
            "Tags": {"multi_select": [{"name": str(tag)} for tag in tags[:3]]}, # 最大3つまで
            "PublishedDate": {"date": {"start": datetime.now().isoformat()}}
        },
        "children": [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": f"AI要約: {gemini_data.get('summary', '')}"}}],
                    "icon": {"emoji": "📰"}
                }
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "🤖 AI討論 (Bull vs Bear)"}}]}
            },
            {
                "object": "block",
                "type": "column_list",
                "column_list": {
                    "children": [
                        {
                            "object": "block",
                            "type": "column",
                            "column": {
                                "children": [
                                    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🚀 Gemini (強気派)"}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": gemini_data.get('opportunity', '-')}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"強気スコア: {bull}/10"}}]}}
                                ]
                            }
                        },
                        {
                            "object": "block",
                            "type": "column",
                            "column": {
                                "children": [
                                    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🛡️ Groq (慎重派)"}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": groq_data.get('risk_point', '-')}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"リスクスコア: {bear}/10"}}]}}
                                ]
                            }
                        }
                    ]
                }
            }
        ]
    }
    
    try:
        res = requests.post(notion_url, headers=headers, data=json.dumps(payload))
        if res.status_code != 200:
            print(f"❌ Notion Post Error: {res.text}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")

# ==========================================
# メイン処理
# ==========================================
def main():
    print(f"📡 ニュース取得: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)
    entries = feed.entries[:5] 

    for entry in entries:
        print(f"Checking: {entry.title}")
        
        text_content = f"{entry.title}\n{entry.summary if 'summary' in entry else ''}"

        # 1. Gemini分析 (タグも一緒に取得)
        print("   Thinking (Gemini)...")
        gemini_res = analyze_with_gemini(text_content)
        
        # 2. Groq分析
        print("   Thinking (Groq)...")
        groq_res = analyze_with_groq(text_content)

        # 3. Notionへ保存
        post_to_notion(entry.title, entry.link, gemini_res, groq_res)
        print("✅ Discussion Saved.")
        
        # ★改良点：待機時間を15秒に延長（レート制限回避）
        print("   Sleeping 15s...")
        time.sleep(15)

if __name__ == "__main__":
    main()
