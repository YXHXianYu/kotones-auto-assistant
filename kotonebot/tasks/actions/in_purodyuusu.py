import logging
from typing_extensions import deprecated
from typing import Generic, Iterable, Literal, NamedTuple, Callable, Generator, TypeVar, ParamSpec, cast

import cv2
import numpy as np
from cv2.typing import MatLike

from kotonebot.backend.context.context import use_screenshot

from .. import R
from . import loading
from ..common import conf
from .scenes import at_home
from .common import until_acquisition_clear
from kotonebot.errors import UnrecoverableError
from kotonebot.backend.util import AdaptiveWait, Countdown, crop, cropped
from kotonebot.backend.dispatch import DispatcherContext, SimpleDispatcher
from kotonebot import ocr, device, contains, image, regex, action, sleep, color, Rect
from .non_lesson_actions import (
    enter_allowance, allowance_available, study_available, enter_study,
    is_rest_available, rest
)

class SkillCard(NamedTuple):
    available: bool
    rect: Rect

logger = logging.getLogger(__name__)

ActionType = None | Literal['lesson', 'rest']
@deprecated('OCR 方法效果不佳')
def enter_recommended_action_ocr(final_week: bool = False) -> ActionType:
    """
    在行动选择页面，执行推荐行动

    :param final_week: 是否是考试前复习周
    :return: 是否成功执行推荐行动
    """
    # 获取课程
    logger.debug("Waiting for recommended lesson...")
    with cropped(device, y1=0.00, y2=0.30):
        ret = ocr.wait_for(regex('ボーカル|ダンス|ビジュアル|休|体力'))
    logger.debug("ocr.wait_for: %s", ret)
    if ret is None:
        return None
    if not final_week:
        if "ボーカル" in ret.text:
            lesson_text = "Vo"
        elif "ダンス" in ret.text:
            lesson_text = "Da"
        elif "ビジュアル" in ret.text:
            lesson_text = "Vi"
        elif "休" in ret.text or "体力" in ret.text:
            rest()
            return 'rest'
        else:
            return None
        logger.info("Rec. lesson: %s", lesson_text)
        # 点击课程
        logger.debug("Try clicking lesson...")
        lesson_ret = ocr.expect(contains(lesson_text))
        device.double_click(lesson_ret.rect)
        return 'lesson'
    else:
        if "ボーカル" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeVocal
        elif "ダンス" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeDance
        elif "ビジュアル" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeVisual
        else:
            return None
        logger.debug("Try clicking lesson...")
        device.double_click(image.expect_wait(template))
        return 'lesson'

@action('执行推荐行动')
def handle_recommended_action(final_week: bool = False) -> ActionType:
    """
    在行动选择页面，执行推荐行动

    前置条件：位于行动选择页面\n
    结束状态：
        * `lesson`：练习场景，以及中间可能出现的加载、支援卡奖励、交流等
        * `rest`：休息动画。

    :param final_week: 是否是考试前复习周
    :return: 是否成功执行推荐行动
    """
    # 获取课程
    logger.debug("Getting recommended lesson...")
    with cropped(device, y1=0.00, y2=0.30):
        result = image.find_multi([
            R.InPurodyuusu.TextSenseiTipDance,
            R.InPurodyuusu.TextSenseiTipVocal,
            R.InPurodyuusu.TextSenseiTipVisual,
            R.InPurodyuusu.TextSenseiTipRest,
        ])
    logger.debug("image.find_multi: %s", result)
    if result is None:
        logger.debug("No recommended lesson found")
        return None
    if not final_week:
        if result.index == 0:
            lesson_text = contains("Da")
        elif result.index == 1:
            lesson_text = regex("Vo|V0")
        elif result.index == 2:
            lesson_text = contains("Vi")
        elif result.index == 3:
            rest()
            return 'rest'
        else:
            return None
        logger.info("Rec. lesson: %s", lesson_text)
        # 点击课程
        logger.debug("Try clicking lesson...")
        lesson_ret = ocr.expect(lesson_text)
        device.double_click(lesson_ret.rect)
        return 'lesson'
    else:
        if result.index == 0:
            template = R.InPurodyuusu.ButtonFinalPracticeDance
        elif result.index == 1:
            template = R.InPurodyuusu.ButtonFinalPracticeVocal
        elif result.index == 2:
            template = R.InPurodyuusu.ButtonFinalPracticeVisual
        else:
            return None
        logger.debug("Try clicking lesson...")
        device.double_click(image.expect_wait(template))
        return 'lesson'

