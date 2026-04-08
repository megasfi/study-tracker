import streamlit as st
from supabase import create_client
import requests
import datetime
import math
import re

# Supabaseの設定
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(URL, KEY)

st.set_page_config(page_title="study tracker", layout="centered")
st.title("📚 study tracker")

# --- 便利関数：目次からページ数を抽出する試み ---
def extract_page_number(text):
    # 文末にある数字を探す（例：「第1章 基礎知識 ... 12」の 12）
    match = re.search(r'(\d+)$', text.strip())
    return int(match.group(1)) if match else None

# --- タブの設定 ---
tab1, tab2 = st.tabs(["今日のタスク", "新しい本を登録"])

# --- タブ1: 今日のタスク (修正版) ---
with tab1:
    # 本の選択処理（既存のコード）
    books_res = supabase.table("study_books").select("*").execute()
    if not books_res.data:
        st.info("本を登録してください。")
    else:
        book_options = {b['title']: b for b in books_res.data}
        selected_title = st.selectbox("学習中の本を選択", book_options.keys())
        book = book_options[selected_title]

        today = datetime.date.today()
        goal_date = datetime.date.fromisoformat(book['goal_date'])
        
        # 平日カウント関数
        def count_study_days(start, end):
            count = 0
            curr = start
            while curr <= end:
                if curr.weekday() < 5:
                    count += 1
                curr += datetime.timedelta(days=1)
            return count

        is_weekend = today.weekday() >= 5
        study_days_left = count_study_days(today, goal_date)

# --- タブ1: 今日のタスク (3周対応版) ---

# (中略：本を選択し、平日数をカウントした後の計算部分)

total_pages = book['total_pages']
current_page = book['current_page']
current_pass = book.get('current_pass', 1) # DBに未追加の場合は1とする
total_passes = 3

# 1. 全体の進捗計算
total_workload = total_pages * total_passes
completed_workload = ((current_pass - 1) * total_pages) + current_page
remaining_workload = total_workload - completed_workload

if not is_weekend:
    # 2. 1日あたりのノルマ（総残りページ数 ÷ 残り平日数）
    daily_pages_needed = math.ceil(remaining_workload / max(study_days_left, 1))
    
    # 3. 今日の終了地点を計算
    # 終了地点が今の周のページ数を超える場合がある（例：1周目のP.290から1日20ページ進むなら2周目のP.10まで）
    end_point_total = completed_workload + daily_pages_needed
    
    # 終了時点での周回数とページ数を割り出す
    target_pass = ((end_point_total - 1) // total_pages) + 1
    target_page = ((end_point_total - 1) % total_pages) + 1
    
    # 表示用の処理
    st.subheader(f"🔄 現在 {current_pass} 周目 / 全 {total_passes} 周")
    st.metric("今日の目標", f"{current_pass}周目 P.{current_page + 1} 〜 {target_pass}周目 P.{target_page}")
    st.caption(f"全3周完了まであと {remaining_workload} ページ / 残り {study_days_left} 平日")

# 進捗更新ボタンの処理
new_page_input = st.number_input("現在の到達ページを入力", value=current_page)
if st.button("進捗を保存"):
    # もし入力されたページが総ページ数を超えたら、周回数を上げてページをリセット
    new_page = new_page_input
    new_pass = current_pass
    
    # 簡易的な周回アップ処理
    if new_page >= total_pages and current_pass < total_passes:
        new_pass += 1
        new_page = 0 # 次の周の最初に戻る
        st.balloons() # 周回達成のお祝い
        st.success(f"🎊 第{current_pass}周クリア！ 第{new_pass}周に入ります。")
    
    supabase.table("study_books").update({
        "current_page": new_page,
        "current_pass": new_pass
    }).eq("id", book['id']).execute()
    st.rerun()

# --- 「今日のタスク」タブ内、進捗更新ボタンの後ろなどに追加 ---
with st.expander("🛠 登録情報の修正 (総ページ数・目標日など)"):
    st.write("本の基本情報を変更できます。変更すると明日以降のノルマが再計算されます。")
    
    # 1. 修正用入力フィールド
    new_title = st.text_input("タイトルを修正", value=book['title'])
    new_total_pages = st.number_input("総ページ数を修正", min_value=1, value=book['total_pages'])
    new_goal_date = st.date_input("目標日を修正", value=datetime.date.fromisoformat(book['goal_date']))
    
    if st.button("基本情報を更新"):
        update_data = {
            "title": new_title,
            "total_pages": new_total_pages,
            "goal_date": str(new_goal_date)
        }
        supabase.table("study_books").update(update_data).eq("id", book['id']).execute()
        st.success("情報を更新しました！")
        st.rerun()

    st.divider()
    
    # 2. 章の開始ページの修正 (オプション)
    st.write("各章の開始ページを修正します")
    chapters_res = supabase.table("book_chapters").select("*").eq("book_id", book['id']).order("start_page").execute()
    
    if chapters_res.data:
        # データエディタを使って一覧形式で修正可能にする
        edited_chapters = st.data_editor(
            chapters_res.data,
            column_config={
                "chapter_name": "章の名前",
                "start_page": st.column_config.NumberColumn("開始ページ", min_value=1)
            },
            disabled=["id", "book_id"],
            hide_index=True
        )
        
        if st.button("章の情報を一括保存"):
            for row in edited_chapters:
                supabase.table("book_chapters").update({
                    "chapter_name": row['chapter_name'],
                    "start_page": row['start_page']
                }).eq("id", row['id']).execute()
            st.success("章の区切りを更新しました！")
            st.rerun()

# --- タブ2: 新しい本を登録 ---
with tab2:
    isbn_input = st.text_input("ISBNを入力してください (ハイフンなし13桁推奨)")
    target_date = st.date_input("目標完了日", value=datetime.date(2026, 11, 22))
    
    if st.button("本を検索・登録"):
            with st.spinner("書籍情報を取得中..."):
                # 1. まず、すでに登録されていないかチェック
                existing_book = supabase.table("study_books").select("id").eq("isbn", isbn_input).execute()
                
                if existing_book.data:
                    st.warning("⚠️ この本はすでに登録されています。「今日のタスク」タブで選択してください。")
                else:
                    # 2. 未登録なら、APIから情報を取得
                    res = requests.get(f"https://api.openbd.jp/v1/get?isbn={isbn_input}").json()
                    
                    if res and res[0]:
                        data = res[0]
                        title = data['summary']['title']
                        
                        # 総ページ数の取得
                        try:
                            extents = data['onix']['DescriptiveDetail']['Extent']
                            total_pages = next(int(e['ExtentValue']) for e in extents if e['ExtentType'] == '00')
                        except:
                            # 取得できない場合はユーザーに入力してもらう（暫定で300）
                            total_pages = 300 

                        # 3. study_booksに保存
                        book_data = {
                            "isbn": isbn_input,
                            "title": title,
                            "total_pages": total_pages,
                            "goal_date": str(target_date),
                            "current_page": 0
                        }
                        
                        try:
                            insert_res = supabase.table("study_books").insert(book_data).execute()
                            book_id = insert_res.data[0]['id']

                            # 4. book_chaptersに章情報を保存（以下、前回のコードと同じ）
                            # ... (中略) ...
                            st.success(f"「{title}」を新しく登録しました！")
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存中にエラーが発生しました: {e}")
                    else:
                        st.error("書籍情報が見つかりませんでした。")
#EOF