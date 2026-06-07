from __future__ import annotations

import streamlit as st

from config import APP_NAME
from ui.dashboard import render_dashboard


st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="PD")
render_dashboard()

