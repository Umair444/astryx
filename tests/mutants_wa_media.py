"""Authored mutants for inbound media's sender-controlled id, bridges/whatsapp.py fetch_media() (tests/test_wa_media.py)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "bridges" / "whatsapp.py"
ORACLE = REPO / "tests" / "test_wa_media.py"
ENV = "WA_SRC"
TIMEOUT = 120

MUTANTS = {
    "the fetch trusts the sender's id (a walking id reads outside the store, a1 #62931 R2)":
        ('''    if not MSGID_OK.fullmatch(msgid):
        return f"<{media} attached, refused: its message id is not a WhatsApp id>"''',
         '''    if False:
        return f"<{media} attached, refused: its message id is not a WhatsApp id>"'''),
    "the docker copy-out goes back through a shell (a quote in an id runs commands, a1 #62931 R1)":
        ('''"docker", "exec", WA_DOCKER, "find", f"{DATA_CTR}/{rel}", "-type", "f",''',
         '''"docker", "exec", WA_DOCKER, "sh", "-c", f"find '{DATA_CTR}/{rel}' -type f | head -1",'''),
    "the fetch matches only message-* again (a document's own filename is never found, #62888)":
        ('''base.rglob("*")''', '''base.rglob("message-*")'''),
}
