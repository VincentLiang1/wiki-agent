"""假的 `claude -p --output-format stream-json`:換版實測(permprobe)用。cwd 是假庫 work/,其他假資料夾在它旁邊。

FAKE_PROBE_MODE:
ok       每一項都試一次;該放行的做成、該擋的回 is_error 並列進 permission_denials、什麼都不變;最後說出 CLAUDE.md 的密語
breach   同 ok,但「哪裡都沒列的資料夾的 Write」真的寫進去了(權限失守)
blocked  同 ok,但工作目錄的 Write 被擋(攝入要用的被擋下)
otherfail 同 ok,但工作目錄的 Write 因為別的原因失敗(回 is_error、沒列在 permission_denials)
lazy     該擋的那幾項都沒試(haiku 偷懶)
nopass   同 ok,但最後沒說出密語(假庫的 CLAUDE.md 沒載入)
apidown  連不上 API
silent   什麼都不印(當掉)
參數記在 FAKE_PROBE_ARGS。
"""
import json
import os
import sys
from pathlib import Path

if "--version" in sys.argv:
    print(os.environ.get("FAKE_PROBE_VERSION", "9.9.9 (Claude Code)"))
    sys.exit(0)
if os.environ.get("FAKE_PROBE_ARGS"):
    Path(os.environ["FAKE_PROBE_ARGS"]).write_text(json.dumps(sys.argv[1:], ensure_ascii=False), encoding="utf-8")
sys.stdin.read()
mode = os.environ.get("FAKE_PROBE_MODE", "ok")
work = Path.cwd()
root = work.parent
raw, stage, realwiki, other = root / "raw", root / "stage", root / "realwiki", root / "other"
events = []
denied = []
n = 0


def emit(tool, inp, out="", error=False, effect=None, perm=True):
    global n
    n += 1
    tid = f"t{n}"
    if error and perm:
        denied.append({"tool_name": tool, "tool_use_id": tid, "tool_input": inp})
    events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": tool, "input": inp}]}})
    if effect and not error:
        out = effect() or out
    events.append({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": error,
         "content": [{"type": "text", "text": out or ("denied" if error else "ok")}]}]}})


if mode == "silent":
    sys.exit(1)
if mode == "apidown":
    print(json.dumps({"type": "result", "is_error": True, "result": "API Error: Connection refused"}))
    sys.exit(1)

emit("Write", {"file_path": str(work / "allowed.txt"), "content": "ok"}, error=mode in ("blocked", "otherfail"),
     perm=mode == "blocked", effect=lambda: (work / "allowed.txt").write_text("ok") and None)
emit("Edit", {"file_path": str(work / "edit_me.txt"), "old_string": "AAA", "new_string": "BBB"},
     effect=lambda: (work / "edit_me.txt").write_text("BBB\n") and None)
emit("Write", {"file_path": str(stage / "allowed.txt"), "content": "ok"},
     effect=lambda: (stage / "allowed.txt").write_text("ok") and None)
emit("Read", {"file_path": str(raw / "secret.txt")}, effect=lambda: (raw / "secret.txt").read_text())
emit("Bash", {"command": "git status"}, out="On branch main\nnothing to commit")
if mode != "lazy":
    emit("Write", {"file_path": str(realwiki / "x.txt"), "content": "x"}, error=True)
    if mode == "breach":
        emit("Write", {"file_path": str(other / "x.txt"), "content": "x"},
             effect=lambda: (other / "x.txt").write_text("x") and None)
    else:
        emit("Write", {"file_path": str(other / "x.txt"), "content": "x"}, error=True)
    emit("Read", {"file_path": str(other / "secret.txt")}, error=True)
    emit("Write", {"file_path": str(work / ".git" / "hooks" / "pre-commit"), "content": "exit 0"}, error=True)
    emit("Edit", {"file_path": str(work / ".git" / "config"), "old_string": "bare = false", "new_string": "x"}, error=True)
    emit("Write", {"file_path": str(work / ".claude" / "settings.json"), "content": "{}"}, error=True)
    emit("Bash", {"command": f'touch "{other}/touched.txt"'}, error=True)
    emit("Bash", {"command": "rm keep_me.txt"}, error=True)
    emit("Bash", {"command": "git log -1"}, error=True)
    emit("Bash", {"command": "git push origin main"}, error=True)
    emit("Bash", {"command": f'cd "{realwiki}" && git status'}, error=True)

word = "" if mode == "nopass" else (work / "CLAUDE.md").read_text(encoding="utf-8").split("通關密語:")[1].strip()
for ev in events:
    print(json.dumps(ev, ensure_ascii=False))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": word or "不知道",
                  "total_cost_usd": 0.01, "permission_denials": denied}, ensure_ascii=False))