class CardDetectResult(NamedTuple):
    type: int
    """
    点击的卡片类型。

    0=第一张卡片，1=第二张卡片，2=第三张卡片，3=第四张卡片，10=SKIP。
    """
    score: float
    """总分数"""
    left_score: float
    """左边分数"""
    right_score: float
    """右边分数"""
    top_score: float
    """上边分数"""
    bottom_score: float
    """下边分数"""
    rect: Rect

def detect_recommended_card(
        card_count: int,
        threshold_predicate: Callable[[CardDetectResult], bool],
        *,
        img: MatLike | None = None,
    ):
    """
    识别推荐卡片

    前置条件：练习或考试中\n
    结束状态：-

    :param card_count: 卡片数量(2-4)
    :param threshold_predicate: 阈值判断函数
    :return: 执行结果。若返回 None，表示未识别到推荐卡片。
    """
    YELLOW_LOWER = np.array([20, 100, 100])
    YELLOW_UPPER = np.array([30, 255, 255])
    CARD_POSITIONS_1 = [
        # 格式：(x, y, w, h, return_value)
        (264, 883, 192, 252, 0)
    ]
    CARD_POSITIONS_2 = [
        (156, 883, 192, 252, 0),
        (372, 883, 192, 252, 1),
        # delta_x = 216, delta_x-width = 24
    ]
    CARD_POSITIONS_3 = [
        (47, 883, 192, 252, 0),  # 左卡片 (x, y, w, h)
        (264, 883, 192, 252, 1),  # 中卡片
        (481, 883, 192, 252, 2)   # 右卡片
        # delta_x = 217, delta_x-width = 25
    ]
    CARD_POSITIONS_4 = [
        (17, 883, 192, 252, 0),
        (182, 883, 192, 252, 1),
        (346, 883, 192, 252, 2),
        (511, 883, 192, 252, 3),
        # delta_x = 165, delta_x-width = -27
    ]
    SKIP_POSITION = (621, 739, 85, 85, 10)
    GLOW_EXTENSION = 15

    if card_count == 1:
        cards = CARD_POSITIONS_1
    elif card_count == 2:
        cards = CARD_POSITIONS_2
    elif card_count == 3:
        cards = CARD_POSITIONS_3
    elif card_count == 4:
        cards = CARD_POSITIONS_4
    else:
        raise ValueError(f"Unsupported card count: {card_count}")
    cards.append(SKIP_POSITION)

    
    image = use_screenshot(img)
    results: list[CardDetectResult] = []
    for x, y, w, h, return_value in cards:
        outer = (max(0, x - GLOW_EXTENSION), max(0, y - GLOW_EXTENSION))
        # 裁剪出检测区域
        glow_area = image[outer[1]:y + h + GLOW_EXTENSION, outer[0]:x + w + GLOW_EXTENSION]
        area_h = glow_area.shape[0]
        area_w = glow_area.shape[1]
        glow_area[GLOW_EXTENSION:area_h-GLOW_EXTENSION, GLOW_EXTENSION:area_w-GLOW_EXTENSION] = 0

        # 过滤出目标黄色
        glow_area = cv2.cvtColor(glow_area, cv2.COLOR_BGR2HSV)
        yellow_mask = cv2.inRange(glow_area, YELLOW_LOWER, YELLOW_UPPER)
        
        # 分割出每一边
        left_border = yellow_mask[:, 0:GLOW_EXTENSION]
        right_border = yellow_mask[:, area_w-GLOW_EXTENSION:area_w]
        top_border = yellow_mask[0:GLOW_EXTENSION, :]
        bottom_border = yellow_mask[area_h-GLOW_EXTENSION:area_h, :]
        y_border_pixels = area_h * GLOW_EXTENSION
        x_border_pixels = area_w * GLOW_EXTENSION

        # 计算每一边的分数
        left_score = np.count_nonzero(left_border) / y_border_pixels
        right_score = np.count_nonzero(right_border) / y_border_pixels
        top_score = np.count_nonzero(top_border) / x_border_pixels
        bottom_score = np.count_nonzero(bottom_border) / x_border_pixels

        result = (left_score + right_score + top_score + bottom_score) / 4
        results.append(CardDetectResult(
            return_value,
            result,
            left_score,
            right_score,
            top_score,
            bottom_score,
            (x, y, w, h)
        ))

    filtered_results = list(filter(threshold_predicate, results))
    if not filtered_results:
        max_result = max(results, key=lambda x: x.score)
        logger.info("Max card detect result (discarded): value=%d score=%.4f borders=(%.4f, %.4f, %.4f, %.4f)",
            max_result.type,
            max_result.score,
            max_result.left_score,
            max_result.right_score,
            max_result.top_score,
            max_result.bottom_score
        )
        return None
    filtered_results.sort(key=lambda x: x.score, reverse=True)
    logger.info("Max card detect result: value=%d score=%.4f borders=(%.4f, %.4f, %.4f, %.4f)",
        filtered_results[0].type,
        filtered_results[0].score,
        filtered_results[0].left_score,
        filtered_results[0].right_score,
        filtered_results[0].top_score,
        filtered_results[0].bottom_score
    )
    return filtered_results[0]

