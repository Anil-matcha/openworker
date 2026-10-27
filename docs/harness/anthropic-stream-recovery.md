# Anthropic output-limit recovery

A token-limited Anthropic response can end in either of these forms:

1. A partial tool-input JSON block closes, followed by `message_delta` with
   `stop_reason: max_tokens`.
2. The final tool block stays open: `message_delta(max_tokens)` arrives without
   a preceding `content_block_stop`.

The second form was observed with a real Claude Sonnet 5 request using a forced
synthetic tool and a 64-token output budget. The response contained incomplete
JSON and no block-stop event. This is metadata evidence, not an assertion about
any earlier failed stream whose contents were not retained.

Previously the decoder rejected incomplete JSON at block close, or rejected an
open block before reading the final stop reason. Both paths produced
`invalid_response` and skipped the runtime's existing output-limit recovery.

The decoder now reads the message outcome before validating block contents.
`max_tokens` and `model_context_window_exceeded` produce `Truncated` even when
there is an unfinished block. The runtime discards that attempt and uses its
existing bounded continuation (at most two consecutive continuations). It does
not append the partial tool to history, queue it, execute it, or invent a result.
Repeated truncation still terminates the turn rather than looping indefinitely.

Successful responses still require closed blocks, complete object-valued tool
JSON, thinking signatures, a valid terminal event, and consistent tool/stop
reason pairing. Missing stream endings and malformed successful responses still
fail closed. Refusals remain safety failures.

Validation includes closed and unclosed truncation fixtures, unsigned partial
thinking, malformed completed tool inputs, interrupted streams, real HTTP SSE,
and an application-level SDK test asserting no partial file write occurs before
recovery. Provider tests pass on macOS and Linux; process-tool integration runs
on Linux. No output budget was increased globally.

Reference: [Anthropic fine-grained tool streaming](https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming).
