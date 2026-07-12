import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import rankdata
from sqlalchemy import text
import io

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


# --- HELPER FUNCTION: CALCULATE INDIVIDUAL USER SCORES ---
def calculate_user_scores(df_scores_raw, df_factors):
    """
    Calculate priority score and rank for each user individually.
    Returns a dataframe with columns: username, factor_id, impact, performance, user_score, user_rank
    """
    results = []
    
    for username in df_scores_raw['username'].unique():
        user_data = df_scores_raw[df_scores_raw['username'] == username].copy()
        user_data = user_data.merge(df_factors[['factor_id', 'factor_text', 'type']], on='factor_id', how='left')
        
        # Calculate user's priority score for each factor
        user_data['user_score'] = (0.75 * user_data['impact']) + (0.25 * user_data['performance'].abs())
        
        # Rank the user's scores (1 = highest priority)
        user_data['user_rank'] = rankdata(-user_data['user_score'], method='min')
        
        results.append(user_data[['username', 'factor_id', 'impact', 'performance', 'user_score', 'user_rank']])
    
    if results:
        return pd.concat(results, ignore_index=True)
    else:
        return pd.DataFrame()


# --- HELPER FUNCTION: BUILD DETAILED CSV ---
def build_detailed_csv(conn):
    """
    Builds a comprehensive CSV with:
    - Serial No
    - Factor_ID
    - Factor_Text
    - Type
    - For each user: Impact, Performance, Score, Rank
    - Mean_Score
    - Auto_Final_Rank
    - Admin_Final_Rank (from overrides)
    """
    # Get all data
    df_factors = conn.query("SELECT * FROM factors ORDER BY factor_id", ttl=0)
    df_scores_raw = conn.query("SELECT username, factor_id, impact, performance FROM scores", ttl=0)
    df_overrides = conn.query("SELECT factor_id, override_rank FROM rank_overrides", ttl=0)
    
    if df_scores_raw.empty:
        return None
    
    # Calculate individual user scores
    user_scores = calculate_user_scores(df_scores_raw, df_factors)
    
    # Start building the final dataframe
    result = df_factors[['factor_id', 'factor_text', 'type']].copy()
    result.insert(0, 'Serial_No', range(1, len(result) + 1))
    
    # Add columns for each user
    users = sorted(df_scores_raw['username'].unique())
    
    for user in users:
        user_data = user_scores[user_scores['username'] == user]
        user_dict = user_data.set_index('factor_id')[['impact', 'performance', 'user_score', 'user_rank']].to_dict('index')
        
        result[f'{user}_Impact'] = result['factor_id'].map(lambda x: user_dict.get(x, {}).get('impact', ''))
        result[f'{user}_Performance'] = result['factor_id'].map(lambda x: user_dict.get(x, {}).get('performance', ''))
        result[f'{user}_Score'] = result['factor_id'].map(lambda x: user_dict.get(x, {}).get('user_score', ''))
        result[f'{user}_Rank'] = result['factor_id'].map(lambda x: user_dict.get(x, {}).get('user_rank', ''))
    
    # Calculate mean scores across all users
    df_agg = df_scores_raw.groupby('factor_id').agg(
        Mean_Impact=('impact', 'mean'),
        Mean_Performance=('performance', 'mean')
    ).reset_index()
    
    df_agg['Mean_Score'] = (0.75 * df_agg['Mean_Impact']) + (0.25 * df_agg['Mean_Performance'].abs())
    df_agg['Auto_Final_Rank'] = rankdata(-df_agg['Mean_Score'], method='min')
    
    # Merge mean scores
    result = result.merge(df_agg[['factor_id', 'Mean_Score', 'Auto_Final_Rank']], on='factor_id', how='left')
    
    # Add admin override ranks
    override_dict = df_overrides.set_index('factor_id')['override_rank'].to_dict()
    result['Admin_Final_Rank'] = result['factor_id'].map(override_dict)
    
    # Fill NaN in Admin_Final_Rank with Auto_Final_Rank
    result['Admin_Final_Rank'] = result['Admin_Final_Rank'].fillna(result['Auto_Final_Rank']).astype('Int64')
    
    return result


# --- ADMIN DASHBOARD ---

