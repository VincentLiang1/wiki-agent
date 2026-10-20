"""攝入時 claude 能用的只讀指令:page-history、commit-detail、check-pages、table-sums(pagetools.py)。

git log／show／diff 不開放(`--output=` 能清空任意檔),改由程式組參數;claude 只給頁面、雜湊、關鍵字。
"""
from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder.cli import main
from wiki_feeder.config import INGEST_TOOLS_CMD, RepoConfig
from wiki_feeder.pagetools import (PageRoot, PageToolError, check_pages, commit_detail, new_problems, page_history,
                                   page_path, scan_text, table_sums)

# 公事庫 CLAUDE.md〈CJK 粗體／斜體 flanking〉的壞例與「勿誤改」:判定要跟那張表一致
BROKEN = ["前文**X（Y）**中文", "說**「quoted」**中文", "**Q：問題？**中文", "中文**[文字](path)**中文"]
SAFE = ["**粗體**（註解）", "（前）**粗體**", "空白 **粗體** 空白", "**粗體**中文", "中文**粗體**中文",
        "- **項目**：說明", "| **欄** | 值 |", "> **註**：引用", "`a**b` 程式碼"]


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "FWIKI"
    git("init", "-q", "-b", "master", str(r), cwd=tmp_path)
    (r / "Wiki_Pages").mkdir()
    (r / "Wiki_Pages" / "頁.md").write_text("# 頁\n", encoding="utf-8")
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "docs(ingest): 建頁", "-m", "來源:使用者 10-01 口頭更正 營收 12 億", cwd=r)
    git("mv", "Wiki_Pages/頁.md", "Wiki_Pages/新頁.md", cwd=r)
    git("commit", "-q", "-m", "refactor(Wiki_Pages): 改名", cwd=r)
    (tmp_path / "外面.md").write_text("外面", encoding="utf-8")
    return r


def test_bold_check_matches_the_company_wiki_table():
    for s in BROKEN:
        assert [k for _, k, _ in scan_text(s)] == ["粗體失效(渲染後還留著 **)"], s
    for s in SAFE:
        assert scan_text(s) == [], s


def test_control_characters_are_found_and_code_blocks_are_not_bold_checked():
    """`\\202` 被 Python 吃成八進位跳脫留下的 U+0082(公事庫 2026-08-28 實跡);換行、tab 不算。"""
    text = "路徑 FRaw_Sources\x826BSI\n\t縮排\n```\n**X（Y）**中文\n```\n"
    assert scan_text(text) == [(1, "控制字元 U+0082", "路徑 FRaw_Sources\x826BSI")]


def test_only_problems_new_in_this_ingest_are_reported():
    old = "前文**X（Y）**中文\n"
    assert new_problems(old, old + "說**「quoted」**中文\n") == [(2, "粗體失效(渲染後還留著 **)", "說**「quoted」**中文")]


def test_page_history_follows_renames_and_greps_messages(repo):
    out = page_history(repo, "Wiki_Pages/新頁.md")
    assert "改名" in out and "建頁" in out                      # 跟著改名查到建頁那次
    assert len(out.splitlines()) == 2                             # 一個 commit 一行:內文要看用 commit-detail
    assert "建頁" in page_history(repo, grep="口頭更正")         # --grep 照樣比對內文
    assert "改名" not in page_history(repo, grep="口頭更正")


def test_paths_outside_the_wiki_are_refused(repo):
    for bad in ("../外面.md", str(repo.parent / "外面.md"), ".git/config", "."):
        with pytest.raises(PageToolError):
            page_path(repo, bad)


def test_commit_detail_only_takes_a_hash(repo, tmp_path):
    """git 的選項不可能混進去:`--output=` 能把任意檔清成 0 bytes。"""
    victim = tmp_path / "外面.md"
    for bad in (f"--output={victim}", "master", "-p", "HEAD~1", "HEAD^", "@", "HEAD --output=x", "head"):
        with pytest.raises(PageToolError):
            commit_detail(repo, bad)
    assert victim.read_text(encoding="utf-8") == "外面"
    head = git("rev-parse", "HEAD", cwd=repo)
    out = commit_detail(repo, head[:7])
    assert "改名" in out and "新頁.md" in out                    # 中文檔名不跳脫
    assert "口頭更正 營收 12 億" in commit_detail(repo, git("rev-parse", "HEAD~1", cwd=repo))   # 內文全文
    assert commit_detail(repo, "HEAD") == out                     # commit 完確認自己 commit 了什麼


