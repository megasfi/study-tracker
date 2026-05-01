import streamlit as st
from supabase import create_client
import requests
import datetime
import math
import re
import plotly.express as px
import pandas as pd
import time

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

def calculate_streak(book_id=None, goal_id=None):
    """本または目標のストリーク計算"""
    if book_id:
        res = supabase.table("study_logs").select("study_date").eq("book_id", book_id).order("study_date", desc=True).execute()
    elif goal_id:
        res = supabase.table("goal_logs").select("log_date").eq("goal_id", goal_id).order("log_date", desc=True).execute()
    else:
        return 0
    
    if not res.data: return 0
    
    date_key = 'study_date' if book_id else 'log_date'
    dates = sorted(list(set([datetime.date.fromisoformat(d[date_key]) for d in res.data])), reverse=True)
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

def display_habit_tracker(book_id=None, goal_id=None, title="Study Habit Tracker"):
    """ハビットトラッカーの表示"""
    if book_id:
        res = supabase.table("study_logs").select("study_date, minutes, memo").eq("book_id", book_id).order("study_date", desc=True).execute()
        date_key, value_key = 'study_date', 'minutes'
    elif goal_id:
        res = supabase.table("goal_logs").select("log_date, progress_value, memo").eq("goal_id", goal_id).order("log_date", desc=True).execute()
        date_key, value_key = 'log_date', 'progress_value'
    else:
        return
    
    if res.data:
        df = pd.DataFrame(res.data)
        df[date_key] = pd.to_datetime(df[date_key])
        df['week'] = df[date_key].dt.isocalendar().week
        df['day'] = df[date_key].dt.day_name()
        
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        fig = px.density_heatmap(
            df, x="week", y="day", z=value_key,
            category_orders={'day': day_order},
            title=f"{title} (Learning Activity)",
            labels={value_key: '進捗', 'week': '週', 'day': '曜日'},
            color_continuous_scale="Viridis"
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # メモを日付順に表示
        st.subheader("📝 メモ一覧")
        if book_id:
            memo_logs = supabase.table("study_logs").select("study_date, memo").eq("book_id", book_id).order("study_date", desc=True).execute()
        else:
            memo_logs = supabase.table("goal_logs").select("log_date, memo").eq("goal_id", goal_id).order("log_date", desc=True).execute()
        
        if memo_logs.data:
            for log in memo_logs.data:
                date_field = 'study_date' if 'study_date' in log else 'log_date'
                if log.get('memo') and log['memo'].strip():
                    st.write(f"**{log[date_field]}**: {log['memo']}")
        else:
            st.caption("メモがまだです")
    else:
        st.info("まだデータがありません")

# --- タブの設定 ---
tab1, tab2, tab3 = st.tabs(["Today's Task", "+ Add New Book", "🎯 Goals"])

# --- タブ1: 今日のタスク ---
with tab1:
    # セッション状態の初期化
    if 'timer_start' not in st.session_state:
        st.session_state.timer_start = None
    if 'total_study_seconds' not in st.session_state:
        st.session_state.total_study_seconds = 0
    if 'timer_running' not in st.session_state:
        st.session_state.timer_running = False
    if 'memo_input' not in st.session_state:
        st.session_state.memo_input = ""
    
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
        streak = calculate_streak(book_id=book['id'])
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
            col_p, col_start, col_end = st.columns(3)
            new_page_input = col_p.number_input("到達ページ (この周の)", min_value=0, max_value=total_pages, value=current_page)
            
            # メモ入力
            memo_input = st.text_area("メモ (最大200文字)", max_chars=200, height=80)
            
            # タイマーコントロール
            if col_start.button("▶ はじめ"):
                st.session_state.timer_start = time.time()
                st.session_state.timer_running = True
                st.rerun()
            
            if col_end.button("⏹ 終わり"):
                if st.session_state.timer_start is not None:
                    elapsed_seconds = time.time() - st.session_state.timer_start
                    st.session_state.total_study_seconds += elapsed_seconds
                    st.session_state.timer_start = None
                    st.session_state.timer_running = False
                    st.rerun()
            
            # タイマー表示
            st.divider()
            if st.session_state.timer_running and st.session_state.timer_start is not None:
                elapsed_seconds = time.time() - st.session_state.timer_start
                total_seconds = st.session_state.total_study_seconds + elapsed_seconds
                total_minutes = int(total_seconds / 60)
                total_secs = int(total_seconds % 60)
                st.metric(" 今日の勉強時間", f"{total_minutes}分 {total_secs}秒", delta="計測中")
                st.rerun()
            else:
                total_minutes = int(st.session_state.total_study_seconds / 60)
                total_secs = int(st.session_state.total_study_seconds % 60)
                st.metric(" 今日の勉強時間", f"{total_minutes}分 {total_secs}秒")
            
            study_mins = int(st.session_state.total_study_seconds / 60) if st.session_state.total_study_seconds > 0 else 1
            
            st.divider()
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
                supabase.table("study_logs").upsert({"book_id": book['id'], "study_date": str(today), "minutes": study_mins, "memo": memo_input.strip()}, on_conflict="book_id,study_date").execute()
                
                # セッション状態をリセット
                st.session_state.timer_start = None
                st.session_state.total_study_seconds = 0
                st.session_state.timer_running = False
                st.session_state.memo_input = ""
                
                st.rerun()

        # メモ表示セクション
        st.divider()
        st.subheader("📝 学習メモ")
        memo_logs = supabase.table("study_logs").select("study_date, memo").eq("book_id", book['id']).order("study_date", desc=True).execute()
        if memo_logs.data:
            for log in memo_logs.data:
                if log.get('memo') and log['memo'].strip():
                    st.write(f"**{log['study_date']}**: {log['memo']}")
        else:
            st.caption("メモがまだです")

        with st.expander("Habit Tracker"):
            display_habit_tracker(book_id=book['id'], title="Study Habit Tracker")

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
                try:
                    res = requests.get(f"https://api.openbd.jp/v1/get?isbn={isbn_input}").json()
                    if res and res[0]:
                        data = res[0]
                        title = data['summary']['title']
                        try:
                            extents = data['onix']['DescriptiveDetail']['Extent']
                            total_pages = next(int(e['ExtentValue']) for e in extents if e['ExtentType'] == '00')
                        except Exception as page_error:
                            st.warning(f"ページ数が取得できなかったため、デフォルト値(300)を使用します")
                            total_pages = 300
                        
                        try:
                            ins = supabase.table("study_books").insert({
                                "isbn": isbn_input,
                                "title": title,
                                "total_pages": total_pages,
                                "goal_date": str(target_date),
                                "current_page": 0,
                                "current_pass": 1
                            }).execute()
                            b_id = ins.data[0]['id']
                        except Exception as db_error:
                            st.error(f"データベースエラー: 本の登録に失敗しました。\n{str(db_error)}")
                            st.stop()
                        
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
                        except Exception as toc_error:
                            # 目次取得失敗時は基本情報のみ登録
                            supabase.table("book_chapters").insert({
                                "book_id": b_id,
                                "chapter_name": "第1章",
                                "start_page": 1
                            }).execute()
                        
                        st.success(f"「{title}」を登録しました！")
                        st.rerun()
                    else:
                        st.error("指定されたISBNの書籍が見つかりません。ISBNを確認してください。")
                except Exception as api_error:
                    st.error(f"APIエラー: 書籍情報の取得に失敗しました。\n{str(api_error)}")

# --- タブ3: 目標管理 ---
with tab3:
    st.subheader("🎯 任意の目標を管理")
    
    # 目標追加セクション
    with st.expander("➕ 新しい目標を追加", expanded=False):
        goal_title = st.text_input("目標タイトル (例: 読書時間、運動時間など)")
        goal_desc = st.text_area("目標の説明", height=80)
        goal_target = st.number_input("目標値", min_value=1, value=100)
        goal_unit = st.text_input("単位 (例: ページ、時間、回数など)", value="回")
        goal_deadline = st.date_input("期限")
        
        if st.button("目標を作成"):
            supabase.table("goals").insert({
                "title": goal_title,
                "description": goal_desc,
                "target_value": goal_target,
                "unit": goal_unit,
                "deadline": str(goal_deadline),
                "progress": 0
            }).execute()
            st.success(f"「{goal_title}」を作成しました！")
            st.rerun()
    
    st.divider()
    
    # 登録済み目標の表示
    goals_res = supabase.table("goals").select("*").order("deadline", desc=False).execute()
    
    if not goals_res.data:
        st.info("目標がまだ登録されていません")
    else:
        for goal in goals_res.data:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.subheader(goal['title'])
                    if goal.get('description'):
                        st.caption(goal['description'])
                    
                    # ストリーク表示
                    streak = calculate_streak(goal_id=goal['id'])
                    st.markdown(f"**連続達成: {streak} 日**")
                    
                    # 進捗表示
                    progress_pct = min(100, (goal['progress'] / goal['target_value'] * 100)) if goal['target_value'] > 0 else 0
                    st.progress(progress_pct / 100)
                    st.caption(f"{goal['progress']} / {goal['target_value']} {goal['unit']}")
                
                with col2:
                    # 削除ボタン
                    if st.button("削除", key=f"delete_{goal['id']}"):
                        supabase.table("goals").delete().eq("id", goal['id']).execute()
                        st.rerun()
                
                st.divider()
                
                # 本日のログ入力
                today = datetime.date.today()
                today_log_res = supabase.table("goal_logs").select("*").eq("goal_id", goal['id']).eq("log_date", str(today)).execute()
                today_log = today_log_res.data[0] if today_log_res.data else None
                
                col_progress, col_memo = st.columns([1, 2])
                
                with col_progress:
                    current_progress = today_log['progress_value'] if today_log else 0
                    new_progress = st.number_input(
                        "本日の進捗",
                        min_value=0,
                        value=current_progress,
                        key=f"progress_{goal['id']}"
                    )
                
                with col_memo:
                    memo = st.text_input(
                        "メモ",
                        value=today_log['memo'] if today_log else "",
                        key=f"memo_{goal['id']}"
                    )
                
                if st.button("保存", key=f"save_{goal['id']}"):
                    # 本日の進捗を保存
                    supabase.table("goal_logs").upsert({
                        "goal_id": goal['id'],
                        "log_date": str(today),
                        "progress_value": new_progress,
                        "memo": memo
                    }, on_conflict="goal_id,log_date").execute()
                    
                    # 目標の総進捗を更新（本日の値に更新）
                    supabase.table("goals").update({
                        "progress": new_progress
                    }).eq("id", goal['id']).execute()
                    
                    st.success("保存しました！")
                    st.rerun()
                
                # Habit Tracker
                with st.expander("📊 進捗チャート"):
                    display_habit_tracker(goal_id=goal['id'], title=goal['title'])
