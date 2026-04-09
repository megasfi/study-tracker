import streamlit as st
from supabase import create_client
import requests
import datetime
import math
import re
import plotly.express as px
import pandas as pd

# 1. Supabaseの設定
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(URL, KEY)

st.set_page_config(page_title="study tracker", layout="centered")
st.title("Study Tracker")

# --- 便利関数 ---
def extract_page_number(text):
    match = re.search(r'(\d+)$', text.strip())
    return int(match.group(1)) if match else None

def calculate_streak(book_id):
    res = supabase.table("study_logs").select("study_date").eq("book_id", book_id).order("study_date", desc=True).execute()
    if not res.data: return 0
    
    dates = sorted(list(set([datetime.date.fromisoformat(d['study_date']) for d in res.data])), reverse=True)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    if dates[0] != today and dates[0] != yesterday: return 0
    
    streak = 0
    current_check = dates[0]
    for d in dates:
        if d == current_check:
            streak += 1
            current_check -= datetime.timedelta(days=1)
        else: break
    return streak

def display_habit_tracker(book_id):
    res = supabase.table("study_logs").select("study_date, minutes").eq("book_id", book_id).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        df['study_date'] = pd.to_datetime(df['study_date'])
        df['week'] = df['study_date'].dt.isocalendar().week
        df['day'] = df['study_date'].dt.day_name()
        
        # 曜日の順序を固定
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        fig = px.density_heatmap(
            df, x="week", y="day", z="minutes",
            category_orders={'day': day_order},
            title="Study Habit Tracker (Learning Minutes)",
            labels={'minutes': '分', 'week': '週', 'day': '曜日'},
            color_continuous_scale="Viridis"
        )
        st.plotly_chart(fig, use_container_width=True)

# --- タブの設定 ---
tab1, tab2 = st.tabs(["Today’s Task", "+ Add New Book"])

