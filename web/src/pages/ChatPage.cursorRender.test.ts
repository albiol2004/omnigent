import { describe, expect, it } from "vitest";
import type { AnyBlock, BlockContext } from "@/lib/blocks";
import { LIVE_ITEM_PREFIX } from "@/lib/blocks";
import { buildBubbles, createBubbleCache, type Bubble } from "@/lib/renderItems";
import {
  bindConversationForTest,
  handleSessionEvent,
  pumpStreamEvents,
  releaseConversation,
} from "@/store/chatStore";
import { buildPendingBubbles, mergePendingBubbles } from "./ChatPage";

function ctx(itemId: string | null, responseId = "resp_live"): BlockContext {
  return {
    agent: null,
    depth: 0,
    turn: 0,
    timestamp: 0,
    responseId,
    itemId,
  };
}

function liveText(
  messageId = "cursor-live-session-0",
  responseId = "resp_live",
  text = "live preview",
): AnyBlock {
  return {
    type: "text_done",
    ctx: ctx(`${LIVE_ITEM_PREFIX}${messageId}`, responseId),
    fullText: text,
    hasCodeBlocks: false,
  };
}

function pending(id: string) {
  return [
    {
      tempId: id,
      content: [{ type: "input_text" as const, text: id }],
    },
  ];
}

function bubbleIds(bubbles: Bubble[]): string[] {
  return bubbles.map((bubble) => (bubble.kind === "assistant" ? bubble.stableId : bubble.itemId));
}

function assistantText(bubbles: Bubble[]): string {
  return bubbles
    .flatMap((bubble) => (bubble.kind === "assistant" ? bubble.items : []))
    .filter((item) => item.kind === "text")
    .map((item) => item.text)
    .join("\n");
}

interface StreamSink {
  stream: ReadableStream<Uint8Array>;
  push: (frame: string) => void;
  close: () => void;
}

function pushableStream(): StreamSink {
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(nextController) {
      controller = nextController;
    },
  });
  return {
    stream,
    push(frame) {
      controller!.enqueue(encoder.encode(frame));
    },
    close() {
      controller!.close();
    },
  };
}

function sse(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const nextTick = () =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, 0);
  });

describe("ChatPage cursor render ordering", () => {
  it("lifts a pending user above a trailing live preview", () => {
    const committed = buildBubbles(
      [liveText("cursor-live-order-0", "resp_order", "streaming text")],
      null,
      createBubbleCache(),
    );
    const merged = mergePendingBubbles(committed, buildPendingBubbles(pending("pending_1"), null));

    expect(bubbleIds(merged)).toEqual(["pending_1", "resp_order:0"]);
    expect(assistantText(merged)).toContain("streaming text");
  });

  it("keeps a committed user before a live preview followed by a tool", () => {
    const conversationId = "render_splice_order";
    const tool: AnyBlock = {
      type: "tool_group",
      ctx: ctx("tool_1", "resp_order"),
      executions: [
        {
          name: "Read",
          arguments: {},
          argsSummary: "",
          callId: "call_1",
          agentName: "test",
          executedBy: "server",
          output: null,
        },
      ],
      iteration: 0,
    };
    const { get } = bindConversationForTest(conversationId, {
      blocks: [liveText("cursor-live-order-1", "resp_order"), tool],
      pendingUserMessages: pending("pending_1"),
    });

    handleSessionEvent(
      {
        type: "session_input_consumed",
        itemId: "user_1",
        itemType: "message",
        clearedPendingId: "pending_1",
        data: {
          role: "user",
          content: [{ type: "input_text", text: "committed prompt" }],
        },
      },
      conversationId,
    );

    const committed = buildBubbles(get().blocks, get().activeResponse, createBubbleCache());
    const merged = mergePendingBubbles(committed, buildPendingBubbles(pending("pending_2"), null));

    expect(committed.map((bubble) => bubble.kind)).toEqual(["user", "assistant"]);
    expect(bubbleIds(merged)).toEqual(["user_1", "tool_1", "pending_2"]);
    releaseConversation(conversationId);
  });

  it("renders later cursor deltas after the first turn finalizes", async () => {
    const conversationId = "render_cursor_reused_id";
    const { set, get } = bindConversationForTest(conversationId, {
      blocks: [],
      isNativeTerminalSession: true,
    });
    const sink = pushableStream();
    const controller = new AbortController();
    const done = pumpStreamEvents(conversationId, sink.stream, controller, set, get, {
      schedule: (callback) => callback(),
      cancel: () => {},
    });

    sink.push(
      sse("response.created", {
        id: "resp_cursor_1",
        status: "in_progress",
        output: [],
      }),
    );
    sink.push(
      sse("response.output_text.delta", {
        message_id: "cursor-live-reused",
        index: 0,
        delta: "first turn",
      }),
    );
    await nextTick();
    sink.push(
      sse("response.completed", {
        id: "resp_cursor_1",
        status: "completed",
        output: [],
      }),
    );
    await nextTick();
    sink.push(
      sse("response.output_text.delta", {
        message_id: "cursor-live-reused",
        index: 1,
        delta: "second turn",
      }),
    );
    await nextTick();

    const bubbles = buildBubbles(get().blocks, get().activeResponse, createBubbleCache());
    const merged = mergePendingBubbles(bubbles, []);
    expect(assistantText(merged)).toContain("first turn");
    expect(assistantText(merged)).toContain("second turn");
    const liveIds = get()
      .blocks.filter(
        (block) =>
          block.type === "text_done" && block.ctx.itemId?.startsWith(LIVE_ITEM_PREFIX) === true,
      )
      .map((block) => block.ctx.itemId);
    expect(liveIds).toEqual([`${LIVE_ITEM_PREFIX}cursor-live-reused`]);

    sink.push("data: [DONE]\n\n");
    sink.close();
    await done;
    controller.abort();
    releaseConversation(conversationId);
  });

  it("keeps live assistant text when response_end has no replacement", async () => {
    const conversationId = "render_response_end_preview";
    const { set, get } = bindConversationForTest(conversationId, {
      blocks: [],
      isNativeTerminalSession: true,
    });
    const sink = pushableStream();
    const controller = new AbortController();
    const done = pumpStreamEvents(conversationId, sink.stream, controller, set, get, {
      schedule: (callback) => callback(),
      cancel: () => {},
    });

    sink.push(
      sse("response.created", {
        id: "resp_preview",
        status: "in_progress",
        output: [],
      }),
    );
    sink.push(
      sse("response.output_text.delta", {
        message_id: "cursor-live-unreplaced",
        index: 0,
        delta: "text that must remain",
      }),
    );
    await nextTick();
    sink.push(
      sse("response.completed", {
        id: "resp_preview",
        status: "completed",
        output: [],
      }),
    );
    await nextTick();

    const bubbles = buildBubbles(get().blocks, get().activeResponse, createBubbleCache());
    const merged = mergePendingBubbles(bubbles, []);
    expect(assistantText(merged)).toContain("text that must remain");

    sink.push("data: [DONE]\n\n");
    sink.close();
    await done;
    controller.abort();
    releaseConversation(conversationId);
  });
});
