from collections.abc import Iterator
from types import SimpleNamespace, TracebackType
from typing import Self


class FakeMessageStream:
    """Expose raw stream events and the original completed response."""

    def __init__(self, response: object) -> None:
        self.response = response

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    def __iter__(self) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(type="message_start")
        for index, block in enumerate(getattr(self.response, "content")):
            yield SimpleNamespace(type="content_block_start", index=index, content_block=block)
            if block.type == "text":
                for text in (block.text[:2], block.text[2:]):
                    yield SimpleNamespace(
                        type="content_block_delta",
                        index=index,
                        delta=SimpleNamespace(type="text_delta", text=text),
                    )
            elif block.type == "tool_use":
                yield SimpleNamespace(
                    type="content_block_delta",
                    index=index,
                    delta=SimpleNamespace(type="input_json_delta", partial_json='{"input":'),
                )
            elif block.type == "thinking":
                yield SimpleNamespace(
                    type="content_block_delta",
                    index=index,
                    delta=SimpleNamespace(type="thinking_delta", thinking=block.thinking),
                )
            yield SimpleNamespace(type="content_block_stop", index=index)
        yield SimpleNamespace(type="message_stop")

    def get_final_message(self) -> object:
        return self.response