def handle_recommended_card(
        card_count: int, timeout: float = 7,
        threshold_predicate: Callable[[CardDetectResult], bool] = lambda _: True,
        *,
        img: MatLike | None = None,
    ):
    # cd = Countdown(seconds=timeout)
    # while not cd.expired():
    #     result = detect_recommended_card(card_count, threshold_predicate, img=img)
    #     if result is not None:
    #         device.double_click(result)
    #         return result
    #     sleep(np.random.uniform(0.01, 0.1))
    # return None

    result = detect_recommended_card(card_count, threshold_predicate, img=img)
    if result is not None:
        device.double_click(result)
        return result
    return None


@action('获取当前卡片数量', screenshot_mode='manual-inherit')
def skill_card_count(img: MatLike | None = None):
    """获取当前持有的技能卡数量"""
    device.click(0, 0)
    img = use_screenshot(img)
    img = crop(img, y1=0.83, y2=0.90)
    count = image.raw().count(img, R.InPurodyuusu.A)
    count += image.raw().count(img, R.InPurodyuusu.M)
    logger.info("Current skill card count: %d", count)
    return count


Yield = TypeVar('Yield')
Send = TypeVar('Send')
Return = TypeVar('Return')
P = ParamSpec('P')
class GeneratorWrapper(Iterable[Yield], Generic[P, Yield, Send, Return]):
    def __init__(
        self,
        generator_func: Callable[P, Generator[Yield, Send, Return]],
        *args: P.args,
        **kwargs: P.kwargs
    ):
        self.generator_func = generator_func
        self.generator = generator_func(*args, **kwargs)
        self.args = args
        self.kwargs = kwargs

    def __iter__(self):
        return self

    def __call__(self):
        return next(self.generator)

    def reset(self):
        self.generator = self.generator_func(*self.args, **self.kwargs)

    def loop(self) -> Return:
        while True:
            try:
                next(self.generator)
            except StopIteration as e:
                return cast(Return, e.value)

@action('获取当前卡牌信息', screenshot_mode='manual-inherit')
def obtain_cards(img: MatLike | None = None):
    img = use_screenshot(img)
    cards_rects = image.find_all_multi([
        R.InPurodyuusu.A,
        R.InPurodyuusu.M
    ])
    logger.info("Current cards: %s", len(cards_rects))
    cards = []
    for result in cards_rects:
        available = color.find_rgb('#7a7d7d', rect=result.rect) is None
        cards.append(SkillCard(available=available, rect=result.rect))
    return cards


