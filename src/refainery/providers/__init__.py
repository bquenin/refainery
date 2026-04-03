from __future__ import annotations

from datetime import datetime
from typing import Protocol

from refainery.models import ConversationRef, ToolInvocation


class ConversationReader(Protocol):
    """Interface that all providers implement."""

    @property
    def provider_name(self) -> str: ...

    def discover_conversations(self, since: datetime | None = None) -> list[ConversationRef]: ...

    def extract_invocations(self, conversation: ConversationRef) -> list[ToolInvocation]: ...


class ProviderRegistry:
    """Holds registered providers and coordinates extraction across them."""

    def __init__(self, providers: list[ConversationReader] | None = None) -> None:
        if providers is None:
            from refainery.providers.claude import ClaudeProvider
            from refainery.providers.cursor import CursorProvider

            providers = []
            claude = ClaudeProvider()
            if claude.detect():
                providers.append(claude)
            cursor = CursorProvider()
            if cursor.detect():
                providers.append(cursor)

        self.providers = providers

    def get_all_invocations(
        self,
        since: datetime | None = None,
        provider_filter: str | None = None,
        skill_filter: str | None = None,
    ) -> list[ToolInvocation]:
        invocations: list[ToolInvocation] = []

        for provider in self.providers:
            if provider_filter and provider.provider_name != provider_filter:
                continue

            conversations = provider.discover_conversations(since=since)
            for conv in conversations:
                conv_invocations = provider.extract_invocations(conv)
                if skill_filter:
                    conv_invocations = [i for i in conv_invocations if i.skill_context == skill_filter]
                invocations.extend(conv_invocations)

        return invocations
