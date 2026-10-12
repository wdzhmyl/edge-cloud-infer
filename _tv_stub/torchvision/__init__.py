"""最小 torchvision 桩，仅提供 ultralytics 后处理所需的 ops.nms（纯 torch 实现）。

仅用于在无法安装 CPU 版 torchvision 的沙箱环境里让 YOLO 推理跑通。
不要把本目录加入生产环境的 PYTHONPATH。
"""

__version__ = "0.0.0-stub"

# 让 `torchvision.ops` 可作为属性访问（真实 torchvision 也会在 __init__ 里导入 ops）
from torchvision import ops  # noqa: F401
