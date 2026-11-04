from datetime import datetime, timedelta, timezone
import hmac
import math
import unicodedata

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials


# -----------------------------------------------------------------------------
# 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="530시간 공부 챌린지",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HISTORY_HEADERS = ["기록 시각", "차감한 사람", "과목", "세부 항목", "차감 시간(분)"]
KST = timezone(timedelta(hours=9))
DEADLINE = datetime(2026, 12, 15).date()

# 요청한 과목별 목표 시간. 세부 항목의 합계는 전체 530시간입니다.
STUDY_PLAN = {
    "수학": [
        ("본교재 끝내기", 25),
        ("부교재 끝내기", 30),
        ("1등급 만들기 끝내기", 70),
    ],
    "영어": [
        ("본문 3, 4과 통암기", 60),
        ("문법", 20),
        ("내신콘서트 문제 다 풀기", 20),
        ("모의고사", 50),
    ],
    "국어": [
        ("강의 완강", 10),
        ("문제집 다 풀기", 20),
        ("암기 + 프린트", 30),
    ],
    "과학": [
        ("백신과학 강의", 50),
        ("백신과학 문제풀이", 10),
        ("1등급 만들기 끝내기", 15),
    ],
    "사회": [
        ("1등급 만들기", 15),
        ("개념완성 + 프린트 + 교과서", 35),
    ],
    "한국사": [
        ("암기노트 만들기", 35),
        ("평가문제집 다 풀기", 8),
        ("1등급 만들기 끝내기", 15),
        ("프린트 + 교과서", 7),
    ],
    "기술·가정": [
        ("기술·가정 학습", 5),
    ],
}

TOTAL_MINUTES = sum(
    hours * 60
    for tasks in STUDY_PLAN.values()
    for _, hours in tasks
)