@action('等待进入行动场景')
def until_action_scene():
    """等待进入行动场景"""
    # 检测是否到行动页面
    while not image.find_multi([
        R.InPurodyuusu.TextPDiary, # 普通周
        R.InPurodyuusu.ButtonFinalPracticeDance # 离考试剩余一周
    ]):
        logger.info("Action scene not detected. Retry...")
        until_acquisition_clear()
    else:
        logger.info("Now at action scene.")
        return 

@action('等待进入练习场景')
def until_practice_scene():
    """等待进入练习场景"""
    while image.find(R.InPurodyuusu.TextClearUntil) is None:
        until_acquisition_clear()

@action('等待进入考试场景')
def until_exam_scene():
    """等待进入考试场景"""
    while ocr.find(regex("合格条件|三位以上")) is None:
        until_acquisition_clear()

@action('执行练习', screenshot_mode='manual')
def practice():
    """
    执行练习
    
    前置条件：位于练习场景\n
    结束状态：各种奖励领取弹窗、加载画面等
    """
    logger.info("Practice started")

    def threshold_predicate(result: CardDetectResult):
        border_scores = (result.left_score, result.right_score, result.top_score, result.bottom_score)
        return (
            result.score >= 0.03
            # and len(list(filter(lambda x: x >= 0.01, border_scores))) >= 3
        )

    # 循环打出推荐卡
    while True:
        img = device.screenshot()
        if image.find(R.Common.ButtonIconCheckMark):
            logger.info("Confirmation dialog detected")
            device.click()
            sleep(3) # 等待卡片刷新
            continue

        card_count = skill_card_count(img)
        # cards = obtain_cards(img)
        # card_count = len(cards)
        # available_cards = [card for card in cards if card.available]
        # if len(available_cards) == 1:
        #     device.double_click(available_cards[0].rect)
        #     sleep(3) # 等待卡片刷新
        #     continue
        if card_count > 0 and handle_recommended_card(
            card_count=card_count,
            threshold_predicate=threshold_predicate,
            img=img
        ) is not None:
            sleep(3)
        elif (
            card_count == 0
            and not image.find_multi([
                R.InPurodyuusu.TextClearUntil,
                R.InPurodyuusu.TextPerfectUntil
            ])
        ):
            break
        sleep(np.random.uniform(0.01, 0.2))

    # 结束动画
    logger.info("CLEAR/PERFECT not found. Practice finished.")
    (SimpleDispatcher('practice.end')
        .click(contains("上昇"), finish=True, log="Click to finish 上昇 ")
        .click('center')
    ).run()

@action('执行考试')
def exam(type: Literal['mid', 'final']):
    """
    执行考试
    
    前置条件：考试进行中场景（手牌可见）\n
    结束状态：考试结束交流/对话（TODO：截图）
    """
    logger.info("Exam started")

    def threshold_predicate(result: CardDetectResult):
        if type == 'final':
            return (
                result.score >= 0.4
                and result.left_score >= 0.2
                and result.right_score >= 0.2
                and result.top_score >= 0.2
                and result.bottom_score >= 0.2
            )
        else:
            return result.score >= 0.10
        # 关于上面阈值的解释：
        # 两个阈值均指卡片周围的“黄色度”，
        # total_threshold 指卡片平均的黄色度阈值，border_thresholds 指卡片四边的黄色度阈值

        # 为什么期中和期末考试阈值不一样：
        # 期末考试的场景为黄昏，背景中含有大量黄色，
        # 非常容易对推荐卡的检测造成干扰。
        # 解决方法是提高平均阈值的同时，为每一边都设置阈值。
        # 这样可以筛选出只有四边都包含黄色的发光卡片，
        # 而由夕阳背景造成的假发光卡片通常不会四边都包含黄色。

    while True:
        img = device.screenshot()
        if image.find(R.Common.ButtonIconCheckMark):
            logger.info("Confirmation dialog detected")
            device.click()
            sleep(3) # 等待卡片刷新
            continue

        card_count = skill_card_count(img)
        # cards = obtain_cards(img)
        # card_count = len(cards)
        # available_cards = [card for card in cards if card.available]
        # if len(available_cards) == 1:
        #     device.double_click(available_cards[0].rect)
        #     sleep(3) # 等待卡片刷新
        #     continue
        if card_count > 0 and handle_recommended_card(
            card_count=card_count,
            threshold_predicate=threshold_predicate,
            img=img
        ) is not None:
            sleep(3) # 等待卡片刷新
        elif (
            card_count == 0
            and not ocr.find(contains('残りターン'), rect=R.InPurodyuusu.BoxExamTop)
        ):
            break
        sleep(np.random.uniform(0.01, 0.1))

    # 点击“次へ”
    device.click(image.expect_wait(R.Common.ButtonNext))
    if type == 'final':
        while ocr.wait_for(contains("メモリー"), timeout=7):
            device.click_center()

