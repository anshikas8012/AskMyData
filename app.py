
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai


# ---------------- PAGE SETTINGS ----------------

st.set_page_config(
    page_title="AskMyData",
    page_icon="📊",
    layout="wide"
)

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "sales.db"
MODEL_NAME = "gemini-3.8-flash"

st.title("📊 AskMyData")
st.subheader("Ask Questions. Get SQL. Discover Insights.")
st.write(
    "Ask questions in simple English and explore your data "
    "using AI-powered SQL."
)


# ---------------- DATABASE HELPERS ----------------

def load_sales_data():
    if not DB_PATH.exists():
        return None

    # Read-only connection
    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True
    ) as conn:
        return pd.read_sql_query("SELECT * FROM sales", conn)


def get_database_schema():
    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True
    ) as conn:
        tables = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
        """).fetchall()

        schema_parts = []

        for (table_name,) in tables:
            # Table names are obtained from our own database.
            safe_name = table_name.replace('"', '""')

            columns = conn.execute(
                f'PRAGMA table_info("{safe_name}")'
            ).fetchall()

            column_info = ", ".join(
                f"{column[1]} ({column[2] or 'unknown type'})"
                for column in columns
            )

            schema_parts.append(
                f"Table: {table_name}\nColumns: {column_info}"
            )

        return "\n\n".join(schema_parts)


def generate_sql(question, schema, api_key):
    client = genai.Client(api_key=api_key)

    prompt = f"""
You convert natural-language questions into SQLite SQL.

DATABASE SCHEMA:
{schema}

USER QUESTION:
{question}

RULES:
- Generate exactly one SQLite SELECT query.
- You may use WITH ... SELECT queries.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER,
  CREATE, REPLACE, ATTACH, DETACH, or PRAGMA statements.
- Use only tables and columns present in the schema.
- Do not invent columns or tables.
- Return only SQL, without Markdown fences or explanations.
- If the question cannot be answered from the schema,
  return exactly: UNSUPPORTED
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    if not response.text:
        raise ValueError("The AI returned an empty response.")

    sql = response.text.strip()

    # Remove Markdown fences if the model adds them.
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql).strip()

    return sql


def run_read_only_query(sql):
    # Only one SELECT/WITH query is allowed.
    cleaned_sql = sql.strip()

    if cleaned_sql.endswith(";"):
        cleaned_sql = cleaned_sql[:-1].strip()

    if not re.match(r"^(SELECT|WITH)\b", cleaned_sql, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")

    # Reject multiple SQL statements.
    if ";" in cleaned_sql:
        raise ValueError("Only one SQL statement is allowed.")

    with sqlite3.connect(
        f"{DB_PATH.as_uri()}?mode=ro",
        uri=True
    ) as conn:

        # Deny all SQLite operations except reading data,
        # selecting, and calling functions.
        allowed_actions = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
        }

        def authorize(action, arg1, arg2, database, source):
            if action in allowed_actions:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)

        return pd.read_sql_query(cleaned_sql, conn)


# ---------------- LOAD DATABASE ----------------

if not DB_PATH.exists():
    st.error(
        "sales.db was not found. Run `python setup_db.py` "
        "in your project folder first."
    )
    st.stop()

try:
    df = load_sales_data()
except Exception as error:
    st.error(f"Could not load the sales database: {error}")
    st.stop()

if df is None or df.empty:
    st.warning("Your sales database is empty.")
    st.stop()


# ---------------- DASHBOARD ----------------

st.divider()
st.header("📁 Sales Dashboard")

col1, col2, col3 = st.columns(3)

if "sales" in df.columns:
    total_sales = pd.to_numeric(
        df["sales"], errors="coerce"
    ).sum()

    col1.metric("Total Sales", f"₹{total_sales:,.0f}")
else:
    col1.metric("Total Sales", "N/A")

col2.metric("Total Records", len(df))

if "quantity" in df.columns:
    total_quantity = pd.to_numeric(
        df["quantity"], errors="coerce"
    ).sum()

    col3.metric("Total Quantity", f"{total_quantity:,.0f}")
else:
    col3.metric("Total Quantity", "N/A")

with st.expander("📋 View Sales Data"):
    st.dataframe(df, use_container_width=True)


# ---------------- AI TEXT-TO-SQL ----------------

st.divider()
st.header("🤖 Ask Your Data")
st.write(
    "Enter a question in everyday English. Gemini will "
    "generate SQL for your sales database."
)

question = st.text_input(
    "Your question",
    placeholder="Which product has the highest sales?"
)

