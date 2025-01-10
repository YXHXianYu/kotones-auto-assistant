import os
from typing import NamedTuple, Protocol, TypeVar, Sequence, runtime_checkable
from logging import getLogger

from .debug import result, debug, img

import cv2
import numpy as np
from cv2.typing import MatLike, Rect, Point, Size

logger = getLogger(__name__)

class TemplateNotFoundError(Exception):
    """模板未找到异常。"""
    def __init__(self, image: MatLike, template: MatLike | str):
        self.image = image
        self.template = template
        super().__init__(f"Template not found: {template}")

@runtime_checkable
class ResultProtocol(Protocol):
    @property
    def rect(self) -> Rect:
        """结果区域。左上角坐标和宽高。"""
        ...


class TemplateMatchResult(NamedTuple):
    score: float
    position: Point
    """结果位置。左上角坐标。"""
    size: Size
    """输入模板的大小。宽高。"""

    @property
    def rect(self) -> Rect:
        """结果区域。左上角坐标和宽高。"""
        return (self.position[0], self.position[1], self.size[0], self.size[1])
    
    @property
    def right_bottom(self) -> Point:
        """结果右下角坐标。"""
        return (self.position[0] + self.size[0], self.position[1] + self.size[1])

class MultipleTemplateMatchResult(NamedTuple):
    score: float
    position: Point
    """结果位置。左上角坐标。"""
    size: Size
    """命中模板的大小。宽高。"""
    index: int
    """命中模板在列表中的索引。"""

    @property
    def rect(self) -> Rect:
        """结果区域。左上角坐标和宽高。"""
        return (self.position[0], self.position[1], self.size[0], self.size[1])
    
    @property
    def right_bottom(self) -> Point:
        """结果右下角坐标。"""
        return (self.position[0] + self.size[0], self.position[1] + self.size[1])

class CropResult(NamedTuple):
    score: float
    position: Point
    size: Size
    image: MatLike

    @property
    def rect(self) -> Rect:
        return (self.position[0], self.position[1], self.size[0], self.size[1])

def _unify_image(image: MatLike | str) -> MatLike:
    if isinstance(image, str):
        image = cv2.imread(image)
    return image

T = TypeVar('T')
# TODO: 这个方法太慢了，需要优化
def _remove_duplicate_matches(
        matches: list[T],
        offset: int = 10
    ) -> list[T]:
    result = []
    # TODO: 解决这个函数的 typing 问题
    for match in matches:
        if any(abs(match.position[0] - r.position[0]) < offset for r in result): # type: ignore
            continue
        result.append(match)
    return result

def _draw_result(image: MatLike, matches: Sequence[ResultProtocol] | ResultProtocol | None) -> MatLike:
    if matches is None:
        return image
    if isinstance(matches, ResultProtocol):
        matches = [matches]
    result_image = image.copy()
    for match in matches:
        cv2.rectangle(result_image, match.rect, (0, 0, 255), 2)
    return result_image

def template_match(
    template: MatLike | str,
    image: MatLike | str,
    mask: MatLike | str | None = None,
    transparent: bool = False,
    threshold: float = 0.8,
    max_results: int = 5,
    remove_duplicate: bool = True,
) -> list[TemplateMatchResult]:
    """
    寻找模板在图像中的位置。

    .. note::
        `mask` 和 `transparent` 参数不能同时使用。

    :param template: 模板图像，可以是图像路径或 cv2.Mat。
    :param image: 图像，可以是图像路径或 cv2.Mat。
    :param mask: 掩码图像，可以是图像路径或 cv2.Mat。
    :param transparent: 若为 True，则认为输入模板是透明的，并自动将透明模板转换为 Mask 图像。
    :param threshold: 阈值，默认为 0.8。
    :param max_results: 最大结果数，默认为 1。
    :param remove_duplicate: 是否移除重复结果，默认为 True。
    """
    if isinstance(template, str):
        _template_name = os.path.relpath(template)
    else:
        _template_name = '<opencv Mat>'
    logger.debug(f'match template: {_template_name} threshold: {threshold} max_results: {max_results}')
    # 统一参数
    template = _unify_image(template)
    image = _unify_image(image)
    if mask is not None:
        mask = _unify_image(mask)
        mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)[1]
    
    # 匹配模板
    if mask is not None:
        # https://stackoverflow.com/questions/35642497/python-opencv-cv2-matchtemplate-with-transparency
        # 使用 Mask 时，必须使用 TM_CCORR_NORMED 方法
        result = cv2.matchTemplate(image, template, cv2.TM_CCORR_NORMED, mask=mask)
    else:
        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    # 获取所有大于阈值的匹配结果
    locations = list(zip(*np.where(result >= threshold)))
    
    # 转换为 TemplateMatchResult 列表
    matches = []
    for y, x in locations:
        h, w = template.shape[:2]
        score = float(result[y, x])
        matches.append(TemplateMatchResult(score=score, position=(int(x), int(y)), size=(int(w), int(h))))
    
    # 按分数排序并限制结果数量
    matches.sort(key=lambda x: x.score, reverse=True)
    if max_results > 0:
        matches = matches[:max_results]
        
    return matches

