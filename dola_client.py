"""Dola API Client Module: Handles chat, image recognition, and video generation protocols."""

import asyncio
import binascii
import hashlib
import hmac
import json
import re
import time
import uuid as uuid_lib
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

import aiohttp

# ============ Constants ============

DOLA_AID = "495671"
DOLA_BOT_ID = "7339470689562525703"
VERSION_CODE = "20800"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "Accept-Language": "en,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Origin": "https://www.dola.com",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

# Insufficient credit keywords (multi-language)
CREDIT_FAIL_PATTERN = re.compile(
    r"無法生成|无法生成|不能生成|无法完成|無法完成|"
    r"余额不足|餘額不足|额度不足|額度不足|额度耗尽|額度耗盡|"
    r"生成できません|残高不足|"
    r"生成할 수 없|한도.*부족|부족.*한도|"
    r"insufficient|unable to (generate|create)|failed to (generate|create)",
    re.IGNORECASE,
)


# ============ Helpers ============

def parse_cookie(cookie: str) -> dict:
    """Extracts required Dola parameters from cookie."""
    def extract(key):
        m = re.search(key + r"=([^;]+)", cookie or "")
        return m.group(1) if m else ""
    return {
        "msToken": extract("msToken"),
        "fp": extract("s_v_web_id"),
        "sessionid": extract("sessionid"),
    }


def uuid() -> str:
    return str(uuid_lib.uuid4())


def crc32_hex(data: bytes) -> str:
    """CRC32 hexadecimal string for Volcano ImageX PUT TOS."""
    return format(binascii.crc32(data) & 0xFFFFFFFF, "x")