# -----------------------------------------------------------------------------
# 화면 디자인
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f5f7ff 0%, #fbfcff 45%, #ffffff 100%);
    }
    .block-container {
        max-width: 1120px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3 {
        letter-spacing: -0.04em;
    }
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid #e7eaf3;
        border-radius: 16px;
        padding: 16px 18px;
        box-shadow: 0 4px 16px rgba(35, 48, 86, 0.04);
    }
    div.stButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 11px;
        font-weight: 650;
        min-height: 2.8rem;
    }
    div[data-testid="stTabs"] button {
        font-weight: 650;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# 구글 시트 연결 및 기록 관리
# -----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def connect_spreadsheet():
    """Streamlit Secrets에 저장한 서비스 계정으로 구글 시트에 연결합니다."""
    try:
        account_info = dict(st.secrets["gcp_service_account"])
        spreadsheet_id = str(st.secrets["app"]["spreadsheet_id"]).strip()

        if not spreadsheet_id:
            raise ValueError("spreadsheet_id가 비어 있습니다.")

        credentials = Credentials.from_service_account_info(
            account_info,
            scopes=SCOPES,
        )
        client = gspread.authorize(credentials)
        return client.open_by_key(spreadsheet_id)
    except (KeyError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Streamlit Secrets 설정이 없습니다. 배포 페이지의 Settings → Secrets에 "
            "구글 서비스 계정 정보와 spreadsheet_id를 입력해 주세요."
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            "구글 시트 연결에 실패했습니다. 스프레드시트 ID와 서비스 계정 공유 권한을 "
            f"확인해 주세요. 오류 종류: {type(exc).__name__}"
        ) from exc


def normalize_header(value):
    """눈에 보이지 않는 공백·유니코드 차이 때문에 제목 검사가 실패하지 않게 정리합니다."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    # 복사/붙여넣기 과정에서 섞일 수 있는 BOM 및 zero-width 문자 제거
    for invisible in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"):
        text = text.replace(invisible, "")
    # 제목 안의 공백 종류나 개수가 달라도 같은 제목으로 인식
    return "".join(text.split())


def history_headers_match(row):
    actual = [normalize_header(cell) for cell in row[: len(HISTORY_HEADERS)]]
    expected = [normalize_header(cell) for cell in HISTORY_HEADERS]
    return actual == expected


def get_history_worksheet(spreadsheet):
    """차감 내역을 저장할 History 탭을 찾고, 없으면 자동으로 만듭니다."""
    try:
        worksheet = spreadsheet.worksheet("History")
    except gspread.WorksheetNotFound:
        try:
            worksheet = spreadsheet.add_worksheet(
                title="History",
                rows=10000,
                cols=len(HISTORY_HEADERS),
            )
        except Exception:
            # 두 기기에서 처음 접속하는 순간 탭 생성이 겹친 경우 다시 확인합니다.
            worksheet = spreadsheet.worksheet("History")

    current_values = worksheet.get_all_values()
    if not current_values:
        worksheet.update(
            values=[HISTORY_HEADERS],
            range_name="A1",
            value_input_option="RAW",
        )
    elif not history_headers_match(current_values[0]):
        actual_headers = current_values[0][: len(HISTORY_HEADERS)]
        raise RuntimeError(
            "구글 시트 History 탭의 첫 번째 행을 앱이 예상한 제목으로 읽지 못했습니다. "
            f"현재 읽힌 제목: {actual_headers!r}. "
            f"필요한 제목: {HISTORY_HEADERS!r}. "
            "첫 번째 행과 연결된 스프레드시트의 History 탭을 확인해 주세요."
        )

    return worksheet


def read_history(worksheet):
    """시트에서 모든 차감 기록을 읽고 데이터 형식을 검사합니다."""
    values = worksheet.get_all_values()
    if not values:
        return []

    if not history_headers_match(values[0]):
        actual_headers = values[0][: len(HISTORY_HEADERS)]
        raise RuntimeError(
            "History 탭의 제목 행을 찾을 수 없습니다. "
            f"현재 읽힌 제목: {actual_headers!r}."
        )

    history = []
    for row_number, row in enumerate(values[1:], start=2):
        if not row or not any(str(cell).strip() for cell in row):
            continue

        padded = list(row) + [""] * (len(HISTORY_HEADERS) - len(row))
        timestamp, person, subject, task, raw_minutes = padded[:5]

        try:
            numeric_minutes = float(raw_minutes)
            if not math.isfinite(numeric_minutes) or not numeric_minutes.is_integer():
                raise ValueError("차감 시간은 정수여야 합니다.")
            minutes = int(numeric_minutes)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"History 탭 {row_number}행의 차감 시간이 올바른 정수가 아닙니다."
            ) from exc

        if minutes <= 0 or minutes % 15 != 0:
            raise RuntimeError(
                f"History 탭 {row_number}행의 차감 시간은 15분 단위의 양수여야 합니다."
            )
        if subject not in STUDY_PLAN:
            raise RuntimeError(
                f"History 탭 {row_number}행에서 등록되지 않은 과목을 발견했습니다."
            )
        valid_tasks = {task_name for task_name, _ in STUDY_PLAN[subject]}
        if task not in valid_tasks:
            raise RuntimeError(
                f"History 탭 {row_number}행에서 등록되지 않은 세부 항목을 발견했습니다."
            )

        history.append(
            {
                "timestamp": timestamp,
                "person": person or "이름 미입력",
                "subject": subject,
                "task": task,
                "minutes": minutes,
            }
        )

    return history


def calculate_stats(history):
    """기록을 합산해 항목별 사용 시간, 남은 시간, 초과 여부를 계산합니다."""
    used = {
        subject: {task_name: 0 for task_name, _ in tasks}
        for subject, tasks in STUDY_PLAN.items()
    }

    for record in history:
        used[record["subject"]][record["task"]] += record["minutes"]

    remaining = {}
    completed_minutes = 0
    overused_items = []

    for subject, tasks in STUDY_PLAN.items():
        remaining[subject] = {}
        for task_name, target_hours in tasks:
            target_minutes = target_hours * 60
            used_minutes = used[subject][task_name]
            remaining_minutes = max(0, target_minutes - used_minutes)
            remaining[subject][task_name] = remaining_minutes
            completed_minutes += min(target_minutes, used_minutes)
            if used_minutes > target_minutes:
                overused_items.append(subject + " - " + task_name)

    return used, remaining, completed_minutes, overused_items


def append_deduction(spreadsheet, worksheet, timestamp, person, subject, task, minutes):
    """한 번의 Sheets batchUpdate로 차감 기록 한 줄을 추가합니다."""
    if subject not in STUDY_PLAN:
        raise ValueError("등록되지 않은 과목입니다.")
    valid_tasks = {task_name for task_name, _ in STUDY_PLAN[subject]}
    if task not in valid_tasks:
        raise ValueError("등록되지 않은 세부 항목입니다.")
    if not isinstance(minutes, int) or minutes <= 0 or minutes % 15 != 0:
        raise ValueError("차감 시간은 15분 단위의 양수여야 합니다.")
    if not str(person).strip():
        raise ValueError("차감한 사람을 입력해 주세요.")

    row = {
        "values": [
            {"userEnteredValue": {"stringValue": timestamp}},
            {"userEnteredValue": {"stringValue": person}},
            {"userEnteredValue": {"stringValue": subject}},
            {"userEnteredValue": {"stringValue": task}},
            {"userEnteredValue": {"numberValue": int(minutes)}},
        ]
    }
    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "appendCells": {
                        "sheetId": worksheet.id,
                        "rows": [row],
                        "fields": "userEnteredValue",
                    }
                }
            ]
        }
    )


def format_duration(minutes):
    """분 단위 숫자를 '3시간 15분' 형태로 바꿉니다."""
    hours, rest_minutes = divmod(int(minutes), 60)
    if hours and rest_minutes:
        return f"{hours}시간 {rest_minutes}분"
    if hours:
        return f"{hours}시간"
    return f"{rest_minutes}분"


def get_deadline_summary(remaining_minutes, today=None):
    """한국 날짜 기준 D-day와 마감일까지 필요한 하루 평균 공부량을 계산합니다.

    오늘과 마감일을 모두 공부 가능한 날로 계산합니다.
    하루 평균은 목표를 기한 안에 채울 수 있도록 분 단위 올림 처리합니다.
    """
    if today is None:
        today = datetime.now(KST).date()

    days_until_deadline = (DEADLINE - today).days
    if days_until_deadline > 0:
        dday_text = f"D-{days_until_deadline}"
    elif days_until_deadline == 0:
        dday_text = "D-DAY"
    else:
        dday_text = f"D+{abs(days_until_deadline)}"

    if remaining_minutes <= 0:
        daily_average_text = "목표 달성"
        daily_average_minutes = 0
    elif days_until_deadline >= 0:
        available_days = days_until_deadline + 1  # 오늘 포함
        daily_average_minutes = math.ceil(remaining_minutes / available_days)
        daily_average_text = f"{format_duration(daily_average_minutes)} / 일"
    else:
        daily_average_minutes = None
        daily_average_text = "기한 지남"

    return {
        "dday": dday_text,
        "days_until_deadline": days_until_deadline,
        "daily_average_text": daily_average_text,
        "daily_average_minutes": daily_average_minutes,
        "available_days": max(0, days_until_deadline + 1),
        "today": today,
    }


def password_gate():
    """APP_PASSWORD Secret을 설정한 경우에만 앱 입장을 제한합니다."""
    try:
        app_password = str(st.secrets.get("APP_PASSWORD", "")).strip()
    except Exception:
        app_password = ""

    if not app_password or st.session_state.get("authenticated", False):
        return

    st.title("🔐 공부 챌린지 입장")
    st.caption("앱 관리자에게 공유받은 접속 비밀번호를 입력해 주세요.")
    with st.form("login_form"):
        entered_password = st.text_input("접속 비밀번호", type="password")
        login_clicked = st.form_submit_button("입장하기", type="primary")

    if login_clicked:
        if hmac.compare_digest(entered_password, app_password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()


# -----------------------------------------------------------------------------
# 메인 앱
# -----------------------------------------------------------------------------
if sum(hours for tasks in STUDY_PLAN.values() for _, hours in tasks) != 530:
    st.error("과목별 목표 시간의 합계가 530시간이 아닙니다. 계획 설정을 확인해 주세요.")
    st.stop()

password_gate()

st.title("📚 530시간 공부 챌린지")
st.markdown("과목별 목표를 끝낼 때마다 공부한 시간을 차감해 보세요.")

if st.session_state.get("last_success"):
    st.success(st.session_state.pop("last_success"))

try:
    spreadsheet = connect_spreadsheet()
    history_worksheet = get_history_worksheet(spreadsheet)
    history = read_history(history_worksheet)
except Exception as exc:
    st.error("저장소에 연결하지 못해 앱을 불러오지 못했습니다.")
    st.info(
        "구글 시트가 서비스 계정 이메일에 편집자로 공유되어 있는지, "
        "Streamlit의 Settings → Secrets 설정이 정확한지 확인해 주세요."
    )
    with st.expander("오류 종류 확인"):
        st.code(f"{type(exc).__name__}: {exc}")
    st.stop()

used, remaining, completed_minutes, overused_items = calculate_stats(history)
remaining_total = max(0, TOTAL_MINUTES - completed_minutes)
completion_rate = completed_minutes / TOTAL_MINUTES if TOTAL_MINUTES else 0

# 상단 요약
deadline_summary = get_deadline_summary(remaining_total)
metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric("전체 남은 시간", format_duration(remaining_total))
metric2.metric("누적 완료 시간", format_duration(completed_minutes))
metric3.metric("전체 달성률", f"{completion_rate * 100:.1f}%")
metric4.metric("12월 15일 D-day", deadline_summary["dday"])

st.progress(completion_rate)
st.caption(f"전체 목표 530시간 · 완료 {format_duration(completed_minutes)} · 남음 {format_duration(remaining_total)}")

with st.container(border=True):
    st.subheader("🎯 마감일까지 필요한 하루 평균 공부량")
    st.metric(
        "하루 평균 공부량",
        deadline_summary["daily_average_text"],
        help="오늘과 2026년 12월 15일을 모두 포함해 계산합니다. 분 단위로 올림해 목표 시간에 부족하지 않도록 표시합니다.",
    )
    if deadline_summary["days_until_deadline"] >= 0:
        st.caption(
            f"기준일: {deadline_summary['today']:%Y년 %m월 %d일} · "
            f"마감일: 2026년 12월 15일 · "
            f"남은 공부 가능 일수: {deadline_summary['available_days']}일 (오늘 포함)"
        )
    elif remaining_total > 0:
        st.warning(
            f"마감일인 2026년 12월 15일이 지났습니다. "
            f"아직 {format_duration(remaining_total)}이 남아 있습니다."
        )
    else:
        st.success("축하합니다! 마감일과 관계없이 530시간 목표를 모두 달성했습니다.")

if overused_items:
    st.warning(
        "일부 항목의 누적 차감 시간이 목표를 초과했습니다. 기록을 확인해 주세요: "
        + ", ".join(overused_items)
    )

# 탭 구성
tab_deduct, tab_subjects, tab_history = st.tabs(
    ["⏱️ 시간 차감", "📊 과목별 현황", "🧾 차감 기록"]
)

with tab_deduct:
    st.subheader("공부한 시간 차감하기")
    st.caption("15분 단위로 차감할 수 있습니다. 다른 휴대폰에서 한 차감은 새로고침하면 반영됩니다.")

    active_subjects = [
        subject
        for subject, tasks in STUDY_PLAN.items()
        if any(remaining[subject][task_name] > 0 for task_name, _ in tasks)
    ]

    if not active_subjects:
        st.success("🎉 530시간 공부 계획을 모두 완료했습니다!")
    else:
        selected_subject = st.selectbox("과목 선택", active_subjects, key="subject_select")
        active_tasks = [
            task_name
            for task_name, _ in STUDY_PLAN[selected_subject]
            if remaining[selected_subject][task_name] > 0
        ]
        selected_task = st.selectbox(
            "세부 항목 선택",
            active_tasks,
            format_func=lambda task_name: (
                f"{task_name}  ·  남은 {format_duration(remaining[selected_subject][task_name])}"
            ),
            key=f"task_select_{selected_subject}",
        )
        task_remaining = remaining[selected_subject][selected_task]
        max_hours = task_remaining / 60
        default_hours = min(1.0, max_hours)

        st.info(f"선택한 항목의 남은 시간: **{format_duration(task_remaining)}**")
        hours_to_deduct = st.number_input(
            "차감할 시간 (시간 단위)",
            min_value=0.25,
            max_value=max_hours,
            value=default_hours,
            step=0.25,
            format="%.2f",
            key=f"hours_{selected_subject}_{selected_task}_{task_remaining}",
            help="0.25시간은 15분입니다. 예: 1.5시간 = 1시간 30분",
        )
        person = st.text_input(
            "차감한 사람",
            value="나",
            key="person_name",
            help="형 휴대폰에서는 '형'으로 바꿔 두면 기록에서 구분할 수 있습니다.",
        )

        if st.button("선택한 시간 차감하기", type="primary", use_container_width=True):
            minutes_to_deduct = int(round(hours_to_deduct * 60))
            cleaned_person = person.strip()

            if not cleaned_person:
                st.error("차감한 사람을 입력해 주세요.")
            elif minutes_to_deduct <= 0 or minutes_to_deduct % 15 != 0:
                st.error("차감 시간은 15분 단위로 입력해 주세요.")
            else:
                try:
                    # 다른 기기에서 먼저 차감했을 수 있으므로 저장 직전에 최신 기록을 다시 읽습니다.
                    latest_history = read_history(history_worksheet)
                    _, latest_remaining, _, _ = calculate_stats(latest_history)
                    latest_task_remaining = latest_remaining[selected_subject][selected_task]

                    if minutes_to_deduct > latest_task_remaining:
                        st.error(
                            "다른 기기에서 먼저 차감했거나 남은 시간이 부족합니다. "
                            f"현재 남은 시간은 {format_duration(latest_task_remaining)}입니다. "
                            "화면을 새로고침한 뒤 다시 시도해 주세요."
                        )
                    else:
                        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                        append_deduction(
                            spreadsheet,
                            history_worksheet,
                            timestamp,
                            cleaned_person,
                            selected_subject,
                            selected_task,
                            minutes_to_deduct,
                        )
                        st.session_state["last_success"] = (
                            f"{selected_subject} · {selected_task}에서 "
                            f"{format_duration(minutes_to_deduct)} 차감했습니다."
                        )
                        st.rerun()
                except Exception as exc:
                    st.error("차감 기록을 저장하지 못했습니다. 인터넷 연결과 시트 권한을 확인해 주세요.")
                    st.caption(f"오류 종류: {type(exc).__name__}")

with tab_subjects:
    st.subheader("과목별 진행 상황")
    subject_names = list(STUDY_PLAN.keys())

    for start in range(0, len(subject_names), 2):
        columns = st.columns(2)
        for column, subject in zip(columns, subject_names[start : start + 2]):
            with column:
                target_minutes = sum(hours * 60 for _, hours in STUDY_PLAN[subject])
                subject_used = sum(used[subject].values())
                subject_done = min(target_minutes, subject_used)
                subject_remaining = max(0, target_minutes - subject_done)
                with st.container(border=True):
                    st.markdown(f"#### {subject}")
                    st.metric("남은 시간", format_duration(subject_remaining))
                    st.progress(subject_done / target_minutes if target_minutes else 0)
                    st.caption(
                        f"완료 {format_duration(subject_done)} / 목표 {format_duration(target_minutes)}"
                    )
                    with st.expander("세부 항목 보기"):
                        for task_name, target_hours in STUDY_PLAN[subject]:
                            target = target_hours * 60
                            task_left = remaining[subject][task_name]
                            task_done = min(target, used[subject][task_name])
                            st.write(
                                f"**{task_name}**  ·  {format_duration(task_left)} 남음"
                            )
                            st.progress(task_done / target if target else 0)

with tab_history:
    st.subheader("최근 차감 기록")
    if not history:
        st.info("아직 차감한 기록이 없습니다. 첫 기록을 남겨 보세요!")
    else:
        st.caption(f"총 {len(history)}건의 차감 기록이 저장되어 있습니다.")
        recent_records = []
        for record in reversed(history[-100:]):
            recent_records.append(
                {
                    "기록 시각": record["timestamp"],
                    "차감한 사람": record["person"],
                    "과목": record["subject"],
                    "세부 항목": record["task"],
                    "차감 시간": format_duration(record["minutes"]),
                }
            )
        st.dataframe(
            recent_records,
            use_container_width=True,
            hide_index=True,
        )
        st.caption("화면에는 최근 100건을 표시합니다. 전체 기록은 연결된 구글 시트의 History 탭에서 확인할 수 있습니다.")

# 페이지 하단
st.divider()
footer_left, footer_right = st.columns([4, 1])
with footer_left:
    st.caption("공유 저장소: Google Sheets · 차감 단위: 15분 · 목표 시간: 530시간")
with footer_right:
    if st.button("🔄 새로고침", use_container_width=True):
        st.rerun()
