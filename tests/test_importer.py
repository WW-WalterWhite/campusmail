import pytest

from campusmail.importer import MAX_BODY_CHARS, CSVImportError, load_csv, parse_course_list

HEADER = "message_id,received,subject,body,thread_id\n"


def test_valid_rows_and_naive_times_are_hong_kong():
    [m] = load_csv(HEADER + "a1,2026-10-21T09:30,Hi,Hello there,t1\n")
    assert m.problems == []
    assert m.received.utcoffset().total_seconds() == 8 * 3600
    assert m.thread_id == "t1"


def test_missing_columns_rejected():
    with pytest.raises(CSVImportError, match="body"):
        load_csv("message_id,received,subject\na,2026-10-21T09:30,x\n")


def test_too_many_messages_rejected():
    rows = "".join(f"m{i},2026-10-21T09:30,s,b,\n" for i in range(31))
    with pytest.raises(CSVImportError, match="limit is 30"):
        load_csv(HEADER + rows)


def test_oversized_message_flagged_not_truncated():
    body = "word " * (MAX_BODY_CHARS // 4)
    [m] = load_csv(HEADER + f"a1,2026-10-21T09:30,Long,{body},\n")
    assert len(m.body) > MAX_BODY_CHARS  # kept whole
    assert any("limit" in p for p in m.problems)


def test_bad_rows_flagged():
    messages = load_csv(HEADER + "a1,yesterday,s,body,\n,2026-10-21T09:30,s,,\na1,2026-10-21T09:30,s,dup,\n")
    assert "ISO 8601" in messages[0].problems[0]
    assert "Missing message ID." in messages[1].problems and "Empty message body." in messages[1].problems
    assert "Duplicate message ID." in messages[2].problems


def test_non_english_flagged():
    [m] = load_csv(HEADER + "a1,2026-10-21T09:30,小組會議,小組會議改到星期五下午三時,\n")
    assert any("English" in p for p in m.problems)


def test_course_list_parsing():
    assert parse_course_list("comp 3297, AILT9019\nAILT9019") == ["AILT9019", "COMP3297"]
