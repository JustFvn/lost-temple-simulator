#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fall Guys「Lost Temple」佈局資料萃取器
=====================================

從 losttemple.app 的前端 bundle 中萃取全部 125 種真實迷宮佈局，
驗證資料一致性後，輸出可直接內嵌進 index.html 的壓縮 JS 陣列。

用法:
    python extract_layouts.py                 # 從網路抓取
    python extract_layouts.py path/to/main.js # 用本機檔案
    python extract_layouts.py --emit          # 只印出 JS 資料區塊

盤面約定（與原站 ci(row,col) 完全一致）:
    row 0 在最上面 = E 排, row 4 在最下面 = A 排
    col 0 在最左邊 = 1,    col 4 在最右邊 = 5
    起點固定 A3 (row 4, col 2), 終點固定 E3 (row 0, col 2)
"""

import collections
import re
import sys
import urllib.request

SITE = "https://losttemple.app/"
LAYOUT_RE = re.compile(
    r"\{key:(\d+),"
    r"openDoors:new Set\(\[(.*?)\]\),"
    r"openRooms:new Set\(\[(.*?)\]\),"
    r"percent:([0-9.e+-]+)\}"
)
ROOM_RE = re.compile(r'"([A-E][1-5])"')
DOOR_RE = re.compile(r'"([A-E][1-5],[A-E][1-5])"')

START, GOAL = "A3", "E3"
# 這道門在 125 種佈局中一次都沒出現，原站的繪圖程式也把它排除 -> 永久實牆
NEVER_A_DOOR = "A3,B3"


def room_name(row, col):
    """row 0 = E 排（最上）, row 4 = A 排（最下）; col 0 = 第 1 欄（最左）。"""
    return chr(ord("E") - row) + str(col + 1)


def door_name(a, b):
    return ",".join(sorted((a, b)))


def build_door_table():
    """回傳 (doors, index_of)。doors[i] = [r1, c1, r2, c2]，索引即門 id。"""
    doors, index_of = [], {}
    for row in range(5):  # 左右相鄰的門
        for col in range(4):
            doors.append((row, col, row, col + 1))
    for row in range(4):  # 上下相鄰的門
        for col in range(5):
            if door_name(room_name(row, col), room_name(row + 1, col)) == NEVER_A_DOOR:
                continue
            doors.append((row, col, row + 1, col))
    for i, (r1, c1, r2, c2) in enumerate(doors):
        index_of[door_name(room_name(r1, c1), room_name(r2, c2))] = i
    return doors, index_of


def fetch_bundle(source=None):
    if source and not source.startswith("http"):
        with open(source, encoding="utf-8") as fh:
            return fh.read()
    with urllib.request.urlopen(SITE) as resp:
        html = resp.read().decode("utf-8")
    match = re.search(r'src="(/static/js/main\.[0-9a-f]+\.js)"', html)
    if not match:
        raise SystemExit("找不到 main.js 的路徑，網站結構可能已改變。")
    url = SITE.rstrip("/") + match.group(1)
    print(f"抓取 {url}")
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8")


def parse(bundle, index_of):
    layouts = []
    for key, doors_src, rooms_src, percent in LAYOUT_RE.findall(bundle):
        names = DOOR_RE.findall(doors_src)
        layouts.append(
            {
                "key": int(key),
                "doors": names,
                "ids": sorted(index_of[n] for n in names),
                "rooms": set(ROOM_RE.findall(rooms_src)),
                "percent": float(percent),
            }
        )
    layouts.sort(key=lambda item: item["key"])
    return layouts


def validate(layouts, index_of):
    problems = []

    if len(layouts) != 125:
        problems.append(f"筆數應為 125，實得 {len(layouts)}")
    if [item["key"] for item in layouts] != list(range(len(layouts))):
        problems.append("key 不是連續的 0..124")

    total = sum(item["percent"] for item in layouts)
    if abs(total - 1.0) > 1e-6:
        problems.append(f"機率總和應為 1.0，實得 {total!r}")

    for item in layouts:
        key = item["key"]
        touched, graph = set(), collections.defaultdict(set)

        for name in item["doors"]:
            if name == NEVER_A_DOOR:
                problems.append(f"#{key}: 出現了不該存在的門 {NEVER_A_DOOR}")
            if name not in index_of:
                problems.append(f"#{key}: 門 {name} 連接的兩房並不相鄰")
                continue
            a, b = name.split(",")
            touched.update((a, b))
            graph[a].add(b)
            graph[b].add(a)

        if touched != item["rooms"]:
            problems.append(f"#{key}: openRooms 與門所觸及的房間不符")
        if START not in item["rooms"] or GOAL not in item["rooms"]:
            problems.append(f"#{key}: 缺少 {START} 或 {GOAL}")
            continue

        seen, stack = {START}, [START]
        while stack:
            node = stack.pop()
            for nxt in graph[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if GOAL not in seen:
            problems.append(f"#{key}: {START} 走不到 {GOAL}")
        elif seen != item["rooms"]:
            problems.append(f"#{key}: 有與起點不連通的孤立房間")

    return problems


def shortest_steps(item):
    graph = collections.defaultdict(set)
    for name in item["doors"]:
        a, b = name.split(",")
        graph[a].add(b)
        graph[b].add(a)
    dist, queue = {START: 0}, collections.deque([START])
    while queue:
        node = queue.popleft()
        for nxt in graph[node]:
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
    return dist.get(GOAL, -1)


def emit(doors, layouts):
    lines = ["// 由 extract_layouts.py 從 losttemple.app 萃取，請勿手動編輯。"]
    lines.append("// DOORS[i] = [r1, c1, r2, c2]（row 0 = E 排在最上，col 0 = 第 1 欄在最左）")
    lines.append("const DOORS = [")
    for row in range(0, len(doors), 8):
        chunk = ", ".join("[%d,%d,%d,%d]" % d for d in doors[row : row + 8])
        lines.append("  " + chunk + ",")
    lines.append("];")
    lines.append("")
    lines.append("// LAYOUTS[key] = [出現機率, [開啟的門 id, ...]]")
    lines.append("const LAYOUTS = [")
    for item in layouts:
        ids = ",".join(str(i) for i in item["ids"])
        lines.append("  [%.10g,[%s]]," % (item["percent"], ids))
    lines.append("];")
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if a != "--emit"]
    emit_only = "--emit" in sys.argv

    doors, index_of = build_door_table()
    layouts = parse(fetch_bundle(args[0] if args else None), index_of)
    problems = validate(layouts, index_of)

    if problems:
        print("\n驗證失敗：")
        for line in problems:
            print("  - " + line)
        raise SystemExit(1)

    if emit_only:
        print(emit(doors, layouts))
        return

    steps = collections.Counter(shortest_steps(item) for item in layouts)
    print(f"\n125 layouts OK")
    print(f"  門位數量        : {len(doors)}（40 個相鄰組合扣掉永久實牆 {NEVER_A_DOOR}）")
    print(f"  機率總和        : {sum(i['percent'] for i in layouts):.12f}")
    print(f"  連通性 / 相鄰性 : 全部通過（每局 {START} 均可走到 {GOAL}，且無孤立房）")
    print(f"  最短步數分布    : {dict(sorted(steps.items()))}")
    print("\n用 --emit 輸出可貼進 index.html 的 JS 資料區塊。")


if __name__ == "__main__":
    main()