def test_cli_only_looks_at_the_company_wiki(cfg, repo, tmp_path, capsys):
    """看的是設定裡的公事庫、不是目前目錄;失敗時結束碼 1。"""
    (repo / "Wiki_Pages" / "壞.md").write_text(f"中文**[文字](path)**中文\n來源 `C:\\{tmp_path.name}\\FRaw\\a.pdf`\n",
                                              encoding="utf-8")
    c = replace(cfg, repos=(RepoConfig("company", "公事庫", repo, tmp_path / "FRaw", "me/FWIKI"),))
    assert main(["check-pages", "Wiki_Pages/壞.md", "Wiki_Pages/新頁.md"], c) == 0
    out = capsys.readouterr().out
    assert "壞.md:第 1 行 粗體失效" in out and "新頁.md:沒有問題" in out
    assert "第 2 行 來源路徑帶磁碟前綴" in out             # 照設定裡那個庫的原件樹位置查
    assert main(["page-history", "../外面.md"], c) == 1
    assert main(["commit-detail", "--", "--output=x"], c) == 1
    with pytest.raises(SystemExit):   # 不加 -- 的話 argparse 先擋下(不認得的選項)
        main(["commit-detail", "--output=x"], c)


def test_check_pages_also_takes_the_personal_wiki_and_its_stage(cfg, repo, tmp_path, capsys):
    """回填寫的是個人 WIKI 副本:2026-10-08 以前 check-pages 只收公事庫,回填的頁每筆都寫成粗體判定「未驗」。"""
    wiki = tmp_path / "WIKI"
    stage = cfg.wiki_stage_dir
    for d in (wiki, stage):
        (d / "Wiki_Pages").mkdir(parents=True)
        (d / "Wiki_Pages" / "通用.md").write_text("中文**[文字](path)**中文\n## 甲、乙\n", encoding="utf-8")
    (wiki / ".git").mkdir()
    (wiki / ".git" / "config").write_text("x", encoding="utf-8")
    c = replace(cfg, repos=(RepoConfig("company", "公事庫", repo, tmp_path / "FRaw", "me/FWIKI"),
                            RepoConfig("personal", "個人庫", wiki, tmp_path / "Raw", "me/WIKI")))
    assert main(["check-pages", str(stage / "Wiki_Pages" / "通用.md"), "../WIKI/Wiki_Pages/通用.md",
                 "Wiki_Pages/新頁.md"], c) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("WIKI 副本 Wiki_Pages/通用.md:第 1 行 粗體失效")
    assert out[1].startswith("WIKI Wiki_Pages/通用.md:第 1 行 粗體失效")
    assert out[2] == "Wiki_Pages/新頁.md:沒有問題"
    assert all("H2" not in line for line in out)                      # 個人 WIKI 的 H2 可以用頓號
    for bad in ("../外面.md", str(wiki / ".git" / "config")):          # 三個庫以外、.git 裡照樣擋下
        assert main(["check-pages", bad], c) == 1
    roots = [PageRoot("FWIKI", repo), PageRoot("WIKI", wiki, True)]
    assert "不在 FWIKI、WIKI 裡" in str(pytest.raises(PageToolError, check_pages, roots, ["../外面.md"]).value)


def test_personal_wiki_is_checked_by_its_own_rules():
    """個人 WIKI 的 H2 禁用字元沒有頓號、全形減號。來源路徑的磁碟前綴照該庫原件樹的位置查,不寫死資料夾名。"""
    rel = "Wiki_Pages/群組/頁.md"
    raw = Path("/x/LLMWIKI/Raw_Sources")
    assert [k for _, k, _ in scan_text("## 甲、乙", rel)] == ["H2 含禁用字元"]
    assert scan_text("## 甲、乙", rel, personal=True) == []
    assert [k for _, k, _ in scan_text("## 甲：乙", rel, personal=True)] == ["H2 含禁用字元"]
    assert [k for _, k, _ in scan_text("`C:\\LLMWIKI\\Raw_Sources\\a.pdf`", rel, True, raw)] == ["來源路徑帶磁碟前綴"]
    assert scan_text("`C:\\LLMWIKI\\Raw_Sources\\a.pdf`", rel, True, Path("/x/LLMWIKI/公事原件")) == []
    assert scan_text("`C:\\LLMWIKI\\Raw_Sources\\a.pdf`", rel, True) == []        # 沒給原件樹就不查
    assert scan_text("來源:`Raw_Sources\\群組\\a.pdf`", rel, True, raw) == []     # 相對路徑才對