# --- タブ1: 今日のタスク ---
with tab1:
    books_res = supabase.table("study_books").select("*").execute()
    
    if not books_res.data:
        st.info("本が登録されていません。「+ Add New Book」タブから登録してください。")
    else:
        # 本の選択
        book_options = {b['title']: b for b in books_res.data}
        selected_title = st.selectbox("学習中の本を選択", book_options.keys())
        book = book_options[selected_title]

        # 基本データ
        today = datetime.date.today()
        goal_date = datetime.date.fromisoformat(book['goal_date'])
        total_pages = book['total_pages']
        current_page = book['current_page']
        current_pass = book.get('current_pass', 1)
        total_passes = 3

        # 平日カウント関数
        def count_study_days(start, end):
            count = 0
            curr = start
            while curr <= end:
                if curr.weekday() < 5: count += 1
                curr += datetime.timedelta(days=1)
            return count

        is_weekend = today.weekday() >= 5
        study_days_left = count_study_days(today, goal_date)

        # 3周対応の進捗計算
        total_workload = total_pages * total_passes
        completed_workload = ((current_pass - 1) * total_pages) + current_page
        remaining_workload = total_workload - completed_workload

        # --- 表示部分 ---
        streak = calculate_streak(book['id'])
        st.markdown(f"### 現在 **{streak}** 日連続学習中！")

        if is_weekend:
            st.info("**今日は復習の日です**")
            st.metric("現在の進捗", f"{current_pass}周目 P.{current_page}")
        else:
            daily_pages_needed = math.ceil(remaining_workload / max(study_days_left, 1))
            end_point_total = completed_workload + daily_pages_needed
            target_pass = ((end_point_total - 1) // total_pages) + 1
            target_page = ((end_point_total - 1) % total_pages) + 1
            
            # 現在の章を特定
            chapter_res = supabase.table("book_chapters").select("chapter_name").eq("book_id", book['id']).lte("start_page", current_page + 1).order("start_page", desc=True).limit(1).execute()
            current_chapter = chapter_res.data[0]['chapter_name'] if chapter_res.data else "章情報なし"

            st.subheader(f" {current_pass} / {total_passes} 周目")
            st.metric("今日の目標", f"P.{current_page + 1} 〜 P.{target_page}")
            if target_pass > current_pass:
                st.warning(f"※今日中に第{target_pass}周目に入ります！")
            st.info(f"セクション: **{current_chapter}**")
            st.caption(f"残り {remaining_workload} ページ / 平日あと {study_days_left} 日")

        st.divider()

        # 進捗更新エリア
        with st.container():
            col_p, col_t = st.columns(2)
            new_page_input = col_p.number_input("到達ページ (この周の)", min_value=0, max_value=total_pages, value=current_page)
            study_mins = col_t.number_input("今日の勉強時間 (分)", min_value=0, value=30)
            
            if st.button("進捗と勉強時間を保存"):
                new_page = new_page_input
                new_pass = current_pass
                
                # 周回アップ判定
                if new_page >= total_pages and current_pass < total_passes:
                    new_pass += 1
                    new_page = 0
                    st.balloons()
                
                # DB更新
                supabase.table("study_books").update({"current_page": new_page, "current_pass": new_pass}).eq("id", book['id']).execute()
                supabase.table("study_logs").upsert({"book_id": book['id'], "study_date": str(today), "minutes": study_mins}, on_conflict="book_id, study_date").execute()
                st.rerun()

        with st.expander("Habit Tracker"):
            display_habit_tracker(book['id'])

        with st.expander("🛠 登録情報の修正"):
            new_title = st.text_input("タイトル修正", value=book['title'])
            new_total = st.number_input("総ページ数修正", value=book['total_pages'])
            new_goal = st.date_input("目標日修正", value=datetime.date.fromisoformat(book['goal_date']))
            if st.button("基本情報を更新"):
                supabase.table("study_books").update({"title": new_title, "total_pages": new_total, "goal_date": str(new_goal)}).eq("id", book['id']).execute()
                st.rerun()

# --- タブ2: 新しい本を登録 ---
with tab2:
    isbn_input = st.text_input("ISBN (13桁)")
    target_date = st.date_input("目標完了日", value=datetime.date(2026, 11, 22))
    
    if st.button("本を検索・登録"):
        with st.spinner("書籍情報を取得中..."):
            existing = supabase.table("study_books").select("id").eq("isbn", isbn_input).execute()
            if existing.data:
                st.warning("登録済みです。")
            else:
                res = requests.get(f"https://api.openbd.jp/v1/get?isbn={isbn_input}").json()
                if res and res[0]:
                    data = res[0]
                    title = data['summary']['title']
                    try:
                        extents = data['onix']['DescriptiveDetail']['Extent']
                        total_pages = next(int(e['ExtentValue']) for e in extents if e['ExtentType'] == '00')
                    except: total_pages = 300
                    
                    ins = supabase.table("study_books").insert({"isbn": isbn_input, "title": title, "total_pages": total_pages, "goal_date": str(target_date), "current_page": 0, "current_pass": 1}).execute()
                    b_id = ins.data[0]['id']
                    
                    # 目次保存ロジック
                    try:
                        toc = data['onix']['CollateralDetail']['TextContent'][0]['Text']
                        chapters = []
                        last_p = 1
                        for line in toc.split("\n"):
                            if not line.strip(): continue
                            p = extract_page_number(line)
                            p_val = p if p else last_p
                            chapters.append({"book_id": b_id, "chapter_name": line.strip(), "start_page": p_val})
                            if p: last_p = p
                        supabase.table("book_chapters").insert(chapters).execute()
                    except:
                        supabase.table("book_chapters").insert({"book_id": b_id, "chapter_name": "第1章", "start_page": 1}).execute()
                    
                    st.success(f"「{title}」を登録しました！")
                    st.rerun()
#EOF