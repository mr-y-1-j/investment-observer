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
GROQ_MODEL = 'llama3-70b-8192' # 高性能かつ高速なオープンモデル

# ==========================================
# 1. AI分析関数群
# ==========================================

# A. Gemini (強気・機会探索担当)
def analyze_with_gemini(text):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    prompt = f"""
    あなたは「成長株投資家」です。以下のニュースから「投資機会」や「将来性」を見出し、ポジティブな視点で分析してください。
    
    【ニュース】{text}
    
    【出力】JSON形式のみ
    {{
        "summary": "要約",
        "opportunity": "どのような収益機会があるか（一言）",
        "bull_score": 1〜10の点数（10が超強気）
    }}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        return {"summary": "分析失敗", "opportunity": "-", "bull_score": 5}

# B. Groq/Llama3 (弱気・リスク管理担当)
def analyze_with_groq(text):
    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
    You are a "Risk Manager". Analyze the following news critically. Find potential risks, competitors, or overhype.
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
    except:
        return {"risk_point": "分析失敗", "bear_score": 5}

# ==========================================
# 2. Notion送信機能（リッチ構成）
# ==========================================
def post_to_notion(title, url, gemini_data, groq_data, tags):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # 総合スコア計算（強気度 - リスク度）
    sentiment_label = "中立"
    score_diff = gemini_data['bull_score'] - groq_data['bear_score']
    if score_diff >= 3: sentiment_label = "強気"
    elif score_diff <= -3: sentiment_label = "弱気"

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "Sentiment": {"select": {"name": sentiment_label}},
            "Tags": {"multi_select": [{"name": tag} for tag in tags]},
            "PublishedDate": {"date": {"start": datetime.now().isoformat()}}
        },
        "children": [
            # セクション1: 概要
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": f"AI要約: {gemini_data['summary']}"}}],
                    "icon": {"emoji": "📰"}
                }
            },
            # セクション2: 議論（Gemini vs Groq）
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
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": gemini_data['opportunity']}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"強気スコア: {gemini_data['bull_score']}/10"}}]}}
                                ]
                            }
                        },
                        {
                            "object": "block",
                            "type": "column",
                            "column": {
                                "children": [
                                    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🛡️ Groq (慎重派)"}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": groq_data['risk_point']}}]}},
                                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"リスクスコア: {groq_data['bear_score']}/10"}}]}}
                                ]
                            }
                        }
                    ]
                }
            }
        ]
    }
    requests.post(notion_url, headers=headers, data=json.dumps(payload))

# ==========================================
# メイン処理
# ==========================================
def main():
    print(f"📡 ニュース取得: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)
    entries = feed.entries[:5] 

    for entry in entries:
        print(f"Checking: {entry.title}")
        
        # 本文がない場合はタイトルを使う
        text_content = f"{entry.title}\n{entry.summary if 'summary' in entry else ''}"

        # 1. Gemini分析（タグ生成も任せる）
        # ※タグ生成用プロンプトは簡略化のためここで処理
        genai.configure(api_key=GEMINI_API_KEY)
        tag_model = genai.GenerativeModel('gemini-2.5-flash')
        tag_res = tag_model.generate_content(f"以下の記事の関連タグを3つ、Pythonリスト形式['A','B']で出して: {entry.title}")
        try:
            tags = eval(tag_res.text.replace("```json", "").replace("```", "").strip())
        except:
            tags = ["Tech"]

        # 2. それぞれ分析
        print("   Thinking (Gemini)...")
        gemini_res = analyze_with_gemini(text_content)
        
        print("   Thinking (Groq)...")
        groq_res = analyze_with_groq(text_content)

        # 3. Notionへ保存
        post_to_notion(entry.title, entry.link, gemini_res, groq_res, tags)
        print("✅ Discussion Saved.")
        time.sleep(2)

if __name__ == "__main__":
    main()
