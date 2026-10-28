#!/usr/bin/env python3
"""体测成绩分析：学生体质健康测试 CSV → 单项得分 / 总分 / 等级 / 班级报告。

用法：
  python tools/fitness_analyzer.py data/sample_students.csv
  python tools/fitness_analyzer.py 我的班级.csv --standards data/standards_sample.json --out 输出目录

输入 CSV 列：学号,姓名,性别,年级，身高cm，体重kg（自动算 BMI），其余列名与标准表项目名一致即可
（肺活量、50米跑、坐位体前屈、立定跳远、1分钟跳绳、1分钟仰卧起坐、引体向上、50米x8往返跑、800米跑、1000米跑）。
耐力跑成绩支持 245 / 4:05 / 4'05" / 4分05秒 四种写法。

注意：内置为示例评分表（节选整理），正式上报前请对照官方最新标准替换 standards 文件。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))


def parse_time(v) -> float:
    """把 4:05 / 4'05" / 4分05秒 / 245 统一成秒（或原样数值）。"""
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip().replace("：", ":").replace("′", "'").replace("″", '"')
    try:
        return float(s)
    except ValueError:
        pass
    import re
    m = re.match(r"^(?:(\d+)\s*[:'分])?\s*(\d+(?:\.\d+)?)\s*(?:\"|秒)?$", s)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    raise ValueError(f"无法解析成绩：{v}")


def score_points(breakpoints: list, value: float) -> float:
    """breakpoints: [[成绩, 分值], ...]，线性插值，自动识别高优/低优。"""
    pts = sorted(([float(p), float(s)] for p, s in breakpoints), key=lambda x: x[0])
    if value <= pts[0][0]:
        lo_perf, hi_perf = (pts[0], pts[1]) if len(pts) > 1 else (pts[0], pts[0])
        if lo_perf[1] >= hi_perf[1]:  # 低优项目：比最好还好 → 满分
            return pts[0][1]
        return _interp(pts[0], pts[1] if len(pts) > 1 else pts[0], value)
    if value >= pts[-1][0]:
        if pts[-1][1] >= pts[-2][1]:
            return pts[-1][1]
        return max(0.0, _interp(pts[-2], pts[-1], value))
    for a, b in zip(pts, pts[1:]):
        if a[0] <= value <= b[0]:
            return _interp(a, b, value)
    return pts[-1][1]


def _interp(a, b, v) -> float:
    if b[0] == a[0]:
        return b[1]
    t = (v - a[0]) / (b[0] - a[0])
    return a[1] + t * (b[1] - a[1])


def score_bmi(bands: list, bmi: float) -> float:
    for lo, hi, score in bands:
        if float(lo) <= bmi < float(hi) or (float(hi) >= 99 and bmi >= float(lo)):
            return float(score)
    return 60.0


def level_of(total: float) -> str:
    if total >= 90:
        return "优秀"
    if total >= 80:
        return "良好"
    if total >= 60:
        return "及格"
    return "不及格"


def analyze(students: list[dict], standards: dict) -> list[dict]:
    results = []
    for st in students:
        grade = st.get("年级", "").strip()
        gender = st.get("性别", "").strip()
        gtable = (standards.get(grade) or {}).get(gender)
        if not gtable:
            results.append({**st, "error": f"标准表缺少 {grade}/{gender}"})
            continue
        weights = standards[grade].get("权重", {})
        scores: dict[str, float] = {}
        # BMI
        try:
            h = float(st.get("身高cm") or 0) / 100
            w = float(st.get("体重kg") or 0)
            if h > 0 and w > 0:
                bmi = w / (h * h)
                st["BMI值"] = round(bmi, 1)
                spec = gtable.get("BMI")
                if isinstance(spec, dict) and spec.get("type") == "bands":
                    scores["BMI"] = score_bmi(spec["bands"], bmi)
        except ValueError:
            pass
        for item, spec in gtable.items():
            if item == "BMI" or not isinstance(spec, list):
                continue
            raw = st.get(item)
            if raw is None or str(raw).strip() == "":
                continue
            try:
                val = parse_time(raw)
                scores[item] = round(max(0.0, min(100.0, score_points(spec, val))), 1)
            except (ValueError, TypeError):
                continue
        wsum = sum(weights.get(k, 10) for k in scores)
        total = round(sum(scores[k] * weights.get(k, 10) for k in scores) / wsum, 1) if scores and wsum else 0.0
        results.append({**st, "scores": scores, "total": total,
                        "level": level_of(total), "items_done": len(scores)})
    return results


