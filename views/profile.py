"""Profile page: who the student is and which courses they take. Saved on this computer only."""

from __future__ import annotations

import streamlit as st

from campusmail import userdata
from campusmail.importer import parse_course_list

state = st.session_state
profile = state.profile
YEARS = ["", "Year 1", "Year 2", "Year 3", "Year 4", "Year 5 or above", "Postgraduate", "Exchange student", "Other"]

st.title(":material/badge: Your profile")
st.caption("Your courses decide which updates count as yours. Everything here is saved on this computer only "
           "(in the git-ignored `private/` folder) and is never sent anywhere.")

with st.form("profile_form", border=True):
    left, right = st.columns(2)
    name = left.text_input("Name", value=profile["name"], placeholder="e.g. Chan Tai Man",
                           help="Used to greet you. Optional.")
    email = right.text_input("Email for signing in", value=profile["email"], placeholder="you@gmail.com",
                             help="Pre-fills the Google or Microsoft sign-in window. Optional.")
    programme = left.text_input("Programme or faculty", value=profile["programme"],
                                placeholder="e.g. BEng Computer Science")
    year = right.selectbox("Year of study", YEARS, index=YEARS.index(profile["year"]) if profile["year"] in YEARS else 0)
    courses_text = st.text_area("Your courses this semester", value=", ".join(profile["courses"]),
                                placeholder="e.g. COMP3297, AILT9019, ECON1210", height=90,
                                help="Course codes, separated by commas or one per line.")
    found = parse_course_list(courses_text)
    if st.form_submit_button("Save profile", type="primary", icon=":material/save:"):
        state.profile = userdata.save_profile({"name": name, "email": email, "programme": programme,
                                               "year": year, "courses": courses_text})
        state.courses_text = ", ".join(state.profile["courses"])  # the inbox uses them straight away
        st.toast("Profile saved on this computer.", icon=":material/check_circle:")
        st.rerun()

with st.container(border=True):
    st.markdown("**At a glance**")
    who = " · ".join(x for x in (profile["name"], profile["programme"], profile["year"]) if x)
    st.markdown(who or "No details yet.")
    if profile["courses"]:
        st.markdown(f"{len(profile['courses'])} courses: " + " ".join(f":red-badge[{c}]" for c in profile["courses"]))
    else:
        st.caption("No courses yet. Without them, CampusMail cannot tell your course updates from others'.")
