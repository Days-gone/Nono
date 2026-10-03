"""Scaffold an AI short-drama project: directories and template files."""

from __future__ import annotations

import argparse
from pathlib import Path

SCRIPT_TEMPLATE = """# 《{title}》剧本

## 场景 1：<地点> · <时间>

人物：<出场角色>

<动作描述>

**<角色名>**：<台词>

"""

CHARACTERS_TEMPLATE = """# 角色与场景设定

风格基调：<如：写实、电影感、冷色调>

## 角色：<角色名>

- 外貌：<年龄感、脸型、发型发色、标志特征——具体，禁模糊词>
- 服装：<标志性服装>
- 气质：<神态、举止>

## 场景：<场景名>

- 环境：<时代、地点、光线、关键道具>
"""

STORYBOARD_TEMPLATE = """# 《{title}》分镜脚本

## 镜头 01

- 景别：<特写/近景/中景/全景>
- 运镜：<固定/推/拉/摇/移/跟>
- 画面：<画面描述，出现角色名>
- 台词：<无台词则留空>
- 时长：5
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 AI 短剧项目目录")
    parser.add_argument("directory", help="项目目录路径")
    parser.add_argument("--title", default="未命名短剧", help="短剧标题")
    args = parser.parse_args()

    root = Path(args.directory)
    for sub in ("prompts", "clips", "output"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    templates = {
        "script.md": SCRIPT_TEMPLATE.format(title=args.title),
        "characters.md": CHARACTERS_TEMPLATE,
        "storyboard.md": STORYBOARD_TEMPLATE.format(title=args.title),
    }
    for filename, content in templates.items():
        path = root / filename
        if path.exists():
            print(f"跳过（已存在）：{path}")
            continue
        path.write_text(content, encoding="utf-8")
        print(f"已创建：{path}")

    print(f"\n项目就绪：{root.resolve()}")
    print("接下来填写 script.md（剧本）→ characters.md（设定）→ storyboard.md（分镜），"
          "然后运行 make_prompts.py 合成提示词。")


if __name__ == "__main__":
    main()
