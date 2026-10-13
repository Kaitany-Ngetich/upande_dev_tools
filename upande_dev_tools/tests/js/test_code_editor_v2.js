// Pure helpers of public/js/dev-v2-code-editor.js (no DOM needed). Run: node tests/js/test_code_editor_v2.js
const assert = require("assert");
const { formatBytes, tabKey, iconName, clampWidth } = require("../../public/js/dev-v2-code-editor.js");

assert.strictEqual(formatBytes(0), "0 B");
assert.strictEqual(formatBytes(512), "512 B");
assert.strictEqual(formatBytes(1536), "1.5 KB");
assert.strictEqual(formatBytes(3 * 1048576), "3.0 MB");
assert.notStrictEqual(tabKey("a", "x.py"), tabKey("b", "x.py"));
assert.strictEqual(iconName(".py"), "python");
assert.strictEqual(iconName(".unknown"), "file");
assert.strictEqual(iconName("", true, true), "folder-open");
assert.strictEqual(iconName("", true, false), "folder");
assert.strictEqual(clampWidth("explorer", 10), 180);
assert.strictEqual(clampWidth("explorer", 9999), 560);
assert.strictEqual(clampWidth("details", 300.4), 300);
console.log("code-editor-v2 helpers: ok");