def find_crop(
    image: MatLike | str,
    template: MatLike | str,
    mask: MatLike | str | None = None,
    transparent: bool = False,
    threshold: float = 0.8,
) -> list[CropResult]:
    """
    使用 Mask 寻找指定图像，并裁剪出结果。
    """
    matches = template_match(template, image, mask, transparent, threshold, max_results=-1)
    matches = _remove_duplicate_matches(matches)
    return [CropResult(
        match.score,
        match.position,
        match.size,
        image[match.rect[1]:match.rect[1]+match.rect[3], match.rect[0]:match.rect[0]+match.rect[2]] # type: ignore
    ) for match in matches]

def find(
    image: MatLike,
    template: MatLike | str,
    mask: MatLike | str | None = None,
    transparent: bool = False,
    threshold: float = 0.8,
    *,
    debug_output: bool = True,
) -> TemplateMatchResult | None:
    """寻找一个模板图像"""
    matches = template_match(template, image, mask, transparent, threshold, max_results=-1)
    # 调试输出
    if debug.enabled and debug_output:
        result_image = _draw_result(image, matches)
        result_text = f"template: {img(template)} \n"
        result_text += f"matches: {len(matches)} \n"
        for match in matches:
            result_text += f"score: {match.score} position: {match.position} size: {match.size} \n"
        result(f"image.find", result_image, result_text)
    return matches[0] if len(matches) > 0 else None

def find_any(
    image: MatLike,
    templates: list[MatLike | str],
    masks: list[MatLike | str | None] | None = None,
    transparent: bool = False,
    threshold: float = 0.8,
) -> MultipleTemplateMatchResult | None:
    """指定多个模板，返回第一个匹配到的结果"""
    ret = None
    if masks is None:
        _masks = [None] * len(templates)
    else:
        _masks = masks
    for index, (template, mask) in enumerate(zip(templates, _masks)):
        find_result = find(image, template, mask, transparent, threshold, debug_output=False)
        # 调试输出
        if find_result is not None:
            ret = MultipleTemplateMatchResult(
                score=find_result.score,
                position=find_result.position,
                size=find_result.size,
                index=index
            )
            break
    if debug.enabled:
        msg = (
            "<table class='result-table'>" +
            "<tr><th>Template</th><th>Mask</th><th>Result</th></tr>" +
            "\n".join([
                f"<tr><td>{img(t)}</td><td>{img(m)}</td><td>{'✓' if ret and t == templates[0] else '✗'}</td></tr>"
                for t, m in zip(templates, _masks)
            ]) +
            "</table>\n"
        )
        result(
            'image.find_any',
            _draw_result(image, ret),
            msg
        )
    return ret

def count(
    image: MatLike,
    template: MatLike | str,
    mask: MatLike | str | None = None,
    transparent: bool = False,
    threshold: float = 0.9,
    remove_duplicate: bool = True,
) -> int:
    results = template_match(template, image, mask, transparent, threshold, max_results=-1)
    if remove_duplicate:
        results = _remove_duplicate_matches(results)
    if debug.enabled:
        result_image = _draw_result(image, results)
        result(
            'image.count',
            result_image,
            (
                f"template: {img(template)} \n"
                f"mask: {img(mask)} \n"
                f"transparent: {transparent} \n"
                f"threshold: {threshold} \n"
                f"count: {len(results)} \n"
            )
        )
    return len(results)

def expect(
    image: MatLike,
    template: MatLike | str,
    mask: MatLike | str | None = None,
    transparent: bool = False,
    threshold: float = 0.9,
) -> TemplateMatchResult:
    ret = find(image, template, mask, transparent, threshold)
    if debug.enabled:
        result(
            'image.expect',
            _draw_result(image, ret),
            (
                f"template: {img(template)} \n"
                f"mask: {img(mask)} \n"
                f"args: transparent={transparent} threshold={threshold} \n"
                f"result: {ret}  "
                '<span class="text-success">SUCCESS</span>' if ret is not None 
                    else '<span class="text-danger">FAILED</span>'
            )
        )
    if ret is None:
        raise TemplateNotFoundError(image, template)
    else:
        return ret

