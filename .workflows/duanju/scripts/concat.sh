#!/usr/bin/env bash
# Concatenate clips/shot-*.mp4 into output/final.mp4, in shot order.
# Assumes all clips share codec settings (same generator, same parameters).
set -euo pipefail

project="${1:?用法: concat.sh <项目目录>}"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "未找到 ffmpeg：请先安装并加入 PATH（Windows 可用 winget install ffmpeg）" >&2
    exit 1
fi

shopt -s nullglob
clips=("$project"/clips/shot-*.mp4)
if [ ${#clips[@]} -eq 0 ]; then
    echo "clips/ 里没有 shot-*.mp4，请先生成片段" >&2
    exit 1
fi

list="$project/clips/.concat.txt"
: > "$list"
for f in "${clips[@]}"; do
    printf "file '%s'\n" "$(realpath "$f")" >> "$list"
done

mkdir -p "$project/output"
ffmpeg -y -f concat -safe 0 -i "$list" -c copy "$project/output/final.mp4"
rm -f "$list"
echo "已合成：$project/output/final.mp4（${#clips[@]} 个片段）"
