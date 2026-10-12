// レシートの画像・動画を /ocr/receipt/ に送り、読み取った内容を返す。
window.readReceipt = async function (file) {
  const form = new FormData();
  form.append("file", file);
  const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const res = await fetch("/ocr/receipt/", { method: "POST", body: form, headers: { "X-CSRFToken": token } });
  let json;
  try { json = await res.json(); } catch (e) { throw new Error("読み取りに失敗しました（" + res.status + "）。"); }
  if (!json.ok) throw new Error(json.error || "読み取りに失敗しました。");
  return json;
};

// 読み取り結果の表示（エンジン・注意・読み取った文字）
window.renderOcrResult = function (box, json, message) {
  const d = json.data;
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const items = d.items.map(i => `<li>${esc(i.name)}${i.reduced ? "（軽減）" : ""} … ${Number(i.amount).toLocaleString("ja-JP")}円</li>`).join("");
  box.innerHTML = `
    <div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
      <div class="font-semibold">${esc(message)}（${json.engine === "claude" ? "Claude API" : "ローカルOCR"}${d.frames_used > 1 ? `・${d.frames_used}フレーム` : ""}）</div>
      <div>読み取った値は必ず領収書と見比べて確認してください。</div>
      ${d.warnings.map(w => `<div class="text-amber-800">⚠ ${esc(w)}</div>`).join("")}
      ${items ? `<details class="mt-1"><summary class="cursor-pointer">読み取った明細（${d.items.length}件）</summary><ul class="list-disc pl-5">${items}</ul></details>` : ""}
      <details class="mt-1"><summary class="cursor-pointer">読み取った文字</summary><pre class="whitespace-pre-wrap">${esc(d.raw_text)}</pre></details>
    </div>`;
};
