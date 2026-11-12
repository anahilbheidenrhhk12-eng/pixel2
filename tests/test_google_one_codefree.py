"""Regression checks for code-free /google_one and unchanged /login.

Tests run without Telegram credentials or Google access.
"""
import ast
from pathlib import Path
import unittest


def source_tree(filename):
    return ast.parse(Path(filename).read_text(encoding="utf-8"))


def function(filename, name):
    return next(
        node for node in source_tree(filename).body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == name
    )


def call_names(function_node):
    names = []
    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            try:
                names.append(ast.unparse(node.func))
            except Exception:
                pass
    return names


class CodeFreeGoogleOneTests(unittest.TestCase):
    def test_google_one_starts_at_email_not_code(self):
        fn = function("main.py", "begin_google_one_mobile")
        rendered = ast.unparse(fn)
        self.assertIn("AWAIT_EMAIL", rendered)
        self.assertNotIn("AWAIT_KEY", rendered)
        self.assertNotIn("accept_key(", rendered)
        self.assertNotIn("STORE.claim(", rendered)

    def test_normal_login_remains_code_gated(self):
        fn = function("main.py", "login_start")
        self.assertIn("accept_key", ast.unparse(fn))
        self.assertIn("AWAIT_KEY", ast.unparse(fn))

    def test_google_one_skips_code_claim_and_begin(self):
        fn = function("main.py", "check_offer")
        branches = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.If)
            and ast.unparse(n.test) == "not code_free_google_one"
        ]
        self.assertGreaterEqual(len(branches), 2)
        self.assertTrue(any("STORE.claim" in ast.unparse(n) for n in branches))
        self.assertTrue(any("STORE.begin" in ast.unparse(n) for n in branches))

    def test_code_consumption_skipped_for_free_mode(self):
        fn = function("google_automation.py", "check_gemini_offer")
        rendered = ast.unparse(fn)
        self.assertIn("not google_one_mobile_mode and (not STORE.consume(remote_session.token))", rendered)

    def test_registration_and_credentials_unchanged(self):
        fn = function("main.py", "login_totp")
        rendered = ast.unparse(fn)
        self.assertIn("google_one_mobile_mode", rendered)
        self.assertIn("check_offer(", rendered)


if __name__ == "__main__":
    unittest.main()
