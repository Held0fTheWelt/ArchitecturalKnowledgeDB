from architectural_knowledge_db.db.database import to_pyformat


def test_qmark_becomes_pyformat():
    assert to_pyformat("SELECT * FROM t WHERE a = ? AND b = ?") \
        == "SELECT * FROM t WHERE a = %s AND b = %s"


def test_literal_percent_is_escaped_before_placeholders():
    assert to_pyformat("SELECT '100%' AS p WHERE a = ?") \
        == "SELECT '100%%' AS p WHERE a = %s"