def aws4_sign(method: str, url: str, ak: str, sk: str, sts: str) -> dict:
    """AWS4-HMAC-SHA256 signature for Volcano ImageX ApplyImageUpload."""
    from urllib.parse import urlparse, parse_qsl
    u = urlparse(url)
    now = datetime.now(timezone.utc)
    date = now.strftime("%Y%m%dT%H%M%SZ")
    date_short = date[:8]

    # canonical query
    params = sorted(parse_qsl(u.query, keep_blank_values=True))
    canonical_query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in params)

    canonical_headers = f"x-amz-date:{date}\nx-amz-security-token:{sts}\n"
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_request = "\n".join([
        method, u.path, canonical_query, canonical_headers,
        "x-amz-date;x-amz-security-token", payload_hash
    ])
    scope = f"{date_short}/us-east-1/imagex/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest()
    ])

    k_date = hmac.new(("AWS4" + sk).encode(), date_short.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, b"us-east-1", hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"imagex", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return {
        "Authorization": f"AWS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders=x-amz-date;x-amz-security-token, Signature={signature}",
        "x-amz-date": date,
        "x-amz-security-token": sts,
    }


def _find_url_in_data(data, *keywords) -> str:
    """递归遍历数据结构（dict/list/str），找包含所有关键词的 http URL。
    比从 json.dumps 字符串正则提取更可靠（不会有转义残留）。"""
    if isinstance(data, str):
        if all(kw in data for kw in keywords) and data.startswith("http"):
            return data
        # Strings may contain embedded JSON or URLs
        for m in re.finditer(r"https?://[^\s\"'\\]+", data):
            url = m.group(0)
            if all(kw in url for kw in keywords):
                return url
    elif isinstance(data, dict):
        for v in data.values():
            found = _find_url_in_data(v, *keywords)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_url_in_data(item, *keywords)
            if found:
                return found
    return ""


def build_query_params(cookie: str, extra: dict = None) -> dict:
    """Builds common Dola API URL parameters."""
    info = parse_cookie(cookie)
    params = {
        "aid": DOLA_AID,
        "channel": "g",
        "device_platform": "web",
        "language": "zh-Hant",
        "region": "JP",
        "sys_region": "JP",
        "samantha_web": "1",
        "use-olympus-account": "1",
        "version_code": VERSION_CODE,
        "web_platform": "browser",
        "web_tab_id": uuid(),
    }
    if info["msToken"]:
        params["msToken"] = info["msToken"]
    if info["fp"]:
        params["fp"] = info["fp"]
    if extra:
        params.update(extra)
    return params


# ============ DolaClient ============

class DolaClient:
    """Dola API Client instance."""

    def __init__(self, cookie: str, api_base: str = "https://www.dola.com"):
        self.cookie = cookie
        self.api_base = api_base
        self.info = parse_cookie(cookie)

    @property
    def is_valid(self) -> bool:
        return bool(self.info["sessionid"])

    # ===== Common Requests =====

    async def _request_chat_completion(self, session: aiohttp.ClientSession, body: dict, timeout: int = 300) -> aiohttp.ClientResponse:
        """POST /chat/completion (SSE stream). Caller must close."""
        url = f"{self.api_base}/chat/completion"
        headers = {
            **FAKE_HEADERS,
            "Cookie": self.cookie,
            "Content-Type": "application/json",
            "agw-js-conv": "str, str",
            "Referer": f"{self.api_base}/chat/",
        }
        params = build_query_params(self.cookie)
        return await session.post(
            url, params=params, json=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout)
        )

    async def _request_im_chain(self, session: aiohttp.ClientSession, body: dict, conversation_id: str = "", timeout: int = 15) -> dict:
        """POST /im/chain/single（轮询用，非流式），直接返回 JSON
        注意：Content-Type 要带 encoding=utf-8，agw-js-conv 用 str（不是 str, str）
        """
        url = f"{self.api_base}/im/chain/single"
        headers = {
            **FAKE_HEADERS,
            "Cookie": self.cookie,
            "Content-Type": "application/json; encoding=utf-8",
            "agw-js-conv": "str",
            "Referer": f"{self.api_base}/chat/{conversation_id}" if conversation_id else f"{self.api_base}/chat/",
        }
        params = build_query_params(self.cookie)
        async with session.post(
            url, params=params, json=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            return await resp.json(content_type=None)

    # ===== SSE Parsing =====

    async def _read_sse_stream(self, resp: aiohttp.ClientResponse) -> list:
        """Reads SSE stream and returns all events."""
        events = []
        buffer = ""
        async for chunk in resp.content:
            buffer += chunk.decode("utf-8", errors="replace")
            # SSE events separated by \n\n
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                event_name = ""
                data_lines = []
                for line in raw_event.split("\n"):
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                data_str = "\n".join(data_lines)
                try:
                    data = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    data = {"_raw": data_str}
                events.append((event_name, data))
        return events

    @staticmethod
    def _extract_text(event_data: dict) -> str:
        """Extracts text delta from SSE event."""
        # STREAM_MSG_NOTIFY: first token
        content = event_data.get("content", {})
        if isinstance(content, dict) and content.get("content_block"):
            for block in content["content_block"]:
                if block.get("content", {}).get("thinking_block", {}).get("text"):
                    return block["content"]["thinking_block"]["text"]
                if block.get("content", {}).get("text_block", {}).get("text"):
                    return block["content"]["text_block"]["text"]
        # STREAM_CHUNK: subsequent delta
        text = ""
        if event_data.get("patch_op"):
            for op in event_data["patch_op"]:
                blocks = (op.get("patch_value") or {}).get("content_block") or []
                if isinstance(blocks, list):
                    for block in blocks:
                        c = block.get("content", {})
                        if c.get("thinking_block", {}).get("text"):
                            text += c["thinking_block"]["text"]
                        if c.get("text_block", {}).get("text"):
                            text += c["text_block"]["text"]
        return text

    # ===== Chat =====

    async def chat(self, messages: list, deep_think: bool = False) -> str:
        """Chat completion, returns full text."""
        body = self._build_chat_body(messages, deep_think)
        async with aiohttp.ClientSession(trust_env=True) as session:
            resp = await self._request_chat_completion(session, body)
            async with resp:
                events = await self._read_sse_stream(resp)
        full_text = ""
        for event_name, data in events:
            if event_name in ("SSE_HEARTBEAT", "FULL_MSG_NOTIFY", "DOWNLINK_CMD", "SSE_REPLY_END"):
                continue
            text = self._extract_text(data)
            if text:
                full_text += text
        return full_text

    async def chat_stream(self, messages: list, deep_think: bool = False):
        """Streaming chat completion, yields text deltas."""
        body = self._build_chat_body(messages, deep_think)
        async with aiohttp.ClientSession(trust_env=True) as session:
            resp = await self._request_chat_completion(session, body)
            async with resp:
                buffer = ""
                async for chunk in resp.content:
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n\n" in buffer:
                        raw_event, buffer = buffer.split("\n\n", 1)
                        event_name = ""
                        data_lines = []
                        for line in raw_event.split("\n"):
                            if line.startswith("event:"):
                                event_name = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].strip())
                        data_str = "\n".join(data_lines)
                        try:
                            data = json.loads(data_str) if data_str else {}
                        except json.JSONDecodeError:
                            continue
                        if event_name in ("SSE_HEARTBEAT", "FULL_MSG_NOTIFY", "DOWNLINK_CMD", "SSE_REPLY_END"):
                            continue
                        text = self._extract_text(data)
                        if text:
                            yield text

    def _build_chat_body(self, messages: list, deep_think: bool = False) -> dict:
        """Builds chat completion request body."""
        now_ms = int(time.time() * 1000)
        now_sec = now_ms // 1000

        # Merge multi-turn dialogue into single text
        combined = []
        for msg in messages:
            role = "Assistant" if msg.get("role") == "assistant" else "User"
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
            combined.append(f"{role}: {content}")
        combined_text = "\n".join(combined).strip()

        return {
            "client_meta": {
                "local_conversation_id": f"local_{now_ms}",
                "conversation_id": "",
                "bot_id": DOLA_BOT_ID,
                "last_section_id": "",
                "last_message_index": None,
            },
            "messages": [{
                "local_message_id": uuid(),
                "content_block": [{
                    "block_type": 10000,
                    "content": {
                        "text_block": {
                            "text": combined_text,
                            "icon_url": "",
                            "icon_url_dark": "",
                            "summary": "",
                        },
                        "pc_event_block": "",
                    },
                    "block_id": uuid(),
                    "parent_id": "",
                    "meta_info": [],
                    "append_fields": [],
                }],
                "message_status": 0,
            }],
            "option": {
                "create_time_ms": now_ms,
                "need_create_conversation": True,
                "conversation_init_option": {"need_ack_conversation": True},
                "unique_key": uuid(),
                "recovery_option": {
                    "is_recovery": False,
                    "req_create_time_sec": now_sec,
                    "append_sse_event_scene": 0,
                },
                "need_deep_think": 1 if deep_think else 0,
                "is_user_chat_input": True,
                "sse_recv_event_options": {"support_chunk_delta": True},
                "is_old_user": False,
                "send_message_scene": "",
                "collect_id": "",
                "is_audio": False,
                "answer_with_suggest": False,
                "tts_switch": False,
                "message_from": 0,
            },
            "chat_ability": {"ability_type": 0},
            "user_context": [],
            "ext": {
                "fp": self.info["fp"],
                "use_deep_think": "1" if deep_think else "0",
                "sub_conv_firstmet_type": "1",
                "conversation_init_option": '{"need_ack_conversation":true}',
                "commerce_credit_config_enable": "0",
            },
        }

    # ===== Image Upload =====

    async def upload_image(self, image_input: str) -> str:
        """完整上传链路：prepare_upload → ApplyImageUpload → PUT TOS → 返回 StoreUri
        接受 base64 / http URL / 已有 uri
        """
        # 1) Get image binary
        if image_input.startswith("tos-mya-i-"):
            return image_input  # Already a TOS uri
        image_buf = await self._fetch_image(image_input)

        # 2. prepare_upload for STS
        prep_url = f"{self.api_base}/alice/resource/prepare_upload"
        prep_params = build_query_params(self.cookie, {
            "device_id": "7655726059970627125",
            "pc_version": "3.23.10",
            "pkg_type": "release_version",
            "real_aid": DOLA_AID,
            "tea_uuid": "7655726485928068629",
            "web_id": "7655726485928068629",
        })
        prep_headers = {
            **FAKE_HEADERS,
            "Cookie": self.cookie,
            "Content-Type": "application/json",
            "agw-js-conv": "str, str",
            "Referer": f"{self.api_base}/chat/",
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                prep_url, params=prep_params,
                json={"tenant_id": "5", "scene_id": "4", "resource_type": 2},
                headers=prep_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as p1:
                p1_data = await p1.json(content_type=None)
        if p1_data.get("code") != 0:
            raise Exception(f"prepare_upload failed: {json.dumps(p1_data)[:100]}")

        sts_info = p1_data["data"]
        service_id = sts_info["service_id"]
        upload_host = sts_info["upload_host"]
        auth = sts_info["upload_auth_token"]
        ak, sk, sts_token = auth["access_key"], auth["secret_key"], auth["session_token"]

        # 3. ApplyImageUpload (AWS4 signature)
        apply_url = (
            f"https://{upload_host}/?Action=ApplyImageUpload&Version=2018-08-01"
            f"&ServiceId={service_id}&FileSize={len(image_buf)}&FileExtension=.png"
        )
        sig = aws4_sign("GET", apply_url, ak, sk, sts_token)
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(apply_url, headers=sig, timeout=aiohttp.ClientTimeout(total=15)) as p2:
                p2_data = await p2.json(content_type=None)
        if p2_data.get("ResponseMetadata", {}).get("Error"):
            raise Exception(f"ApplyImageUpload failed: {p2_data['ResponseMetadata']['Error']['Message']}")

        store_info = p2_data["Result"]["UploadAddress"]["StoreInfos"][0]
        store_uri = store_info["StoreUri"]
        tos_host = p2_data["Result"]["UploadAddress"]["UploadHosts"][0]

        # 4. PUT TOS
        crc = crc32_hex(image_buf)
        tos_url = f"https://{tos_host}/{store_uri}"
        tos_headers = {
            "Authorization": store_info["Auth"],
            "Content-Type": "application/octet-stream",
            "content-crc32": crc,
            "x-storage-u": "7655722254806270981",
            "Content-Disposition": 'attachment; filename="image.png"',
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.put(tos_url, data=image_buf, headers=tos_headers,
                                   timeout=aiohttp.ClientTimeout(total=30)) as p3:
                p3_data = await p3.json(content_type=None)
        if p3_data.get("success") not in (0, None) and p3_data.get("code"):
            raise Exception(f"PUT TOS failed: {json.dumps(p3_data)[:100]}")

        return store_uri

    async def _fetch_image(self, image_input: str) -> bytes:
        """Downloads image: supports HTTP URL or base64."""
        if image_input.startswith("http"):
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(image_input, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    return await r.read()
        # base64 (optional data: prefix)
        b64 = re.sub(r"^data:[^;]+;base64,", "", image_input)
        import base64
        return base64.b64decode(b64)

    # ===== Image Recognition =====

    async def vision(self, image_input: str, prompt: str) -> str:
        """Image recognition: upload + block_type:10052 + chat."""
        image_uri = await self.upload_image(image_input)
        body = self._build_vision_body(image_uri, prompt)
        async with aiohttp.ClientSession(trust_env=True) as session:
            resp = await self._request_chat_completion(session, body, timeout=120)
            async with resp:
                events = await self._read_sse_stream(resp)
        full_text = ""
        for event_name, data in events:
            if event_name in ("SSE_HEARTBEAT", "FULL_MSG_NOTIFY", "DOWNLINK_CMD", "SSE_REPLY_END"):
                continue
            text = self._extract_text(data)
            if text:
                full_text += text
        return full_text

    def _build_vision_body(self, image_uri: str, prompt: str) -> dict:
        """Builds image recognition request body."""
        now_ms = int(time.time() * 1000)
        now_sec = now_ms // 1000
        att_id = uuid()

        image_msg = {
            "local_message_id": uuid(),
            "content_block": [{
                "block_type": 10052,
                "content": {
                    "attachment_block": {
                        "attachments": [{
                            "type": 1,
                            "identifier": att_id,
                            "image": {
                                "name": "image.png",
                                "uri": image_uri,
                                "image_ori": {"url": "", "width": 1024, "height": 1024, "format": "", "url_formats": {}},
                            },
                            "parse_state": 0,
                            "review_state": 1,
                            "upload_status": 1,
                            "progress": 100,
                            "src": "",
                        }],
                    },
                    "pc_event_block": "",
                },
                "block_id": uuid(),
                "parent_id": "",
                "meta_info": [],
                "append_fields": [],
            }],
            "message_status": 0,
        }
        text_msg = {
            "local_message_id": uuid(),
            "content_block": [{
                "block_type": 10000,
                "content": {
                    "text_block": {"text": prompt, "icon_url": "", "icon_url_dark": "", "summary": ""},
                    "pc_event_block": "",
                },
                "block_id": uuid(),
                "parent_id": "",
                "meta_info": [],
                "append_fields": [],
            }],
            "message_status": 0,
        }
        return {
            "client_meta": {
                "local_conversation_id": f"local_{now_ms}",
                "conversation_id": "",
                "bot_id": DOLA_BOT_ID,
                "last_section_id": "",
                "last_message_index": None,
            },
            "messages": [image_msg, text_msg],
            "option": {
                "send_message_scene": "",
                "create_time_ms": now_ms,
                "collect_id": "",
                "is_audio": False,
                "answer_with_suggest": False,
                "tts_switch": False,
                "need_deep_think": 0,
                "click_clear_context": False,
                "from_suggest": False,
                "is_regen": False,
                "is_replace": False,
                "is_from_click_option": False,
                "disable_sse_cache": False,
                "select_text_action": "",
                "is_select_text": False,
                "resend_for_regen": False,
                "scene_type": 0,
                "unique_key": uuid(),
                "start_seq": 0,
                "need_create_conversation": True,
                "conversation_init_option": {"need_ack_conversation": True},
                "regen_query_id": [],
                "edit_query_id": [],
                "regen_instruction": "",
                "no_replace_for_regen": False,
                "message_from": 0,
                "shared_app_name": "",
                "shared_app_id": "",
                "sse_recv_event_options": {"support_chunk_delta": True},
                "is_ai_playground": False,
                "is_old_user": False,
                "recovery_option": {"is_recovery": False, "req_create_time_sec": now_sec, "append_sse_event_scene": 0},
                "message_storage_type": 0,
            },
            "chat_ability": {"ability_type": 0},
            "user_context": [],
            "ext": {
                "fp": self.info["fp"],
                "use_deep_think": "0",
                "sub_conv_firstmet_type": "1",
                "collection_id": "",
                "conversation_init_option": '{"need_ack_conversation":true}',
                "commerce_credit_config_enable": "0",
            },
        }

    # ===== Text-to-Image =====

    async def generate_image(self, prompt: str, ratio: str = "1:1", style: str = "auto") -> str:
        """Text-to-Image generation, returns image URL."""
        body = self._build_image_body(prompt, ratio, style)
        async with aiohttp.ClientSession(trust_env=True) as session:
            resp = await self._request_chat_completion(session, body, timeout=60)
            async with resp:
                events = await self._read_sse_stream(resp)

        conv_id = ""
        image_url = ""
        for event_name, data in events:
            if event_name == "SSE_ACK":
                conv_id = (data.get("ack_client_meta") or {}).get("conversation_id", "")
            # Recursive search for image URLs
            found = _find_url_in_data(data, "ibyteimg", "image_raw")
            if found:
                image_url = found

        if image_url:
            return image_url

        # Poll for image
        if conv_id:
            return await self._poll_image(conv_id)
        raise Exception("Image generation: failed to acquire conversation_id")

    def _build_image_body(self, prompt: str, ratio: str, style: str) -> dict:
        now_ms = int(time.time() * 1000)
        return {
            "client_meta": {
                "local_conversation_id": f"local_{now_ms}",
                "conversation_id": "",
                "bot_id": DOLA_BOT_ID,
                "last_section_id": "",
                "last_message_index": None,
            },
            "messages": [{
                "local_message_id": uuid(),
                "content_block": [{
                    "block_type": 10000,
                    "content": {
                        "text_block": {
                            "text": f"帮我生成图片：{prompt}\n风格：{style}\n比例：{ratio}",
                            "icon_url": "", "icon_url_dark": "", "summary": "",
                        },
                        "pc_event_block": "",
                    },
                    "block_id": uuid(),
                    "parent_id": "",
                    "meta_info": [],
                    "append_fields": [],
                }],
                "message_status": 0,
            }],
            "option": {
                "create_time_ms": now_ms,
                "need_create_conversation": True,
                "conversation_init_option": {"need_ack_conversation": True},
                "override_ability_config_path": "",
                "is_user_chat_input": True,
                "sse_recv_event_options": {"support_chunk_delta": True},
                "is_old_user": False,
            },
            "chat_ability": {"ability_type": 16, "ability_param": "{}"},
            "user_context": [],
            "ext": {
                "fp": self.info["fp"],
                "use_deep_think": "0",
                "sub_conv_firstmet_type": "1",
                "conversation_init_option": '{"need_ack_conversation":true}',
                "commerce_credit_config_enable": "0",
            },
        }

    async def _poll_image(self, conversation_id: str, timeout: int = 120) -> str:
        """Polls /im/chain/single for image generation."""
        start = time.time()
        attempt = 0
        async with aiohttp.ClientSession(trust_env=True) as session:
            while time.time() - start < timeout:
                await asyncio.sleep(2)
                attempt += 1
                try:
                    body = {"cmd": 3100, "conversation_id": conversation_id, "anchor_index": 0, "direction": 1, "limit": 20}
                    data = await self._request_im_chain(session, body, conversation_id)
                    messages = (data.get("data") or {}).get("messages") or data.get("messages") or []
                    for msg in messages:
                        blocks = msg.get("content") or msg.get("content_block") or []
                        if isinstance(blocks, str):
                            try:
                                blocks = json.loads(blocks)
                            except json.JSONDecodeError:
                                continue
                        for block in blocks:
                            if block.get("block_type") != 2074:
                                continue
                            creations = (block.get("content") or {}).get("creation_block", {}).get("creations", [])
                            for cre in creations:
                                img = cre.get("image", {})
                                for key in ("image_raw", "image_ori"):
                                    url = (img.get(key) or {}).get("url", "")
                                    if url:
                                        return url
                                # Fallback search for image URL
                                found = _find_url_in_data(cre, "ibyteimg")
                                if found:
                                    return found
                except Exception:
                    pass
        raise Exception("Image generation timeout")

    # ===== Video Generation =====

    async def generate_video(self, prompt: str, ratio: str = "9:16", duration: int = 5, timeout: int = 300) -> str:
        """Video generation, returns video download URL."""
        body = self._build_video_body(prompt, ratio, duration)
        async with aiohttp.ClientSession(trust_env=True) as session:
            resp = await self._request_chat_completion(session, body, timeout=120)
            async with resp:
                events = await self._read_sse_stream(resp)

        conv_id = ""
        for event_name, data in events:
            if event_name == "SSE_ACK":
                conv_id = (data.get("ack_client_meta") or {}).get("conversation_id", "")

        if not conv_id:
            raise Exception("Video accepted but no conversation_id returned")

        # Poll for video
        return await self._poll_video(conv_id, timeout)

    def _build_video_body(self, prompt: str, ratio: str, duration: int) -> dict:
        now_ms = int(time.time() * 1000)
        now_sec = now_ms // 1000
        # Video prompt trigger prefix
        video_prompt = f"生成影片：{prompt}，{ratio}"
        return {
            "client_meta": {
                "local_conversation_id": f"local_{now_ms}",
                "conversation_id": "",
                "bot_id": DOLA_BOT_ID,
                "last_section_id": "",
                "last_message_index": None,
            },
            "messages": [{
                "local_message_id": uuid(),
                "content_block": [{
                    "block_type": 10000,
                    "content": {
                        "text_block": {"text": video_prompt, "icon_url": "", "icon_url_dark": "", "summary": ""},
                        "pc_event_block": "",
                    },
                    "block_id": uuid(),
                    "parent_id": "",
                    "meta_info": [],
                    "append_fields": [],
                }],
                "message_status": 0,
            }],
            "option": {
                "send_message_scene": "",
                "create_time_ms": now_ms,
                "collect_id": "",
                "is_audio": False,
                "answer_with_suggest": False,
                "tts_switch": False,
                "need_deep_think": 0,
                "click_clear_context": False,
                "from_suggest": False,
                "is_regen": False,
                "is_replace": False,
                "is_from_click_option": False,
                "disable_sse_cache": False,
                "select_text_action": "",
                "is_select_text": False,
                "resend_for_regen": False,
                "scene_type": 0,
                "unique_key": uuid(),
                "start_seq": 0,
                "need_create_conversation": True,
                "conversation_init_option": {"need_ack_conversation": True},
                "regen_query_id": [],
                "edit_query_id": [],
                "regen_instruction": "",
                "no_replace_for_regen": False,
                "message_from": 0,
                "shared_app_name": "",
                "shared_app_id": "",
                "sse_recv_event_options": {"support_chunk_delta": True},
                "is_ai_playground": False,
                "is_old_user": False,
                "recovery_option": {"is_recovery": False, "req_create_time_sec": now_sec, "append_sse_event_scene": 0},
                "message_storage_type": 0,
            },
            "chat_ability": {
                "ability_type": 17,
                "ability_param": json.dumps({"ratio": ratio, "model": "seedance_v2.0", "duration": duration}),
            },
            "user_context": [],
            "ext": {
                "fp": self.info["fp"],
                "use_deep_think": "0",
                "sub_conv_firstmet_type": "1",
                "collection_id": "",
                "conversation_init_option": '{"need_ack_conversation":true}',
                "commerce_credit_config_enable": "0",
            },
        }

    async def _poll_video(self, conversation_id: str, timeout: int = 300) -> str:
        """Polls /im/chain/single for video, checking quota limits."""
        start = time.time()
        attempt = 0
        async with aiohttp.ClientSession(trust_env=True) as session:
            while time.time() - start < timeout:
                await asyncio.sleep(5)
                attempt += 1
                try:
                    body = {
                        "cmd": 3100,
                        "conversation_id": conversation_id,
                        "anchor_index": 0,
                        "direction": 1,
                        "limit": 20,
                    }
                    data = await self._request_im_chain(session, body, conversation_id)
                    dl_body = data.get("downlink_body") or {}
                    messages = (dl_body.get("pull_singe_chain_downlink_body") or {}).get("messages") or []

                    for msg in messages:
                        content = msg.get("content")
                        if isinstance(content, str):
                            try:
                                content = json.loads(content)
                            except json.JSONDecodeError:
                                continue
                        if not isinstance(content, list):
                            continue

                        for block in content:
                            # Check for quota limit text
                            block_text = (block.get("content") or {}).get("text_block", {}).get("text", "")
                            if block_text and CREDIT_FAIL_PATTERN.search(block_text):
                                raise CreditError(f"Insufficient quota: {block_text[:60]}")

                            # Check for video output (block_type=2074, type=2)
                            if block.get("block_type") != 2074:
                                continue
                            creations = (block.get("content") or {}).get("creation_block", {}).get("creations") or []
                            for cre in creations:
                                if cre.get("type") != 2:
                                    continue
                                url = (cre.get("video") or {}).get("download_url", "")
                                if url and url.startswith("http"):
                                    return url
                except CreditError:
                    raise
                except Exception:
                    pass
        raise Exception("Video generation timeout")


class CreditError(Exception):
    """Insufficient quota, rotate account without retrying."""
    pass


# ============ Multi-Account Rotation ============

class DolaPool:
    """Multi-cookie rotation pool with quota detection."""

    def __init__(self, cookies: list, api_base: str = "https://www.dola.com",
                 video_timeout: int = 300, image_timeout: int = 120, max_retry: int = 2):
        self.clients = []
        for c in cookies:
            try:
                client = create_client(c, api_base)
                if client.is_valid:
                    self.clients.append(client)
            except Exception:
                pass
        self.video_timeout = video_timeout
        self.image_timeout = image_timeout
        self.max_retry = max_retry

    @property
    def available(self) -> bool:
        return len(self.clients) > 0

    async def run_with_pool(self, fn_name: str, *args, **kwargs):
        """Shuffles cookie pool, rotating accounts on quota limits."""
        import random
        clients = self.clients[:]
        random.shuffle(clients)
        last_err = None
        for client in clients:
            for retry in range(self.max_retry + 1):
                try:
                    fn = getattr(client, fn_name)
                    return await fn(*args, **kwargs)
                except CreditError as e:
                    last_err = e
                    break  # Insufficient quota, rotate account
                except Exception as e:
                    last_err = e
                    if retry < self.max_retry:
                        await asyncio.sleep(3)
                        continue
                    break  # Retries exhausted, rotate account
        raise last_err or Exception("No available cookies")

    # Convenience methods
    async def chat(self, messages, **kw):
        return await self.run_with_pool("chat", messages, **kw)

    async def chat_stream(self, messages, **kw):
        """Streaming chat using first available cookie."""
        import random
        clients = self.clients[:]
        random.shuffle(clients)
        for client in clients:
            try:
                async for chunk in client.chat_stream(messages, **kw):
                    yield chunk
                return
            except Exception:
                continue
        raise Exception("All cookies failed")

    async def vision(self, image_input, prompt):
        return await self.run_with_pool("vision", image_input, prompt)

    async def generate_image(self, prompt, ratio="1:1", style="auto"):
        return await self.run_with_pool("generate_image", prompt, ratio, style)

    async def generate_video(self, prompt, ratio="9:16", duration=5):
        return await self.run_with_pool(
            "generate_video", prompt, ratio, duration,
            timeout=self.video_timeout
        )


# ============ Domestic Engine (doubao.com) ============

CN_DOMAIN = "www.doubao.com"
CN_DEFAULT_ASSISTANT_ID = "497858"
CN_PC_VERSION = "2.44.0"

CN_FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Last-event-id": "undefined",
    "Origin": "https://www.doubao.com",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Referer": "https://www.doubao.com",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def _fake_ms_token() -> str:
    """Generates pseudo msToken."""
    import base64
    import os
    return base64.urlsafe_b64encode(os.urandom(96)).rstrip(b"=").decode()


def _fake_a_bogus() -> str:
    """Generates pseudo a_bogus."""
    import random
    import string
    part1 = "".join(random.choices(string.ascii_letters + string.digits, k=34))
    part2 = "".join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"mf-{part1}-{part2}"


def _random_numeric(length: int) -> str:
    import random
    return "".join(random.choices("0123456789", k=length))


class DoubaoCNClient:
    """Doubao Client: Chat, image recognition, and image generation."""

    def __init__(self, token: str):
        self.token = token  # sessionid
        self.cookie = f"sessionid={token}; sessionid_ss={token}"
        self.device_id = "7" + _random_numeric(18)
        self.web_id = "7" + _random_numeric(18)

    @property
    def is_valid(self) -> bool:
        return bool(self.token) and len(self.token) >= 20

    @staticmethod
    def _extract_cn_text(events: list) -> str:
        """Extracts text delta from domestic SSE events."""
        full_text = ""
        for event_name, data in events:
            event_type = data.get("event_type")
            event_data_str = data.get("event_data", "")
            if event_type == 2005:
                try:
                    err = json.loads(event_data_str)
                    raise Exception(f"Domestic engine error: {err.get('code')} {err.get('message', '')[:60]}")
                except json.JSONDecodeError:
                    pass
                continue
            if event_type == 2003:
                continue
            if event_type != 2001:
                continue
            try:
                result = json.loads(event_data_str)
            except json.JSONDecodeError:
                continue
            message = result.get("message", "")
            text = ""
            if isinstance(message, str):
                text = message
            elif isinstance(message, dict):
                if isinstance(message.get("text"), str):
                    text = message["text"]
                elif isinstance(message.get("delta"), dict) and isinstance(message["delta"].get("text"), str):
                    text = message["delta"]["text"]
            if text:
                full_text += text
        return full_text

    def _build_params(self, extra: dict = None) -> dict:
        params = {
            "aid": CN_DEFAULT_ASSISTANT_ID,
            "device_id": self.device_id,
            "device_platform": "web",
            "language": "zh",
            "pc_version": CN_PC_VERSION,
            "pkg_type": "release_version",
            "real_aid": CN_DEFAULT_ASSISTANT_ID,
            "region": "CN",
            "samantha_web": 1,
            "sys_region": "CN",
            "tea_uuid": self.web_id,
            "use-olympus-account": 1,
            "version_code": VERSION_CODE,
            "web_id": self.web_id,
            "web_tab_id": str(uuid_lib.uuid4()),
        }
        if extra:
            params.update(extra)
        return params

    def _build_headers(self, referer: str = None) -> dict:
        """Builds domestic request headers."""
        u = str(uuid_lib.uuid4())
        return {
            **CN_FAKE_HEADERS,
            "Cookie": self.cookie,
            "X-Flow-Trace": f"04-{u}-{u[:16]}-01",
            "Referer": referer or f"https://{CN_DOMAIN}/chat/",
        }

    def _messages_to_text(self, messages: list) -> str:
        """Merges multi-turn dialogue into format string."""
        if len(messages) < 2:
            # Single message passthrough
            parts = []
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
                parts.append(content)
            return "\n".join(parts)

        result = ""
        for msg in messages:
            role = msg.get("role", "user")
            role_tag = {"system": "<|im_start|>system", "assistant": "<|im_start|>assistant", "user": "<|im_start|>user"}.get(role, "<|im_start|>user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = "\n".join(text_parts)
            result += f"{role_tag}\n{content}\n<|im_end|>\n"
        return result

    async def chat(self, messages: list, deep_think: bool = False) -> str:
        """Domestic chat completion."""
        body = {
            "messages": [{
                "content": json.dumps({"text": self._messages_to_text(messages)}),
                "content_type": 2001,
                "attachments": [],
                "references": [],
            }],
            "completion_option": {
                "is_regen": False,
                "with_suggest": True,
                "need_create_conversation": True,
                "launch_stage": 1,
                "is_replace": False,
                "is_delete": False,
                "message_from": 0,
                "action_bar_skill_id": 0,
                "use_deep_think": deep_think,
                "use_auto_cot": False,
                "resend_for_regen": False,
                "enable_commerce_credit": False,
                "event_id": "0",
            },
            "evaluate_option": {"web_ab_params": ""},
            "section_id": "26" + _random_numeric(16),
            "conversation_id": "0",
            "local_conversation_id": "local_16" + _random_numeric(14),
            "local_message_id": str(uuid_lib.uuid4()),
        }
        url = f"https://{CN_DOMAIN}/samantha/chat/completion"
        headers = {**self._build_headers(), "agw-js-conv": "str, str"}
        params = self._build_params({"msToken": _fake_ms_token(), "a_bogus": _fake_a_bogus()})
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(url, params=params, json=body, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=300)) as resp:
                events = await self._read_sse(resp)
        return self._extract_cn_text(events)

    async def _read_sse(self, resp: aiohttp.ClientResponse) -> list:
        """Reads SSE stream."""
        events = []
        buffer = ""
        async for chunk in resp.content:
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                event_name = ""
                data_lines = []
                for line in raw_event.split("\n"):
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                data_str = "\n".join(data_lines)
                try:
                    data = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    data = {"_raw": data_str}
                events.append((event_name, data))
        return events

    async def upload_image(self, image_input: str) -> str:
        """Domestic image upload flow."""
        if image_input.startswith("tos-cn-i-"):
            return image_input
        image_buf = await self._fetch_image(image_input)

        # 1. prepare_upload (scene_id="5")
        url = f"https://{CN_DOMAIN}/alice/resource/prepare_upload"
        headers = {**self._build_headers(), "agw-js-conv": "str"}
        params = self._build_params({"msToken": _fake_ms_token(), "a_bogus": _fake_a_bogus()})
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(url, params=params,
                                     json={"tenant_id": "5", "scene_id": "5", "resource_type": 2},
                                     headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as p1:
                p1_data = await p1.json(content_type=None)
        # Response structure: service_id, upload_host, upload_auth_token
        upload_data = p1_data.get("data") or p1_data
        if not upload_data.get("upload_auth_token"):
            raise Exception(f"Domestic prepare_upload failed: {json.dumps(p1_data)[:100]}")

        auth = upload_data["upload_auth_token"]
        service_id = upload_data["service_id"]
        upload_host = upload_data["upload_host"]
        ak, sk, sts = auth["access_key"], auth["secret_key"], auth["session_token"]

        # 2. ApplyImageUpload
        apply_url = (
            f"https://{upload_host}/?Action=ApplyImageUpload&Version=2018-08-01"
            f"&ServiceId={service_id}&NeedFallback=true&UploadNum=1"
            f"&FileSize={len(image_buf)}&FileExtension=.png"
        )
        sig = aws4_sign("GET", apply_url, ak, sk, sts)
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(apply_url, headers=sig, timeout=aiohttp.ClientTimeout(total=15)) as p2:
                p2_data = await p2.json(content_type=None)
        store_info = p2_data["Result"]["UploadAddress"]["StoreInfos"][0]
        store_uri = store_info["StoreUri"]
        tos_host = p2_data["Result"]["UploadAddress"]["UploadHosts"][0]

        # 3. PUT TOS
        crc = crc32_hex(image_buf)
        tos_url = f"https://{tos_host}/{store_uri}"
        tos_headers = {
            "Authorization": store_info["Auth"],
            "Content-Type": "application/octet-stream",
            "content-crc32": crc,
            "Content-Disposition": 'attachment; filename="image.png"',
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.put(tos_url, data=image_buf, headers=tos_headers,
                                   timeout=aiohttp.ClientTimeout(total=30)) as p3:
                await p3.read()
        return store_uri

    async def _fetch_image(self, image_input: str) -> bytes:
        if image_input.startswith("http"):
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(image_input, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    return await r.read()
        import base64
        b64 = re.sub(r"^data:[^;]+;base64,", "", image_input)
        return base64.b64decode(b64)

    async def vision(self, image_input: str, prompt: str) -> str:
        """Domestic image recognition."""
        image_uri = await self.upload_image(image_input)
        body = {
            "messages": [{
                "content": json.dumps({"text": prompt}),
                "content_type": 2001,
                "attachments": [{
                    "type": "vlm_image",
                    "id": str(uuid_lib.uuid4()),
                    "name": "image.png",
                    "key": image_uri,
                    "url": image_uri,
                }],
                "references": [],
            }],
            "completion_option": {
                "is_regen": False, "with_suggest": True, "need_create_conversation": True,
                "launch_stage": 1, "is_replace": False, "is_delete": False,
                "message_from": 0, "action_bar_skill_id": 0, "use_deep_think": False,
                "use_auto_cot": False, "resend_for_regen": False,
                "enable_commerce_credit": False, "event_id": "0",
            },
            "evaluate_option": {"web_ab_params": ""},
            "section_id": "26" + _random_numeric(16),
            "conversation_id": "0",
            "local_conversation_id": "local_16" + _random_numeric(14),
            "local_message_id": str(uuid_lib.uuid4()),
        }
        url = f"https://{CN_DOMAIN}/samantha/chat/completion"
        headers = {**self._build_headers(), "agw-js-conv": "str, str"}
        params = self._build_params({"msToken": _fake_ms_token(), "a_bogus": _fake_a_bogus()})
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(url, params=params, json=body, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=120)) as resp:
                events = await self._read_sse(resp)
        return self._extract_cn_text(events)

    async def generate_image(self, prompt: str, ratio: str = "1:1", style: str = "auto") -> str:
        """Domestic text-to-image generation."""
        # Domestic text-to-image uses ability_type=16
        body = {
            "messages": [{
                "content": json.dumps({"text": f"帮我生成图片：{prompt}\n风格：{style}\n比例：{ratio}"}),
                "content_type": 2001,
                "attachments": [],
                "references": [],
            }],
            "completion_option": {
                "is_regen": False, "with_suggest": True, "need_create_conversation": True,
                "launch_stage": 1, "is_replace": False, "is_delete": False,
                "message_from": 0, "action_bar_skill_id": 0, "use_deep_think": False,
                "use_auto_cot": False, "resend_for_regen": False,
                "enable_commerce_credit": False, "event_id": "0",
            },
            "evaluate_option": {"web_ab_params": ""},
            "chat_ability": {"ability_type": 16, "ability_param": "{}"},
            "section_id": "26" + _random_numeric(16),
            "conversation_id": "0",
            "local_conversation_id": "local_16" + _random_numeric(14),
            "local_message_id": str(uuid_lib.uuid4()),
        }
        url = f"https://{CN_DOMAIN}/samantha/chat/completion"
        headers = {**self._build_headers(), "agw-js-conv": "str, str"}
        params = self._build_params({"msToken": _fake_ms_token(), "a_bogus": _fake_a_bogus()})
        conv_id = ""
        image_url = ""
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(url, params=params, json=body, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=60)) as resp:
                events = await self._read_sse(resp)
        for event_name, data in events:
            if event_name == "SSE_ACK":
                conv_id = (data.get("ack_client_meta") or {}).get("conversation_id", "")
            raw = json.dumps(data)
            urls = re.findall(r"https?://[^\"']*ibyteimg[^\"']*", raw)
            if urls:
                image_url = urls[0].replace("\\u0026", "&")
        if image_url:
            return image_url
        raise Exception("Domestic text-to-image failed to acquire image URL")

    async def generate_video(self, *args, **kwargs):
        """Domestic engine does not support video generation."""
        raise CreditError("Domestic engine does not support video generation")


# ============ Unified Client Factory ============

def create_client(cookie_or_token: str, api_base: str = "https://www.dola.com") -> "DolaClient | DoubaoCNClient":
    """Factory creating appropriate client based on cookie format."""
    if "msToken=" in cookie_or_token:
        return DolaClient(cookie_or_token, api_base)
    else:
        # Domestic: plain sessionid or doubao cookie
        token = cookie_or_token
        m = re.search(r"sessionid=([^;]+)", cookie_or_token)
        if m:
            token = m.group(1)
        return DoubaoCNClient(token)
