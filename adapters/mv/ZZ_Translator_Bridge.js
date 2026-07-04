//=============================================================================
// ZZ_Translator_Bridge.js  (P1)
// 由 game-translator 產生。遊戲自己載入，不做任何注入。
//=============================================================================
(function () {
  "use strict";

  var dict = Object.create(null); // 原文 -> 譯文

  // 延後讀取 PORT／組 ENDPOINT：不在 IIFE 載入當下就讀，避免與 boot script
  // 載入順序耦合（bridge 若比 boot 先執行，當下讀到的 window.$TRANSLATOR_PORT
  // 可能尚未就緒）。改成每次要發請求時才即時讀取。
  function getEndpoint() {
    var port = window.$TRANSLATOR_PORT || 0;
    return { port: port, url: "http://127.0.0.1:" + port + "/translate" };
  }

  // --- 從 $dataXXX 抽可見字串（P1：抽對話事件文字與基本名稱）---
  function collectStrings() {
    var set = Object.create(null);
    function add(s) {
      if (typeof s === "string" && s.trim() && /[぀-ヿ一-鿿]/.test(s)) set[s] = 1;
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

  // --- 送 localhost 大腦翻譯，回填記憶體字典 ---
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

  // --- hook：整串查表替換（查不到就回原文）---
  var _conv = Window_Base.prototype.convertEscapeCharacters;
  Window_Base.prototype.convertEscapeCharacters = function (text) {
    if (dict[text]) text = dict[text];
    return _conv.call(this, text);
  };

  // --- 開機流程：資料載完 → 抽字串 → 翻譯 ---
  var _onLoad = Scene_Boot.prototype.start;
  Scene_Boot.prototype.start = function () {
    try {
      var texts = collectStrings();
      requestTranslation(texts, function () {});
    } catch (e) { console.warn("[Translator_Bridge] 開機抽字串/翻譯失敗:", e); }
    _onLoad.call(this);
  };
})();
