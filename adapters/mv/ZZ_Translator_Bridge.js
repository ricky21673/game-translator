//=============================================================================
// ZZ_Translator_Bridge.js  (P2)
// 由 game-translator 產生。遊戲自己載入，不做任何注入。
//
// P2 變更：新增「離線整字典模式」（MTool 式）。
// 若部署時偵測到 window.$translatorDict（整份 {原文:譯文} 字典已嵌入遊戲端），
// 就改走「hook 底層畫字函式 Bitmap.prototype.drawText」的全面覆蓋路線，
// 不再需要開機時對 server 發 XHR 要譯文（字典已經在本地、不必再問大腦）。
// 沒有 $translatorDict 時，維持原本「collectStrings + requestTranslation」的
// DeepL 線上模式路徑，兩者用 if 分流、互不影響。
//=============================================================================
(function () {
  "use strict";

  // 是否為離線整字典模式：window.$translatorDict 存在且為物件（非 null、非陣列亦可，
  // 但實務上只會是 launcher 端 json.dumps 出的純物件）。
  var hasFullDict = (typeof window.$translatorDict === "object" && window.$translatorDict !== null);

  // dict：實際查表用的原文 -> 譯文字典。
  // 離線整字典模式：直接沿用 window.$translatorDict（已含整份字典，開機不必再抽字串送翻）。
  // 非整字典模式（DeepL 線上）：維持原本的空字典，靠 collectStrings/requestTranslation 動態回填。
  var dict = hasFullDict ? window.$translatorDict : Object.create(null); // 原文（或正規化內文）-> 譯文

  // --- 正規化：剝除「說話者名條前綴」與「plugin 條件/script 前綴」---
  // 實測發現整串查表命中率偏低，是因為對話文字常帶固定格式的前綴：
  //   1. 說話者名條：字面上的 \n<名字> （注意：資料內是「反斜線 + n + < 名 >」共兩個字元的跳脫記號，非真正換行）
  //   2. plugin 條件/script 前綴：en(...) 或 if(...)，例如 en(s[441])、if(v[29]==1)
  // 反覆剝除直到不再變化，再修剪頭尾全形/半形空白，即可還原「純內文」用來查表命中。
  var RE_SPEAKER_TAG = /^\\n<[^>]*>/;
  var RE_PLUGIN_COND = /^(?:en|if)\([^)]*\)/;
  var RE_LEADING_SPACE = /^[\s　]+/;
  var RE_TRAILING_SPACE = /[\s　]+$/;

  function normalize(text) {
    if (typeof text !== "string" || !text) return { prefix: "", inner: text };
    // 用「已剝除的頭部字元數」直接記錄剝除量，而非事後用長度差反推——
    // 因為尾端還會再修剪空白，若用「text.length - inner.length」反推頭部剝除量，
    // 會把尾端剝掉的量也算進頭部，導致 prefix 多切、少切字元（切錯位置）。
    var cut = 0; // 累計從頭部剝除的字元數
    var rest = text;
    var changed = true;
    // 迴圈套用「名條」「plugin 前綴」「頭部空白」三種 lstrip，直到不再變化為止
    while (changed) {
      changed = false;
      var m;
      if ((m = rest.match(RE_SPEAKER_TAG))) { rest = rest.slice(m[0].length); cut += m[0].length; changed = true; }
      if ((m = rest.match(RE_PLUGIN_COND))) { rest = rest.slice(m[0].length); cut += m[0].length; changed = true; }
      if ((m = rest.match(RE_LEADING_SPACE))) { rest = rest.slice(m[0].length); cut += m[0].length; changed = true; }
    }
    // 頭部剝除完成後才修剪尾端空白，inner 是「乾淨內文」，方便查表命中；
    // prefix 只用「頭部剝除量 cut」切，與尾端修剪完全無關，避免上述錯位。
    var inner = rest.replace(RE_TRAILING_SPACE, "");
    var prefix = text.slice(0, cut);
    return { prefix: prefix, inner: inner };
  }

  // --- 查表快取（memo）---
  // 只快取「確定命中」的查表結果（key -> 已翻譯字串），避免重複畫同一段文字時
  // 反覆做 normalize 運算。務必不快取「未命中」，否則字典之後若被替換／擴充
  // （理論上不會，但保守起見）不會被誤判成「原文即最終結果」而卡住。
  // 未命中的情況一律即時回傳原文，不進 memo。
  var memo = Object.create(null);

  // --- lookup：統一查表入口，drawText 與 convertEscapeCharacters 都呼叫這支 ---
  // 規則（依序）：
  //   1. 非字串或空字串 → 原樣回傳（安全處理 drawText 可能傳數字等非字串參數）。
  //   2. memo 命中 → 直接回傳快取結果。
  //   3. 整串 dict[text] 命中且譯文 !== 原文 → 回傳譯文，存入 memo。
  //   4. 未命中 → normalize 剝前綴取 inner，dict[inner] 命中且譯文 !== inner
  //      → 回傳 prefix + dict[inner]，存入 memo。
  //   5. 都沒中 → 回傳原文（不存 memo，避免誤把原文當成已翻結果快取住）。
  function lookup(text) {
    if (typeof text !== "string" || !text) return text;
    if (memo[text] !== undefined) return memo[text];

    var result = text;
    try {
      if (dict[text] && dict[text] !== text) {
        result = dict[text];
      } else {
        var norm = normalize(text);
        if (norm.inner && dict[norm.inner] && dict[norm.inner] !== norm.inner) {
          result = norm.prefix + dict[norm.inner];
        }
      }
    } catch (e) {
      console.warn("[Translator_Bridge] 查表失敗，維持原文:", e);
      result = text;
    }

    if (result !== text) memo[text] = result; // 只快取確定命中的結果
    return result;
  }

  // --- 從 $dataXXX 抽可見字串（非整字典模式專用：P1 抽對話事件文字與基本名稱送 DeepL）---
  function collectStrings() {
    var set = Object.create(null);
    function add(s) {
      if (typeof s === "string" && s.trim() && /[぀-ヿ一-鿿]/.test(s)) {
        set[s] = 1;
        // 額外送「正規化內文」：對話文字常帶說話者名條/plugin 前綴，
        // 導致整串在離線字典查不到；改送 inner 讓字典能用內文命中，
        // hook 端再用同一份 normalize 邏輯查表、保留原前綴顯示。
        try {
          var inner = normalize(s).inner;
          if (inner && inner !== s && /[぀-ヿ一-鿿]/.test(inner)) set[inner] = 1;
        } catch (e) { console.warn("[Translator_Bridge] 正規化抽字串失敗，略過內文:", e); }
      }
    }
    // 各資料庫的 name / description
    [$dataActors, $dataItems, $dataSkills, $dataWeapons, $dataArmors,
     $dataStates, $dataClasses, $dataEnemies].forEach(function (arr) {
      if (!arr) return;
      arr.forEach(function (o) { if (o) { add(o.name); add(o.description); } });
    });
    // 地圖事件中的「顯示文字(code 401)/選項(102)」等指令參數
    (window.$translatorMaps || []).forEach(function (map) {
      if (!map || !map.events) return;
      map.events.forEach(function (ev) {
        if (!ev || !ev.pages) return;
        ev.pages.forEach(function (pg) {
          (pg.list || []).forEach(function (cmd) {
            if ([401, 405, 102, 101, 402].indexOf(cmd.code) >= 0) {
              (cmd.parameters || []).forEach(function (p) {
                if (typeof p === "string") add(p);
                else if (Array.isArray(p)) p.forEach(add);
              });
            }
          });
        });
      });
    });
    return Object.keys(set);
  }

  // 延後讀取 PORT／組 ENDPOINT：不在 IIFE 載入當下就讀，避免與 boot script
  // 載入順序耦合（bridge 若比 boot 先執行，當下讀到的 window.$TRANSLATOR_PORT
  // 可能尚未就緒）。改成每次要發請求時才即時讀取。
  function getEndpoint() {
    var port = window.$TRANSLATOR_PORT || 0;
    return { port: port, url: "http://127.0.0.1:" + port + "/translate" };
  }

  // --- 送 localhost 大腦翻譯，回填記憶體字典（非整字典模式專用：DeepL 線上）---
  function requestTranslation(texts, done) {
    var ep = getEndpoint();
    if (!texts.length || !ep.port) { done(); return; }
    var xhr = new XMLHttpRequest();
    xhr.open("POST", ep.url, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try {
        if (xhr.status === 200) {
          var res = JSON.parse(xhr.responseText).translations || [];
          for (var i = 0; i < texts.length; i++) {
            if (res[i]) dict[texts[i]] = res[i];
          }
        }
      } catch (e) { console.warn("[Translator_Bridge] 解析翻譯回應失敗，維持原文:", e); }
      done();
    };
    xhr.send(JSON.stringify({ texts: texts }));
  }

  // --- hook 1：底層畫字函式（主要的全面覆蓋點）---
  // RPG Maker MV 選單、道具、狀態欄等大量文字最終都經由 Bitmap.prototype.drawText 畫出，
  // 不會經過 convertEscapeCharacters；hook 這裡才能涵蓋訊息文字以外的介面文字。
  // text 可能非字串（例如數字血量、座標等），lookup() 內已對非字串安全直接回傳原值。
  var _drawText = Bitmap.prototype.drawText;
  Bitmap.prototype.drawText = function (text, x, y, maxWidth, lineHeight, align) {
    var translated = text;
    try {
      translated = lookup(text);
    } catch (e) {
      console.warn("[Translator_Bridge] drawText 查表替換失敗，維持原文:", e);
      translated = text;
    }
    return _drawText.call(this, translated, x, y, maxWidth, lineHeight, align);
  };

  // --- hook 2：訊息文字轉義字元處理（涵蓋對話視窗文字，保留既有行為）---
  var _conv = Window_Base.prototype.convertEscapeCharacters;
  Window_Base.prototype.convertEscapeCharacters = function (text) {
    var translated = text;
    try {
      translated = lookup(text);
    } catch (e) {
      console.warn("[Translator_Bridge] convertEscapeCharacters 查表替換失敗，維持原文:", e);
      translated = text;
    }
    return _conv.call(this, translated);
  };

  // --- 開機流程 ---
  // 離線整字典模式：字典已在本地（window.$translatorDict），不需要再對 server 發請求要譯文，
  // 靠 hook 1/2 在畫字當下即時查表即可，故略過 collectStrings/requestTranslation。
  // 非整字典模式（DeepL 線上）：維持原有「資料載完 → 抽字串 → 送翻」流程，不受本次修改影響。
  if (!hasFullDict) {
    var _onLoad = Scene_Boot.prototype.start;
    Scene_Boot.prototype.start = function () {
      try {
        var texts = collectStrings();
        requestTranslation(texts, function () {});
      } catch (e) { console.warn("[Translator_Bridge] 開機抽字串/翻譯失敗:", e); }
      _onLoad.call(this);
    };
  }
})();
