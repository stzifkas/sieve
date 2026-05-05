from __future__ import annotations

import json
from html import escape

from sieve.config import OutputFormat
from sieve.core import CompressedOutput, Status


class Formatter:
    def format(self, compressed: CompressedOutput, fmt: OutputFormat) -> str:
        if fmt == OutputFormat.PLAIN:
            return compressed.content

        if fmt == OutputFormat.STRUCTURED:
            return json.dumps(compressed.to_dict(), indent=2)

        if fmt == OutputFormat.XML:
            items = "\n".join(
                f'<item>{escape(item.compressed_repr)}</item>'
                for item in compressed.items
            )
            return (
                f'<tool_result tool="{escape(compressed.tool_type)}" '
                f'status="{escape(compressed.status.value)}">\n'
                f"<summary>{escape(compressed.summary)}</summary>\n"
                f"{items}\n"
                "</tool_result>"
            )

        if fmt == OutputFormat.MINIMAL:
            if compressed.status == Status.SUCCESS:
                return compressed.summary
            item_lines = [item.compressed_repr for item in compressed.items]
            return "\n".join(item_lines) if item_lines else compressed.summary

        return compressed.content
