//=============================================================================
// ZZ_Translator_Bridge.js  (P1)
// 由 game-translator 產生。遊戲自己載入，不做任何注入。
//=============================================================================
(function () {
  "use strict";

  var PORT = window.$TRANSLATOR_PORT || 0;
  var ENDPOINT = "http://127.0.0.1:" + PORT + "/translate";
  var dict = Object.create(null); // 原文 -> 譯文

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
    if (!texts.length || !PORT) { done(); return; }
    var xhr = new XMLHttpRequest();
    xhr.open("POST", ENDPOINT, true);
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
      } catch (e) { /* 失敗則維持原文，不崩 */ }
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
    } catch (e) { /* 不影響遊戲啟動 */ }
    _onLoad.call(this);
  };
})();