@action('考试结束流程')
def produce_end():
    """执行考试结束流程"""
    bottom = (int(device.screen_size[0] / 2), int(device.screen_size[1] * 0.9))
    # 1. 考试结束交流 [screenshots/produce/in_produce/final_exam_end_commu.png]
    # 2. 然后是，考试结束对话 [screenshots\produce_end\step2.jpg]
    # 3. MV
    # 4. 培育结束交流
    # 上面这些全部一直点就可以


    # 等待选择封面画面 [screenshots/produce_end/select_cover.jpg]
    # 次へ
    logger.info("Waiting for select cover screen...")
    wait = AdaptiveWait(timeout=60 * 5, max_interval=20)
    while not image.find(R.InPurodyuusu.ButtonNextNoIcon):
        wait()
        device.click(0, 0)
    # 选择封面
    logger.info("Use default cover.")
    sleep(3)
    logger.debug("Click next")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1)
    # 确认对话框 [screenshots/produce_end/select_cover_confirm.jpg]
    # 決定
    logger.debug("Click Confirm")
    device.click(image.expect_wait(R.Common.ButtonConfirm, threshold=0.8))
    sleep(1)
    # 上传图片，等待“生成”按钮
    # 注意网络可能会很慢，可能出现上传失败对话框
    logger.info("Waiting for cover uploading...")
    retry_count = 0
    MAX_RETRY_COUNT = 5
    while True:
        img = device.screenshot()
        # 处理上传失败
        if image.raw().find(img, R.InPurodyuusu.ButtonRetry):
            logger.info("Upload failed. Retry...")
            retry_count += 1
            if retry_count >= MAX_RETRY_COUNT:
                logger.info("Upload failed. Max retry count reached.")
                logger.info("Cancel upload.")
                device.click(image.expect_wait(R.InPurodyuusu.ButtonCancel))
                sleep(2)
                continue
            device.click()
        # 记忆封面保存失败提示
        elif image.raw().find(img, R.Common.ButtonClose):
            logger.info("Memory cover save failed. Click to close.")
            device.click()
        elif gen_btn := ocr.raw().find(img, contains("生成")):
            logger.info("Generate memory cover completed.")
            device.click(gen_btn)
            break
        else:
            device.click_center()
        sleep(2)
    # 后续动画
    logger.info("Waiting for memory generation animation completed...")
    while not image.find(R.InPurodyuusu.ButtonNextNoIcon):
        device.click_center()
        sleep(1)
    
    # 结算完毕
    logger.info("Finalize")
    # [screenshots/produce_end/end_next_1.jpg]
    logger.debug("Click next 1")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_next_2.png]
    logger.debug("Click next 2")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_next_3.png]
    logger.debug("Click next 3")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_complete.png]
    logger.debug("Click complete")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonComplete))
    sleep(1.3)
    # 点击结束后可能还会弹出来：
    # 活动进度、关注提示
    # [screenshots/produce_end/end_activity.png]
    # [screenshots/produce_end/end_activity1.png]
    # [screenshots/produce_end/end_follow.png]
    while not at_home():
        if image.find(R.Common.ButtonClose):
            logger.info("Activity award claim dialog found. Click to close.")
            device.click()
        elif image.find(R.Common.ButtonNextNoIcon):
            logger.debug("Click next")
            device.click(image.expect_wait(R.Common.ButtonNextNoIcon))
        elif image.find(R.InPurodyuusu.ButtonCancel):
            logger.info("Follow producer dialog found. Click to close.")
            if conf().produce.follow_producer:
                logger.info("Follow producer")
                device.click(image.expect_wait(R.InPurodyuusu.ButtonFollowNoIcon))
            else:
                logger.info("Skip follow producer")
                device.click()
        else:
            device.click_center()
        sleep(1)
    logger.info("Produce completed.")