def test_tools_command_does_not_import_from_the_wiki(tmp_path):
    """-P:攝入時 cwd 是公事庫、claude 能寫檔。它寫一個 wiki_feeder.py 再跑放行的指令,就等於能執行任意程式。"""
    (tmp_path / "wiki_feeder.py").write_text("open('pwned', 'w').write('x')\n", encoding="utf-8")
    cmd = INGEST_TOOLS_CMD   # Config.default() 與設定檔都用它;Windows 沒設定檔時 default() 會報錯
    subprocess.run([*cmd, "check-pages", "a.md"], cwd=tmp_path, capture_output=True, timeout=60)
    assert not (tmp_path / "pwned").exists()


def test_company_wiki_grep_checks_only_apply_to_wiki_pages():
    """公事庫 CLAUDE.md 列的 grep 健檢:攝入時跑不了 grep -P／python,改由 check-pages 查。"""
    bad = {
        "見 [[某頁]]": "wikilink",
        "## 第一章：概論": "H2 含禁用字元",
        "## AI 導入": "H2 含禁用字元",
        "見[章](#AI導入)": "錨點含大寫字母",
        "- [名稱](../資訊安全/某頁.md) — 進階：x": "跨群組清單項的顯示文字要寫成路徑 資訊安全/某頁",
        "- [某頁](某頁.md) — 延伸：x": "相關連結的 type label",
        "來源 `/Users/me/LLMWIKI/公事原件/群組/a.pdf`": "來源路徑帶磁碟前綴",
    }
    raw = Path("/x/LLMWIKI/公事原件")
    for line, kind in bad.items():
        assert [k for _, k, _ in scan_text(line, "Wiki_Pages/群組/頁.md", raw=raw)][0].startswith(kind), line
    good = ["## 第一章-概論", "## AI導入", "見[章](#ai導入)", "- [資訊安全/某頁](../資訊安全/某頁.md) — 進階：x",
            "- [某頁](某頁.md) — 對比：x", "教學:不要寫 `[[名稱]]`", "- [外部](https://x.md) — 參考"]
    for line in good:
        assert scan_text(line, "Wiki_Pages/群組/頁.md") == [], line
    assert scan_text("```mermaid\nA[[\"六角形\"]]\n```", "Wiki_Pages/群組/頁.md") == []   # Mermaid 不是 wikilink
    assert scan_text("見 [[某頁]]\n## 第一章：概論", "memory/x.md") == []                 # memory/ 不受約束
    assert [k for _, k, _ in scan_text("LLMWIKI\\公事原件\\a", "memory/x.md", raw=raw)] == ["來源路徑帶磁碟前綴"]


def test_index_summaries_over_400_characters_are_reported():
    line = "- [群組/頁](群組/頁.md) — 單位 2026-10：" + "字" * 400
    (( _, kind, _),) = scan_text(line, "Wiki_Pages/index.md")
    assert kind == "index 摘要 411 字(上限 400)"
    assert scan_text(line[:200], "Wiki_Pages/index.md") == []
    assert scan_text("- [某頁](某頁.md) — 延伸", "Wiki_Pages/index.md") == []   # index 的摘要行不是相關連結


TABLE_PAGE = """# 統計

## 統計摘要

**依廠商**：

| 廠商 | 筆數 | 含稅合計 | 佔合計 |
|---|---:|---:|---:|
| 甲 | 2 | 1,000 | 33.3% |
| 乙 | **1** | 2,000元 | 66.7% |
| 丙 | — | — | — |
| **合計** | **3** | **3,500** | **100%** |

## 分攤

| 單位 | 金額 |
|---|---:|
| 一處 | 100 |
| 臺北小計 | 100 |
| 臺中小計 | 50 |
| 總計 | 150 |

```
| 程式碼 | 1 |
|---|---|
```
"""


def test_table_sums_add_up_columns_and_check_the_total_row(repo):
    """請款統計表要「用腳本 assert 重算」:python 不開放,改由這裡加總、比對合計列。"""
    (repo / "Wiki_Pages" / "統計.md").write_text(TABLE_PAGE, encoding="utf-8")
    out = table_sums(repo, "Wiki_Pages/統計.md").splitlines()
    assert out[0] == "第 7 行〈統計 > 統計摘要〉**依廠商**：:3 列、1 列合計"
    assert out[1] == "  筆數:加總 3(另有 1 格不是數字、沒算進去),合計列相符"
    assert out[2] == "  含稅合計:加總 3,000(另有 1 格不是數字、沒算進去),⚠️ 合計列寫 3,500、差 500"
    assert out[3] == "  佔合計:加總 100.0%(另有 1 格不是數字、沒算進去),合計列相符"
    assert out[4] == "  佔比欄 佔合計:= 含稅合計 ÷ 3,000,2 列全部相符"   # 合計列寫錯(3,500),各列加總當分母
    assert out[5] == "第 16 行〈統計 > 分攤〉:1 列、另有 2 列小計、1 列合計"
    assert out[6] == "  金額:加總 100,合計列與小計列的加總相符"
    assert len(out) == 7                                                   # 程式碼區塊裡的表不算
    assert table_sums(repo, "Wiki_Pages/統計.md", "分攤").splitlines()[0].startswith("第 16 行")
    assert table_sums(repo, "Wiki_Pages/統計.md", "依廠商").splitlines()[0].startswith("第 7 行")   # 表前的粗體標示
    assert "沒有表格" in table_sums(repo, "Wiki_Pages/統計.md", "不存在")
    with pytest.raises(PageToolError):
        table_sums(repo, "../外面.md")


