
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai


# ================= CONFIG =================

st.set_page_config(
    page_title="AskMyData",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "sales.db"
MODEL_NAME = "gemini-3.8-flash"


# ================= CUSTOM DESIGN =================

st.markdown("""
<style>
.stApp {
    background: #f7f8ff;
    color: #172554;
}

.block-container {
    padding-top: 1.4rem;
    padding-bottom: 2rem;
    max-width: 1500px;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #e9edff !important;
    border-right: 2px solid #d2dbff;
    min-width: 245px;
}

[data-testid="stSidebar"] > div {
    background: #e9edff !important;
}

/* Keep sidebar title clearly visible */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #182c68 !important;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #172554 !important;
}

[data-testid="stSidebar"] label {
    color: #172554 !important;
    font-weight: 650 !important;
    font-size: 15px !important;
}

[data-testid="stSidebar"] [role="radiogroup"] {
    gap: 8px;
}

[data-testid="stSidebar"] [role="radiogroup"] label {
    background: #ffffff;
    border: 1px solid #d7def9;
    border-radius: 10px;
    padding: 11px 12px;
    width: 100%;
}

[data-testid="stSidebar"] [role="radiogroup"] label:has(
    input:checked
) {
    background: #d6ddff;
    border: 2px solid #6555f5;
}

/* Main header */
.brand {
    font-size: 2.5rem;
    font-weight: 850;
    color: #182c68;
    letter-spacing: -1px;
}

.brand span {
    color: #6555f5;
}

.tagline {
    color: #66739a;
    font-size: 1rem;
    margin-top: -7px;
    margin-bottom: 22px;
}

/* Cards */
.panel {
    background: #ffffff;
    border: 1px solid #e0e7ff;
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 5px 20px rgba(40, 60, 120, 0.05);
}

.metric-card {
    background: linear-gradient(135deg, #ffffff, #eff2ff);
    border: 1px solid #dfe6ff;
    border-radius: 15px;
    padding: 16px;
    min-height: 100px;
}

.metric-label {
    color: #5e6c91;
    font-size: 0.9rem;
}

.metric-value {
    color: #233b83;
    font-size: 1.65rem;
    font-weight: 800;
    margin-top: 7px;
    overflow-wrap: anywhere;
}

.section-title {
    color: #1b2c63;
    font-size: 1.3rem;
    font-weight: 750;
}

.muted {
    color: #66739a;
}

.stButton > button {
    background: linear-gradient(90deg, #6555f5, #4676f4);
    color: white;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    min-height: 42px;
}

.stButton > button:hover {
    color: white;
    border: 1px solid #6555f5;
}

[data-testid="stFileUploader"] {
    background: #ffffff;
    border: 2px dashed #9aacf4;
    border-radius: 14px;
    padding: 12px;
}

[data-testid="stDataFrame"] {
    border: 1px solid #e0e7ff;
    border-radius: 10px;
}

h1, h2, h3, h4 {
    color: #1b2c63;
}

hr {
    border-color: #e0e7ff;
}

footer {
    visibility: hidden;
}
</style>
""", unsafe_allow_html=True)


# ================= DATABASE =================

def load_sales_data():
    if not DB_PATH.exists():
        return None

    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True,
    ) as conn:
        return pd.read_sql_query("SELECT * FROM sales", conn)


def get_database_schema():
    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True,
    ) as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
        """).fetchall()

        parts = []

        for (table_name,) in tables:
            safe_name = table_name.replace('"', '""')
            columns = conn.execute(
                f'PRAGMA table_info("{safe_name}")'
            ).fetchall()

            column_text = ", ".join(
                f"{col[1]} ({col[2] or 'unknown type'})"
                for col in columns
            )

            parts.append(
                f"Table: {table_name}\nColumns: {column_text}"
            )

        return "\n\n".join(parts)


def get_csv_schema(dataframe):
    columns = ", ".join(
        f'"{str(col)}" ({dataframe[col].dtype})'
        for col in dataframe.columns
    )
    return f"Table: uploaded_data\nColumns: {columns}"


# ================= AI / SQL =================

def generate_sql(question, schema, api_key):
    client = genai.Client(api_key=api_key)

    prompt = f"""
Convert the user's question into one SQLite SELECT query.

SCHEMA:
{schema}

QUESTION:
{question}

Rules:
- Return one SELECT query or a WITH ... SELECT query.
- Use only the supplied tables and columns.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER,
  CREATE, REPLACE, ATTACH, DETACH or PRAGMA statements.
- Return SQL only, without Markdown.
- If the question cannot be answered using this schema,
  return exactly UNSUPPORTED.
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    if not response.text:
        raise ValueError("The AI returned an empty response.")

    sql = response.text.strip()
    sql = re.sub(
        r"^```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\s*```$", "", sql).strip()
    return sql


def validate_sql(sql):
    cleaned = sql.strip()

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()

    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")

    if ";" in cleaned:
        raise ValueError("Only one SQL statement is allowed.")

    return cleaned


def set_read_only_authorizer(conn):
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }

    def authorize(action, arg1, arg2, database, source):
        if action in allowed:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    conn.set_authorizer(authorize)


