"""Merge characters.md and storyboard.md into per-shot generation prompts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_STYLE = "竖屏 9:16 短剧，写实风格，电影感布光"

_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_STYLE_RE = re.compile(r"^风格基调[：:]\s*(.+)$", re.MULTILINE)
_SHOT_RE = re.compile(r"镜头\s*(\d+)")
_FIELD_RE = re.compile(r"^-\s*(\S+?)\s*[：:]\s*(.*)$")


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) pairs at '## ' headings."""
    matches = list(_HEADING_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1).strip(), text[match.end() : end].strip()))
    return blocks


def _parse_settings(path: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    """Read characters.md: style line plus 角色/场景 blocks keyed by name."""
    text = path.read_text(encoding="utf-8")
    style_match = _STYLE_RE.search(text)
    style = style_match.group(1).strip() if style_match else DEFAULT_STYLE
    characters: dict[str, str] = {}
    scenes: dict[str, str] = {}
    for heading, body in _blocks(text):
        for prefix, target in (("角色", characters), ("场景", scenes)):
            if heading.startswith(prefix):
                name = heading[len(prefix) :].lstrip("：:").strip()
                target[name] = body
    return style, characters, scenes


def _parse_shots(path: Path) -> list[dict[str, str]]:
    """Read storyboard.md: one dict per '## 镜头 NN' block with its '- 字段：值'."""
    shots = []
    for heading, body in _blocks(path.read_text(encoding="utf-8")):
        match = _SHOT_RE.match(heading)
        if not match:
            continue
        fields = {}
        for line in body.splitlines():
            field = _FIELD_RE.match(line.strip())
            if field:
                fields[field.group(1)] = field.group(2).strip()
        shots.append({"number": match.group(1), **fields})
    return shots


def _prompt(style: str, characters: dict[str, str], scenes: dict[str, str], shot: dict[str, str]) -> str:
    """Assemble one shot's prompt: global style + all settings + this shot."""
    parts = [style]
    if characters:
        roster = "\n\n".join(f"{name}：\n{body}" for name, body in characters.items())
        parts.append(f"【角色设定】\n{roster}")
    if scenes:
        sets = "\n\n".join(f"{name}：\n{body}" for name, body in scenes.items())
        parts.append(f"【场景设定】\n{sets}")
    shot_text = f"【本镜头】{shot.get('景别', '')}，{shot.get('运镜', '')}。{shot.get('画面', '')}"
    if shot.get("台词"):
        shot_text += f"\n台词：{shot['台词']}"
    parts.append(shot_text)
    return "\n\n".join(parts)


def _warnings(shots: list[dict[str, str]], characters: dict[str, str]) -> list[str]:
    """Consistency checks worth surfacing before the user generates clips."""
    warnings = []
    if not characters:
        warnings.append("characters.md 没有任何「## 角色：」块，提示词缺少角色一致性约束")
    used = " ".join(f"{shot.get('画面', '')} {shot.get('台词', '')}" for shot in shots)
    for name in characters:
        if name not in used:
            warnings.append(f"角色「{name}」已设定但分镜中从未出现")
    for shot in shots:
        for field in ("画面", "时长"):
            if not shot.get(field):
                warnings.append(f"镜头 {shot['number']} 缺少字段：{field}")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="把角色设定与分镜合成逐镜头提示词")
    parser.add_argument("directory", help="项目目录路径")
    args = parser.parse_args()
    root = Path(args.directory)

    for required in ("characters.md", "storyboard.md"):
        if not (root / required).is_file():
            print(f"缺少 {required}，请先完成前置步骤", file=sys.stderr)
            return 1

    style, characters, scenes = _parse_settings(root / "characters.md")
    shots = _parse_shots(root / "storyboard.md")
    if not shots:
        print("storyboard.md 里没有解析到任何「## 镜头 NN」块", file=sys.stderr)
        return 1

    prompts_dir = root / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    for shot in shots:
        number = int(shot["number"])
        path = prompts_dir / f"shot-{number:02d}.txt"
        path.write_text(_prompt(style, characters, scenes, shot) + "\n", encoding="utf-8")
        print(f"已生成：{path}")

    warnings = _warnings(shots, characters)
    print(f"\n共 {len(shots)} 个镜头。" + ("检查通过。" if not warnings else "注意："))
    for warning in warnings:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
