from example.hl7_utils import normalize_hl7, get_hl7_message_type, redact_hl7_basic

SAMPLE = 'MSH|^~\\&|MIRTH|SENDING|RECV|FAC|202512181200||ADT^A01|MSG00001|P|2.3\rPID|1||12345^^^MRN||DOE^JOHN||19800101|M|||123 MAIN ST^^ALLEN^TX^75013||555-5555\rPV1|1|I|W^101^1\r'

def test_message_type():
    assert get_hl7_message_type(SAMPLE) == "ADT^A01"

def test_redaction_masks_pid_fields():
    red = redact_hl7_basic(SAMPLE)
    assert "DOE^JOHN" not in red
    assert "19800101" not in red
    assert "123 MAIN ST" not in red
