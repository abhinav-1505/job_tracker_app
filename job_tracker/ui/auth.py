from __future__ import annotations

import streamlit as st

from job_tracker.db_session import session_scope
from job_tracker.repositories import authenticate_user, create_user, user_count


SESSION_KEY = "job_tracker_authed"
SESSION_USER = "job_tracker_username"
SESSION_USER_ID = "job_tracker_user_id"
SESSION_IS_ADMIN = "job_tracker_is_admin"


def is_authed() -> bool:
    return bool(st.session_state.get(SESSION_KEY))


def current_user_id() -> int | None:
    value = st.session_state.get(SESSION_USER_ID)
    return int(value) if value is not None else None


def current_user_is_admin() -> bool:
    return bool(st.session_state.get(SESSION_IS_ADMIN))


def require_auth() -> None:
    if is_authed():
        return

    st.title("Job Tracker Login")
    with session_scope() as db:
        has_users = user_count(db) > 0

    mode = st.radio(
        "Choose",
        ["Log in", "Sign up"],
        horizontal=True,
        index=0 if has_users else 1,
    )

    if mode == "Sign up":
        is_first = not has_users
        if is_first:
            st.info("Create the first account (admin).")
        else:
            st.caption("Create a new user account.")

        with st.form("signup_form", clear_on_submit=True):
            username = st.text_input("Username", placeholder="yourname")
            password = st.text_input("Password", type="password")
            password2 = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account", type="primary")
            if submitted:
                if not username.strip():
                    st.error("Username is required.")
                elif not password:
                    st.error("Password is required.")
                elif password != password2:
                    st.error("Passwords do not match.")
                else:
                    with session_scope() as db:
                        create_user(db, username=username.strip(), password=password, is_admin=is_first)
                    st.success("Account created. Please log in.")
                    st.rerun()
        st.stop()

    # Log in
    with st.form("login_form"):
        username = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")
        if submitted:
            with session_scope() as db:
                u = authenticate_user(db, username=username, password=pw)
                # Avoid DetachedInstanceError by extracting primitives before session closes.
                user_id = int(u.id) if u else None
                user_name = str(u.username) if u else None
                is_admin = bool(u.is_admin) if u else False

            if user_id is not None and user_name is not None:
                st.session_state[SESSION_KEY] = True
                st.session_state[SESSION_USER] = user_name
                st.session_state[SESSION_USER_ID] = user_id
                st.session_state[SESSION_IS_ADMIN] = is_admin
                st.rerun()
            st.error("Invalid username or password.")

    st.stop()


def logout_button() -> None:
    if st.sidebar.button("Logout"):
        st.session_state.pop(SESSION_KEY, None)
        st.session_state.pop(SESSION_USER, None)
        st.session_state.pop(SESSION_USER_ID, None)
        st.session_state.pop(SESSION_IS_ADMIN, None)
        st.rerun()

