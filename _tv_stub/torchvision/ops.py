"""torchvision.ops 桩：提供纯 torch 实现的 nms，语义与 torchvision.ops.nms 一致。"""
import torch


def nms(boxes, scores, iou_threshold):
    """纯 torch 的非极大值抑制。

    Args:
        boxes (torch.Tensor): shape (N,4)，坐标为 xyxy。
        scores (torch.Tensor): shape (N,)，每个框的置信度。
        iou_threshold (float): IoU 阈值。
    Returns:
        torch.Tensor: 保留框的索引（按 scores 降序后的保留集合），dtype=long。
    """
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.long, device=boxes.device)

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    order = scores.argsort(descending=True)
    keep = []

    while order.numel() > 0:
        i = order[0]
        keep.append(i.item())
        if order.numel() == 1:
            break
        rest = order[1:]
        xx1 = torch.maximum(x1[i], x1[rest])
        yy1 = torch.maximum(y1[i], y1[rest])
        xx2 = torch.minimum(x2[i], x2[rest])
        yy2 = torch.minimum(y2[i], y2[rest])
        w = (xx2 - xx1).clamp(min=0)
        h = (yy2 - yy1).clamp(min=0)
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]

    return torch.tensor(keep, dtype=torch.long, device=boxes.device)
