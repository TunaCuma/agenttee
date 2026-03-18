import pytest
from agenttee.tokenizer import tokenize_line, strip_ansi, TokenType


class TestStripAnsi:
    def test_removes_color_codes(self):
        assert strip_ansi("\033[31mERROR\033[0m") == "ERROR"

    def test_preserves_plain_text(self):
        assert strip_ansi("hello world") == "hello world"

    def test_handles_empty(self):
        assert strip_ansi("") == ""


class TestTokenizeLine:
    def test_timestamp_detection(self):
        tl = tokenize_line('2024-01-15T10:30:00Z INFO starting server')
        types = [t.type for t in tl.tokens]
        assert TokenType.TIMESTAMP in types

    def test_log_level_detection(self):
        for level in ["INFO", "ERROR", "WARNING", "DEBUG", "WARN"]:
            tl = tokenize_line(f"2024-01-15 {level} something happened")
            types = [t.type for t in tl.tokens]
            assert TokenType.LEVEL in types, f"Failed to detect level: {level}"

    def test_ip_detection(self):
        tl = tokenize_line("connecting to 192.168.1.100:8080")
        types = [t.type for t in tl.tokens]
        assert TokenType.IP in types

    def test_path_detection(self):
        tl = tokenize_line("loading /usr/local/bin/python")
        types = [t.type for t in tl.tokens]
        assert TokenType.PATH in types

    def test_url_detection(self):
        tl = tokenize_line("fetching https://api.example.com/v1/users")
        types = [t.type for t in tl.tokens]
        assert TokenType.URL in types

    def test_signature_stability(self):
        """Same structure should produce the same signature."""
        sig1 = tokenize_line("2024-01-15 INFO user logged in from 10.0.0.1").signature
        sig2 = tokenize_line("2024-01-16 INFO admin logged in from 172.16.0.5").signature
        assert sig1 == sig2

    def test_different_structures_differ(self):
        sig1 = tokenize_line("INFO starting server").signature
        sig2 = tokenize_line("ERROR failed to connect to 192.168.1.1").signature
        assert sig1 != sig2
