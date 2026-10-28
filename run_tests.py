#!/usr/bin/env python3
"""体测成绩分析（独立版）测试：python run_tests.py"""

import csv
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from fitness_analyzer import (analyze, bar, class_report, compare_reports,
                              load_students, parse_time, process_one,
                              score_bmi, score_points)

PASS = []
def check(name, cond):
    PASS.append((name, bool(cond)))
    print(("✅" if cond else "❌"), name)
    assert cond, name

std = json.load(open(os.path.join(BASE, "data", "standards_sample.json"), encoding="utf-8"))

check("时间解析", parse_time("4分05秒") == 245 and parse_time("8.6") == 8.6)
bp = std["五年级"]["男"]["50米跑"]
check("计分插值", score_points(bp, 8.0) == 100 and abs(score_points(bp, 8.2) - 95) < 0.01)
check("BMI分档", score_bmi(std["五年级"]["男"]["BMI"]["bands"], 26.0) == 60)

t1 = load_students(os.path.join(BASE, "data", "sample_students_t1.csv"))
t2 = load_students(os.path.join(BASE, "data", "sample_students_t2.csv"))
r1, r2 = analyze(t1, std), analyze(t2, std)
check("两次都出分", len(r1) == len(r2) == 12)
avg1 = sum(r["total"] for r in r1) / 12
avg2 = sum(r["total"] for r in r2) / 12
check("第二次整体进步", avg2 > avg1)
cmp_text = compare_reports(r1, r2)
check("对比报告结构", "进步最大" in cmp_text and "各项目平均分变化" in cmp_text)
by_id_1 = {r["学号"]: r for r in r1}
by_id_2 = {r["学号"]: r for r in r2}
sid = "20250101"
check("对比按学号匹配", by_id_2[sid]["total"] > by_id_1[sid]["total"])

check("条形图", bar(50, 100, 10) == "█████░░░░░" and bar(100) == "█" * 24)
rep = class_report(r2)
check("班级报告", "等级分布" in rep and "需要重点关注" in rep)

out = tempfile.mkdtemp()
res = process_one(os.path.join(BASE, "data", "sample_students_t2.csv"), std, out)
files = os.listdir(out)
check("单班输出文件", any(f.endswith("-scores.csv") for f in files) and any(f.endswith("-report.md") for f in files))

r = subprocess.run([sys.executable, os.path.join(BASE, "fitness_analyzer.py"), "--demo",
                    "--out", tempfile.mkdtemp()], capture_output=True, text=True)
check("CLI演示（含对比）", r.returncode == 0 and "两次体测对比" in r.stdout)

print(f"\n全部 {len(PASS)} 项测试通过 ✅" if all(c for _, c in PASS) else "\n存在失败 ❌")
