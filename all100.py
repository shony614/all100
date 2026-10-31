import json
import os
import streamlit as st

st.set_page_config(page_title="시험 공부 시간 관리", page_icon="🎯", layout="centered")

DATA_FILE = "study_data.json"

# 기본 데이터 (단위: 분)
DEFAULT_STUDY_DATA = {
    "수학": {
        "본교재 끝내기": 1500,
        "부교재 끝내기": 1800,
        "1등급 만들기 끝내기": 4200,
    },
    "영어": {
        "본문 3, 4과 통암기": 3600,
        "문법": 1200,
        "내신콘서트 문제 다 풀기": 1200,
        "모의고사": 3000,
    },
    "국어": {
        "강의 완강": 600,
        "문제집 다풀기": 1200,
        "암기+프린트": 1800,
    },
    "과학": {
        "백신과학 강의": 3000,
        "백신과학 문제풀이": 600,
        "1등급 만들기 끝내기": 900,
    },
    "사회": {
        "1등급 만들기": 900,
        "개념완성+프린트+교과서": 2100,
    },
    "한국사": {
        "암기노트 만들기": 2100,
        "평가문제집 다풀기": 480,
        "1등급 만들기 끝내기": 900,
        "프린트+교과서": 420,
    },
    "기술가정": {"교과서 및 암기 학습": 300},
}


# 데이터 불러오기
def load_data():
  if os.path.exists(DATA_FILE):
    try:
      with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except:
      pass
  return {subject: items.copy() for subject, items in DEFAULT_STUDY_DATA.items()}


# 데이터 저장하기
def save_data(data):
  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


# 세션 상태 초기화
if "study_data" not in st.session_state:
  st.session_state.study_data = load_data()

TOTAL_TARGET_MINUTES = 31800  # 총 530시간 (31,800분)

# 남은 총 시간 및 달성률 계산
current_total_remaining = sum(
    sum(items.values()) for items in st.session_state.study_data.values()
)
completed_minutes = TOTAL_TARGET_MINUTES - current_total_remaining
progress_ratio = max(
    0.0, min(1.0, completed_minutes / TOTAL_TARGET_MINUTES)
)


def format_time(minutes):
  h = minutes // 60
  m = minutes % 60
  if h > 0 and m > 0:
    return f"{h}시간 {m}분"
  elif h > 0:
    return f"{h}시간"
  else:
    return f"{m}분"


# --- UI 레이아웃 ---
st.title("🎯 시험 D-Day 공부 시간 관리")

col1, col2 = st.columns(2)
col1.metric("남은 총 시간", format_time(current_total_remaining))
col2.metric("전체 달성률", f"{progress_ratio * 100:.1f}%")
st.progress(progress_ratio)

st.markdown("---")

st.subheader("⏱️ 공부 시간 기록")

col_s, col_i = st.columns(2)
with col_s:
  subject = st.selectbox(
      "과목",
      list(st.session_state.study_data.keys()),
      label_visibility="collapsed",
  )
with col_i:
  item = st.selectbox(
      "항목",
      list(st.session_state.study_data[subject].keys()),
      label_visibility="collapsed",
  )

max_rem_mins = st.session_state.study_data[subject][item]

# ⏱️ 시간 / 분 개별 입력 필드 배치
col_h, col_m = st.columns(2)
with col_h:
  input_hours = st.number_input(
      "시간", min_value=0, max_value=24, value=1, step=1
  )
with col_m:
  input_mins = st.number_input(
      "분", min_value=0, max_value=59, value=0, step=10
  )

total_deduct_mins = (input_hours * 60) + input_mins

if st.button("시간 차감하기", use_container_width=True, type="primary"):
  if total_deduct_mins <= 0:
    st.error("차감할 시간을 1분 이상 입력해주세요.")
  elif max_rem_mins >= total_deduct_mins:
    st.session_state.study_data[subject][item] -= total_deduct_mins
    save_data(st.session_state.study_data)
    st.success(f"[{item}] {format_time(total_deduct_mins)} 차감 완료!")
    st.rerun()
  else:
    st.error("해당 항목의 남은 시간보다 많이 차감할 수 없습니다.")

st.markdown("---")

st.subheader("📊 과목별 잔여 시간")

for subj, items in st.session_state.study_data.items():
  sub_rem = sum(items.values())

  with st.expander(f"📌 {subj} — 남은 시간: {format_time(sub_rem)}"):
    for itm, rem_m in items.items():
      orig_m = DEFAULT_STUDY_DATA[subj][itm]
      pct = (rem_m / orig_m) if orig_m > 0 else 0

      c1, c2 = st.columns([3, 1])
      c1.markdown(f"<small>{itm}</small>", unsafe_allow_html=True)
      c2.markdown(
          f"<small style='float:right;'><b>{format_time(rem_m)}</b></small>",
          unsafe_allow_html=True,
      )
      st.progress(pct)

st.markdown("---")

if st.button("🔄 전체 기록 초기화", use_container_width=True):
  st.session_state.study_data = {
      subject: items.copy() for subject, items in DEFAULT_STUDY_DATA.items()
  }
  save_data(st.session_state.study_data)
  st.success("초기화되었습니다.")
  st.rerun()