def week_normal():
    until_action_scene()
    executed_action = handle_recommended_action()
    logger.info("Executed recommended action: %s", executed_action)
    # 推荐练习
    if executed_action == 'lesson':
        until_practice_scene()
        practice()
    # 推荐休息
    elif executed_action == 'rest':
        pass
    # 没有推荐行动
    elif executed_action is None:
        if allowance_available():
            enter_allowance()
        elif study_available():
            enter_study()
        elif is_rest_available():
            rest()
        else:
            raise ValueError("No action available.")
    until_action_scene()

def week_final_lesson():
    if handle_recommended_action(final_week=True) != 'lesson':
        raise ValueError("Failed to enter recommended action on final week.")
    sleep(5)
    until_practice_scene()
    practice()

def week_mid_exam():
    logger.info("Week mid exam started.")
    logger.info("Wait for exam scene...")
    until_exam_scene()
    logger.info("Exam scene detected.")
    sleep(5)
    device.click_center()
    sleep(5)
    exam('mid')
    until_action_scene()

def week_final_exam():
    logger.info("Week final exam started.")
    logger.info("Wait for exam scene...")
    until_exam_scene()
    logger.info("Exam scene detected.")
    sleep(5)
    device.click_center()
    sleep(0.5)
    loading.wait_loading_end()
    exam('final')
    produce_end()

@action('执行 Regular 培育')
def hajime_regular(week: int = -1, start_from: int = 1):
    """
    「初」 Regular 模式

    :param week: 第几周，从1开始，-1表示全部
    :param start_from: 从第几周开始，从1开始。
    """
    weeks = [
        week_normal, # 1: Vo.レッスン、Da.レッスン、Vi.レッスン
        week_normal, # 2: 授業
        week_normal, # 3: Vo.レッスン、Da.レッスン、Vi.レッスン、授業
        week_normal, # 4: おでかけ、相談、活動支給
        week_final_lesson, # 5: 追い込みレッスン
        week_mid_exam, # 6: 中間試験
        week_normal, # 7: おでかけ、活動支給
        week_normal, # 8: 授業、活動支給
        week_normal, # 9: Vo.レッスン、Da.レッスン、Vi.レッスン
        week_normal, # 10: Vo.レッスン、Da.レッスン、Vi.レッスン、授業
        week_normal, # 11: おでかけ、相談、活動支給
        week_final_lesson, # 12: 追い込みレッスン
        week_final_exam, # 13: 最終試験
    ]
    if week not in [6, 13] and start_from not in [6, 13]:
        until_action_scene()
    else:
        until_exam_scene()
    if week != -1:
        logger.info("Week %d started.", week)
        weeks[week - 1]()
    else:
        for i, w in enumerate(weeks[start_from-1:]):
            logger.info("Week %d started.", i + start_from)
            w()

@action('执行 PRO 培育')
def hajime_pro(week: int = -1, start_from: int = 1):
    """
    「初」 PRO 模式

    :param week: 第几周，从1开始，-1表示全部
    :param start_from: 从第几周开始，从1开始。
    """
    weeks = [
        week_normal, # 1
        week_normal, # 2
        week_normal, # 3
        week_normal, # 4
        week_normal, # 5
        week_final_lesson, # 6
        week_mid_exam, # 7
        week_normal, # 8
        week_normal, # 9
        week_normal, # 10
        week_normal, # 11
        week_normal, # 12
        week_normal, # 13
        week_normal, # 14
        week_final_lesson, # 15
        week_final_exam, # 16
    ]
    if week != -1:
        logger.info("Week %d started.", week)
        weeks[week - 1]()
    else:
        for i, w in enumerate(weeks[start_from-1:]):
            logger.info("Week %d started.", i + start_from)
            w()

@action('是否在考试场景')
def is_exam_scene():
    """是否在考试场景"""
    return ocr.find(contains('残りターン'), rect=R.InPurodyuusu.BoxExamTop) is not None

