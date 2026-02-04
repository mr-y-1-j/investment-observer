import feedparser
import google.generativeai as genai
import requests
import json
import time
import os
from datetime import datetime
from groq import Groq

# ==========================================
# 🔧 設定エリア
# ==========================================
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
DATABASE_ID = os.environ["DATABASE_ID"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"] # ★追加

RSS_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"
GEMINI_MODEL = 'gemini-2.5-flash'
GROQ_MODEL = 'llama3-70b-8192'

# ==========================================
# 1. AI分析関数（日本語強制版）
# ==========================================

def analyze_with_gemini(text):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    # ★改良: 「日本語で」と強く指示
    prompt = f"""
    あなたは「成長株投資家」です。以下のニュースから「投資機会」を見出し分析してください。
    出力は必ず日本語で行ってください。
    
    【ニュース】{text}
    
    【出力JSON形式】
    {{
        "summary": "3行要約（日本語）",
        "opportunity": "収益機会（日本語）",
        "bull_score": 1〜10の整数,
        "tags": ["タグA", "タグB"] 
    }}
    """
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except:
        return {"summary": "分析失敗", "opportunity": "-", "bull_score": 5, "tags": []}

def analyze_with_groq(text):
    client = Groq(api_key=GROQ_API_KEY)
    
    # ★改良: Llama3に日本語出力を強制するプロンプト
    prompt = f"""
    You are a skeptial Risk Manager. Analyze the news critically.
    You MUST output JSON in Japanese language.
    
    News: {text}
    
    JSON Format:
    {{
        "risk_point": "最大のリスク要因（日本語で記述）",
        "bear_score": 1-10 integer
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
# 2. Notion & Discord 送信機能
# ==========================================

def post_to_notion(title, url, gemini_data, groq_data):
    # (前回と同じコードですが、省略せず記載します)
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    bull = gemini_data.get('bull_score', 5)
    bear = groq_data.get('bear_score', 5)
    score_diff = bull - bear
    sentiment_label = "強気" if score_diff >= 3 else "弱気" if score_diff <= -3 else "中立"
    
    tags = gemini_data.get('tags', [])[:3]

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "URL": {"url": url},
            "Sentiment": {"select": {"name": sentiment_label}},
            "Tags": {"multi_select": [{"name": str(tag)} for tag in tags]},
            "PublishedDate": {"date": {"start": datetime.now().isoformat()}}
        },
        "children": [
            {
                "object": "block", "type": "callout",
                "callout": {"rich_text": [{"text": {"content": f"要約: {gemini_data.get('summary', '')}"}}], "icon": {"emoji": "📰"}}
            },
            {
                "object": "block", "type": "column_list",
                "column_list": {
                    "children": [
                        {
                            "object": "block", "type": "column",
                            "column": {"children": [
                                {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🚀 強気視点"}}]}},
                                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": gemini_data.get('opportunity', '-')}}]}},
                                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"Score: {bull}"}}]}}
                            ]}
                        },
                        {
                            "object": "block", "type": "column",
                            "column": {"children": [
                                {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🛡️ 慎重視点"}}]}},
                                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": groq_data.get('risk_point', '-')}}]}},
                                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": f"Score: {bear}"}}]}}
                            ]}
                        }
                    ]
                }
            }
        ]
    }
    requests.post(notion_url, headers=headers, data=json.dumps(payload))

# ★追加機能: 編集長によるDiscordレポート
def send_daily_report_to_discord(analyzed_news_list):
    if not analyzed_news_list:
        return

    # 全ニュースの要点をまとめる
    news_summary_text = ""
    for item in analyzed_news_list:
        news_summary_text += f"- {item['title']} (強気:{item['bull']} vs 弱気:{item['bear']})\n"

    # Gemini編集長にレポートを書かせる
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    あなたは投資ファンドの「チーフ・ストラテジスト」です。
    本日の重要ニュースのリストを元に、投資家向けの「朝刊サマリーレポート」を作成してください。
    
    【ニュースリスト】
    {news_summary_text}
    
    【指示】
    - 日本語で記述してください。
    - 冒頭に市場全体の「今日のムード（センチメント）」を一言で述べてください。
    - 特に注目すべき1記事を選び、深掘りしてください。
    - 最後に投資家へのアクション提案をしてください。
    - 文字数は600文字程度で、Discordで読みやすいフォーマットにしてください。
    """
    
    try:
        response = model.generate_content(prompt)
        report_content = response.text
        
        # Discord送信
        payload = {
            "username": "AI Investment CIO",
            "content": f"**📊 本日の投資モーニング・ブリーフィング**\n{datetime.now().strftime('%Y-%m-%d')}\n\n{report_content}\n\n詳細: [Notionデータベースを確認](https://www.notion.so/)"
        }
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
        print("✅ Discord Report Sent.")
    except Exception as e:
        print(f"❌ Discord Error: {e}")

# ==========================================
# メイン処理
# ==========================================
def main():
    print(f"📡 ニュース取得: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)
    entries = feed.entries[:5] 
    
    # レポート用にデータを貯めるリスト
    todays_insights = []

    for entry in entries:
        print(f"Checking: {entry.title}")
        text_content = f"{entry.title}\n{entry.summary if 'summary' in entry else ''}"

        # 1. 分析（15秒待機を挟む）
        gemini_res = analyze_with_gemini(text_content)
        groq_res = analyze_with_groq(text_content)
        
        # 2. Notionへ保存
        post_to_notion(entry.title, entry.link, gemini_res, groq_res)
        
        # 3. レポート用リストに追加
        todays_insights.append({
            "title": entry.title,
            "bull": gemini_res.get('bull_score', 5),
            "bear": groq_res.get('bear_score', 5)
        })
        
        print("✅ Saved & Stacked.")
        time.sleep(15)

    # 4. 最後にまとめてレポート作成＆通知
    print("📝 Generating Daily Report...")
    send_daily_report_to_discord(todays_insights)

if __name__ == "__main__":
    main()
