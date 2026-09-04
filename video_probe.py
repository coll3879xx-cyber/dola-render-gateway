"""Video generation probe: Submits video generation within active Dola page session and streams SSE.

Validates that in-page fetch with real browser fingerprint bypasses captcha checks.
SUBMIT_JS contains the core submission payload used by video workers.
"""
import asyncio
import sys

from patchright.async_api import async_playwright

from browser import cookie_value, launch_account_context

SUBMIT_JS = r"""
async ({prompt, ratio, duration, msToken, fp}) => {
  const nowMs = Date.now();
  const nowSec = Math.floor(nowMs / 1000);
  const uuid = () => crypto.randomUUID();
  const videoPrompt = `Generate video: ${prompt}, ${ratio}`;

  const body = {
    client_meta: {
      local_conversation_id: `local_${nowMs}`,
      conversation_id: "",
      bot_id: "7339470689562525703",
      last_section_id: "",
      last_message_index: null,
    },
    messages: [{
      local_message_id: uuid(),
      content_block: [{
        block_type: 10000,
        content: {
          text_block: {text: videoPrompt, icon_url: "", icon_url_dark: "", summary: ""},
          pc_event_block: "",
        },
        block_id: uuid(),
        parent_id: "",
        meta_info: [],
        append_fields: [],
      }],
      message_status: 0,
    }],
    option: {
      send_message_scene: "", create_time_ms: nowMs, collect_id: "",
      is_audio: false, answer_with_suggest: false, tts_switch: false,
      need_deep_think: 0, click_clear_context: false, from_suggest: false,
      is_regen: false, is_replace: false, is_from_click_option: false,
      disable_sse_cache: false, select_text_action: "", is_select_text: false,
      resend_for_regen: false, scene_type: 0, unique_key: uuid(), start_seq: 0,
      need_create_conversation: true,
      conversation_init_option: {need_ack_conversation: true},
      regen_query_id: [], edit_query_id: [], regen_instruction: "",
      no_replace_for_regen: false, message_from: 0, shared_app_name: "", shared_app_id: "",
      sse_recv_event_options: {support_chunk_delta: true},
      is_ai_playground: false, is_old_user: false,
      recovery_option: {is_recovery: false, req_create_time_sec: nowSec, append_sse_event_scene: 0},
      message_storage_type: 0,
    },
    chat_ability: {
      ability_type: 17,
      ability_param: JSON.stringify({ratio, model: "seedance_v2.0", duration}),
    },
    user_context: [],
    ext: {
      fp: fp, use_deep_think: "0", sub_conv_firstmet_type: "1", collection_id: "",
      conversation_init_option: '{"need_ack_conversation":true}',
      commerce_credit_config_enable: "0",
    },
  };

  const params = new URLSearchParams({
    aid: "495671", channel: "g", device_platform: "web", language: "zh-Hant",
    region: "JP", sys_region: "JP", samantha_web: "1", "use-olympus-account": "1",
    version_code: "20800", web_platform: "browser", web_tab_id: uuid(),
  });
  if (msToken) params.set("msToken", msToken);
  if (fp) params.set("fp", fp);

  const resp = await fetch("/chat/completion?" + params.toString(), {
    method: "POST",
    headers: {"Content-Type": "application/json", "agw-js-conv": "str, str", "Accept": "*/*"},
    body: JSON.stringify(body),
    credentials: "include",
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const events = [];
  const errors = [];
  let convId = "";

  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let eventName = "";
      const dataLines = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      const dataStr = dataLines.join("\n");
      events.push({event: eventName, data: dataStr.slice(0, 300)});
      // Preserve risk control events (e.g. captcha 710022004, rate limit 710022002)
      if (dataStr.includes("error_code")) errors.push(dataStr.slice(0, 1000));
      if (eventName === "SSE_ACK") {
        try {
          const d = JSON.parse(dataStr);
          convId = (d.ack_client_meta || {}).conversation_id || "";
        } catch (e) {}
      }
    }
  }
  return {status: resp.status, convId, events: events.slice(0, 8), errors};
}
"""


async def main():
    account = sys.argv[1] if len(sys.argv) > 1 else "acc1"

    async with async_playwright() as p:
        context = await launch_account_context(p, account)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.dola.com/chat", timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        cookies = await context.cookies("https://www.dola.com")
        msToken = cookie_value(cookies, "msToken")
        fp = cookie_value(cookies, "s_v_web_id")
        print(f"msToken: {'Found' if msToken else 'None'}  fp: {fp[:20] if fp else 'None'}...")

        print("Submitting video generation (in-page fetch)...")
        result = await page.evaluate(
            SUBMIT_JS,
            {"prompt": "A cinematic shot of a cat in garden", "ratio": "9:16", "duration": 3, "msToken": msToken, "fp": fp},
        )

        print(f"\nHTTP status: {result['status']}")
        print(f"conversation_id: {result['convId'] or '(not acquired)'}")
        if result["errors"]:
            print("\n=== Errors / Risk Control Events ===")
            for e in result["errors"]:
                print(e)
        print("\n=== SSE Events ===")
        for ev in result["events"]:
            print(f"[{ev['event']}] {ev['data']}")

        await context.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()