if st.button("✨ Generate Answer", type="primary"):
    if not question.strip():
        st.warning("Please enter a question first.")

    elif len(question) > 500:
        st.warning("Please keep your question under 500 characters.")

    else:
        api_key = st.secrets.get("GEMINI_API_KEY", "")

        if not api_key:
            st.error(
                "Gemini API key is missing. Add GEMINI_API_KEY "
                "to .streamlit/secrets.toml and restart the app."
            )

        else:
            try:
                with st.spinner("AI is generating SQL..."):
                    schema = get_database_schema()
                    sql = generate_sql(
                        question, schema, api_key
                    )

                if sql.strip().upper() == "UNSUPPORTED":
                    st.warning(
                        "This question cannot be answered "
                        "using the current database schema."
                    )

                else:
                    st.subheader("🧾 AI-Generated SQL")
                    st.code(sql, language="sql")

                    with st.spinner("Running read-only query..."):
                        result = run_read_only_query(sql)

                    st.success("Query completed!")

                    st.subheader("📊 Query Result")
                    st.dataframe(
                        result,
                        use_container_width=True
                    )

                    if not result.empty:
                        numeric_columns = result.select_dtypes(
                            include="number"
                        ).columns.tolist()

                        if numeric_columns:
                            chart_column = st.selectbox(
                                "Choose a numeric column to chart",
                                numeric_columns,
                                key="result_chart_column"
                            )

                            st.bar_chart(result[chart_column])

            except Exception as error:
                st.error(
                    "Could not complete the request. Check your "
                    "API key, internet connection, generated SQL, "
                    "and database schema."
                )
                st.caption(f"Technical details: {error}")


with st.expander("💡 Example Questions"):
    st.markdown("""
    - Which product has the highest sales?
    - What are the total sales?
    - Show the top 5 products by sales.
    - What is the total quantity sold?
    - Compare sales by category.
    - Show the average sales.
    - Which products have sales above 10000?
    """)


# ---------------- SALES ANALYTICS ----------------

st.divider()
st.header("📈 Sales Analytics")

if {"product", "sales"}.issubset(df.columns):
    product_sales = (
        df.assign(sales=pd.to_numeric(df["sales"], errors="coerce"))
        .groupby("product", as_index=False)["sales"]
        .sum()
        .sort_values("sales", ascending=False)
    )

    st.subheader("Product-wise Sales")
    st.bar_chart(
        product_sales,
        x="product",
        y="sales",
        x_label="Product",
        y_label="Sales (₹)"
    )

if {"category", "sales"}.issubset(df.columns):
    category_sales = (
        df.assign(sales=pd.to_numeric(df["sales"], errors="coerce"))
        .groupby("category", as_index=False)["sales"]
        .sum()
        .sort_values("sales", ascending=False)
    )

    st.subheader("Category-wise Sales")
    st.bar_chart(
        category_sales,
        x="category",
        y="sales",
        x_label="Category",
        y_label="Sales (₹)"
    )

if {"product", "quantity"}.issubset(df.columns):
    product_quantity = (
        df.assign(
            quantity=pd.to_numeric(df["quantity"], errors="coerce")
        )
        .groupby("product", as_index=False)["quantity"]
        .sum()
        .sort_values("quantity", ascending=False)
    )

    st.subheader("📦 Product-wise Quantity Sold")
    st.bar_chart(
        product_quantity,
        x="product",
        y="quantity",
        x_label="Product",
        y_label="Quantity"
    )


# ---------------- CSV UPLOAD ----------------

st.divider()
st.header("📂 Explore Your Own CSV")

st.write(
    "Upload a CSV file to preview it, view basic statistics, "
    "and create a simple chart."
)

uploaded_file = st.file_uploader(
    "Choose a CSV file",
    type=["csv"]
)

if uploaded_file is not None:
    try:
        uploaded_df = pd.read_csv(uploaded_file)

        st.subheader("Uploaded Data")
        st.dataframe(
            uploaded_df,
            use_container_width=True
        )

        row_col1, row_col2 = st.columns(2)
        row_col1.metric("Rows", uploaded_df.shape[0])
        row_col2.metric("Columns", uploaded_df.shape[1])

        numeric_columns = uploaded_df.select_dtypes(
            include="number"
        ).columns.tolist()

        if numeric_columns:
            selected_column = st.selectbox(
                "Choose a numeric column",
                numeric_columns,
                key="csv_chart_column"
            )

            st.subheader("CSV Chart")
            st.bar_chart(uploaded_df[selected_column])

            with st.expander("View Statistics"):
                st.dataframe(
                    uploaded_df[numeric_columns].describe(),
                    use_container_width=True
                )
        else:
            st.info(
                "No numeric columns were found for a chart."
            )

    except Exception as error:
        st.error(f"Could not read this CSV file: {error}")


# ---------------- FOOTER ----------------

st.divider()
st.caption(
    "AskMyData | AI-powered Text-to-SQL | Built with "
    "Python, Streamlit, Pandas, SQLite and Gemini"
)