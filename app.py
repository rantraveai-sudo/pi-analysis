import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import rankdata
from sqlalchemy import text  # Important: Use for running raw SQL with st.connection

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="PI Analysis System",
    page_icon="🎯",
    layout="wide"
)

# --- DATABASE FUNCTIONS for NeonDB (PostgreSQL) ---

def get_db_connection():
    """
    Establishes a connection to the NeonDB database using Streamlit's
    built-in connection management and secrets.
    """
    return st.connection("neon_db", type="sql")

def init_db():
    """
    Initializes the database tables if they do not exist.
    """
    conn = get_db_connection()
    with conn.session as s:
        s.execute(text('''CREATE TABLE IF NOT EXISTS users 
                         (username TEXT PRIMARY KEY, password TEXT, role TEXT);'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS factors 
                         (factor_id TEXT PRIMARY KEY, factor_text TEXT, type TEXT);'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS scores 
                         (username TEXT, factor_id TEXT, impact REAL, performance REAL,
                          PRIMARY KEY(username, factor_id));'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS rank_overrides 
                         (factor_id TEXT PRIMARY KEY, override_rank INTEGER);'''))

        # Check if users table is empty before inserting defaults
        user_count = s.execute(text("SELECT COUNT(*) FROM users;")).scalar()
        if user_count == 0:
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('admin', 'admin', 'Admin');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('karan', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('sgopal', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('gmallan', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('sushil', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('ssharma', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('raghvinder', 'password', 'User');"))
            s.execute(text("INSERT INTO users (username, password, role) VALUES ('himanshu', 'password', 'User');"))

        s.commit()


# --- AUTHENTICATION FUNCTIONS ---

def login(username, password):
    """
    Validates user credentials against the database.
    NOTE: conn.query() is cached — never pass text() here, plain string only.
    """
    conn = get_db_connection()
    query = "SELECT * FROM users WHERE username = :user AND password = :pass"
    user = conn.query(query, params={"user": username, "pass": password}, ttl=0)
    if not user.empty:
        st.session_state['logged_in'] = True
        st.session_state['username'] = user.iloc[0]['username']
        st.session_state['role'] = user.iloc[0]['role']
        st.success("Logged in successfully!")
        st.rerun()
    else:
        st.error("Invalid username or password")

def logout():
    """Clears the session state to log the user out."""
    for key in list(st.session_state.keys()):
        if key not in ['logged_in', 'username', 'role']:
            del st.session_state[key]
    st.session_state['logged_in'] = False
    st.session_state['username'] = None
    st.session_state['role'] = None
    st.info("You have been logged out.")
    st.rerun()


# --- ADMIN DASHBOARD ---

def admin_dashboard():
    st.sidebar.title(f"Welcome, {st.session_state['username']} (Admin)")
    st.sidebar.button("Logout", on_click=logout, use_container_width=True)

    st.title("Admin Control Panel")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📤 Upload Factors",
        "📊 Live Tracking",
        "🎯 PI Matrix & Rankings",
        "✍️ Resolve Tied Ranks"
    ])

    conn = get_db_connection()

    # Tab 1: Upload Factors
    with tab1:
        st.header("Upload Key Factors")
        st.info("Upload an Excel file with a sheet named 'Key_Factors'. Columns must be: `Factor_ID`, `Factor_Text`, `Type` (Strength/Weakness).")
        uploaded_file = st.file_uploader("Choose an Excel file", type="xlsx")

        if uploaded_file:
            try:
                df_factors = pd.read_excel(uploaded_file, sheet_name="Key_Factors")
                st.write("Preview of Uploaded Factors:")
                st.dataframe(df_factors)

                if st.button("💾 Save to Database", key="save_factors"):
                    with st.spinner("Processing... This will clear all existing scores and overrides."):
                        try:
                            with conn.session as s:
                                s.execute(text("DELETE FROM factors;"))
                                s.execute(text("DELETE FROM scores;"))
                                s.execute(text("DELETE FROM rank_overrides;"))
                                for _, row in df_factors.iterrows():
                                    s.execute(text("""
                                        INSERT INTO factors (factor_id, factor_text, type) 
                                        VALUES (:fid, :ftext, :ftype)
                                    """), {'fid': row['Factor_ID'], 'ftext': row['Factor_Text'], 'ftype': row['Type']})
                                s.commit()
                            st.cache_data.clear()
                            st.success("Factors saved successfully! All previous scores and overrides have been cleared.")
                        except Exception as e:
                            st.error(f"Database error while saving factors: {e}")
            except Exception as e:
                st.error(f"An error occurred while reading the Excel file: {e}")

    # Tab 2: Live Tracking
    with tab2:
        st.header("Submission Status")
        all_users = conn.query("SELECT username FROM users WHERE role='User'", ttl=0)
        submitted_users = conn.query("SELECT DISTINCT username FROM scores", ttl=0)

        total_users = len(all_users)
        submitted_count = len(submitted_users)
        pending_count = total_users - submitted_count

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Users", total_users)
        col2.metric("Submissions Received", submitted_count)
        col3.metric("Pending Submissions", pending_count)

        if not submitted_users.empty:
            st.write("Users who have submitted:")
            st.dataframe(submitted_users, use_container_width=True)

        if pending_count > 0:
            pending_users = all_users[~all_users['username'].isin(submitted_users['username'])]
            st.write("Users who have NOT submitted:")
            st.dataframe(pending_users, use_container_width=True)

        if st.button("🔄 Refresh Now"):
            st.rerun()

    # Tab 3: PI Matrix & Rankings
    with tab3:
        st.header("Performance-Impact Analysis")
        df_scores_query = """
            SELECT s.factor_id, f.factor_text, f.type, s.impact, s.performance 
            FROM scores s JOIN factors f ON s.factor_id = f.factor_id
        """
        df_scores = conn.query(df_scores_query, ttl=0)

        if df_scores.empty:
            st.warning("No scores have been submitted yet.")
        else:
            # --- Calculation Engine ---
            df_agg = df_scores.groupby(['factor_id', 'factor_text', 'type']).agg(
                Avg_Impact=('impact', 'mean'),
                Avg_Performance=('performance', 'mean')
            ).reset_index()

            df_agg['Performance_Index'] = df_agg['Avg_Performance']
            df_agg['Priority_Score'] = (0.75 * df_agg['Avg_Impact']) + (0.25 * df_agg['Performance_Index'].abs())

            # --- Handle Rank Overrides ---
            overrides_df = conn.query("SELECT factor_id, override_rank FROM rank_overrides", ttl=0)
            override_map = pd.Series(overrides_df.override_rank.values, index=overrides_df.factor_id).to_dict()
            df_agg['override_sort_key'] = df_agg['factor_id'].map(override_map).fillna(9999)

            df_agg = df_agg.sort_values(by=['Priority_Score', 'override_sort_key'], ascending=[False, True])
            df_agg['Final_Rank'] = range(1, len(df_agg) + 1)

            # Display Final Rankings Table
            st.markdown("### 🏆 Final Strategic Rankings")
            display_cols = {
                'Final_Rank': 'Rank', 'factor_id': 'Factor ID', 'factor_text': 'Description',
                'type': 'Type', 'Avg_Impact': 'Avg Impact', 'Performance_Index': 'Perf. Index',
                'Priority_Score': 'Priority Score'
            }
            st.dataframe(
                df_agg[list(display_cols.keys())].rename(columns=display_cols),
                use_container_width=True,
                hide_index=True
            )

            # --- Visualization ---
            st.divider()
            st.markdown("### 🎯 Performance-Impact Matrix Visualization")
            fig = go.Figure()
            fig.add_shape(type="rect", x0=-10, y0=0, x1=0, y1=10, fillcolor="rgba(255, 200, 200, 0.2)", line_width=0, layer="below")
            fig.add_shape(type="rect", x0=0, y0=0, x1=10, y1=10, fillcolor="rgba(200, 255, 200, 0.2)", line_width=0, layer="below")

            colors = ['red' if t.lower() == 'weakness' else 'green' for t in df_agg['type']]

            fig.add_trace(go.Scatter(
                x=df_agg['Performance_Index'],
                y=df_agg['Avg_Impact'],
                mode='markers+text',
                text=df_agg['factor_id'],
                textposition="top center",
                customdata=df_agg[['factor_text', 'type', 'Priority_Score', 'Final_Rank']],
                marker=dict(size=16, color=colors, opacity=0.7),
                hovertemplate=(
                    "<b>%{text}</b> | Rank: %{customdata[3]:.0f}<br>"
                    "<b>%{customdata[0]}</b><br>"
                    "Type: %{customdata[1]}<br>"
                    "Impact: %{y:.2f}<br>"
                    "Performance: %{x:.2f}<br>"
                    "Priority: %{customdata[2]:.2f}<extra></extra>"
                )
            ))

            fig.update_layout(
                xaxis_title="<b>Performance Index</b> (← Weaknesses | Strengths →)",
                yaxis_title="<b>Average Impact</b> (Low → High)",
                xaxis=dict(range=[-10, 10], zeroline=True, zerolinewidth=3, zerolinecolor='black'),
                yaxis=dict(range=[0, 10], zeroline=True, zerolinewidth=1, zerolinecolor='gray'),
                height=600,
                hovermode="closest",
                plot_bgcolor='white'
            )
            st.plotly_chart(fig, use_container_width=True)

            if st.button("🔄 Refresh Matrix Now", key="refresh_tab3"):
                st.rerun()

    # Tab 4: Resolve Tied Ranks
    with tab4:
        st.header("Resolve Tied Rankings")
        df_scores_query_tab4 = """
            SELECT s.factor_id, f.factor_text, f.type, s.impact, s.performance 
            FROM scores s JOIN factors f ON s.factor_id = f.factor_id
        """
        df_scores_tab4 = conn.query(df_scores_query_tab4, ttl=0)

        if not df_scores_tab4.empty:
            df_agg_tab4 = df_scores_tab4.groupby(['factor_id', 'factor_text', 'type']).agg(
                Avg_Impact=('impact', 'mean'),
                Avg_Performance=('performance', 'mean')
            ).reset_index()
            df_agg_tab4['Performance_Index'] = df_agg_tab4['Avg_Performance']
            df_agg_tab4['Priority_Score'] = (0.75 * df_agg_tab4['Avg_Impact']) + (0.25 * df_agg_tab4['Performance_Index'].abs())
            df_agg_tab4['Initial_Rank'] = rankdata(-df_agg_tab4['Priority_Score'], method='min')

            tied_scores = df_agg_tab4[df_agg_tab4.duplicated(subset=['Priority_Score'], keep=False)].sort_values('Priority_Score', ascending=False)

            if not tied_scores.empty:
                st.warning("Tied ranks detected! Please set a manual priority for the factors below.")
                st.dataframe(
                    tied_scores[['Initial_Rank', 'factor_id', 'factor_text', 'Priority_Score']],
                    use_container_width=True,
                    hide_index=True
                )

                with st.form("override_form"):
                    overrides = {}
                    for _, row in tied_scores.iterrows():
                        overrides[row['factor_id']] = st.number_input(
                            f"Set manual rank for {row['factor_id']} ({row['factor_text']})",
                            min_value=1, max_value=len(df_agg_tab4), step=1, value=int(row['Initial_Rank'])
                        )

                    if st.form_submit_button("Save Overrides"):
                        try:
                            with conn.session as s:
                                for factor_id, rank in overrides.items():
                                    s.execute(text("""
                                        INSERT INTO rank_overrides (factor_id, override_rank)
                                        VALUES (:fid, :rank)
                                        ON CONFLICT (factor_id)
                                        DO UPDATE SET override_rank = EXCLUDED.override_rank;
                                    """), {'fid': factor_id, 'rank': rank})
                                s.commit()
                            st.cache_data.clear()
                            st.success("Overrides saved! The PI Matrix tab has been updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Database error while saving overrides: {e}")
            else:
                st.success("No tied ranks detected.")
        else:
            st.info("No scores available to check for ties.")


# --- USER DASHBOARD ---

def user_dashboard():
    st.sidebar.title(f"Welcome, {st.session_state['username']}")
    st.sidebar.button("Logout", on_click=logout, use_container_width=True)
    st.title("Performance-Impact Scoring")

    conn = get_db_connection()
    df_factors = conn.query("SELECT * FROM factors ORDER BY factor_id;", ttl=0)

    if df_factors.empty:
        st.warning("The admin has not uploaded any factors to score yet. Please check back later.")
        return

    # Initialize wizard step if not present
    if 'wizard_step' not in st.session_state:
        st.session_state.wizard_step = 1

    # --- Step 1: Impact Scoring ---
    if st.session_state.wizard_step == 1:
        st.header("Step 1: Rate the Impact")
        st.info("Rate each factor based on its potential strategic influence on your objectives (1=Low, 9=High).")

        with st.form("impact_form"):
            impact_scores = {}
            for _, row in df_factors.iterrows():
                label = f"**{row['factor_id']}**: {row['factor_text']}"
                impact_scores[row['factor_id']] = st.slider(label, 1, 9, 5, key=f"imp_{row['factor_id']}")

            submitted = st.form_submit_button("Next: Rate Performance →")
            if submitted:
                st.session_state['impact_scores'] = impact_scores
                st.session_state.wizard_step = 2
                st.rerun()

    # --- Step 2: Performance Scoring ---
    elif st.session_state.wizard_step == 2:
        st.header("Step 2: Rate the Performance")
        st.info("Rate each factor's current performance. Strengths (1=Low, 9=High), Weaknesses (-9=Severe, -1=Minor).")

        with st.form("performance_form"):
            performance_scores = {}
            for _, row in df_factors.iterrows():
                label = f"**{row['factor_id']}**: {row['factor_text']}"
                if row['type'].lower() == 'weakness':
                    performance_scores[row['factor_id']] = st.slider(
                        label, min_value=-9, max_value=-1, value=-5, key=f"perf_{row['factor_id']}"
                    )
                else:  # Strengths
                    performance_scores[row['factor_id']] = st.slider(
                        label, min_value=1, max_value=9, value=5, key=f"perf_{row['factor_id']}"
                    )

            col1, col2 = st.columns([1, 0.3])
            with col1:
                submit_button = st.form_submit_button("✅ Submit All Scores", use_container_width=True)
            with col2:
                back_button = st.form_submit_button("← Back")

            if back_button:
                st.session_state.wizard_step = 1
                st.rerun()

            if submit_button:
                with st.spinner("Saving your scores..."):
                    impact_scores_to_save = st.session_state.get('impact_scores', {})
                    try:
                        with conn.session as s:
                            for factor_id in df_factors['factor_id']:
                                s.execute(text("""
                                    INSERT INTO scores (username, factor_id, impact, performance)
                                    VALUES (:user, :fid, :imp, :perf)
                                    ON CONFLICT (username, factor_id)
                                    DO UPDATE SET impact = EXCLUDED.impact, performance = EXCLUDED.performance;
                                """), {
                                    'user': st.session_state['username'],
                                    'fid': factor_id,
                                    'imp': impact_scores_to_save.get(factor_id),
                                    'perf': performance_scores.get(factor_id)
                                })
                            s.commit()
                        st.cache_data.clear()
                        st.session_state.wizard_step = 3
                        st.rerun()
                    except Exception as e:
                        st.error(
                            "We couldn't save your scores due to a database error. "
                            f"Please contact the admin with this detail: {e}"
                        )

    # --- Step 3: Completion ---
    elif st.session_state.wizard_step == 3:
        st.success("Thank you! Your scores have been successfully submitted.")
        st.balloons()
        st.info("The administrator can now view the updated analysis in the main dashboard.")


# --- MAIN APPLICATION ROUTER ---

def main():
    """
    The main function that routes the user to the correct
    view based on their login status and role.
    """
    init_db()
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        if st.session_state['role'] == 'Admin':
            admin_dashboard()
        else:
            user_dashboard()
    else:
        st.title("Welcome to the PI Analysis System")
        st.write("Please log in to continue.")

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                login(username, password)

if __name__ == "__main__":
    main()