def class_report(results: list[dict], title: str = "班级体测报告") -> str:
    ok = [r for r in results if "scores" in r]
    lines = [f"# {title}", ""]
    lines.append(f"总人数 {len(results)}（有效 {len(ok)}）")
    if not ok:
        return "\n".join(lines + ["", "没有可分析的数据。"])
    totals = [r["total"] for r in ok]
    lines.append(f"平均总分 **{sum(totals) / len(totals):.1f}** · 最高 {max(totals)} · 最低 {min(totals)}")
    dist = defaultdict(int)
    for r in ok:
        dist[r["level"]] += 1
    lines.append("")
    lines.append("## 等级分布")
    for lv in ("优秀", "良好", "及格", "不及格"):
        n = dist.get(lv, 0)
        lines.append(f"- {lv}：{n} 人（{n / len(ok) * 100:.0f}%）")
    lines.append(f"- 及格率：{(len(ok) - dist.get('不及格', 0)) / len(ok) * 100:.0f}% · 优秀率：{dist.get('优秀', 0) / len(ok) * 100:.0f}%")
    per_item = defaultdict(list)
    for r in ok:
        for k, v in r["scores"].items():
            per_item[k].append(v)
    lines.append("")
    lines.append("## 各项目平均分（弱项在前）")
    for k, vs in sorted(per_item.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        lines.append(f"- {k}：{sum(vs) / len(vs):.1f}（{len(vs)} 人）")
    weak = [r for r in ok if r["level"] == "不及格"]
    if weak:
        lines.append("")
        lines.append("## 需要重点关注（不及格）")
        for r in sorted(weak, key=lambda x: x["total"]):
            low = sorted(r["scores"].items(), key=lambda kv: kv[1])[:2]
            lines.append(f"- {r.get('姓名')}（{r['total']} 分）弱项：{'、'.join(f'{k} {v}' for k, v in low)}")
    top = sorted(ok, key=lambda x: -x["total"])[:3]
    lines.append("")
    lines.append("## 班级前三")
    for r in top:
        lines.append(f"- {r.get('姓名')}：{r['total']} 分（{r['level']}）")
    return "\n".join(lines)



def bar(value: float, max_value: float = 100.0, width: int = 24) -> str:
    filled = int(round(width * max(0.0, min(value, max_value)) / max_value))
    return "█" * filled + "░" * (width - filled)


def distribution_block(results: list[dict]) -> str:
    """各项目平均分条形图（文本），一眼看出全班弱项。"""
    per_item: dict[str, list] = {}
    for r in results:
        if "scores" in r:
            for k, v in r["scores"].items():
                per_item.setdefault(k, []).append(v)
    if not per_item:
        return ""
    lines = ["", "## 各项目平均分分布"]
    for k, vs in sorted(per_item.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        avg = sum(vs) / len(vs)
        lines.append(f"- {k} {bar(avg)} {avg:.1f}")
    return "\n".join(lines)


def compare_reports(old: list[dict], new: list[dict]) -> str:
    """两次体测对比（按学号匹配）：总分变化、进步/退步名单、各项目平均分变化。"""
    old_by_id = {r.get("学号"): r for r in old if "total" in r}
    new_by_id = {r.get("学号"): r for r in new if "total" in r}
    common = sorted(set(old_by_id) & set(new_by_id))
    lines = ["# 两次体测对比报告", "", f"可对比学生 {len(common)} 人（按学号匹配）"]
    if not common:
        return "\n".join(lines + ["", "没有学号可匹配的学生。"])
    diffs = []
    item_old: dict[str, list] = {}
    item_new: dict[str, list] = {}
    for sid in common:
        o, n = old_by_id[sid], new_by_id[sid]
        diffs.append((n["total"] - o["total"], n))
        for k, v in o["scores"].items():
            item_old.setdefault(k, []).append(v)
        for k, v in n["scores"].items():
            item_new.setdefault(k, []).append(v)
    avg_diff = sum(d for d, _ in diffs) / len(diffs)
    lines.append(f"全班平均总分变化：**{avg_diff:+.1f}** 分")
    lines.append("")
    lines.append("## 各项目平均分变化")
    for k in sorted(set(item_old) & set(item_new)):
        a = sum(item_old[k]) / len(item_old[k])
        b = sum(item_new[k]) / len(item_new[k])
        lines.append(f"- {k}：{a:.1f} → {b:.1f}（{b - a:+.1f}）")
    improved = sorted([d for d in diffs if d[0] > 0], key=lambda x: -x[0])[:5]
    declined = sorted([d for d in diffs if d[0] < 0], key=lambda x: x[0])[:5]
    if improved:
        lines.append("")
        lines.append("## 进步最大")
        for d, r in improved:
            lines.append(f"- {r.get('姓名')}：{old_by_id[r.get('学号')]['total']} → {r['total']}（{d:+.1f}）")
    if declined:
        lines.append("")
        lines.append("## 需要关注（退步）")
        for d, r in declined:
            lines.append(f"- {r.get('姓名')}：{old_by_id[r.get('学号')]['total']} → {r['total']}（{d:+.1f}）")
    return "\n".join(lines)


def load_students(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_scores_csv(results: list[dict], path: str):
    items = sorted({k for r in results if "scores" in r for k in r["scores"]})
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["学号", "姓名", "性别", "年级", "BMI值"] + items + ["总分", "等级"])
        for r in results:
            if "scores" in r:
                w.writerow([r.get("学号"), r.get("姓名"), r.get("性别"), r.get("年级"), r.get("BMI值", "")]
                           + [r["scores"].get(k, "") for k in items] + [r["total"], r["level"]])


def process_one(csv_path: str, standards: dict, out_dir: str) -> list[dict]:
    results = analyze(load_students(csv_path), standards)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    write_scores_csv(results, os.path.join(out_dir, f"{stem}-scores.csv"))
    report = class_report(results, title=f"体测分析报告 · {stem}") + "\n" + distribution_block(results)
    with open(os.path.join(out_dir, f"{stem}-report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return results


def main():
    ap = argparse.ArgumentParser(description="体测成绩分析（独立版：单班 / 批量多班 / 两次对比）")
    ap.add_argument("csv_path", nargs="?", default="", help="学生成绩 CSV，或包含多个 CSV 的目录（批量模式）")
    ap.add_argument("--demo", action="store_true", help="用内置示例演示（含两次对比）")
    ap.add_argument("--compare", default="", help="再给一份 CSV，与主文件做两次体测对比")
    ap.add_argument("--standards", default=os.path.join(BASE, "data", "standards_sample.json"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    with open(args.standards, encoding="utf-8") as f:
        standards = json.load(f)
    out_dir = args.out or os.path.join(BASE, "output")

    if args.demo:
        t1 = os.path.join(BASE, "data", "sample_students_t1.csv")
        t2 = os.path.join(BASE, "data", "sample_students_t2.csv")
        r1 = process_one(t1, standards, out_dir)
        r2 = process_one(t2, standards, out_dir)
        cmp_text = compare_reports(r1, r2)
        with open(os.path.join(out_dir, "compare-report.md"), "w", encoding="utf-8") as f:
            f.write(cmp_text)
        print(class_report(r2, title="第二次体测 · 班级报告"))
        print("\n" + cmp_text)
        print(f"\n全部输出在 {out_dir}/")
        return

    if not args.csv_path:
        ap.print_help()
        return
    if os.path.isdir(args.csv_path):
        files = sorted(f for f in os.listdir(args.csv_path) if f.lower().endswith(".csv"))
        print(f"批量模式：{len(files)} 个 CSV")
        for fn in files:
            process_one(os.path.join(args.csv_path, fn), standards, out_dir)
            print(f"  ✓ {fn}")
        print(f"全部输出在 {out_dir}/")
        return
    results = process_one(args.csv_path, standards, out_dir)
    print(class_report(results, title=f"体测分析报告 · {os.path.basename(args.csv_path)}"))
    if args.compare:
        other = process_one(args.compare, standards, out_dir)
        cmp_text = compare_reports(other, results)
        with open(os.path.join(out_dir, "compare-report.md"), "w", encoding="utf-8") as f:
            f.write(cmp_text)
        print("\n" + cmp_text)
    print(f"\n全部输出在 {out_dir}/")


if __name__ == "__main__":
    main()