def test_rounded_percentages_within_rounding_error_are_not_flagged(repo):
    (repo / "Wiki_Pages" / "比例.md").write_text(
        "| 單位 | 佔比 |\n|---|---:|\n| 甲 | 33.3% |\n| 乙 | 33.3% |\n| 丙 | 33.3% |\n| 合計 | 100% |\n",
        encoding="utf-8")
    assert "在四捨五入誤差內" in table_sums(repo, "Wiki_Pages/比例.md")


def test_percent_column_is_checked_row_by_row_against_its_base_column(repo):
    """佔比欄逐列驗算(2026-10-08、10-15 攝入要「用腳本重算佔比」做不到,只能人工逐格算、寫成未驗)。
    兩個金額欄只差一列(含稅 vs 期貨負擔):要認得出是哪一欄的佔比;分母有合計列就用合計列。"""
    page = repo / "Wiki_Pages" / "請款.md"
    page.write_text(
        "| 廠商 | 含稅 | 期貨負擔 | 佔比 |\n|---|---:|---:|---:|\n"
        "| 中華電信 | 6,000 | 6,000 | 60.0% |\n| 三竹 | 3,000 | 1,000 | 30.0% |\n| 其他 | 1,000 | 1,000 | 10.0% |\n"
        "| **合計** | **10,000** | **8,000** | **100.0%** |\n", encoding="utf-8")
    assert "佔比欄 佔比:= 含稅 ÷ 10,000,3 列全部相符" in table_sums(repo, "Wiki_Pages/請款.md")

    page.write_text(page.read_text(encoding="utf-8").replace("| 10.0% |", "| 11.0% |"), encoding="utf-8")
    out = table_sums(repo, "Wiki_Pages/請款.md")
    assert "⚠️ 佔比欄 佔比:最接近 含稅 ÷ 10,000,1 列不符:其他 寫 11.0%、算出 10.0%" in out

    # 四捨五入:1/3 寫成 33.3% 算相符;沒有合計列就用各列加總當分母
    page.write_text("| 單位 | 金額 | 佔比 |\n|---|---:|---:|\n| 甲 | 1 | 33.3% |\n| 乙 | 1 | 33.3% |\n"
                    "| 丙 | 1 | 33.4% |\n", encoding="utf-8")
    assert "3 列全部相符" in table_sums(repo, "Wiki_Pages/請款.md")


def test_agreed_ratios_and_outside_denominators_are_not_flagged(repo):
    """公事庫的分攤表多半有「約定比例」欄(26%、44%,不是算出來的),「佔期貨負擔」的分母寫在表外:
    這兩種報 ⚠️ 的話,claude 會去「改正」對的表(2026-10-16 用真的請款統計頁試出 70 多張這種表)。"""
    page = repo / "Wiki_Pages" / "分攤.md"
    page.write_text("| 單位 | 原比例 | 金額 |\n|---|---:|---:|\n| 甲 | 30% | 500 |\n| 乙 | 50% | 120 |\n"
                    "| 丙 | 20% | 999 |\n| 丁 | 0% | 0 |\n", encoding="utf-8")
    out = table_sums(repo, "Wiki_Pages/分攤.md")
    assert "佔比欄 原比例:對不上表上任何一欄" in out and "⚠️" not in out

    # 分母 1,250 不在表上:各列 400/32.0%、500/40.0%、350/28.0% 反推出同一個範圍
    page.write_text("| 單位 | 金額 | 佔期貨 |\n|---|---:|---:|\n| 甲 | 400 | 32.0% |\n| 乙 | 500 | 40.0% |\n"
                    "| 丙 | 350 | 28.0% |\n| 扣回 | -100 | — |\n", encoding="utf-8")
    out = table_sums(repo, "Wiki_Pages/分攤.md")
    assert "佔比欄 佔期貨:= 金額 ÷ 表上沒有的分母(各列反推約 1,247～1,253),3 列一致" in out