def run_sales_query(sql):
    cleaned = validate_sql(sql)

    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True,
    ) as conn:
        set_read_only_authorizer(conn)
        return pd.read_sql_query(cleaned, conn)


def run_csv_query(sql, dataframe):
    cleaned = validate_sql(sql)

    with sqlite3.connect(":memory:") as conn:
        dataframe.to_sql(
            "uploaded_data",
            conn,
            index=False,
            if_exists="replace",
        )
        set_read_only_authorizer(conn)
        return pd.read_sql_query(cleaned, conn)


def ask_ai(question, schema):
    if not question.strip():
        st.warning("Please enter a question first.")
        return None

    if len(question) > 500:
        st.warning("Please keep your question under 500 characters.")
        return None

    api_key = st.secrets.get("GEMINI_API_KEY", "")

    if not api_key:
        st.error("Gemini API key is missing from your app secrets.")
        return None

    with st.spinner("AI is generating your SQL..."):
        sql = generate_sql(question, schema, api_key)

    if sql.strip().upper() == "UNSUPPORTED":
        st.warning("This question cannot be answered from these columns.")
        return None

    return sql


def show_metric(label, value, icon):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{icon} {label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_query_result(sql, result, key):
    st.markdown("#### 🧾 AI-Generated SQL")
    st.code(sql, language="sql")

    st.markdown("#### 📊 Query Results")
    st.dataframe(result, use_container_width=True)

    numeric = result.select_dtypes(
        include="number"
    ).columns.tolist()

    if not result.empty and numeric:
        selected = st.selectbox(
            "Choose a column for the chart",
            numeric,
            key=f"{key}_chart",
        )
        st.bar_chart(result, y=selected)


# ================= LOAD SAMPLE DATA =================

sample_df = None
database_error = None

try:
    sample_df = load_sales_data()
except Exception as error:
    database_error = str(error)


# ================= SIDEBAR =================

with st.sidebar:
    # Only the app name remains here.
    # Subtitle and Quick Guide have been removed.
    st.markdown(
        """
        <div style="
            color:#182c68;
            font-size:25px;
            font-weight:850;
            padding:8px 0 18px 0;
        ">📊 AskMyData</div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    page = st.radio(
        "NAVIGATION",
        [
            "🏠 Home",
            "📂 Upload CSV",
            "🗃️ Sample Data",
            "ℹ️ About",
        ],
        key="main_navigation",
    )


# ================= MAIN HEADER =================

st.markdown(
    """
    <div class="brand">AskMy<span>Data</span></div>
    <div class="tagline">
        Ask Questions. Get SQL. Discover Insights.
    </div>
    """,
    unsafe_allow_html=True,
)


# ================= HOME =================

if page == "🏠 Home":

    st.markdown(
        """
        <div class="panel">
            <div class="section-title">
                Turn your data into answers ✨
            </div>
            <p class="muted">
                Upload a CSV, ask questions in simple English,
                and explore your data with AI-generated SQL,
                tables and charts.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 📈 Sample Data Overview")

    if database_error:
        st.error(f"Could not load sales.db: {database_error}")

    elif sample_df is None or sample_df.empty:
        st.warning(
            "Sample database is missing or empty. "
            "You can still upload your own CSV."
        )

    else:
        if "sales" in sample_df.columns:
            sales_value = pd.to_numeric(
                sample_df["sales"], errors="coerce"
            ).sum()
            sales_text = f"₹{sales_value:,.0f}"
        else:
            sales_text = "N/A"

        if "quantity" in sample_df.columns:
            quantity_value = pd.to_numeric(
                sample_df["quantity"], errors="coerce"
            ).sum()
            quantity_text = f"{quantity_value:,.0f}"
        else:
            quantity_text = "N/A"

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            show_metric("Total Sales", sales_text, "💰")
        with c2:
            show_metric("Total Records", f"{len(sample_df):,}", "📄")
        with c3:
            show_metric("Total Quantity", quantity_text, "📦")
        with c4:
            show_metric("Columns", str(len(sample_df.columns)), "📊")

        left, right = st.columns([1.1, 1])

        with left:
            st.markdown("#### 📋 Data Preview")
            st.dataframe(
                sample_df.head(8),
                use_container_width=True,
                hide_index=True,
            )

        with right:
            st.markdown("#### 📊 Sales by Product")

            if {"product", "sales"}.issubset(sample_df.columns):
                chart_df = sample_df.copy()
                chart_df["sales"] = pd.to_numeric(
                    chart_df["sales"], errors="coerce"
                )
                chart_df = (
                    chart_df.groupby("product", as_index=False)["sales"]
                    .sum()
                    .sort_values("sales", ascending=False)
                )
                st.bar_chart(chart_df, x="product", y="sales")
            else:
                st.info("This chart needs product and sales columns.")

    st.divider()
    st.markdown("### ✨ Explore AskMyData")

    f1, f2, f3 = st.columns(3)

    with f1:
        st.markdown("""
        <div class="panel">
            <h3>📂 Upload CSV</h3>
            <p class="muted">Preview your own dataset.</p>
        </div>
        """, unsafe_allow_html=True)

    with f2:
        st.markdown("""
        <div class="panel">
            <h3>💬 Ask Questions</h3>
            <p class="muted">Use plain English instead of writing SQL.</p>
        </div>
        """, unsafe_allow_html=True)

    with f3:
        st.markdown("""
        <div class="panel">
            <h3>📈 Explore Results</h3>
            <p class="muted">View result tables and charts.</p>
        </div>
        """, unsafe_allow_html=True)

    st.info("Select **📂 Upload CSV** from the left sidebar to begin.")


# ================= UPLOAD CSV =================

elif page == "📂 Upload CSV":

    st.markdown("### 📂 Upload Your CSV")
    st.caption("Choose a CSV file from your device.")

    uploaded_file = st.file_uploader(
        "Drop your CSV file here or browse",
        type=["csv"],
        key="csv_upload",
    )

    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)

            if uploaded_df.empty or len(uploaded_df.columns) == 0:
                st.warning("This CSV does not contain usable data.")

            else:
                a, b, c = st.columns(3)

                with a:
                    show_metric("Rows", f"{len(uploaded_df):,}", "📄")
                with b:
                    show_metric(
                        "Columns", str(len(uploaded_df.columns)), "📊"
                    )
                with c:
                    show_metric(
                        "Numeric Columns",
                        str(len(uploaded_df.select_dtypes(
                            include="number"
                        ).columns)),
                        "🔢",
                    )

                st.markdown("#### 📋 Data Preview")
                st.dataframe(
                    uploaded_df.head(100),
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("View Statistics"):
                    numeric_df = uploaded_df.select_dtypes(
                        include="number"
                    )
                    if not numeric_df.empty:
                        st.dataframe(
                            numeric_df.describe(),
                            use_container_width=True,
                        )
                    else:
                        st.info("No numeric columns were detected.")

                st.divider()
                st.markdown("### 🤖 Ask a Question About Your CSV")
                st.caption(
                    "Example: Which product has the highest sales?"
                )

                csv_question = st.text_input(
                    "Your question",
                    placeholder="What are the total sales?",
                    key="csv_question",
                )

                if st.button(
                    "✨ Ask My CSV",
                    type="primary",
                    use_container_width=True,
                    key="ask_csv",
                ):
                    try:
                        sql = ask_ai(
                            csv_question,
                            get_csv_schema(uploaded_df),
                        )

                        if sql:
                            result = run_csv_query(sql, uploaded_df)
                            st.success("Query completed!")
                            show_query_result(
                                sql, result, "csv_result"
                            )

                    except Exception as error:
                        st.error("Could not answer your CSV question.")
                        st.caption(f"Technical details: {error}")

        except Exception as error:
            st.error(f"Could not read this CSV file: {error}")


# ================= SAMPLE DATA =================

elif page == "🗃️ Sample Data":

    st.markdown("### 🗃️ Built-in Sales Database")

    if database_error:
        st.error(f"Could not load sales.db: {database_error}")

    elif sample_df is None or sample_df.empty:
        st.warning("The sample database is missing or empty.")

    else:
        st.dataframe(
            sample_df,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("### 💬 Ask Your Sales Data")

        sales_question = st.text_input(
            "Your question",
            placeholder="What are the total sales?",
            key="sales_question",
        )

        if st.button(
            "✨ Generate Answer",
            type="primary",
            key="ask_sales",
        ):
            try:
                sql = ask_ai(
                    sales_question,
                    get_database_schema(),
                )

                if sql:
                    result = run_sales_query(sql)
                    st.success("Query completed!")
                    show_query_result(
                        sql, result, "sales_result"
                    )

            except Exception as error:
                st.error("Could not query the sample database.")
                st.caption(f"Technical details: {error}")


# ================= ABOUT =================

elif page == "ℹ️ About":

    st.markdown("### ℹ️ About AskMyData")

    st.markdown(
        """
        <div class="panel">
            <div class="section-title">
                Your data. Your questions. Your insights.
            </div>
            <p class="muted">
                AskMyData is an AI-powered data exploration app.
                Ask questions in simple English and explore data
                through SQL queries, result tables and charts.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 🛠️ Technology Stack")

    t1, t2, t3, t4, t5 = st.columns(5)

    with t1:
        st.markdown("🐍 **Python**")
    with t2:
        st.markdown("🎈 **Streamlit**")
    with t3:
        st.markdown("🐼 **Pandas**")
    with t4:
        st.markdown("🗄️ **SQLite**")
    with t5:
        st.markdown("✨ **Gemini AI**")

    st.markdown("### 🔄 How It Works")

    st.markdown("""
    1. Upload a CSV or choose the built-in sales data.
    2. Ask a question in plain English.
    3. Gemini generates an SQL query.
    4. The app runs the query and displays results.
    """)


# ================= FOOTER =================

st.divider()

st.markdown(
    """
    <div style="text-align:center; color:#7b87a8; padding:10px;">
        <b>AskMyData</b> · Turn Your Data Into Answers
        <br>
        <small>Built with Python, Streamlit, Pandas, SQLite and Gemini</small>
    </div>
    """,
    unsafe_allow_html=True,
)