ProduceStage = Literal[
    'action', # 行动场景
    'practice-ongoing', # 练习场景
    'exam-start', # 考试开始确认页面
    'exam-ongoing', # 考试进行中
    'exam-end', # 考试结束
    'unknown', # 未知场景
]

@action('检测当前培育场景', dispatcher=True)
def detect_regular_produce_scene(ctx: DispatcherContext) -> ProduceStage:
    """
    判断当前是培育的什么阶段，并开始 Regular 培育。

    前置条件：培育中的任意场景\n
    结束状态：游戏主页面\n
    """
    logger.info("Detecting current produce stage...")
    
    # 行动场景
    texts = ocr.ocr()
    if (
        image.find_multi([
            R.InPurodyuusu.TextPDiary, # 普通周
            R.InPurodyuusu.ButtonFinalPracticeDance # 离考试剩余一周
        ]) 
    ):
        logger.info("Detection result: At action scene.")
        ctx.finish()
        return 'action'
    elif texts.where(regex('CLEARまで|PERFECTまで')):
        logger.info("Detection result: At practice ongoing.")
        ctx.finish()
        return 'practice-ongoing'
    elif is_exam_scene():
        logger.info("Detection result: At exam scene.")
        ctx.finish()
        return 'exam-ongoing'
    elif texts.where(regex('合格条件|三位以上')):
        logger.info("Detection result: At exam start.")
        ctx.finish()
        return 'exam-start'
    else:
        until_acquisition_clear()
        return 'unknown'

@action('开始 Regular 培育')
def hajime_regular_from_stage(stage: ProduceStage):
    """
    开始 Regular 培育。
    """
    if stage == 'action':
        texts = ocr.ocr(rect=R.InPurodyuusu.BoxWeeksUntilExam)
        # 提取周数
        remaining_week = texts.squash().replace('ó', '6').numbers()
        if not remaining_week:
            raise UnrecoverableError("Failed to detect week.")
        # 判断阶段
        if texts.where(contains('中間')):
            week = 6 - remaining_week[0]
            hajime_regular(start_from=week)
        elif texts.where(contains('最終')):
            week = 13 - remaining_week[0]
            hajime_regular(start_from=week)
        else:
            raise UnrecoverableError("Failed to detect produce stage.")
    elif stage == 'exam-start':
        device.click_center()
        until_exam_scene()
        exam()
    elif stage == 'exam-ongoing':
        # TODO: 应该直接调用 week_final_exam 而不是再写一次
        logger.info("Exam ongoing. Start exam.")
        exam()
        result = ocr.expect_wait(contains('中間|最終'))
        if '中間' in result.text:
            return hajime_regular_from_stage(detect_regular_produce_scene())
        elif '最終' in result.text:
            produce_end()
        else:
            raise UnrecoverableError("Failed to detect produce stage.")
    elif stage == 'practice-ongoing':
        # TODO: 应该直接调用 week_final_exam 而不是再写一次
        logger.info("Practice ongoing. Start practice.")
        practice()
        return hajime_regular_from_stage(detect_regular_produce_scene())
    else:
        raise UnrecoverableError(f'Cannot resume produce REGULAR from stage "{stage}".')

@action('继续 Regular 培育')
def resume_regular_produce():
    """
    继续 Regular 培育。
    """
    hajime_regular_from_stage(detect_regular_produce_scene())

if __name__ == '__main__':
    from logging import getLogger

    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')
    getLogger('kotonebot').setLevel(logging.DEBUG)
    getLogger(__name__).setLevel(logging.DEBUG)


    # while True:
    #     cards = obtain_cards()
    #     print(cards)
    #     sleep(1)


    # practice()
    # week_final_exam()
    exam('final')
    produce_end()


    # hajime_pro(start_from=15)
    # exam('mid')
    # stage = (detect_regular_produce_scene())
    # hajime_regular_from_stage(stage)

    # click_recommended_card(card_count=skill_card_count())
    # exam('mid')

    # hajime_regular(start_from=7)

    # import cv2
    # while True:
    #     img = device.screenshot()
    #     cv2.imshow('123', img)
    #     cv2.waitKey(1)
