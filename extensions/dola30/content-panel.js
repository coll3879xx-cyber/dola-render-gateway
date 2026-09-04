(function () {
  const PANEL_ID = "watermark-free-media-panel";
  const DOUBAO_PLAY_INFO_URL = "https://www.doubao.com/samantha/media/get_play_info?version_code=20800&language=zh-CN&device_platform=web&aid=497858&real_aid=497858&pkg_type=release_version&device_id=&pc_version=2.51.7&region=&sys_region=&samantha_web=1&use-olympus-account=1&web_tab_id=";
  const items = new Map();

  if (document.getElementById(PANEL_ID)) {
    return;
  }

  const host = document.createElement("div");
  host.id = PANEL_ID;
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host {
        all: initial;
        position: fixed;
        right: 16px;
        bottom: 16px;
        z-index: 2147483647;
        font-family: Arial, "Microsoft YaHei", sans-serif;
      }

      .panel {
        width: 336px;
        max-height: 420px;
        display: flex;
        flex-direction: column;
        color: #1f2937;
        background: #fff;
        border: 1px solid rgba(31, 41, 55, 0.16);
        border-radius: 8px;
        box-shadow: 0 14px 38px rgba(15, 23, 42, 0.2);
        overflow: hidden;
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 10px 12px;
        background: #f8fafc;
        border-bottom: 1px solid rgba(31, 41, 55, 0.1);
      }

      .title {
        font-size: 14px;
        line-height: 20px;
        font-weight: 700;
      }

      .count {
        min-width: 22px;
        height: 20px;
        padding: 0 6px;
        border-radius: 999px;
        background: #166534;
        color: #fff;
        font-size: 12px;
        line-height: 20px;
        text-align: center;
      }

      .list {
        min-height: 76px;
        max-height: 350px;
        overflow: auto;
        padding: 8px;
      }

      .empty {
        padding: 18px 10px;
        color: #64748b;
        font-size: 13px;
        line-height: 20px;
        text-align: center;
      }

      .item {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 8px;
        align-items: center;
        padding: 8px;
        border: 1px solid rgba(31, 41, 55, 0.12);
        border-radius: 6px;
        background: #fff;
      }

      .item + .item {
        margin-top: 8px;
      }

      .label {
        min-width: 0;
        color: #273444;
        font-size: 13px;
        line-height: 18px;
        font-weight: 700;
      }

      .tag {
        display: inline-block;
        min-width: 34px;
        margin-right: 8px;
        padding: 2px 6px;
        border-radius: 999px;
        color: #fff;
        font-size: 12px;
        line-height: 16px;
        text-align: center;
      }

      .tag.video {
        background: #6d28d9;
      }

      .tag.image {
        background: #0f766e;
      }

      button {
        height: 30px;
        padding: 0 10px;
        border: 0;
        border-radius: 6px;
        background: #2563eb;
        color: #fff;
        font-size: 12px;
        line-height: 30px;
        cursor: pointer;
      }

      button:hover {
        background: #1d4ed8;
      }
    </style>
    <section class="panel" aria-label="Watermark-Free Media Panel">
      <div class="header">
        <div class="title">Master HD Media</div>
        <div class="count">0</div>
      </div>
      <div class="list">
        <div class="empty">Waiting for media...</div>
      </div>
    </section>
  `;

  const list = shadow.querySelector(".list");
  const count = shadow.querySelector(".count");
  let currentSourceKey = "";
  let statusText = "Waiting for media...";

  chrome.runtime.onMessage.addListener((message) => {
    if (!message) {
      return;
    }

    if (message.type === "MEDIA_STATUS" && typeof message.text === "string") {
      resetForSource(message.sourceKey);
      items.clear();
      statusText = message.text;
      render();
      return;
    }

    if (message.type === "MEDIA_FOUND" && Array.isArray(message.items)) {
      resetForSource(message.sourceKey);
      items.clear();
      addItems(message.items);
      statusText = items.size ? "" : "No resources found";
      render();
      return;
    }

    if (message.type === "DOUBAO_VIDS_FOUND" && Array.isArray(message.vids)) {
      resetForSource(message.sourceKey);
      fetchDoubaoVideos(message.sourceKey, message.vids);
    }
  });

  async function fetchDoubaoVideos(sourceKey, vids) {
    const uniqueVids = Array.from(new Set(vids.filter((vid) => typeof vid === "string" && vid)));
    if (!uniqueVids.length) {
      return;
    }

    statusText = items.size ? "" : "Extracting unwatermarked video...";
    render();

    const foundItems = [];
    for (const vid of uniqueVids) {
      const url = await getDoubaoOriginalVideoUrl(vid);
      if (isHttpUrl(url)) {
        foundItems.push({ type: "video", url });
      }
    }

    if (sourceKey !== currentSourceKey) {
      return;
    }

    addItems(foundItems);
    statusText = items.size ? "" : "No resources found";
    render();
  }

  async function getDoubaoOriginalVideoUrl(vid) {
    try {
      const response = await fetch(DOUBAO_PLAY_INFO_URL, {
        method: "POST",
        credentials: "omit",
        headers: {
          "accept": "application/json, text/plain, */*",
          "content-type": "application/json"
        },
        body: JSON.stringify({ key: vid })
      });
      const json = await response.json();
      const url = json?.data?.original_media_info?.main_url;
      return isHttpUrl(url) ? url : "";
    } catch (error) {
      console.warn("doubao play info failed:", error);
      return "";
    }
  }

  function resetForSource(sourceKey) {
    if (typeof sourceKey !== "string" || !sourceKey) {
      return;
    }

    if (sourceKey !== currentSourceKey) {
      currentSourceKey = sourceKey;
      items.clear();
      statusText = "";
    }
  }

  function render() {
    count.textContent = String(items.size);
    list.textContent = "";

    if (!items.size) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = statusText || "Waiting for media...";
      list.appendChild(empty);
      return;
    }

    Array.from(items.values()).forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "item";

      const label = document.createElement("div");
      label.className = "label";
      label.title = item.url;

      const tag = document.createElement("span");
      tag.className = `tag ${item.type}`;
      tag.textContent = item.type === "image" ? "IMAGE" : "VIDEO";

      const indexText = document.createElement("span");
      indexText.textContent = String(index + 1);

      label.append(tag, indexText);

      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Download";
      button.addEventListener("click", () => {
        chrome.runtime.sendMessage({ type: "DOWNLOAD_MEDIA", url: item.url });
      });

      row.append(label, button);
      list.appendChild(row);
    });
  }

  function addItems(nextItems) {
    for (const item of nextItems) {
      if (!item || typeof item.url !== "string" || !isHttpUrl(item.url)) {
        continue;
      }
      items.set(item.url, {
        type: item.type === "image" ? "image" : "video",
        url: item.url
      });
    }
  }

  function isHttpUrl(url) {
    return /^https?:\/\//i.test(url);
  }
})();