def admin_dashboard():
    st.sidebar.title(f"Welcome, {st.session_state['username']} (Admin)")
    st.sidebar.button("Logout", on_click=logout, use_container_width=True)

    st.title("Admin Control Panel")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📤 Upload Factors",
        "📊 Live Tracking",
        "🎯 PI Matrix & Rankings",
        "✍️ Resolve Tied Ranks",
        "📥 Download Detailed Report"
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

            # --- Handle Rank Overrides with ADJUSTED PRIORITY SCORE ---
            overrides_df = conn.query("SELECT factor_id, override_rank FROM rank_overrides", ttl=0)
            
            if not overrides_df.empty:
                # Create a mapping of override ranks
                override_map = overrides_df.set_index('factor_id')['override_rank'].to_dict()
                
                # For factors with overrides, adjust their priority score to force the desired rank
                # We'll use a simple formula: higher rank number = lower priority score
                max_priority = df_agg['Priority_Score'].max()
                min_priority = df_agg['Priority_Score'].min()
                
                def adjust_priority(row):
                    if row['factor_id'] in override_map:
                        # Map override rank to priority score range
                        # Rank 1 should get highest score, Rank N should get lowest
                        target_rank = override_map[row['factor_id']]
                        # Create a score that will place it at the target rank
                        # Use a score slightly above the natural score at that rank position
                        return max_priority + 10 - (target_rank * 0.1)
                    return row['Priority_Score']
                
                df_agg['Adjusted_Priority_Score'] = df_agg.apply(adjust_priority, axis=1)
            else:
                df_agg['Adjusted_Priority_Score'] = df_agg['Priority_Score']

            # Sort by adjusted priority score
            df_agg = df_agg.sort_values(by='Adjusted_Priority_Score', ascending=False).reset_index(drop=True)
            df_agg['Final_Rank'] = range(1, len(df_agg) + 1)

            # Display Final Rankings Table
            st.markdown("### 🏆 Final Strategic Rankings")
            display_cols = {
                'Final_Rank': 'Rank', 'factor_id': 'Factor ID', 'factor_text': 'Description',
                'type': 'Type', 'Avg_Impact': 'Avg Impact', 'Performance_Index': 'Perf. Index',
                'Priority_Score': 'Original Score', 'Adjusted_Priority_Score': 'Adjusted Score'
            }
            st.dataframe(
                df_agg[list(display_cols.keys())].rename(columns=display_cols).style.format({
                    'Avg Impact': '{:.2f}',
                    'Perf. Index': '{:.2f}',
                    'Original Score': '{:.3f}',
                    'Adjusted Score': '{:.3f}'
                }),
                use_container_width=True,
                hide_index=True
            )

            # --- Visualization ---
            st.divider()
            st.markdown("### 🎯 Performance-Impact Matrix Visualization")
            
            # IMPORTANT: Use Adjusted_Priority_Score to determine vertical position in plot
            # This ensures manual rank changes move the points vertically to prevent overlaps
            fig = go.Figure()
            fig.add_shape(type="rect", x0=-10, y0=0, x1=0, y1=10, fillcolor="rgba(255, 200, 200, 0.2)", line_width=0, layer="below")
            fig.add_shape(type="rect", x0=0, y0=0, x1=10, y1=10, fillcolor="rgba(200, 255, 200, 0.2)", line_width=0, layer="below")

            colors = ['red' if t.lower() == 'weakness' else 'green' for t in df_agg['type']]

            # Use a normalized adjusted score for Y-axis to spread points vertically
            # Map adjusted scores to 1-9 range for visual clarity
            score_min = df_agg['Adjusted_Priority_Score'].min()
            score_max = df_agg['Adjusted_Priority_Score'].max()
            df_agg['Plot_Y'] = 1 + 8 * (df_agg['Adjusted_Priority_Score'] - score_min) / (score_max - score_min)

            fig.add_trace(go.Scatter(
                x=df_agg['Performance_Index'],
                y=df_agg['Plot_Y'],  # Use adjusted Y position
                mode='markers+text',
                text=df_agg['factor_id'],
                textposition="top center",
                customdata=df_agg[['factor_text', 'type', 'Priority_Score', 'Final_Rank', 'Adjusted_Priority_Score']],
                marker=dict(size=16, color=colors, opacity=0.7),
                hovertemplate=(
                    "<b>%{text}</b> | Rank: %{customdata[3]:.0f}<br>"
                    "<b>%{customdata[0]}</b><br>"
                    "Type: %{customdata[1]}<br>"
                    "Avg Impact: %{customdata[2]:.2f}<br>"
                    "Performance: %{x:.2f}<br>"
                    "Original Priority: %{customdata[2]:.3f}<br>"
                    "Adjusted Priority: %{customdata[4]:.3f}<extra></extra>"
                )
            ))

            fig.update_layout(
                xaxis_title="<b>Performance Index</b> (← Weaknesses | Strengths →)",
                yaxis_title="<b>Strategic Priority</b> (Low → High)",
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
        st.info("Manually adjust the final rank of any factor. This will change its position on the PI Matrix to prevent overlaps.")
        
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
            df_agg_tab4['Auto_Rank'] = rankdata(-df_agg_tab4['Priority_Score'], method='min')
            df_agg_tab4 = df_agg_tab4.sort_values('Auto_Rank')

            # Get existing overrides
            existing_overrides = conn.query("SELECT factor_id, override_rank FROM rank_overrides", ttl=0)
            override_dict = existing_overrides.set_index('factor_id')['override_rank'].to_dict()

            st.markdown("### Current Rankings")
            st.dataframe(
                df_agg_tab4[['Auto_Rank', 'factor_id', 'factor_text', 'Priority_Score']].rename(columns={
                    'Auto_Rank': 'Current Rank', 'factor_id': 'Factor ID',
                    'factor_text': 'Description', 'Priority_Score': 'Priority Score'
                }),
                use_container_width=True,
                hide_index=True
            )

            st.markdown("### Adjust Rankings Manually")
            st.warning("Set a manual rank for any factor. Lower rank number = Higher priority.")

            with st.form("override_form_all"):
                overrides = {}
                
                # Display all factors with option to override
                for _, row in df_agg_tab4.iterrows():
                    current_override = override_dict.get(row['factor_id'])
                    default_val = current_override if current_override else int(row['Auto_Rank'])
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{row['factor_id']}**: {row['factor_text']}")
                    with col2:
                        overrides[row['factor_id']] = st.number_input(
                            f"Rank for {row['factor_id']}",
                            min_value=1,
                            max_value=len(df_agg_tab4),
                            step=1,
                            value=default_val,
                            key=f"override_{row['factor_id']}",
                            label_visibility="collapsed"
                        )

                col_submit, col_clear = st.columns(2)
                with col_submit:
                    submit_overrides = st.form_submit_button("💾 Save All Rank Overrides", use_container_width=True)
                with col_clear:
                    clear_overrides = st.form_submit_button("🗑️ Clear All Overrides", use_container_width=True)

                if submit_overrides:
                    try:
                        with conn.session as s:
                            # Clear existing overrides first
                            s.execute(text("DELETE FROM rank_overrides;"))
                            # Insert all new overrides
                            for factor_id, rank in overrides.items():
                                s.execute(text("""
                                    INSERT INTO rank_overrides (factor_id, override_rank)
                                    VALUES (:fid, :rank)
                                """), {'fid': factor_id, 'rank': rank})
                            s.commit()
                        st.cache_data.clear()
                        st.success("All rank overrides saved! The PI Matrix has been updated. Go to the 'PI Matrix & Rankings' tab to see changes.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error while saving overrides: {e}")

                if clear_overrides:
                    try:
                        with conn.session as s:
                            s.execute(text("DELETE FROM rank_overrides;"))
                            s.commit()
                        st.cache_data.clear()
                        st.success("All overrides cleared! Rankings restored to automatic calculation.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Database error while clearing overrides: {e}")

        else:
            st.info("No scores available to manage rankings.")

    # Tab 5: Download Detailed Report
    with tab5:
        st.header("📥 Download Detailed Scoring Report")
        st.info("This comprehensive report includes individual user scores, rankings, mean calculations, and final rankings.")

        if st.button("Generate CSV Report", key="generate_csv"):
            with st.spinner("Building detailed report..."):
                try:
                    detailed_csv = build_detailed_csv(conn)
                    
                    if detailed_csv is not None:
                        # Convert to CSV
                        csv_buffer = io.StringIO()
                        detailed_csv.to_csv(csv_buffer, index=False)
                        csv_data = csv_buffer.getvalue()

                        st.success("Report generated successfully!")
                        st.download_button(
                            label="📥 Download CSV Report",
                            data=csv_data,
                            file_name="PI_Analysis_Detailed_Report.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

                        # Show preview
                        st.markdown("### Preview (first 10 rows)")
                        st.dataframe(detailed_csv.head(10), use_container_width=True)
                    else:
                        st.warning("No data available yet. Users must submit their scores first.")
                        
                except Exception as e:
                    st.error(f"Error generating report: {e}")


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

    # --- CUSTOM CSS FOR SLIDER COLORS ---
    st.markdown("""
        <style>
        /* Green sliders for Strengths */
        div[data-testid="stSlider"][data-slider-type="strength"] div[role="slider"] {
            background-color: #28a745 !important;
        }
        div[data-testid="stSlider"][data-slider-type="strength"] .st-emotion-cache-1gulkj5 {
            background: linear-gradient(to right, #d4edda 0%, #28a745 100%) !important;
        }
        
        /* Red sliders for Weaknesses */
        div[data-testid="stSlider"][data-slider-type="weakness"] div[role="slider"] {
            background-color: #dc3545 !important;
        }
        div[data-testid="stSlider"][data-slider-type="weakness"] .st-emotion-cache-1gulkj5 {
            background: linear-gradient(to right, #f8d7da 0%, #dc3545 100%) !important;
        }
        
        /* Default green for impact sliders */
        div[data-testid="stSlider"][data-slider-type="impact"] div[role="slider"] {
            background-color: #007bff !important;
        }
        div[data-testid="stSlider"][data-slider-type="impact"] .st-emotion-cache-1gulkj5 {
            background: linear-gradient(to right, #cce5ff 0%, #007bff 100%) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # --- Step 1: Impact Scoring ---
    if st.session_state.wizard_step == 1:
        st.header("Step 1: Rate the Impact")
        st.info("Rate each factor based on its potential strategic influence on your objectives (1=Low, 9=High).")

        with st.form("impact_form"):
            impact_scores = {}
            
            # Separate strengths and weaknesses
            strengths = df_factors[df_factors['type'].str.lower() == 'strength'].sort_values('factor_id')
            weaknesses = df_factors[df_factors['type'].str.lower() == 'weakness'].sort_values('factor_id')
            
            if not strengths.empty:
                st.markdown("### 💪 Strengths")
                for _, row in strengths.iterrows():
                    # Add green-colored container for visual consistency
                    with st.container():
                        st.markdown(
                            f'<div style="padding:10px; border-left:4px solid #28a745; background-color:#f0fff0; margin-bottom:10px; border-radius:5px;">'
                            f'<b>{row["factor_id"]}</b>: {row["factor_text"]}</div>',
                            unsafe_allow_html=True
                        )
                        impact_scores[row['factor_id']] = st.slider(
                            f"Impact rating for {row['factor_id']}",
                            1, 9, 5,
                            key=f"imp_strength_{row['factor_id']}",
                            label_visibility="collapsed"
                        )
            
            if not weaknesses.empty:
                st.markdown("### ⚠️ Weaknesses")
                for _, row in weaknesses.iterrows():
                    # Add red-colored container for visual consistency
                    with st.container():
                        st.markdown(
                            f'<div style="padding:10px; border-left:4px solid #dc3545; background-color:#fff5f5; margin-bottom:10px; border-radius:5px;">'
                            f'<b>{row["factor_id"]}</b>: {row["factor_text"]}</div>',
                            unsafe_allow_html=True
                        )
                        impact_scores[row['factor_id']] = st.slider(
                            f"Impact rating for {row['factor_id']}",
                            1, 9, 5,
                            key=f"imp_weakness_{row['factor_id']}",
                            label_visibility="collapsed"
                        )

            submitted = st.form_submit_button("Next: Rate Performance →", use_container_width=True, type="primary")
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
            
            # Separate strengths and weaknesses
            strengths = df_factors[df_factors['type'].str.lower() == 'strength'].sort_values('factor_id')
            weaknesses = df_factors[df_factors['type'].str.lower() == 'weakness'].sort_values('factor_id')
            
            if not strengths.empty:
                st.markdown("### 💪 Strengths")
                st.caption("Rate how well each strength is currently performing (1 = Underperforming, 9 = Excellent)")
                for _, row in strengths.iterrows():
                    with st.container():
                        st.markdown(
                            f'<div style="padding:10px; border-left:4px solid #28a745; background-color:#f0fff0; margin-bottom:10px; border-radius:5px;">'
                            f'<b>{row["factor_id"]}</b>: {row["factor_text"]}</div>',
                            unsafe_allow_html=True
                        )
                        performance_scores[row['factor_id']] = st.slider(
                            f"Performance rating for {row['factor_id']}",
                            min_value=1,
                            max_value=9,
                            value=5,
                            key=f"perf_strength_{row['factor_id']}",
                            label_visibility="collapsed"
                        )
            
            if not weaknesses.empty:
                st.markdown("### ⚠️ Weaknesses")
                st.caption("Rate the current severity of each weakness (-9 = Critical problem, -1 = Minor/managed issue)")
                for _, row in weaknesses.iterrows():
                    with st.container():
                        st.markdown(
                            f'<div style="padding:10px; border-left:4px solid #dc3545; background-color:#fff5f5; margin-bottom:10px; border-radius:5px;">'
                            f'<b>{row["factor_id"]}</b>: {row["factor_text"]}</div>',
                            unsafe_allow_html=True
                        )
                        performance_scores[row['factor_id']] = st.slider(
                            f"Performance rating for {row['factor_id']}",
                            min_value=-9,
                            max_value=-1,
                            value=-5,
                            key=f"perf_weakness_{row['factor_id']}",
                            label_visibility="collapsed"
                        )

            col1, col2 = st.columns([1, 0.3])
            with col1:
                submit_button = st.form_submit_button("✅ Submit All Scores", use_container_width=True, type="primary")
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
