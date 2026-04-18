"""Tests for astra_claw.agent.title_generator."""

import time
from unittest.mock import patch

from astra_claw.agent.title_generator import (
    auto_title_session,
    generate_title,
    maybe_auto_title,
)


class TestGenerateTitle:
    def test_returns_title_on_success(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            return_value="Debugging Python Imports",
        ):
            assert (
                generate_title(
                    "help me fix this import",
                    "Sure, let me check...",
                    provider="openai",
                    model="gpt-x",
                )
                == "Debugging Python Imports"
            )

    def test_strips_quotes(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            return_value='"Setting Up Docker"',
        ):
            assert (
                generate_title("a", "b", provider="openai", model="gpt-x")
                == "Setting Up Docker"
            )

    def test_strips_title_prefix(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            return_value="Title: Kubernetes Pod Debugging",
        ):
            assert (
                generate_title("a", "b", provider="openai", model="gpt-x")
                == "Kubernetes Pod Debugging"
            )

    def test_strips_trailing_punctuation(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            return_value="Fixing the bug.",
        ):
            assert (
                generate_title("a", "b", provider="openai", model="gpt-x")
                == "Fixing the bug"
            )

    def test_truncates_long_titles(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            return_value="A" * 120,
        ):
            title = generate_title("a", "b", provider="openai", model="gpt-x")
            assert title is not None
            assert len(title) == 80
            assert title.endswith("...")

    def test_returns_none_on_empty_response(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once", return_value=""
        ):
            assert (
                generate_title("a", "b", provider="openai", model="gpt-x")
                is None
            )

    def test_returns_none_on_exception(self):
        with patch(
            "astra_claw.agent.title_generator.complete_once",
            side_effect=RuntimeError("boom"),
        ):
            assert (
                generate_title("a", "b", provider="openai", model="gpt-x")
                is None
            )

    def test_truncates_long_inputs(self):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return "Short Title"

        with patch(
            "astra_claw.agent.title_generator.complete_once", side_effect=fake
        ):
            generate_title(
                "x" * 2000, "y" * 2000, provider="openai", model="gpt-x"
            )

        user_payload = captured["messages"][1]["content"]
        # 500 user + 500 assistant + fixed formatting < 1100 chars
        assert len(user_payload) < 1100


class TestAutoTitleSession:
    def test_skips_when_title_already_set(self):
        with patch(
            "astra_claw.agent.title_generator.get_session_title",
            return_value="Existing",
        ), patch(
            "astra_claw.agent.title_generator.generate_title"
        ) as gen, patch(
            "astra_claw.agent.title_generator.set_session_title"
        ) as setter:
            auto_title_session(
                "sess-1", "hi", "hello", provider="openai", model="gpt-x"
            )
            gen.assert_not_called()
            setter.assert_not_called()

    def test_sets_title_on_success(self):
        with patch(
            "astra_claw.agent.title_generator.get_session_title",
            return_value=None,
        ), patch(
            "astra_claw.agent.title_generator.generate_title",
            return_value="New Title",
        ), patch(
            "astra_claw.agent.title_generator.set_session_title"
        ) as setter:
            auto_title_session(
                "sess-1", "hi", "hello", provider="openai", model="gpt-x"
            )
            setter.assert_called_once_with("sess-1", "New Title")

    def test_skips_when_generation_returns_none(self):
        with patch(
            "astra_claw.agent.title_generator.get_session_title",
            return_value=None,
        ), patch(
            "astra_claw.agent.title_generator.generate_title",
            return_value=None,
        ), patch(
            "astra_claw.agent.title_generator.set_session_title"
        ) as setter:
            auto_title_session(
                "sess-1", "hi", "hello", provider="openai", model="gpt-x"
            )
            setter.assert_not_called()

    def test_swallows_get_title_exception(self):
        with patch(
            "astra_claw.agent.title_generator.get_session_title",
            side_effect=OSError("disk gone"),
        ), patch(
            "astra_claw.agent.title_generator.generate_title"
        ) as gen:
            auto_title_session(
                "sess-1", "hi", "hello", provider="openai", model="gpt-x"
            )
            gen.assert_not_called()

    def test_no_session_id_is_noop(self):
        with patch(
            "astra_claw.agent.title_generator.get_session_title"
        ) as getter:
            auto_title_session(
                "", "hi", "hello", provider="openai", model="gpt-x"
            )
            getter.assert_not_called()


class TestMaybeAutoTitle:
    def test_fires_thread_on_first_exchange(self):
        with patch(
            "astra_claw.agent.title_generator.auto_title_session"
        ) as worker:
            thread = maybe_auto_title(
                "sess-1",
                "hello",
                "hi there",
                user_msg_count=1,
                provider="openai",
                model="gpt-x",
            )
            assert thread is not None
            thread.join(timeout=2.0)
            worker.assert_called_once_with(
                "sess-1",
                "hello",
                "hi there",
                provider="openai",
                model="gpt-x",
            )

    def test_skips_when_user_count_exceeds_two(self):
        with patch(
            "astra_claw.agent.title_generator.auto_title_session"
        ) as worker:
            assert (
                maybe_auto_title(
                    "sess-1",
                    "later",
                    "still later",
                    user_msg_count=5,
                    provider="openai",
                    model="gpt-x",
                )
                is None
            )
            time.sleep(0.05)
            worker.assert_not_called()

    def test_skips_on_empty_response(self):
        with patch(
            "astra_claw.agent.title_generator.auto_title_session"
        ) as worker:
            assert (
                maybe_auto_title(
                    "sess-1",
                    "hello",
                    "",
                    user_msg_count=1,
                    provider="openai",
                    model="gpt-x",
                )
                is None
            )
            worker.assert_not_called()

    def test_skips_when_disabled(self):
        with patch(
            "astra_claw.agent.title_generator.auto_title_session"
        ) as worker:
            assert (
                maybe_auto_title(
                    "sess-1",
                    "hello",
                    "hi",
                    user_msg_count=1,
                    provider="openai",
                    model="gpt-x",
                    enabled=False,
                )
                is None
            )
            worker.assert_not_called()

    def test_skips_without_session_id(self):
        with patch(
            "astra_claw.agent.title_generator.auto_title_session"
        ) as worker:
            assert (
                maybe_auto_title(
                    "",
                    "hello",
                    "hi",
                    user_msg_count=1,
                    provider="openai",
                    model="gpt-x",
                )
                is None
            )
            worker.assert_not_called()
