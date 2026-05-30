"""
YTEN brand styling for the Streamlit app.

Colors pulled from existing YTEN deliverable templates:
  Navy   #0B1F3A  -- primary brand
  Gold   #C8A04A  -- accent / success / hero numbers
  Cream  #F8F5EE  -- subtle backgrounds
  Slate  #2C3E50  -- body text
  Muted  #6B7785  -- captions / secondary
  Border #E0DBCE

Single source of truth for colors. If brand updates, edit here only.
"""

NAVY = "#0B1F3A"
GOLD = "#C8A04A"
CREAM = "#F8F5EE"
SLATE = "#2C3E50"
MUTED = "#6B7785"
BORDER = "#E0DBCE"


# CSS string applied at the top of every page via st.markdown(unsafe_allow_html=True).
# Streamlit's default theme is light gray; we override containers, buttons,
# headers, and the metric strip to YTEN brand.
CSS = f"""
<style>
/* Page background and global text */
.stApp {{
    background: linear-gradient(180deg, #FFFFFF 0%, {CREAM} 100%);
    color: {SLATE};
}}

/* Headers in navy */
h1, h2, h3, h4 {{
    color: {NAVY} !important;
    font-weight: 600 !important;
}}

/* Primary buttons: navy bg, white text, gold border on hover */
.stButton > button[kind="primary"] {{
    background-color: {NAVY};
    color: white;
    border: 2px solid {NAVY};
    font-weight: 600;
    padding: 0.5rem 1.5rem;
    transition: all 0.15s ease;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: {GOLD};
    border-color: {GOLD};
    color: {NAVY};
}}

/* Secondary buttons: outlined navy */
.stButton > button[kind="secondary"] {{
    background-color: white;
    color: {NAVY};
    border: 2px solid {NAVY};
    font-weight: 600;
}}
.stButton > button[kind="secondary"]:hover {{
    background-color: {NAVY};
    color: white;
}}

/* Sidebar profile selector buttons. Streamlit's sidebar is dark, so default
   button text inherits white from the sidebar theme. Force text color on
   nested elements too — button labels are wrapped in <p> tags. */
[data-testid="stSidebar"] .stButton > button {{
    background-color: white;
    border: 1px solid {BORDER};
    font-weight: 500;
    text-align: left;
    padding: 0.5rem 0.75rem;
    transition: all 0.15s ease;
}}
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span,
[data-testid="stSidebar"] .stButton > button div {{
    color: {NAVY} !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background-color: {GOLD};
    border-color: {GOLD};
}}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stButton > button:hover p,
[data-testid="stSidebar"] .stButton > button:hover span,
[data-testid="stSidebar"] .stButton > button:hover div {{
    color: {NAVY} !important;
}}

/* Metric strip: gold numbers on cream cards */
[data-testid="stMetricValue"] {{
    color: {GOLD} !important;
    font-weight: 700 !important;
    font-size: 2.2rem !important;
}}
[data-testid="stMetricLabel"] {{
    color: {NAVY} !important;
    font-weight: 600 !important;
}}
[data-testid="stMetricDelta"] {{
    color: {MUTED} !important;
}}

/* Input fields: subtle border */
.stTextInput input, .stTextArea textarea {{
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
.stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: {GOLD};
    box-shadow: 0 0 0 2px {GOLD}33;
}}

/* Captions in muted slate */
.stCaption, [data-testid="stCaptionContainer"] {{
    color: {MUTED} !important;
}}

/* Sidebar */
[data-testid="stSidebar"] {{
    background-color: {NAVY};
}}
[data-testid="stSidebar"] *, [data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    color: white !important;
}}

/* Hide Streamlit's default chrome */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}
</style>
"""


def apply():
    """Inject the CSS. Call once at the top of every Streamlit page."""
    import streamlit as st
    st.markdown(CSS, unsafe_allow_html=True)