import feedparser
import google.generativeai as genai
import requests
import json
import time
import os # OSの金庫にアクセスするためのライブラリ
from datetime import datetime

# ==========================================
# 🔧 環境変数からキーを取得（セキュリティ対策）
# ==========================================
# GitHub ActionsのSecretsに設定した名前と一致させる必要があります
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
DATABASE_ID = os.environ["DATABASE_ID"]

# ニュースソース & モデル
RSS_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"
MODEL_NAME = 'gemini-2.5-flash'

# ==========================================
# Notion送信機能
# ==========================================
def post_to_notion(data):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": data["title"]}}]},
            "URL": {"url": data["url"]},
            "Sentiment": {"select": {"name": data["sentiment"]}},
            "Tags": {"multi_select": [{"name": tag} for tag in data["tags"]]},
            "PublishedDate": {"date": {"start": datetime.now().isoformat()}}
        },
        "children": [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "AI分析サマリー"}}]}
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": data["summary"]}}]}
            },
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": f"💡 判断理由: {data['reason']}"}}],
                    "icon": {"emoji": "🤖"}
                }
            }
        ]
    }
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    return response.status_code

# ==========================================
# メイン処理
# ==========================================
def main():
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)

    print(f"📡 ニュースを取得中: {RSS_URL} ...")
    feed = feedparser.parse(RSS_URL)
    entries = feed.entries[:5] # 自動運用時は5件程度に増やす

    for entry in entries:
        print(f"Checking: {entry.title}")
        
        # ※ここで「Notionに既に同じURLがないかチェック」する機能を入れるのが理想ですが
        # 今回は簡易化のため省略し、常に最新を書き込みます。

        prompt = f"""
        以下のニュースを投資家視点で分析し、JSON形式で出力してください。
        【記事】{entry.title}\n{entry.summary if 'summary' in entry else ''}
        【フォーマット】
        {{
            "summary": "要約",
            "sentiment": "強気" or "弱気" or "中立",
            "reason": "理由",
            "tags": ["タグ1", "タグ2"]
        }}
        """
        try:
            response = model.generate_content(prompt)
            json_text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(json_text)
            
            final_data = {
                "title": entry.title,
                "url": entry.link,
                "summary": data.get("summary", "要約なし"),
                "sentiment": data.get("sentiment", "中立"),
                "reason": data.get("reason", "-"),
                "tags": data.get("tags", [])
            }

            post_to_notion(final_data)
            print("✅ Saved.")
            time.sleep(2) # API制限回避の休憩

        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
