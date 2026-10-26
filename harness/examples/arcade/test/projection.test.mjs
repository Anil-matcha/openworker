import test from "node:test";
import assert from "node:assert/strict";
import {
  EventProjection,
  projectMessages,
} from "../build/electron/event-projection.js";
test("display projection deduplicates and separates attempts without reasoning", () => {
  const p = new EventProjection();
  let id = 0;
  const event = (type, data) => ({
    event: { event_id: ++id, type, data },
    summary: null,
  });
  p.consume(event("model_attempt_started", { attempt_id: "a" }));
  const delta = event("assistant_delta", { attempt_id: "a", text: "first" });
  p.consume(delta);
  p.consume(delta);
  assert.equal(p.partial, "first");
  p.consume(event("reasoning_delta", { text: "private" }));
  assert.equal(p.partial, "first");
  p.consume(
    event("model_attempt_finished", { attempt_id: "a", status: "failed" }),
  );
  assert.equal(p.partial, "");
  p.consume(event("model_attempt_started", { attempt_id: "b" }));
  p.consume(event("assistant_delta", { attempt_id: "a", text: "late" }));
  assert.equal(p.partial, "");
  p.consume(event("assistant_delta", { attempt_id: "b", text: "second" }));
  assert.equal(p.partial, "second");
  p.finish("completed");
  assert.equal(p.partial, "");
});
test("canonical transcript shows ordinary text, not tool code, context or reasoning", () => {
  assert.deepEqual(
    projectMessages([
      {
        index: 0,
        item: {
          role: "user",
          content: JSON.stringify({
            arcade_context: { version: 1 },
            user_message: "Make a game",
          }),
        },
      },
      {
        index: 1,
        item: {
          role: "assistant",
          content: [
            { type: "reasoning", text: "secret" },
            { type: "output_text", text: "Ready" },
          ],
        },
      },
      { index: 2, item: { type: "function_call", arguments: "code" } },
      {
        index: 3,
        item: { role: "user", runtime_notice: true, content: "internal" },
      },
    ]),
    [
      { id: "history-0", role: "user", text: "Make a game" },
      { id: "history-1", role: "assistant", text: "Ready" },
    ],
  );
});
