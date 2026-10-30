"""Server-side contact configuration. Never include values in diagnostics."""
import re

CONFIG_WARNING = 'SEC refresh is disabled. Ask the app operator to configure the SEC identity in Streamlit Secrets.'

def valid_user_agent(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 256:
        return False
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        return False
    if value.count('@') != 1:
        return False
    contact = re.search(r'[^\s<>()]+@[^\s<>()]+', value)
    if not contact or len(value[:contact.start()].strip(' ()<>')) < 3:
        return False
    local, domain = contact.group().split('@')
    if not 1 <= len(local) <= 64 or local.startswith('.') or local.endswith('.') or '..' in local:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    labels = domain.split('.')
    return (len(labels) >= 2 and re.fullmatch(r'[A-Za-z]{2,63}', labels[-1]) is not None
            and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels))

def load_sec_user_agent(secrets):
    """Works with st.secrets, including an ignored local secrets.toml file."""
    try:
        value = secrets['sec']['user_agent']
        return value if valid_user_agent(value) else None
    except Exception:
        # Missing file/section/key, malformed TOML and unexpected types stay private.
        return None
